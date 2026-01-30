import logging
import asyncio
from asyncpraw.models import Submission
from html import unescape
from discord import Embed
from typing import Optional, Union
from discord.ext.commands import Context
from urllib.parse import urlparse
import discord
import re

log = logging.getLogger(__name__)

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif")

async def send_meme(
    ctx: Context,
    url: str,
    *,
    content: Optional[str] = None,
    embed: Optional[Embed] = None,
    view: Optional[discord.ui.View] = None,
):
    """
    Send a meme content to Discord.
    Handles Images (Embed + Image) vs Video (Embed + URL for unfurling).
    Unifies Context/Interaction handling.
    """
    
    # 3. Detect Media Type (Video vs Image)
    path = urlparse(url).path.lower()
    is_video = path.endswith((".mp4", ".webm", ".mov"))
    is_image = path.endswith(IMAGE_EXT) and not is_video

    # 4. Modify Embed if needed
    if embed and is_image:
        embed.set_image(url=url)
        # We don't append URL to content if inside embed
        msg_content = content
    elif is_video or (embed and not is_image):
        # For video/gif, we send the URL in content so Discord unfurls it.
        # If we send an embed along with it, sometimes Discord hides the video player.
        # But usually content=URL + embed works.
        if content:
            msg_content = f"{content}\n{url}"
        else:
            msg_content = url
    else:
        # Fallback
        if content:
             msg_content = f"{content}\n{url}"
        else:
             msg_content = url
    
    # 3. Helper to send
    async def _send(text, em, v):
        kwargs = {"content": text, "embed": em}
        if v is not None:
            kwargs["view"] = v

        # try interaction first
        if getattr(ctx, "interaction", None):
            try:
                if not ctx.interaction.response.is_done():
                     await ctx.interaction.response.defer()
                return await ctx.interaction.followup.send(**kwargs)
            except (discord.errors.NotFound, discord.errors.InteractionResponded):
                # Fallback to channel
                pass
        
        # Fallback
        if getattr(ctx, "channel", None):
             return await ctx.channel.send(**kwargs)
        return await ctx.send(**kwargs)

    return await _send(msg_content, embed, view)

def get_image_url(post: Union[Submission, dict]) -> str:
    # Helper to get attributes whether it's an object or dict
    is_obj = hasattr(post, "id")
    def get(key, default=None):
        return getattr(post, key, default) if is_obj else post.get(key, default)

    url = get("url")
    post_id = get("id") or "?"
    log.debug("get_image_url: id=%s url=%s", post_id, url)

    # Check for reddit_video (usually absent in JSON listing unless expanded, but check anyway)
    # in JSON: data['media']['reddit_video'] or data['secure_media']['reddit_video']
    for media_attr in ("media", "secure_media"):
        media = get(media_attr)
        if media and isinstance(media, dict) and (rv := media.get("reddit_video")):
             fallback = rv.get("fallback_url")
             if fallback:
                 return fallback

    if url.lower().endswith(".gif"):
        return url

    # Gallery check
    if get("is_gallery"):
        try:
            gd = get("gallery_data") or {}
            items = gd.get("items", [])
            if items:
                first_id = items[0].get("media_id")
                mm = get("media_metadata") or {}
                meta = mm.get(first_id, {})
                gallery_url = meta.get("s", {}).get("u")
                if not gallery_url and meta.get("p"):
                    gallery_url = meta["p"][-1].get("u")
                if gallery_url:
                    return unescape(gallery_url)
        except Exception:
            pass

    # Preview images
    try:
        preview = get("preview")
        if preview and "images" in preview:
            image = preview["images"][0]
            variants = image.get("variants", {})
            if "gif" in variants:
                return variants["gif"]["source"]["url"]
            if "mp4" in variants:
                return variants["mp4"]["source"]["url"]
    except Exception:
        pass
    
    # Embeds
    for embed_attr in ("secure_media_embed", "media_embed"):
        embed = get(embed_attr)
        if embed and isinstance(embed, dict) and (content := embed.get("content")):
            match = re.search(r'src=["\']([^"\']+)', content)
            if match:
                extracted = match.group(1)
                # FIX: Unwrap Embedly URLs
                if "embedly.com" in extracted:
                    from urllib.parse import parse_qs, unquote
                    parsed = urlparse(unescape(extracted))
                    qs = parse_qs(parsed.query)
                    if "url" in qs:
                        return qs["url"][0]
                    # If extraction fails, extracted is returned below, but let's try other methods first
                else:
                     return extracted

    if url.lower().endswith(IMAGE_EXT):
        return url
        
    # Imgur .gifv -> .mp4
    if "imgur.com" in url and url.endswith(".gifv"):
        return url.replace(".gifv", ".mp4")

    try:
        preview = get("preview")
        if preview and "images" in preview:
            return preview["images"][0]["source"]["url"]
    except Exception:
        pass
        
    return url

