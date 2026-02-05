"""Sound playback and management API endpoints"""
import os
import asyncio
import json
import uuid
import time
from pathlib import Path
from collections import defaultdict, deque
from quart import Blueprint, request, jsonify
from quart_discord import requires_authorization

from memer.config import SOUND_FOLDER
from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.helpers import db
from memer.web.utils.media import generate_thumbnail, generate_waveform_image
from memer.web.utils.security import sanitize_filename, allowed_file

# Module dependencies (injected by webbox)
_bot = None
_discord_oauth = None
_ws_clients = None
_logger = None

# BETA SECURITY: Rate limiting for uploads (5 per minute per user)
_upload_timestamps = defaultdict(deque)  # {user_id: deque of timestamps}
RATE_LIMIT_UPLOADS = 5
RATE_LIMIT_WINDOW = 60  # seconds

def is_rate_limited(user_id: int) -> tuple[bool, int]:
    """Check if user is rate limited. Returns (is_limited, retry_after_seconds)."""
    now = time.time()
    timestamps = _upload_timestamps[user_id]

    # Remove timestamps older than the window
    while timestamps and timestamps[0] < now - RATE_LIMIT_WINDOW:
        timestamps.popleft()

    # Check if limit exceeded
    if len(timestamps) >= RATE_LIMIT_UPLOADS:
        oldest = timestamps[0]
        retry_after = int(RATE_LIMIT_WINDOW - (now - oldest))
        return True, retry_after

    # Add current timestamp
    timestamps.append(now)
    return False, 0

def init_sounds_api(bot, discord_oauth, ws_clients, logger):
    """Initialize module dependencies"""
    global _bot, _discord_oauth, _ws_clients, _logger
    _bot = bot
    _discord_oauth = discord_oauth
    _ws_clients = ws_clients
    _logger = logger

