"""Entrance sound configuration API endpoints"""
import os
from quart import Blueprint, request, jsonify
from quart_discord import requires_authorization

from memer.config import SOUND_FOLDER
from memer.helpers import db
from memer.web.utils.security import sanitize_filename

# Module dependencies (injected by webbox)
_bot = None
_discord_oauth = None
_logger = None

def init_entrance_api(bot, discord_oauth, logger):
    """Initialize module dependencies"""
    global _bot, _discord_oauth, _logger
    _bot = bot
    _discord_oauth = discord_oauth
    _logger = logger

def create_entrance_blueprint() -> Blueprint:
    """Create and return entrance API blueprint"""
    bp = Blueprint('entrance_api', __name__, url_prefix='/api')

    @bp.route("/entrance", methods=["GET"])
    @requires_authorization
    async def get_entrance():
        """Get entrance configuration (legacy)"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        data = entrance_cog.entrance_data.get(str(user.id), {})
        return jsonify({
            "file": data.get("file"),
            "volume": data.get("volume", 1.0)
        })

    @bp.route("/entrance", methods=["POST"])
    @requires_authorization
    async def set_entrance():
        """Set entrance configuration (legacy)"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        form = await request.form
        # Handle JSON or Form
        if not form:
            req_json = await request.json
            if req_json:
                file_name = req_json.get("file")
                volume = float(req_json.get("volume", 1.0))
            else:
                return "No data", 400
        else:
            file_name = form.get("file")
            volume = float(form.get("volume", 1.0))

        if not file_name:
            # Remove entrance
            if str(user.id) in entrance_cog.entrance_data:
                del entrance_cog.entrance_data[str(user.id)]
                entrance_cog.save_data()
            return "Removed", 200

        # Validate file exists
        clean_name = sanitize_filename(file_name)
        if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
            return "File does not exist", 404

        # Cap volume
        volume = max(0.1, min(1.0, volume))

        entrance_cog.entrance_data[str(user.id)] = {
            "file": clean_name,
            "volume": volume
        }
        entrance_cog.save_data()
        return "Saved", 200

    @bp.route("/entrance/config", methods=["GET"])
    @requires_authorization
    async def get_entrance_config():
        """Get full entrance configuration (V3.6.2 Per-Guild)"""
        user = await _discord_oauth.fetch_user()
        guild_id = request.args.get("guild_id")

        if not guild_id:
            return jsonify({"error": "Missing guild_id"}), 400

        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        # Cog method is now async
        config = await entrance_cog.get_entrance_config(str(user.id), int(guild_id))

        # DEBUG: Log what we're returning
        _logger.info(f"[ENTRANCE CONFIG] User: {user.id}, Guild: {guild_id}, Config: {config}")

        return jsonify(config)

    @bp.route("/entrance/single", methods=["POST"])
    @requires_authorization
    async def set_entrance_single():
        """Set single entrance sound (V3.6.2 Per-Guild)"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        req = await request.json
        if not req:
            return "Invalid JSON", 400

        file_name = req.get("file")
        volume = float(req.get("volume", 1.0))
        guild_id = req.get("guild_id")

        if not guild_id:
            return "Missing guild_id", 400

        if not file_name:
            # Remove entrance if file is empty
            await db.delete_entrance_sound(user.id, int(guild_id))
            return "Removed", 200

        clean_name = sanitize_filename(file_name)
        if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
            return "File does not exist", 404

        # Cog method is now async
        await entrance_cog.set_entrance_single(str(user.id), int(guild_id), clean_name, max(0.1, min(1.0, volume)))
        return "Saved", 200

    @bp.route("/entrance/multiple", methods=["POST"])
    @requires_authorization
    async def set_entrance_multiple():
        """Set multiple entrance sounds (V3.4) - random selection"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        req = await request.json
        if not req:
            return "Invalid JSON", 400

        sounds = req.get("sounds", [])
        if not sounds or not isinstance(sounds, list):
            return "Invalid sounds list", 400

        # Validate all files exist
        validated_sounds = []
        for sound in sounds:
            file_name = sound.get("file")
            volume = sound.get("volume", 1.0)

            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return f"File not found: {file_name}", 404

            validated_sounds.append({
                "file": clean_name,
                "volume": max(0.1, min(1.0, volume))
            })

        raw_guild_id = req.get("guild_id")
        if not raw_guild_id:
            return "Missing guild_id", 400
        guild_id = int(raw_guild_id)

        await entrance_cog.set_entrance_multiple(str(user.id), guild_id, validated_sounds)
        return "Saved", 200

    @bp.route("/entrance/combo", methods=["POST"])
    @requires_authorization
    async def set_entrance_combo():
        """Set combo sequence entrance (V3.4) - plays sounds in sequence with delays"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        req = await request.json
        if not req:
            return "Invalid JSON", 400

        sounds = req.get("sounds", [])
        if not sounds or not isinstance(sounds, list):
            return "Invalid sounds list", 400

        # Validate all files exist
        validated_sounds = []
        for sound in sounds:
            file_name = sound.get("file")
            volume = sound.get("volume", 1.0)
            delay = sound.get("delay", 0)

            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return f"File not found: {file_name}", 404

            validated_sounds.append({
                "file": clean_name,
                "volume": max(0.1, min(1.0, volume)),
                "delay": max(0, min(10000, int(delay)))  # Max 10 seconds delay
            })

        raw_guild_id = req.get("guild_id")
        if not raw_guild_id:
            return "Missing guild_id", 400
        guild_id = int(raw_guild_id)

        await entrance_cog.set_entrance_combo(str(user.id), guild_id, validated_sounds)
        return "Saved", 200

    @bp.route("/entrance/scheduled", methods=["POST"])
    @requires_authorization
    async def set_entrance_scheduled():
        """Set scheduled entrance sounds (V3.4) - time-based rules"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        req = await request.json
        if not req:
            return "Invalid JSON", 400

        rules = req.get("rules", [])
        default = req.get("default", {})

        # Validate default
        if not default.get("file"):
            return "Default entrance required", 400

        default_clean = sanitize_filename(default["file"])
        if not os.path.exists(os.path.join(SOUND_FOLDER, default_clean)):
            return "Default file not found", 404

        validated_default = {
            "file": default_clean,
            "volume": max(0.1, min(1.0, default.get("volume", 1.0)))
        }

        # Validate rules
        validated_rules = []
        for rule in rules:
            file_name = rule.get("file")
            days = rule.get("days", [])
            hours = rule.get("hours", [0, 23])

            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return f"File not found: {file_name}", 404

            validated_rules.append({
                "file": clean_name,
                "volume": max(0.1, min(1.0, rule.get("volume", 1.0))),
                "days": [int(d) for d in days if 0 <= int(d) <= 6],
                "hours": [max(0, min(23, int(hours[0]))), max(0, min(23, int(hours[1])))]
            })

        config = {
            "default": validated_default,
            "rules": validated_rules
        }

        raw_guild_id = req.get("guild_id")
        if not raw_guild_id:
            return "Missing guild_id", 400
        guild_id = int(raw_guild_id)

        await entrance_cog.set_entrance_scheduled(str(user.id), guild_id, config)
        return "Saved", 200

    @bp.route("/entrance/clear", methods=["DELETE"])
    @requires_authorization
    async def clear_entrance():
        """Clear entrance configuration for a specific guild (V3.7)"""
        user = await _discord_oauth.fetch_user()
        guild_id = request.args.get("guild_id")

        if not guild_id:
            return "guild_id required", 400

        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        await entrance_cog.clear_entrance(str(user.id), int(guild_id))
        return "Cleared", 200

    @bp.route("/entrance/admin-override", methods=["GET"])
    @requires_authorization
    async def check_admin_override():
        """Check if admin has overridden user's entrance (V3.4)"""
        user = await _discord_oauth.fetch_user()
        entrance_cog = _bot.get_cog("Entrance")
        if not entrance_cog:
            return jsonify({"error": "Entrance system offline"}), 503

        override = entrance_cog.get_admin_override(str(user.id))
        return jsonify(override)

    return bp
