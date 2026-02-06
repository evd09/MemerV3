import os
import asyncio
from pathlib import Path
from hypercorn.asyncio import serve
from hypercorn.config import Config
import discord
from discord.ext import commands
from memer.utils.logger_setup import setup_logger

logger = setup_logger("webbox", "webbox.log")

from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.helpers import db
from memer.web import websocket as ws_module
from memer.web.app import create_app

# Define the template folder explicitly
TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__)) + "/web/templates"


class WebBox(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logger

        # WebSocket clients storage
        self.ws_clients = {}

        # Create app using factory
        static_dir = os.path.join(os.path.dirname(TEMPLATE_DIR), "static")
        self.app = create_app(bot, self.ws_clients, logger, TEMPLATE_DIR, static_dir)

        # Server task
        self.server_task = None

    
    @commands.Cog.listener("on_sound_play")
    async def on_sound_play_event(self, filename, user_id=None, guild_id=None):
        # Skip TTS temp files (they have their own tts_start broadcast)
        if filename.startswith("tmp") and filename.endswith(".mp3"):
            return

        # Stats Increment (V3.8.1: use database instead of JSON)
        try:
            await db.increment_sound_play_count(filename)
        except Exception as e:
            logger.error(f"Failed to update stats: {e}")

        user_name = "Unknown User"
        user_avatar = None
        guild_name = "Unknown Server"

        # V3.6.1: Get display name from database instead of JSON metadata cache
        display_name = filename
        sound_info = await db.get_sound_by_filename(filename)
        if sound_info and sound_info.get('display_name'):
            display_name = sound_info['display_name']

        if guild_id:
             if user_id:
                 guild = self.bot.get_guild(guild_id)
                 if guild:
                     guild_name = guild.name
                     member = guild.get_member(user_id)
                     if member:
                         user_name = member.display_name
                         user_avatar = str(member.display_avatar.url) if member.display_avatar else None

             # 1. Private Guild Event (for Glow/Toasts)
             await ws_module.broadcast_to_guild(guild_id, "play_start", {
                 "filename": filename,
                 "user_id": user_id,
                 "user_name": user_name,
                 "user_avatar": user_avatar,
                 "guild_id": str(guild_id),  # Convert to string to prevent JavaScript precision loss
                 "display_name": display_name
             })
             
             # 2. Public Ticker Event (Global)
             await ws_module.broadcast_public_message("ticker_update", {
                 "message": f"🔥 {user_name} played {display_name}",
                 "guild": guild_name,
                 "filename": filename,
                 "display_name": display_name
             })

    @commands.Cog.listener("on_sound_stop")
    async def on_sound_stop_event(self, guild_id):
        await ws_module.broadcast_to_guild(guild_id, "play_end", {"guild_id": str(guild_id)})

    async def cog_load(self):
        # Run Hypercorn in background with HTTP/2 support
        config = Config()
        config.bind = ["0.0.0.0:3000"]
        
        # Enable HTTP/2 (h2) with HTTP/1.1 fallback
        config.alpn_protocols = ['h2', 'http/1.1']
        
        logger.info("Starting Hypercorn with HTTP/2 support on port 3000")
        self.server_task = self.bot.loop.create_task(serve(self.app, config))

    async def cog_unload(self):
        if self.server_task:
            self.server_task.cancel()

async def setup(bot: commands.Bot):
    await bot.add_cog(WebBox(bot))