def create_sounds_blueprint() -> Blueprint:
    """Create and return sounds API blueprint"""
    bp = Blueprint('sounds_api', __name__, url_prefix='/api')

    @bp.route("/play/<filename>")
    @requires_authorization
    async def play_sound(filename):
        """Queue sound to play in user's voice channel"""
        user = await _discord_oauth.fetch_user()
        user_id = user.id

        # BETA SECURITY: Blocklist check
        if await db.is_user_blocked(user_id):
            return "Access denied. Your account has been blocked.", 403

        # Find User in Voice
        target_vc = None
        user_member = None

        # Search all guilds to find where the user is connected
        for guild in _bot.guilds:
            member = guild.get_member(user_id)
            if member and member.voice and member.voice.channel:
                target_vc = member.voice.channel
                user_member = member
                break

        if not target_vc:
            return "You need to join a voice channel to play this sound!", 400

        # Security Check
        clean_name = sanitize_filename(filename)
        if clean_name != filename:
             return "Invalid filename", 400

        file_path = os.path.join(SOUND_FOLDER, clean_name)
        if not os.path.exists(file_path):
            return "File not found", 404

        # V3.6: Check Guild Permission
        sound_info = await db.get_sound_by_filename(clean_name)
        if sound_info and sound_info['guild_id']:
            if target_vc.guild.id != sound_info['guild_id']:
                return "This sound is exclusive to another server!", 403

        # Queue Audio
        success = await queue_audio(
            target_vc,
            user_member,
            file_path,
            1.0,
            None, # No interaction context
            play_clip # The player function
        )

        if success:
            # Update Stats (V3.7.5: use database instead of JSON)
            await db.increment_sound_play_count(clean_name)

            # Notify Ticker (via WebSocket) if possible
            if _ws_clients:
                # V3.6.1: Get display name from database instead of JSON metadata
                display_name = clean_name
                play_count = 1
                if sound_info:
                    if sound_info.get('display_name'):
                        display_name = sound_info['display_name']
                    play_count = (sound_info.get('play_count') or 0) + 1

                msg = {
                    "type": "ticker_update",
                    "data": {
                        "filename": clean_name,
                        "play_count": play_count,
                        "message": f"Played: {display_name}"
                    }
                }
                # Simple broadcast loop
                filtered_clients = [ws for ws in _ws_clients.keys()]
                for ws in filtered_clients:
                    try:
                        await ws.send(json.dumps(msg))
                    except:
                        pass

            return "Playing", 200
        else:
            return "Failed to queue", 500

    @bp.route("/upload", methods=["POST"])
    @requires_authorization
    async def upload_file():
        """Upload sound files with auto-conversion to Opus"""
        form = await request.form
        raw_guild_id = form.get("guild_id")
        _logger.info(f"[UPLOAD DEBUG] Received raw_guild_id: {raw_guild_id!r} (type: {type(raw_guild_id).__name__})")
        guild_id = int(raw_guild_id) if raw_guild_id and raw_guild_id not in ("null", "global", "") else None
        _logger.info(f"[UPLOAD DEBUG] Converted to guild_id: {guild_id!r} (type: {type(guild_id).__name__})")

        user = await _discord_oauth.fetch_user()

        # BETA SECURITY: Blocklist check
        if await db.is_user_blocked(user.id):
            return "Access denied. Your account has been blocked.", 403

        # BETA SECURITY: Rate limiting check
        is_limited, retry_after = is_rate_limited(user.id)
        if is_limited:
            return f"Rate limit exceeded. Try again in {retry_after} seconds.", 429

        files = await request.files
        uploaded_files = files.getlist('file')
        if not uploaded_files:
             return "No files found", 400

        # BETA SECURITY: Check sound limit per guild
        if guild_id is not None:
            from memer.config import MAX_SOUNDS_PER_GUILD
            current_count = await db.count_sounds_for_guild(guild_id)
            files_to_upload = len([f for f in uploaded_files if f.filename])

            if current_count + files_to_upload > MAX_SOUNDS_PER_GUILD:
                return f"Server sound limit reached ({current_count}/{MAX_SOUNDS_PER_GUILD}). Cannot upload {files_to_upload} more.", 400

        saved_count = 0
        errors = []

        for file in uploaded_files:
            if file.filename == '': continue

            # Original name for Display Name
            original_clean_name = sanitize_filename(Path(file.filename).stem)
            ext = Path(file.filename).suffix.lower()

            if not allowed_file(file.filename):
                errors.append(f"Invalid type: {file.filename}")
                continue

            # Generate UUID
            file_uuid = str(uuid.uuid4())
            save_name = f"{file_uuid}{ext}"
            save_path = os.path.join(SOUND_FOLDER, save_name)

            await file.save(save_path)

            final_filename = save_name

            # Auto-Convert to Opus (if audio)
            if ext in {'.mp3', '.wav', '.m4a'}:
                try:
                    target_name = f"{file_uuid}.opus"
                    target_path = os.path.join(SOUND_FOLDER, target_name)

                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", str(save_path),
                        "-c:a", "libopus", "-b:a", "96k",
                        "-ac", "2", "-v", "error", str(target_path),
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.wait()

                    # If successful, use opus as the entry
                    if os.path.exists(target_path):
                        final_filename = target_name
                except Exception as e:
                    _logger.error(f"Conversion failed for {save_name}: {e}")

            # Insert into DB
            await db.add_sound(
                file_uuid,
                guild_id,
                final_filename,
                original_clean_name, # Display Name
                user.id
            )
            saved_count += 1

            # Generate assets
            final_path = os.path.join(SOUND_FOLDER, final_filename)
            final_ext = Path(final_filename).suffix.lower()

            if final_ext in {'.png', '.jpg', '.jpeg', '.gif'}:
                 asyncio.create_task(generate_thumbnail(final_path))

            if final_ext in {'.mp3', '.wav', '.opus', '.m4a', '.ogg'}:
                 asyncio.create_task(generate_waveform_image(final_path))

        # Sync and Reload
        if saved_count > 0:
            entrance_cog = _bot.get_cog("Entrance")
            if entrance_cog:
                entrance_cog.reload_cache()

        if saved_count == 0 and errors:
            return f"Failed: {', '.join(errors)}", 400

        return f"Uploaded {saved_count} files.", 200

    @bp.route("/sound/image", methods=["POST"])
    @requires_authorization
    async def upload_sound_image():
        """Upload image/thumbnail for a sound"""
        # Validate form data
        files = await request.files
        form = await request.form

        uploaded_file = files.get('file')
        filename = form.get('filename')

        if not uploaded_file or not filename:
            return "Missing file or filename", 400

        clean_filename = sanitize_filename(filename)
        if not os.path.exists(os.path.join(SOUND_FOLDER, clean_filename)):
            return "Target sound file not found", 404

        # Validate Image
        if not uploaded_file.filename:
            return "No selected file", 400

        ext = uploaded_file.filename.rsplit('.', 1)[1].lower() if '.' in uploaded_file.filename else ''
        if ext not in {'png', 'jpg', 'jpeg', 'gif'}:
             return "Invalid image type (png, jpg, jpeg, gif only)", 400

        # Save Image with same stem as sound
        stem = Path(clean_filename).stem
        save_name = f"{stem}.{ext}"
        save_path = os.path.join(SOUND_FOLDER, save_name)

        # Remove existing images for this sound
        for e in {'png', 'jpg', 'jpeg', 'gif'}:
            p = os.path.join(SOUND_FOLDER, f"{stem}.{e}")
            if os.path.exists(p):
                os.remove(p)

        await uploaded_file.save(save_path)

        # Generate Thumbnail
        asyncio.create_task(generate_thumbnail(save_path))

        return "Image uploaded", 200

    @bp.route("/sound/rename", methods=["POST"])
    @requires_authorization
    async def rename_sound():
        """Update sound metadata (display name, tags, shortcut)"""
        user = await _discord_oauth.fetch_user()

        req = await request.json
        if not req: return "Invalid JSON", 400

        filename = req.get("filename")
        new_name = req.get("new_name")
        tags = req.get("tags", [])  # Array of tags from frontend
        shortcut_key = req.get("shortcut_key", "")  # Single char

        if not filename or not new_name:
            return "Missing parameters", 400

        # DB Lookup (V3.6)
        sound = await db.get_sound_by_filename(filename)

        # Fallback checks
        if not sound:
             clean_name = sanitize_filename(filename)
             sound = await db.get_sound_by_filename(clean_name)

        if not sound:
            return "Sound not found in database", 404

        # Convert tags array to comma-separated string for DB
        tags_str = ",".join(tags) if isinstance(tags, list) else str(tags or "")
        shortcut = shortcut_key[:1].upper() if shortcut_key else None

        # Update (V3.7.5: now includes tags and shortcut)
        await db.update_sound(sound["id"], new_name.strip(), tags_str, shortcut)

        return "Renamed", 200

    @bp.route("/sound/favorite", methods=["POST"])
    @requires_authorization
    async def toggle_favorite():
        """Toggle favorite status for a sound"""
        user = await _discord_oauth.fetch_user()
        req = await request.json
        filename = req.get("filename")

        if not filename: return "Missing filename", 400

        # V3.7.5: Use database instead of JSON
        action = await db.toggle_user_favorite(user.id, filename)

        return jsonify({"status": "success", "action": action})

    return bp
