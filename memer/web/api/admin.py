"""Admin dashboard and management API endpoints"""
import os
import json
from pathlib import Path
from quart import Blueprint, request, jsonify, render_template
from quart_discord import requires_authorization

from memer.config import SOUND_FOLDER
from memer.helpers import db
from memer.helpers.guild_subreddits import (
    get_guild_subreddits,
    add_guild_subreddit,
    remove_guild_subreddit,
    persist_cache
)
from memer.web.utils.security import sanitize_filename
from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio

# Module dependencies (injected by webbox)
_bot = None
_discord_oauth = None
_logger = None
_template_folder = None

def init_admin_api(bot, discord_oauth, logger, template_folder):
    """Initialize module dependencies"""
    global _bot, _discord_oauth, _logger, _template_folder
    _bot = bot
    _discord_oauth = discord_oauth
    _logger = logger
    _template_folder = template_folder

def create_admin_blueprint() -> Blueprint:
    """Create and return admin API blueprint"""
    bp = Blueprint('admin_api', __name__, url_prefix='/api/admin')

    # ==================== API ENDPOINTS ====================

    @bp.route("/entrance/overview")
    @requires_authorization
    async def get_entrance_overview():
        """Get entrance overview for all users in a guild"""
        user = await _discord_oauth.fetch_user()
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"error": "Missing guild_id"}), 400

        guild = _bot.get_guild(int(guild_id))
        if not guild:
            return jsonify({"error": "Guild not found"}), 404

        # Check Admin
        member = guild.get_member(user.id)
        if not member or not member.guild_permissions.administrator:
            return jsonify({"error": "Access Denied"}), 403

        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        # Filter users in this guild with entrances
        if not guild.chunked:
            await guild.chunk()

        # 1. Fetch all entrances for this guild in one query efficiently
        guild_entrances = await db.get_all_entrance_sounds_for_guild(int(guild_id))

        # 2. Fetch all proper sound names for this guild (plus globals) to resolve display names
        # Map filename -> display_name
        sound_list = await db.get_sounds_for_guild(int(guild_id))
        sound_map = {s['filename']: s['display_name'] for s in sound_list}

        results = []

        # iterate all members to match requirements of "All Users" filter in frontend
        for m in guild.members:
            uid_int = m.id

            # Check if this user has an entry
            entry = guild_entrances.get(uid_int)

            has_entrance = False
            file_info = "—"
            volume_info = 1.0
            ent_type = None

            if entry:
                has_entrance = True
                ent_type = entry.get('type', 'single')

                if ent_type == 'single':
                    fname = entry.get('filename')
                    if not fname:
                        # Fallback: Parse data if available
                        try:
                            raw = entry.get('data')
                            if isinstance(raw, str):
                                d = json.loads(raw)
                                fname = d.get('file')
                            elif isinstance(raw, dict):
                                fname = raw.get('file')
                        except:
                            pass

                    if fname:
                         display_name = sound_map.get(fname, fname)
                         file_info = display_name
                         volume_info = entry.get('volume', 1.0)
                    else:
                         file_info = "(Error)"

                elif ent_type == 'multiple':
                    data = entry.get('data', [])
                    count = len(data) if isinstance(data, list) else 0
                    file_info = f"{count} files (Pool)"
                    volume_info = "Mixed"

                elif ent_type == 'combo':
                    data = entry.get('data', [])
                    count = len(data) if isinstance(data, list) else 0
                    file_info = f"{count} files (Sequence)"
                    volume_info = "Mixed"

                elif ent_type == 'scheduled':
                    file_info = "Scheduled Rules"
                    volume_info = "Variable"

            results.append({
                "user_id": str(m.id),
                "username": m.name,
                "avatar": str(m.display_avatar.url) if m.display_avatar else None,
                "entrance_type": ent_type if has_entrance else None,
                "file": file_info if has_entrance else None,
                "volume": volume_info if has_entrance else None
            })

        return jsonify(results)

    @bp.route("/entrance/preview", methods=["POST"])
    @requires_authorization
    async def preview_entrance():
        """Preview entrance sound as admin"""
        user = await _discord_oauth.fetch_user()
        req = await request.json
        if not req:
            return "Invalid JSON", 400

        file_name = req.get("file")
        volume = float(req.get("volume", 1.0))

        # Admin needs to be in a VC
        target_vc = None
        user_member = None
        for guild in _bot.guilds:
            member = guild.get_member(user.id)
            if member and member.voice and member.voice.channel:
                target_vc = member.voice.channel
                user_member = member
                break

        if not target_vc:
            return "You must be in a voice channel", 400

        clean_name = sanitize_filename(file_name)
        path = os.path.join(SOUND_FOLDER, clean_name)
        if not os.path.exists(path):
            return "File not found", 404

        await queue_audio(target_vc, user_member, path, max(0.1, min(1.0, volume)), None, play_clip)
        return "Playing", 200

    @bp.route("/analytics")
    @requires_authorization
    async def get_analytics():
        """Get analytics for a guild"""
        user = await _discord_oauth.fetch_user()
        guild_id = request.args.get("guild_id")
        days = int(request.args.get("days", 30))

        if not guild_id:
            return jsonify({"error": "Missing guild_id"}), 400

        guild = _bot.get_guild(int(guild_id))
        if not guild:
            return jsonify({"error": "Guild not found"}), 404

         # Check Admin
        member = guild.get_member(user.id)
        if not member or not member.guild_permissions.administrator:
            return jsonify({"error": "Access Denied"}), 403

        analytics = await db.get_entrance_analytics(int(guild_id), days) or {}

        # Process and aggregate popular sounds (deduplicate mp3/opus)
        raw_popular = analytics.get("most_popular_sounds", [])

        # V3.7.5: Get display names from database instead of removed JSON
        sound_list = await db.get_sounds_for_guild(int(guild_id))
        sound_name_map = {s['filename']: s['display_name'] for s in sound_list}

        aggregated_stats = {}

        for row in raw_popular:
            filename = row["file"]
            stem = Path(filename).stem.lower() # Normalize to stem

            if stem not in aggregated_stats:
                display_name = sound_name_map.get(filename, filename)

                aggregated_stats[stem] = {
                    "file": filename,
                    "display_name": display_name,
                    "play_count": 0,
                    "unique_users": 0
                }

            aggregated_stats[stem]["play_count"] += row["play_count"]
            aggregated_stats[stem]["unique_users"] += row["unique_users"]

        # Convert to list and sort
        final_popular = sorted(
            list(aggregated_stats.values()),
            key=lambda x: x["play_count"],
            reverse=True
        )[:10]

        # V3.7: Get users with/without entrances from database
        users_with_entrance = analytics.get("users_with_entrance", set())
        total_set = len(users_with_entrance)

        # Calculate users without entrances
        users_without = []
        if not guild.chunked:
            await guild.chunk()

        for m in guild.members:
            if m.bot:
                continue  # Skip bots
            if m.id not in users_with_entrance:
                users_without.append({"user_id": str(m.id), "username": m.name})

        # Get entrance type distribution from database
        entrance_type_distribution = analytics.get("entrance_type_distribution", {})

        response = {
            "most_popular_sounds": final_popular,
            "users_without_entrances": users_without,
            "avg_volume": 1.0,
            "total_entrances_set": total_set,
            "entrance_type_distribution": entrance_type_distribution
        }
        return jsonify(response)

    @bp.route("/activity-log")
    @requires_authorization
    async def get_activity_log():
        """Get admin activity log for a guild"""
        user = await _discord_oauth.fetch_user()
        guild_id = request.args.get("guild_id")
        if not guild_id:
            return jsonify({"error": "Missing guild_id"}), 400

        limit = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
        action_type = request.args.get("action_type")
        if not action_type:
            action_type = None

        logs = await db.get_admin_activity_log(int(guild_id), limit, offset, action_type)
        return jsonify(logs)

    @bp.route("/entrance/<int:target_user_id>", methods=["DELETE"])
    @requires_authorization
    async def delete_entrance(target_user_id):
        """Delete entrance for a user (admin only)"""
        user = await _discord_oauth.fetch_user()
        guild_id = int(request.args.get("guild_id") or 0)
        if not guild_id:
            return jsonify({"error": "Missing guild_id"}), 400

        guild = _bot.get_guild(guild_id)
        if not guild:
            return jsonify({"error": "Guild not found"}), 404

        member = guild.get_member(user.id)
        if not member or not member.guild_permissions.administrator:
            return jsonify({"error": "Access Denied"}), 403

        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "System offline"}), 503

        # Remove from DB (V3.6)
        await db.delete_entrance_sound(target_user_id, guild_id)

        # Log action
        target_member = guild.get_member(target_user_id)
        target_name = target_member.name if target_member else f"User {target_user_id}"

        await db.log_admin_action(
            guild_id, user.id, user.username, "remove_entrance",
            {}, target_user_id, target_name
        )
        return "Removed", 200

    @bp.route("/entrance", methods=["POST"])
    @requires_authorization
    async def set_entrance():
        """Set entrance for a user (admin only)"""
        user = await _discord_oauth.fetch_user()
        form = await request.form

        guild_id = int(form.get("guild_id"))
        target_user_id = int(form.get("user_id"))
        file_name = form.get("file")
        volume = float(form.get("volume", 1.0))

        guild = _bot.get_guild(guild_id)
        if not guild:
            return "Guild not found", 404

        admin_member = guild.get_member(user.id)
        if not admin_member or not admin_member.guild_permissions.administrator:
            return "Access Denied", 403

        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return "Entrance system offline", 503

        target_member = guild.get_member(target_user_id)
        target_name = target_member.name if target_member else f"User {target_user_id}"

        if not file_name:
            # Remove
            await db.delete_entrance_sound(target_user_id, guild_id)

            await db.log_admin_action(
                guild_id, user.id, user.username, "remove_entrance",
                {}, target_user_id, target_name
            )
            return "Removed entrance", 200

        clean_name = sanitize_filename(file_name)
        if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
            return "File not found", 404

        # Save to DB (V3.6)
        await db.set_entrance_sound(target_user_id, guild_id, clean_name, max(0.1, min(1.0, volume)))

        # Log
        await db.log_admin_action(
            guild_id, user.id, user.username, "set_entrance",
            {"file": clean_name, "volume": volume}, target_user_id, target_name
        )

        return "Saved", 200

    @bp.route("/subreddit/add", methods=["POST"])
    @requires_authorization
    async def add_subreddit():
        """Add subreddit to guild (admin only)"""
        user = await _discord_oauth.fetch_user()
        form = await request.form

        guild_id = int(form.get("guild_id"))
        subreddit_name = form.get("subreddit")
        sub_type = form.get("type") # sfw or nsfw

        if not subreddit_name or sub_type not in ["sfw", "nsfw"]:
             return "Invalid parameters", 400

        guild = _bot.get_guild(guild_id)
        if not guild:
            return "Guild not found", 404

        member = guild.get_member(user.id)
        if not member or not member.guild_permissions.administrator:
            return "Access Denied", 403

        meme_cog = _bot.get_cog("Meme")
        if not meme_cog:
             return "Meme system offline", 503

        # Validate Subreddit
        try:
            # Use the existing reddit instance from Meme cog
            sub = await meme_cog.reddit.subreddit(subreddit_name, fetch=True)

            # Check for NSFW compatibility
            if sub_type == "sfw" and sub.over18:
                 return "Cannot add NSFW subreddit to SFW list.", 400

        except Exception as e:
            return f"Subreddit validation failed: {str(e)}", 400

        await add_guild_subreddit(guild_id, subreddit_name, sub_type)
        persist_cache()

        # Log action
        await db.log_admin_action(
            guild_id, user.id, user.username, "add_subreddit",
            {"subreddit": subreddit_name, "category": sub_type}
        )

        # Return JSON for dynamic update
        current_list = await get_guild_subreddits(guild_id, sub_type)
        return jsonify({
            "success": True,
            "subreddit": subreddit_name,
            "updated_list": current_list
        })

    @bp.route("/subreddit/remove", methods=["POST"])
    @requires_authorization
    async def remove_subreddit():
        """Remove subreddit from guild (admin only)"""
        user = await _discord_oauth.fetch_user()
        form = await request.form

        guild_id = int(form.get("guild_id"))
        subreddit_name = form.get("subreddit")
        sub_type = form.get("type")

        guild = _bot.get_guild(guild_id)
        if not guild:
            return "Guild not found", 404

        member = guild.get_member(user.id)
        if not member or not member.guild_permissions.administrator:
            return "Access Denied", 403

        await remove_guild_subreddit(guild_id, subreddit_name, sub_type)
        persist_cache()

        # Log action
        await db.log_admin_action(
            guild_id, user.id, user.username, "remove_subreddit",
            {"subreddit": subreddit_name, "category": sub_type}
        )

        # Return JSON
        current_list = await get_guild_subreddits(guild_id, sub_type)
        return jsonify({
            "success": True,
            "subreddit": subreddit_name,
            "updated_list": current_list
        })

    # ==================== BETA SECURITY: User Blocklist Management ====================

    @bp.route("/blocklist", methods=["GET"])
    @requires_authorization
    async def get_blocklist():
        """Get all blocked users (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        # Only bot owner can manage global blocklist
        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        blocked_users = await db.get_all_blocked_users()

        # Resolve user IDs to names
        for entry in blocked_users:
            try:
                discord_user = _bot.get_user(entry["user_id"])
                entry["username"] = discord_user.name if discord_user else f"User {entry['user_id']}"
            except:
                entry["username"] = f"User {entry['user_id']}"

            # Resolve blocker
            try:
                blocker = _bot.get_user(entry["blocked_by"])
                entry["blocked_by_name"] = blocker.name if blocker else f"User {entry['blocked_by']}"
            except:
                entry["blocked_by_name"] = f"User {entry['blocked_by']}"

            # Convert IDs to strings to prevent JavaScript number precision loss
            entry["user_id"] = str(entry["user_id"])
            entry["blocked_by"] = str(entry["blocked_by"])

        return jsonify({"blocked_users": blocked_users})

    @bp.route("/blocklist/add", methods=["POST"])
    @requires_authorization
    async def add_to_blocklist():
        """Add user to blocklist (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        data = await request.json
        target_user_id = int(data.get("user_id"))
        reason = data.get("reason", "No reason provided")

        success = await db.add_user_to_blocklist(target_user_id, reason, user.id)

        if success:
            _logger.info(f"User {target_user_id} added to blocklist by {user.id} (reason: {reason})")
            return jsonify({"success": True, "message": f"User {target_user_id} blocked"})
        else:
            return jsonify({"success": False, "error": "Database error"}), 500

    @bp.route("/blocklist/remove", methods=["POST"])
    @requires_authorization
    async def remove_from_blocklist():
        """Remove user from blocklist (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        data = await request.json
        target_user_id = int(data.get("user_id"))

        success = await db.remove_user_from_blocklist(target_user_id)

        if success:
            _logger.info(f"User {target_user_id} removed from blocklist by {user.id}")
            return jsonify({"success": True, "message": f"User {target_user_id} unblocked"})
        else:
            return jsonify({"success": False, "error": "Database error"}), 500

    @bp.route("/blocklist/clear", methods=["POST"])
    @requires_authorization
    async def clear_all_blocklist():
        """Clear all users from blocklist (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        count = await db.clear_all_blocklist()

        _logger.info(f"All {count} blocked users cleared by {user.id}")
        return jsonify({"success": True, "count": count})

    # ==================== STORAGE MANAGEMENT ====================

    @bp.route("/storage/stats", methods=["GET"])
    @requires_authorization
    async def get_storage_stats():
        """Get disk usage statistics for sounds folder (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        try:
            sounds_path = Path(SOUND_FOLDER)
            if not sounds_path.exists():
                return jsonify({"error": "Sounds folder not found"}), 404

            total_size = 0
            file_count = 0
            originals_size = 0
            converted_size = 0

            # Count all files and sizes
            for file in sounds_path.glob("*"):
                if file.is_file():
                    size = file.stat().st_size
                    total_size += size
                    file_count += 1

                    # Check if it's an original or converted file
                    if file.suffix.lower() == ".opus":
                        converted_size += size
                    elif file.suffix.lower() in {".mp3", ".wav", ".m4a"}:
                        originals_size += size
                    elif file.suffix.lower() == ".webp" and "_thumb" in file.stem:
                        converted_size += size
                    elif file.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
                        originals_size += size

            return jsonify({
                "total_size": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "file_count": file_count,
                "originals_size": originals_size,
                "originals_size_mb": round(originals_size / (1024 * 1024), 2),
                "converted_size": converted_size,
                "converted_size_mb": round(converted_size / (1024 * 1024), 2)
            })

        except Exception as e:
            _logger.error(f"Failed to get storage stats: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/storage/cleanup-candidates", methods=["GET"])
    @requires_authorization
    async def get_cleanup_candidates():
        """List files that have converted versions and can be cleaned up (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        try:
            sounds_path = Path(SOUND_FOLDER)
            if not sounds_path.exists():
                return jsonify({"error": "Sounds folder not found"}), 404

            candidates = []

            # Check for audio files with opus versions
            for ext in [".mp3", ".wav", ".m4a"]:
                for original in sounds_path.glob(f"*{ext}"):
                    opus_file = original.with_suffix(".opus")
                    if opus_file.exists():
                        candidates.append({
                            "original": original.name,
                            "converted": opus_file.name,
                            "original_size": original.stat().st_size,
                            "converted_size": opus_file.stat().st_size,
                            "type": "audio",
                            "savings_bytes": original.stat().st_size
                        })

            # Check for image files with webp thumbnails
            for ext in [".png", ".jpg", ".jpeg", ".gif"]:
                for original in sounds_path.glob(f"*{ext}"):
                    # Check if there's a _thumb.webp version
                    thumb_file = original.with_name(f"{original.stem}_thumb.webp")
                    if thumb_file.exists():
                        candidates.append({
                            "original": original.name,
                            "converted": thumb_file.name,
                            "original_size": original.stat().st_size,
                            "converted_size": thumb_file.stat().st_size,
                            "type": "image",
                            "savings_bytes": original.stat().st_size
                        })

            # Sort by size descending (biggest files first)
            candidates.sort(key=lambda x: x["original_size"], reverse=True)

            total_savings = sum(c["savings_bytes"] for c in candidates)

            return jsonify({
                "candidates": candidates,
                "total_count": len(candidates),
                "total_savings": total_savings,
                "total_savings_mb": round(total_savings / (1024 * 1024), 2)
            })

        except Exception as e:
            _logger.error(f"Failed to get cleanup candidates: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/storage/delete-originals", methods=["POST"])
    @requires_authorization
    async def delete_original_files():
        """Delete selected original files (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        try:
            data = await request.json
            filenames = data.get("filenames", [])

            if not filenames:
                return jsonify({"error": "No files specified"}), 400

            sounds_path = Path(SOUND_FOLDER)
            deleted = []
            errors = []
            total_freed = 0

            for filename in filenames:
                file_path = sounds_path / filename

                # Security check: ensure file is in sounds folder
                if not file_path.resolve().parent == sounds_path.resolve():
                    errors.append(f"{filename}: Invalid path")
                    continue

                if not file_path.exists():
                    errors.append(f"{filename}: File not found")
                    continue

                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted.append(filename)
                    total_freed += file_size
                    _logger.info(f"Deleted original file: {filename} ({file_size} bytes) by user {user.id}")
                except Exception as e:
                    errors.append(f"{filename}: {str(e)}")

            return jsonify({
                "success": True,
                "deleted": deleted,
                "deleted_count": len(deleted),
                "errors": errors,
                "freed_bytes": total_freed,
                "freed_mb": round(total_freed / (1024 * 1024), 2)
            })

        except Exception as e:
            _logger.error(f"Failed to delete original files: {e}")
            return jsonify({"error": str(e)}), 500

    # ==================== BETA SECURITY: Guild Management ====================

    @bp.route("/guilds", methods=["GET"])
    @requires_authorization
    async def get_all_guilds():
        """Get all guilds the bot is in (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        guilds_data = []
        for guild in _bot.guilds:
            guilds_data.append({
                "id": str(guild.id),
                "name": guild.name,
                "member_count": guild.member_count,
                "icon": guild.icon.url if guild.icon else None,
                "owner_id": str(guild.owner_id)
            })

        # Sort by member count descending
        guilds_data.sort(key=lambda g: g["member_count"], reverse=True)

        return jsonify({"guilds": guilds_data})

    @bp.route("/guild/<int:guild_id>/stats", methods=["GET"])
    @requires_authorization
    async def get_guild_stats(guild_id):
        """Get stats for what will be deleted if guild is purged (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        stats = await db.get_guild_data_stats(guild_id)
        return jsonify(stats)

    @bp.route("/guild/<int:guild_id>/leave", methods=["POST"])
    @requires_authorization
    async def leave_guild(guild_id):
        """Make bot leave a guild (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        guild = _bot.get_guild(guild_id)
        if not guild:
            return jsonify({"success": False, "error": "Guild not found"}), 404

        guild_name = guild.name

        try:
            await guild.leave()
            _logger.info(f"Bot left guild {guild_name} ({guild_id}) - triggered by owner {user.id}")
            return jsonify({"success": True, "message": f"Left {guild_name}"})
        except Exception as e:
            _logger.error(f"Failed to leave guild {guild_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/guild/<int:guild_id>/purge", methods=["POST"])
    @requires_authorization
    async def purge_guild_data(guild_id):
        """Delete all data for a guild (Bot Owner only)"""
        user = await _discord_oauth.fetch_user()

        if user.id != _bot.owner_id:
            return "Access Denied: Bot owner only", 403

        try:
            deleted = await db.purge_guild_data(guild_id)
            _logger.info(f"Purged guild {guild_id} data - triggered by owner {user.id}. Deleted: {deleted}")
            return jsonify({
                "success": True,
                "message": f"Deleted all data for guild",
                "deleted": deleted
            })
        except Exception as e:
            _logger.error(f"Failed to purge guild {guild_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    return bp


def create_admin_views_blueprint() -> Blueprint:
    """Create and return admin views blueprint (separate from API)"""
    bp = Blueprint('admin_views', __name__)

    @bp.route("/admin")
    @requires_authorization
    async def admin_dashboard():
        """Admin dashboard - shows all guilds where user is admin"""
        user = await _discord_oauth.fetch_user()

        # Check if user is blocked
        if await db.is_user_blocked(user.id):
            _discord_oauth.revoke()
            from quart import session
            session.clear()
            return redirect(url_for("auth.login"))

        admin_guilds = []
        is_bot_owner = (user.id == _bot.owner_id)

        for guild in _bot.guilds:
            member = guild.get_member(user.id)
            if member and member.guild_permissions.administrator:
                admin_guilds.append({"id": str(guild.id), "name": guild.name})

        return await render_template("admin.html", guilds=admin_guilds, selected_guild=None, bot=_bot.user, is_bot_owner=is_bot_owner)

    @bp.route("/admin/<int:guild_id>")
    @requires_authorization
    async def admin_guild_view(guild_id):
        """Admin dashboard for specific guild"""
        user = await _discord_oauth.fetch_user()

        # Check if user is blocked
        if await db.is_user_blocked(user.id):
            _discord_oauth.revoke()
            from quart import session
            session.clear()
            return redirect(url_for("auth.login"))

        guild = _bot.get_guild(guild_id)

        if not guild:
            return "Guild not found", 404

        member = guild.get_member(user.id)
        if not member or not member.guild_permissions.administrator:
            return "Access Denied: You are not an admin of this server.", 403

        # Fetch members for datalist
        if not guild.chunked:
            await guild.chunk()

        members = [{"id": str(m.id), "name": m.display_name} for m in guild.members]

        # Fetch Sounds from DB (Global + Guild)
        raw_sounds = await db.get_sounds_for_guild(guild_id)

        sounds = []
        for s in raw_sounds:
            sounds.append({
                "filename": s["filename"],
                "display_name": s["display_name"],
                "guild_id": s["guild_id"],
                "is_global": s["guild_id"] is None
            })

        # Fetch subreddits
        sfw_subs = await get_guild_subreddits(guild_id, "sfw")
        nsfw_subs = await get_guild_subreddits(guild_id, "nsfw")

        # Fetch Cache Info
        cache_stats = None
        meme_cog = _bot.get_cog("Meme")
        if meme_cog:
            if hasattr(meme_cog, 'cache_service'):
                 cache_stats = await meme_cog.cache_service.get_cache_info()

        is_bot_owner = (user.id == _bot.owner_id)

        return await render_template(
            "admin.html",
            guilds=[],
            selected_guild={"id": str(guild.id), "name": guild.name},
            members=members,
            sounds=sounds,
            bot=_bot.user,
            is_bot_owner=is_bot_owner,
            sfw_subs=sfw_subs,
            nsfw_subs=nsfw_subs,
            cache_stats=cache_stats
        )

    return bp
