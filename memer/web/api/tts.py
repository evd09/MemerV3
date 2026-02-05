"""Text-to-Speech API endpoints"""
import os
from quart import Blueprint, request
from quart_discord import requires_authorization

from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.web import websocket as ws_module

# Module dependencies (injected by webbox)
_bot = None
_discord_oauth = None
_logger = None

def init_tts_api(bot, discord_oauth, logger):
    """Initialize module dependencies"""
    global _bot, _discord_oauth, _logger
    _bot = bot
    _discord_oauth = discord_oauth
    _logger = logger

def create_tts_blueprint() -> Blueprint:
    """Create and return TTS API blueprint"""
    bp = Blueprint('tts_api', __name__, url_prefix='/api/tts')

    @bp.route("/send", methods=["POST"])
    @requires_authorization
    async def tts_send():
        """Generate TTS and queue to user's voice channel"""
        user = await _discord_oauth.fetch_user()
        req = await request.json

        text = req.get("text", "").strip()
        voice = req.get("voice", "en-US-GuyNeural")
        rate = req.get("rate", 0)
        pitch = req.get("pitch", 0)
        guild_id = req.get("guild_id")

        # Validate
        if not text or len(text) > 500:
            return "Invalid text (max 500 chars)", 400

        if not guild_id or guild_id == "global":
            return "No guild selected", 400

        # Get guild and member
        try:
            guild_id = int(guild_id)
        except (ValueError, TypeError):
            return "Invalid guild ID", 400

        guild = _bot.get_guild(guild_id)
        if not guild:
            return "Guild not found", 404

        member = guild.get_member(user.id)
        if not member:
            return "You are not in this server", 403

        if not member.voice or not member.voice.channel:
            return "You must be in a voice channel", 400

        # Get Voice cog
        voice_cog = _bot.get_cog("Voice")
        if not voice_cog:
            return "TTS service unavailable", 503

        try:
            # Generate TTS
            temp_path = await voice_cog.generate_tts(text, voice, rate, pitch)

            # Queue audio with cleanup
            async def play_and_cleanup(vc, path, volume, context, user=None):
                try:
                    await play_clip(vc, path, volume, context, fallback_label="TTS", user=user)
                finally:
                    # Clean up file
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except:
                            pass

            success = await queue_audio(
                member.voice.channel,
                member,
                temp_path,
                1.0,
                None,
                play_and_cleanup
            )

            if not success:
                # Clean up if queue failed
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return "Failed to queue audio", 500

            # Broadcast event
            await ws_module.broadcast_to_guild(guild_id, "tts_start", {
                "text": text[:100],  # Truncate for display
                "user_id": user.id,
                "user_name": member.display_name,
                "user_avatar": str(member.display_avatar.url) if member.display_avatar else None,
                "voice": voice,
                "guild_id": str(guild_id)
            })

            return "Queued", 200

        except ValueError as e:
            return str(e), 400
        except Exception as e:
            _logger.error(f"TTS error: {e}")
            return "Internal error", 500

    @bp.route("/preview", methods=["POST"])
    @requires_authorization
    async def tts_preview():
        """Preview TTS without broadcasting to guild"""
        user = await _discord_oauth.fetch_user()
        req = await request.json

        text = req.get("text", "").strip()
        voice = req.get("voice", "en-US-GuyNeural")
        rate = req.get("rate", 0)
        pitch = req.get("pitch", 0)

        if not text or len(text) > 500:
            return "Invalid text", 400

        # Find user in ANY voice channel across all guilds
        member_voice_channel = None
        member_obj = None
        for guild in _bot.guilds:
            member = guild.get_member(user.id)
            if member and member.voice and member.voice.channel:
                member_voice_channel = member.voice.channel
                member_obj = member
                break

        if not member_voice_channel:
            return "You must be in a voice channel", 400

        voice_cog = _bot.get_cog("Voice")
        if not voice_cog:
            return "TTS unavailable", 503

        try:
            temp_path = await voice_cog.generate_tts(text, voice, rate, pitch)

            async def play_and_cleanup(vc, path, volume, context, user=None):
                try:
                    await play_clip(vc, path, volume, context, fallback_label="TTS Preview", user=user)
                finally:
                    # Clean up file
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except:
                            pass

            success = await queue_audio(
                member_voice_channel,
                member_obj,
                temp_path,
                1.0,
                None,
                play_and_cleanup
            )

            if not success:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return "Failed to queue audio", 500

            # NO WebSocket broadcast for preview
            return "Playing preview", 200

        except ValueError as e:
            return str(e), 400
        except Exception as e:
            _logger.error(f"TTS preview error: {e}")
            return "Error", 500

    return bp
