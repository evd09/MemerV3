# File: cogs/meme.py
import os
import random
import asyncio
import logging
import json

# 🔐 Define the logger IMMEDIATELY after importing it
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

from datetime import datetime
from typing import Optional

from asyncprawcore import NotFound, Forbidden
import asyncpraw
from memer.helpers.guild_subreddits import (
    get_guild_subreddits,
    DEFAULTS,
)
from memer.meme_stats import (
    update_stats,
    track_reaction,
    get_dashboard_stats,
    get_reactions_for_message,
    get_top_reacted_memes,
    register_meme_message as stats_register_msg,
)

from types import SimpleNamespace
from collections import defaultdict, deque
import discord
import time
from discord import Embed
from discord.ext import commands, tasks
from memer.helpers.meme_utils import (
    get_image_url,
    send_meme,
    get_reddit_url,
    extract_post_data,
)
from memer.helpers.meme_cache_service import MemeCacheService
from memer.helpers.db import (
    get_recent_post_ids,
    register_meme_message,
    has_post_been_sent,
)
from memer.helpers.reddit_cache import NoopCacheManager
# Adapter to keep keywords active during subreddit searches
class _AlwaysOnCacheManager:
    """Wraps an existing cache manager but never disables keywords."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def is_disabled(self, *args, **kwargs):  # pragma: no cover - simple override
        return False

    def record_failure(self, *args, **kwargs):  # pragma: no cover - no-op
        return False
# Refactored utilities and cache
from memer.reddit_meme import (
    fetch_meme      as fetch_meme_util,
    simple_random_meme,
    NoMemeFoundError,
    SubredditUnavailableError,
    start_warmup,
    stop_warmup,
    WARM_CACHE,
    ID_CACHE,
    HASH_CACHE,
)
from memer.helpers.reddit_config import start_observer, stop_observer

class Meme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            log.info("Meme cog initializing...")
        except Exception:
            log.error("[MEME COG INIT ERROR]", exc_info=True)
        self.recent_ids = defaultdict(lambda: deque(maxlen=200))
        log.info("MemeBot initialized at %s", datetime.utcnow())

        # Reddit client
        self.reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="MemeBot (by u/YourUsername)"
        )
        # Inside your bot or cog class init/setup
        self.cache_service = MemeCacheService(
            reddit=self.reddit,
            config=getattr(bot.config, "MEME_CACHE", {})
        )
        try:
            log.info("Reddit + Cache initialized")
        except Exception:
            log.error("[CACHE INIT ERROR]", exc_info=True)

        # Start prune task
        self._prune_cache.start()
        # Kick off warmup immediately
        subs = DEFAULTS["sfw"] + DEFAULTS["nsfw"]
        for mandatory in ("memes", "nsfwmeme"):
            if mandatory not in subs:
                subs.append(mandatory)
        log.debug("Scheduling warmup for subs: %s", subs)
        # Note: session won't be ready until on_ready setup_hook typically,
        # but setup_hook ran before cog load! So self.bot.session is valid.
        asyncio.create_task(start_warmup(self.reddit, subs, session=self.bot.session))
        start_observer()

    def cog_unload(self):
        self._prune_cache.cancel()
        asyncio.create_task(self.cache_service.close())
        asyncio.create_task(stop_warmup())
        stop_observer()
        log.info("MemeBot unloaded; warmup stopped and observer shut down.")

    @tasks.loop(seconds=60)
    async def _prune_cache(self):
        log.debug("_prune_cache: guilds=%s", list(self.recent_ids.keys()))

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("on_ready: bot is ready")
        await self.cache_service.init()

    async def _send_cached(
        self,
        ctx: commands.Context,
        post_dict: dict,
        keyword: str,
        via: str,
        nsfw: bool,
    ):
        """
        Send a single cached meme (post_dict) and update stats.
        ``via`` documents where the meme came from (e.g. ``RAM``, ``DISK``,
        ``WARM CACHE`` or ``LOCAL``).
        """
        permalink = post_dict["permalink"]
        
        # 1️⃣ Build embed
        embed = Embed(
            title=post_dict["title"],
            url=f"https://reddit.com{permalink}",
            description=f"r/{post_dict['subreddit']} • u/{post_dict.get('author', '[deleted]')}"
        )
        embed.set_footer(text=f"via {via}")

        # 2️⃣ Resolve URLs
        raw_url   = post_dict.get("media_url") or post_dict.get("url")
        embed_url = get_reddit_url(raw_url)

        # record in global caches to avoid future duplicates
        pid = post_dict.get("post_id")
        if pid:
            ID_CACHE[pid] = True
        if raw_url:
            HASH_CACHE[raw_url] = True

        # 3️⃣ Send
        sent = await send_meme(ctx, url=embed_url, embed=embed)

        # 4️⃣ Stats
        register_meme_message(
            sent.id,
            ctx.channel.id,
            ctx.guild.id,
            f"https://reddit.com{permalink}",
            post_dict["title"]
        )
        await update_stats(ctx.author.id, keyword or "", post_dict["subreddit"], nsfw=nsfw)

    async def _try_cache_or_local(self, ctx, nsfw: bool, keyword: Optional[str]) -> bool:
        """Attempt to send a meme from warm cache or local fallback files.

        Returns True if a meme was sent, False otherwise.
        """
        subs = get_guild_subreddits(ctx.guild.id, "nsfw" if nsfw else "sfw")

        # 1️⃣ Try WARM_CACHE buffers first
        random.shuffle(subs)
        for listing in ("hot", "new"):
            for sub in subs:
                key = f"{sub}_{listing}"
                buf = WARM_CACHE.get(key)
                if buf:
                    while buf:
                        post = buf.pop()
                        if not post:
                            continue
                        data = await extract_post_data(post)
                        await self._send_cached(ctx, data, keyword or "", "WARM CACHE", nsfw)
                        return True

        # 2️⃣ Local fallback bundle
        config = getattr(self.bot.config, "MEME_CACHE", {})
        folder = config.get("fallback_dir")
        if folder:
            fname = "nsfw.json" if nsfw else "sfw.json"
            path = os.path.join(folder, fname)
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        posts = json.load(f)
                except Exception:
                    posts = []
                if posts:
                    post_dict = random.choice(posts)
                    await self._send_cached(ctx, post_dict, keyword or "", "LOCAL", nsfw)
                    return True

        return False

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Ignore bot's own reactions if any (though usually bot doesn't react)
        if payload.user_id == self.bot.user.id:
            return
            
        try:
            log.info("React event: ID=%s User=%s Emoji=%s", payload.message_id, payload.user_id, payload.emoji)
            await track_reaction(payload.message_id, payload.user_id, str(payload.emoji))
            log.debug("Tracked reaction %s on %s by %s", payload.emoji, payload.message_id, payload.user_id)
        except Exception as e:
            log.error("Failed to track reaction: %s", e)

    async def _cmd_logic(self, ctx, keyword, nsfw):
        log.info("/%s invoked: guild=%s user=%s keyword=%s",
                 "nsfwmeme" if nsfw else "meme", ctx.guild.id, ctx.author.id, keyword)

        if nsfw and not getattr(ctx.channel, "is_nsfw", lambda: False)():
             return await ctx.interaction.response.send_message(
                "🔞 You can only use NSFW memes in NSFW channels.",
                ephemeral=True
            )

        try:
            await ctx.defer()
        except discord.errors.NotFound:
            pass

        recent_ids = await get_recent_post_ids(ctx.channel.id)
        subs = get_guild_subreddits(ctx.guild.id, "nsfw" if nsfw else "sfw")

        start_time = time.perf_counter()
        result = await fetch_meme_util(
            reddit=self.reddit,
            subreddits=subs,
            cache_mgr=self.cache_service.cache_mgr,
            keyword=keyword,
            nsfw=nsfw,
            exclude_ids=recent_ids,
            session=self.bot.session,
        )
        end_time = time.perf_counter()
        elapsed = end_time - start_time
        
        post = getattr(result, "post", None)
        if isinstance(post, dict):
            # Create a shallow wrapper for attribute access
            post = SimpleNamespace(**post)

        # Fallback to local if nothing found
        if not post:
             if await self._try_cache_or_local(ctx, nsfw=nsfw, keyword=keyword):
                 return

             msg = f"✅ No {'NSFW ' if nsfw else ''}memes found—try again later!"
             return await ctx.interaction.followup.send(msg, ephemeral=True)

        # Load post if needed (sometimes required for videos/galleries)
        if hasattr(post, "load"):
             try: await post.load()
             except Exception: pass

        # Build improved embed
        # Random pastel-ish color or reddit orange
        color = discord.Color.from_rgb(255, 69, 0) # Reddit Orange
        
        embed = Embed(
            title=post.title[:256],
            url=f"https://reddit.com{post.permalink}",
            description=f"r/{result.source_subreddit} • u/{post.author}",
            color=color
        )
        
        # Add stats if available - Prefer result.data as it is normalized
        data = getattr(result, "data", {})
        ups = data.get("ups", getattr(post, "ups", 0))
        num_comments = data.get("num_comments", getattr(post, "num_comments", 0))
        
        embed.add_field(name="Stats", value=f"👍 {ups:,}  💬 {num_comments:,}", inline=True)
        
        # Footer info
        footer_text = f"via {result.picked_via.upper()}"
        if hasattr(post, "gallery_urls") and post.gallery_urls:
            footer_text += f" • Image 1 of {len(post.gallery_urls)}"
            
        if result.picked_via not in ("cache_ram", "cache_disk"):
            footer_text += f" • Found in {elapsed:.2f}s"
            
        embed.set_footer(text=footer_text)
        
        # Create View
        # Detect if nsfw command or regular
        cmd_name = ctx.command.name if ctx.command else "meme"
        view = MemeView(ctx, self, cmd_name, keyword, subreddit=result.source_subreddit)

        # Pass original dict if it was wrapped, for robustness in get_image_url? 
        # Actually get_image_url handles SimpleNamespace fine if we pass it as object
        # or we handled it inside fetch_meme_util wrapper
        
        raw_url = get_image_url(post.__dict__ if isinstance(post, SimpleNamespace) else post)
        embed_url = get_reddit_url(raw_url)

        content = None
        if keyword and result.picked_via == "random":
             content = f"No results for {keyword}; serving a random one."

        try:
             sent = await send_meme(ctx, url=embed_url, content=content, embed=embed, view=view)
        except Exception:
             log.exception("Error in send_meme")
             return await ctx.interaction.followup.send("❌ Error sending meme.", ephemeral=True)

        register_meme_message(
             sent.id,
             ctx.channel.id,
             ctx.guild.id,
             f"https://reddit.com{post.permalink}",
             post.title,
             post_id=post.id
        )
        # Register in stats DB as well (for reaction leaderboards)
        await stats_register_msg(
             sent.id,
             ctx.channel.id,
             ctx.guild.id,
             f"https://reddit.com{post.permalink}",
             post.title
        )
        await update_stats(ctx.author.id, keyword or "", result.source_subreddit, nsfw=nsfw)

    @commands.hybrid_command(
        name="meme",
        description="Fetch a SFW meme (title contains your keyword, or random if none found)"
    )
    async def meme(self, ctx, keyword: Optional[str] = None):
        await self._cmd_logic(ctx, keyword, nsfw=False)

    @commands.hybrid_command(
        name="nsfwmeme",
        description="Fetch a NSFW meme (title contains your keyword, or random if none found)"
    )
    async def nsfwmeme(self, ctx, keyword: Optional[str] = None):
        await self._cmd_logic(ctx, keyword, nsfw=True)

    @commands.hybrid_command(name="r_", description="Fetch a meme from a specific subreddit")
    async def r_(self, ctx: commands.Context, subreddit: str, keyword: Optional[str] = None):
        log.info("/r_ invoked: guild=%s user=%s subreddit=%s keyword=%s",
                 ctx.guild.id, ctx.author.id, subreddit, keyword)

        # 1) Defer to give us 3s
        try:
            await ctx.defer()
        except discord.errors.NotFound:
            pass

        # 2) Lookup subreddit
        try:
            sub = await self.reddit.subreddit(subreddit, fetch=True)
        except (NotFound, Forbidden):
            if ctx.interaction:
                return await ctx.interaction.followup.send(
                    f"r/{subreddit} is not available :/",
                    ephemeral=True,
                )
            return await ctx.send(f"r/{subreddit} is not available :/")

        # 2a) NSFW channel check if subreddit is marked NSFW
        if getattr(sub, "over18", False):
            channel_is_nsfw = getattr(ctx.channel, "is_nsfw", lambda: True)()
            if not channel_is_nsfw:
                ctx._no_reward = True
                msg = (
                    f"🔞 Heads up - r/{subreddit} is NSFW. "
                    "Move to an NSFW channel and retry."
                )
                if ctx.interaction:
                    return await ctx.interaction.followup.send(msg, ephemeral=True)
                return await ctx.send(msg)

        # 3) Fetch via pipeline (or random fallback)
        post = None
        try:
            recent_ids = await get_recent_post_ids(ctx.channel.id)

            if keyword is None:
                try:
                    post = await simple_random_meme(self.reddit, subreddit)
                except SubredditUnavailableError:
                    msg = f"r/{subreddit} is not available :/"
                    if ctx.interaction:
                        return await ctx.interaction.followup.send(msg, ephemeral=True)
                    return await ctx.send(msg)
                result = type("F", (), {})()
                result.source_subreddit = subreddit
                result.picked_via = "random"
            else:
                cache_mgr = NoopCacheManager()

                result = await fetch_meme_util(
                    reddit=self.reddit,
                    subreddits=[sub],
                    keyword=keyword,
                    cache_mgr=cache_mgr,
                    nsfw=bool(getattr(sub, "over18", False)),
                    exclude_ids=recent_ids,
                )
                post = getattr(result, "post", None) if result else None

                if not post:
                    log.info("No post found via keyword, trying random fallback in r/%s", subreddit)
                    try:
                        post = await simple_random_meme(self.reddit, subreddit)
                    except SubredditUnavailableError:
                        msg = f"r/{subreddit} is not available :/"
                        if ctx.interaction:
                            return await ctx.interaction.followup.send(msg, ephemeral=True)
                        return await ctx.send(msg)
                    if not post:
                        log.info("No random meme found for r/%s, sending fail message.", subreddit)
                        if ctx.interaction:
                            return await ctx.interaction.followup.send(
                                f"✅ No memes found in r/{subreddit} right now—try again later!",
                                ephemeral=True
                            )
                        return await ctx.send(
                            f"✅ No memes found in r/{subreddit} right now—try again later!"
                        )
                    result = type("F", (), {})()
                    result.source_subreddit = subreddit
                    result.picked_via = "random"

            if isinstance(post, dict):
                post = SimpleNamespace(**post)

            attempts = 0
            while post and (
                post.id in recent_ids or await has_post_been_sent(ctx.channel.id, post.id)
            ) and attempts < 5:
                log.debug("🚫 recently sent, trying another post")
                try:
                    post = await simple_random_meme(self.reddit, subreddit)
                except SubredditUnavailableError:
                    msg = f"r/{subreddit} is not available :/"
                    if ctx.interaction:
                        return await ctx.interaction.followup.send(msg, ephemeral=True)
                    return await ctx.send(msg)
                if post:
                    if isinstance(post, dict):
                        post = SimpleNamespace(**post)
                    result.source_subreddit = subreddit
                    result.picked_via = "random"
                attempts += 1

                if not post:
                    if await self._try_cache_or_local(ctx, nsfw=sub.over18, keyword=keyword):
                        return
                    if ctx.interaction:
                        return await ctx.interaction.followup.send(
                            f"✅ No fresh posts in r/{subreddit} right now—try again later!",
                            ephemeral=True
                        )
                    return await ctx.send(
                        f"✅ No fresh posts in r/{subreddit} right now—try again later!"
                    )



            # Final safety check before processing
            if not post:
                log.warning("Post became None after retry loop in /r_")
                if ctx.interaction:
                     try:
                        await ctx.interaction.followup.send("⚠️ Failed to find a meme.", ephemeral=True)
                     except discord.NotFound:
                        pass
                return

            if hasattr(post, "load"):
                try:
                    await post.load()
                except Exception:
                    pass

            raw_url = get_image_url(post.__dict__ if isinstance(post, SimpleNamespace) else post)
            if raw_url.endswith(('.mp4', '.webm')):
                embed_url = get_reddit_url(raw_url)  # use original URL for videos
            else:
                embed_url = raw_url  # original for images

            ID_CACHE[post.id] = True
            HASH_CACHE[raw_url] = True
            
            # Rich Embed similar to _cmd_logic
            color = discord.Color.from_rgb(255, 69, 0)
            
            embed = Embed(
                title=getattr(post, "title", "No Title")[:256],
                url=f"https://reddit.com/r/{subreddit}/comments/{post.id}/",
                description=f"r/{subreddit} • u/{getattr(post, 'author', '???')}",
                color=color
            )
            
            ups = getattr(post, "ups", 0)
            num_comments = getattr(post, "num_comments", 0)
            embed.add_field(name="Stats", value=f"👍 {ups:,}  💬 {num_comments:,}", inline=True)
            

            footer_text = f"via {result.picked_via.upper()}"
            if hasattr(post, "gallery_urls") and post.gallery_urls:
                footer_text += f" • Image 1 of {len(post.gallery_urls)}"
            embed.set_footer(text=footer_text)

            # View
            view = MemeView(ctx, self, "r_", keyword, subreddit=subreddit)

            if await send_meme(ctx, embed_url, content=None, embed=embed, view=view):
                register_meme_message(
                    ctx.message.id if hasattr(ctx.message, "id") else str(ctx.interaction.id),
                    ctx.channel.id,
                    ctx.guild.id,
                    raw_url,
                    getattr(post, "title", ""),
                    post.id,
                )

            await update_stats(ctx.author.id, keyword or "", result.source_subreddit, nsfw=False)
        except Exception as e:
            log.error(f"Error in /r_ command: {e}", exc_info=True)
            if ctx.interaction:
                try:
                    await ctx.interaction.followup.send(
                        "❌ Error fetching meme from subreddit.", ephemeral=True
                    )
                except discord.NotFound:
                     pass
            else:
                await ctx.send("❌ Error fetching meme from subreddit.")

    @commands.hybrid_command(name="dashboard", description="Show a stats dashboard")
    async def dashboard(self, ctx):
        """Display total memes, top users, subreddits, and keywords."""
        try:
            all_stats = await get_dashboard_stats()
            total = all_stats.get("total_memes", 0)
            nsfw = all_stats.get("nsfw_memes", 0)
            users = all_stats.get("user_counts", {})
            subs = all_stats.get("subreddit_counts", {})
            kws = all_stats.get("keyword_counts", {})

            # Get top users, subreddits, keywords
            top_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:5]
            top_subs = sorted(subs.items(), key=lambda x: x[1], reverse=True)[:5]
            top_kws = sorted(kws.items(), key=lambda x: x[1], reverse=True)[:5]

            # Format user lines with usernames if possible, else show mention
            user_lines = []
            for uid, count in top_users:
                try:
                    member = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
                    name = member.display_name
                except Exception:
                    name = f"<@{uid}>"
                user_lines.append(f"{name}: {count}")
            user_lines = "\n".join(user_lines) or "None"

            sub_lines = "\n".join(f"{s}: {c}" for s, c in top_subs) or "None"
            kw_lines = "\n".join(f"{k}: {c}" for k, c in top_kws) or "None"

            # Build the embed
            embed = discord.Embed(
                title="📊 MemeBot Dashboard",
                description="View detailed stats at the [Web Dashboard](http://your-bot-url/stats)!",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="😂 Total Memes",    value=str(total),      inline=True)
            embed.add_field(name="🔞 NSFW Memes",     value=str(nsfw),       inline=True)
            embed.add_field(name="\u200b",            value="\u200b",        inline=True)  # spacer
            embed.add_field(name="🥇 Top Users",      value=user_lines,      inline=False)
            embed.add_field(name="🌐 Top Subreddits", value=sub_lines,       inline=False)
            embed.add_field(name="🔍 Top Keywords",   value=kw_lines,        inline=False)

            await ctx.reply(embed=embed, ephemeral=True)

        except Exception:
            log.error("dashboard command error", exc_info=True)
            await ctx.reply("❌ Error generating dashboard.", ephemeral=True)

    @commands.hybrid_command(name="help", description="Show all available commands")
    async def help(self, ctx: commands.Context):
        """Show a list of available bot commands."""
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here's what I can do:",
            color=discord.Color.blurple()
        )

        # ---------------- User Commands ----------------
        user_cmds = [
            "`/meme [keyword]` - Fetch a SFW meme",
            "`/nsfwmeme [keyword]` - Fetch a NSFW meme",
            "`/r_ <subreddit> [keyword]` - Fetch from a specific subreddit",
            "`/dashboard` - Show stats and leaderboards",
            "`/entrance` - Set or preview your entrance sound (full UI)",
            "`/beeps` - Play a random beep or choose one",
        ]
        embed.add_field(name="User Commands", value="\n".join(user_cmds), inline=False)

        # ---------------- Admin Commands ----------------
        admin_cmds = [
            "`/memeadmin ping` - Check bot latency",
            "`/memeadmin uptime` - Show bot uptime",
            "`/memeadmin addsubreddit` - Add a subreddit to SFW or NSFW list",
            "`/memeadmin removesubreddit` - Remove a subreddit from SFW or NSFW list",
            "`/memeadmin validatesubreddits` - Validate current subreddits",
            "`/memeadmin reset_voice_error` - Reset voice error cooldowns",
            "`/memeadmin set_idle_timeout` - Set or disable idle timeout for voice",
            "`/memeadmin setentrance` - Set a user's entrance sound",
            "`/memeadmin cacheinfo` - Show the current audio cache stats",
        ]
        embed.add_field(name="Admin Commands", value="\n".join(admin_cmds), inline=False)

        # ---------------- Dynamic Info ----------------
        sfw = ", ".join(get_guild_subreddits(ctx.guild.id, "sfw")) or "None"
        nsfw = ", ".join(get_guild_subreddits(ctx.guild.id, "nsfw")) or "None"
        embed.add_field(
            name="Loaded Subreddits",
            value=f"**SFW:** {sfw}\n**NSFW:** {nsfw}",
            inline=False,
        )

        beep_cog = self.bot.get_cog("Beep")
        if beep_cog:
            beeps = ", ".join(beep_cog.get_valid_files()) or "None"
            embed.add_field(
                name="Available Beeps",
                value=beeps,
                inline=False,
            )

        await ctx.reply(embed=embed, ephemeral=True)

    @help.error
    async def help_error(self, ctx, error):
        log.error("Help command error", exc_info=error)
        await ctx.reply("❌ Could not show help. Please try again later.", ephemeral=True)


    @meme.error
    async def meme_error(self, ctx, error):
        # this will catch exceptions from your meme() command
        log.error("Error in /meme command", exc_info=error)
        # if you already deferred, send via followup
        try:
            await ctx.interaction.followup.send(
                "❌ Oops—something went wrong fetching your meme. Please try again later.",
                ephemeral=True
            )
        except Exception:
            # if followup fails, fall back to a response
            await ctx.interaction.response.send_message(
                "❌ Oops—something went wrong!",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meme(bot))

class MemeView(discord.ui.View):
    def __init__(self, ctx, cog, original_cmd, keyword, subreddit=None, gallery_urls=None):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.cog = cog
        self.original_cmd = original_cmd
        self.keyword = keyword
        self.subreddit = subreddit
        self.gallery_urls = gallery_urls or []
        self.index = 0
        
        # Add Pagination buttons if gallery
        if len(self.gallery_urls) > 1:
            self.update_buttons()

    def update_buttons(self):
        # Remove existing paginators
        for child in list(self.children):
             if getattr(child, "custom_id", "") in ("prev_img", "next_img"):
                 self.remove_item(child)
        
        # Prev
        self.add_item(discord.ui.Button(
            label="◀", 
            style=discord.ButtonStyle.secondary, 
            custom_id="prev_img", 
            disabled=(self.index == 0),
            row=0
        ))
        # Next
        self.add_item(discord.ui.Button(
            label="▶", 
            style=discord.ButtonStyle.secondary, 
            custom_id="next_img", 
            disabled=(self.index == len(self.gallery_urls) - 1),
            row=0
        ))
        # Delete is maintained (or re-added if order matters, but simpler to just append)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # discord.py Interaction object strictly speaking doesn't have .custom_id 
        # for all types, but for component interactions it's in .data['custom_id']
        # or properly casted. Safest access:
        custom_id = interaction.data.get("custom_id")
        
        if custom_id == "delete":
             return True # Handled in callback
             
        if custom_id in ("prev_img", "next_img"):
            if custom_id == "prev_img":
                self.index = max(0, self.index - 1)
            else:
                self.index = min(len(self.gallery_urls) - 1, self.index + 1)
            
            # Rebuild embed with new image
            embed = interaction.message.embeds[0]
            start_url = self.gallery_urls[self.index]
            
            # Ensure reddit url vs media url?
            # send_meme uses helper, but here we have the raw url.
            # Just set image.
            embed.set_image(url=start_url)
            
            # Update footer for "Image X of Y"
            footer_text = embed.footer.text
            if " • Image " in footer_text:
                parts = footer_text.split(" • Image ")
                base = parts[0]
            else:
                base = footer_text
            embed.set_footer(text=f"{base} • Image {self.index + 1} of {len(self.gallery_urls)}")
            
            self.update_buttons()
            await interaction.response.edit_message(embed=embed, view=self)
            return True
            
        return True

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="delete", row=1)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.ctx.author.id:
            try:
                await interaction.message.delete()
            except:
                pass
        else:
             await interaction.response.send_message("Only the requester can delete this!", ephemeral=True)
