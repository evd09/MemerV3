"""Template rendering routes"""
import json
from pathlib import Path
from quart import Blueprint, render_template, redirect, request
from quart_discord import requires_authorization, Unauthorized

from memer.config import SOUND_FOLDER, TICKER_SPEED
from memer.helpers import db
from memer.meme_stats import get_dashboard_stats, get_top_reacted_memes

# Module dependencies (injected by webbox)
_bot = None
_discord_oauth = None

def init_views(bot, discord_oauth):
    """Initialize module dependencies"""
    global _bot, _discord_oauth
    _bot = bot
    _discord_oauth = discord_oauth

def create_views_blueprint() -> Blueprint:
    """Create and return views blueprint"""
    bp = Blueprint('views', __name__)

    @bp.route("/")
    async def home():
        """Main dashboard/soundboard"""
        user = None
        try:
            user = await _discord_oauth.fetch_user()

            # Check if user is blocked
            if user:
                is_blocked = await db.is_user_blocked(user.id)
                if is_blocked:
                    from memer.utils.logger_setup import setup_logger
                    logger = setup_logger("web.views", "web.log")
                    logger.warning(f"🚫 Blocked user {user.id} ({user.name}) attempted to access home page - denying access")
                    _discord_oauth.revoke()
                    from quart import session
                    session.clear()
                    # Show blocked message instead of redirecting to login
                    return """
                    <html>
                    <head><title>Access Denied</title></head>
                    <body style="background: #18181b; color: #fff; font-family: system-ui; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
                        <div style="text-align: center; max-width: 500px; padding: 2rem;">
                            <h1 style="color: #ef4444; font-size: 3rem; margin: 0;">🚫 Access Denied</h1>
                            <p style="color: #a1a1aa; margin: 1rem 0;">Your account has been blocked from accessing this service.</p>
                            <p style="color: #71717a; font-size: 0.875rem;">If you believe this is an error, please contact the bot owner.</p>
                        </div>
                    </body>
                    </html>
                    """, 403

        except Unauthorized:
            pass

        sounds = []
        files = sorted(Path(SOUND_FOLDER).iterdir(), key=lambda f: f.name.lower())

        # Pre-scan for images and waveforms
        # Map clean name -> full filename
        images = {}
        thumbs = {}
        waveforms = {}
        for f in files:
            if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
                if "_thumb" in f.stem:
                    # Map base stem (remove _thumb) -> thumb filename
                    base = f.stem.replace("_thumb", "")
                    thumbs[base.lower()] = f.name
                elif "_wave" in f.stem:
                    # Map base stem (remove _wave) -> waveform filename
                    base = f.stem.replace("_wave", "")
                    waveforms[base.lower()] = f.name
                else:
                    images[f.stem.lower()] = f.name

        # Load User Favorites (V3.7.5: from database)
        user_favs = []
        if user:
             user_favs = await db.get_user_favorites(user.id)

        # Fetch Sounds from DB (Global + Guilds)
        user_guilds_ids = []
        user_guilds_data = [] # For dropdown
        if user:
             for g in _bot.guilds:
                 if g.get_member(user.id):
                     user_guilds_ids.append(g.id)
                     icon_url = g.icon.url if g.icon else None
                     user_guilds_data.append({"id": str(g.id), "name": g.name, "icon": icon_url})

        raw_sounds = await db.get_sounds_for_user(user_guilds_ids)

        for s in raw_sounds:
            f_name = s["filename"]
            stem = Path(f_name).stem.lower()

            # Image/Thumb Resolution
            thumb_url = f"/sounds/{thumbs[stem]}" if stem in thumbs else None
            image_url = f"/sounds/{images[stem]}" if stem in images else None
            wave_url = f"/sounds/{waveforms[stem]}" if stem in waveforms else None

            # Parse tags from comma-separated string (V3.7.5: from database)
            tags_str = s.get("tags") or ""
            tags_list = [t.strip() for t in tags_str.split(",") if t.strip()]

            sounds.append({
                "filename": f_name,
                "display_name": s["display_name"],
                "guild_id": str(s["guild_id"]) if s["guild_id"] is not None else None,
                "is_global": s["guild_id"] is None,
                "tags": tags_list,
                "shortcut": s.get("shortcut") or "",
                "is_favorite": f_name in user_favs,
                "image_url": image_url,
                "thumb_url": thumb_url,
                "wave_url": wave_url,
                "play_count": s.get("play_count", 0)
            })

        # Sort: Favorites first, then Alphabetical
        sounds.sort(key=lambda x: (not x['is_favorite'], x['display_name'].lower()))

        sounds_json = json.dumps(sounds)

        has_global_sounds = any(s['is_global'] for s in sounds)

        return await render_template("index.html",
            user=user,
            sounds=sounds,
            sounds_json=sounds_json,
            user_favs=user_favs,
            bot=_bot.user,
            ticker_speed=TICKER_SPEED,
            user_guilds=user_guilds_data,
            has_global_sounds=has_global_sounds
        )

    @bp.route("/stats")
    @requires_authorization
    async def stats_page():
        """Analytics dashboard"""
        user = await _discord_oauth.fetch_user()

        # Check if user is blocked
        if await db.is_user_blocked(user.id):
            _discord_oauth.revoke()
            from quart import session
            session.clear()
            return redirect(url_for("auth.login"))

        guild_id = request.args.get("guild_id")

        # V3.7.5: Build user's guild list (only servers they're in)
        user_guilds = []
        for g in _bot.guilds:
            mem = g.get_member(user.id)
            if mem:
                user_guilds.append({"id": str(g.id), "name": g.name})

        # If no guild selected, default to first guild user is in
        if not guild_id and user_guilds:
            guild_id = user_guilds[0]["id"]
            return redirect(f"/stats?guild_id={guild_id}")

        # Verify user is a member of the requested guild
        if guild_id and guild_id not in [g["id"] for g in user_guilds]:
            return "Access Denied: You are not a member of this server.", 403

        current_guild_name = "Select a Server"
        for g in user_guilds:
            if g["id"] == guild_id:
                current_guild_name = g["name"]
                break

        # Fetch stats for the selected guild
        stats = await get_dashboard_stats(guild_id)

        # Resolve User IDs to Names
        resolved_users = {}
        for uid, count in stats.get("user_counts", {}).items():
            name = f"User {uid}"
            try:
                u = _bot.get_user(int(uid))
                if u: name = u.display_name
            except:
                pass
            resolved_users[name] = count

        stats["user_counts"] = resolved_users

        # Fetch Top Memes (SFW vs NSFW)
        top_sfw = await get_top_reacted_memes(limit=5, guild_id=guild_id, nsfw_filter=False)
        top_nsfw = await get_top_reacted_memes(limit=5, guild_id=guild_id, nsfw_filter=True)

        top_sfw_resolved = list(top_sfw)
        top_nsfw_resolved = list(top_nsfw)

        return await render_template(
            "stats.html",
            stats=stats,
            guilds=user_guilds,
            current_guild_name=current_guild_name,
            current_guild_id=guild_id,
            top_reactions_sfw=top_sfw_resolved,
            top_reactions_nsfw=top_nsfw_resolved
        )

    @bp.route("/profile")
    @requires_authorization
    async def profile():
        """User profile page"""
        user = await _discord_oauth.fetch_user()

        # Check if user is blocked
        if await db.is_user_blocked(user.id):
            _discord_oauth.revoke()
            from quart import session
            session.clear()
            return redirect(url_for("auth.login"))

        # V3.6.1: Get user's guild IDs and Data for Selector
        user_guilds = []
        user_guild_ids = []
        for g in _bot.guilds:
            if g.get_member(user.id):
                user_guilds.append({
                    "id": str(g.id),
                    "name": g.name,
                    "icon": g.icon.url if g.icon else None
                })
                user_guild_ids.append(g.id)

        # V3.6.1: Get sounds from database filtered by user's guilds + global sounds
        available_sounds = await db.get_sounds_for_user(user_guild_ids)

        # Load user favorites (V3.7.5: from database)
        user_favs = await db.get_user_favorites(user.id)

        # Build list with display names from database
        sounds_list = []
        for sound in available_sounds:
            filename = sound['filename']
            display_name = sound['display_name']
            is_favorite = filename in user_favs
            sounds_list.append({
                "filename": filename,
                "display_name": display_name,
                "is_favorite": is_favorite,
                "guild_id": str(sound['guild_id']) if sound['guild_id'] else None,
                "is_global": sound['guild_id'] is None
            })

        # Sort: favorites first (alphabetically), then non-favorites (alphabetically)
        sounds_list.sort(key=lambda s: (not s["is_favorite"], s["display_name"].lower()))

        return await render_template("profile.html", user=user, sounds=sounds_list, bot=_bot.user, user_guilds=user_guilds)

    @bp.route("/guide")
    async def guide():
        """Onboarding and help guide"""
        user = None
        try:
            user = await _discord_oauth.fetch_user()

            # Check if user is blocked
            if user:
                is_blocked = await db.is_user_blocked(user.id)
                if is_blocked:
                    _discord_oauth.revoke()
                    from quart import session
                    session.clear()
                    return redirect("/guide")  # Redirect to guide without user context
        except Unauthorized:
            pass

        return await render_template("guide.html", user=user, bot=_bot.user)

    return bp