def get_reddit_url(url: str) -> str:
    """Return the original Reddit URL suitable for Discord embeds."""
    return url

async def extract_media_url(url: str) -> Optional[str]:
    """Use yt-dlp to extract the best media URL (with audio if possible)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-g",
            # Force generic mp4 if possible, avoids m3u8 streams that Discord can't play
            "-f", "b[ext=mp4]/best",
            "--no-playlist",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip().split("\n")[0]
        else:
            log.debug("yt-dlp failed for %s: %s", url, stderr.decode())
    except Exception as e:
        log.error("Error running yt-dlp: %s", e)
    return None

async def extract_post_data(post):
    # Handle both PRAW Submission objects and loose dicts (from JSON API)
    if hasattr(post, "load"):
        try:
            await post.load()
        except Exception as e:
            log.debug("post.load() failed: %s", e)

    # Normalize to dict-like access
    is_obj = hasattr(post, "id")
    def get(key, default=None):
        return getattr(post, key, default) if is_obj else post.get(key, default)

    post_id = get("id") or "?"
    url = get("url")
    title = get("title")
    permalink = get("permalink")
    author = str(get("author")) if get("author") else "[deleted]"
    over_18 = get("over_18")
    created_utc = get("created_utc")
    is_video = get("is_video")
    domain = get("domain")
    
    # New stats
    ups = get("ups", 0)
    num_comments = get("num_comments", 0)
    
    # Subreddit handling
    sub_val = get("subreddit")
    subreddit = sub_val.display_name if hasattr(sub_val, "display_name") else str(sub_val)

    # Gather data for get_image_url
    if is_obj:
        post_data = post
    else:
        post_data = post

    media_url = url
    gallery_urls = []

    # 1. Try yt-dlp for videos OR redgifs
    should_try_ytdlp = (
        is_video 
        or domain == "v.redd.it" 
        or url.startswith("https://v.redd.it")
        or "redgifs" in domain
        or "gfycat" in domain
    )
    
    if should_try_ytdlp:
        best = await extract_media_url(url)
        if best:
            media_url = best
        else:
            # Fallback for Reddit/RedGifs if yt-dlp fails
            log.warning(f"yt-dlp failed for {url}, trying manual extraction")
            
            # RedGifs: Try to find HD Video in preview
            if "redgifs" in domain:
                try:
                    preview = get("preview", {})
                    # Path 1: reddit_video_preview
                    if rv := preview.get("reddit_video_preview"):
                         if fallback := rv.get("fallback_url"):
                             media_url = fallback
                    # Path 2: variants
                    elif images := preview.get("images"):
                         variants = images[0].get("variants", {})
                         if mp4 := variants.get("mp4", {}).get("source", {}).get("url"):
                             media_url = unescape(mp4)
                except Exception:
                     pass
            
            # If still just the /ifr/ or /watch/ url, get_image_url might fail to convert it.
            if media_url == url or "ifr" in media_url:
                 # Last ditch: try get_image_url again just in case
                 possible = get_image_url(post_data)
                 if possible and possible != url:
                     media_url = unescape(possible)
                 else:
                     # CRITICAL FALLBACK:
                     # If we can't extract the MP4 (e.g. geo-blocked), just return the ORIGINAL URL.
                     # Discord can often embed RedGifs links directly now.
                     media_url = url
                     
    # 2. Try Gallery
    elif get("is_gallery"):
        # Extract all items
        try:
            mm = get("media_metadata") or {}
            gd = get("gallery_data") or {}
            items = gd.get("items", [])
            for item in items:
                media_id = item.get("media_id")
                meta = mm.get(media_id, {})
                u = meta.get("s", {}).get("u")
                if u:
                    gallery_urls.append(unescape(u))
        except Exception as e:
            log.debug("Gallery extraction failed: %s", e)
        
        if gallery_urls:
            media_url = gallery_urls[0]

    # 3. Standard Image/Gif
    else:
        media_url = get_image_url(post_data)
        if media_url:
             media_url = unescape(media_url)

    return {
        "post_id": post_id,
        "subreddit": subreddit,
        "title": title,
        "url": url,
        "media_url": media_url,
        "gallery_urls": gallery_urls,
        "permalink": permalink,
        "author": author,
        "is_nsfw": over_18,
        "ups": ups,
        "num_comments": num_comments,
        "created_utc": int(created_utc) if created_utc else 0,
    }
