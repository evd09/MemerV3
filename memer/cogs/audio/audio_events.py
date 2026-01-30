# cogs/audio/audio_events.py
import os
import json
import time
import asyncio
import logging
import discord
from .audio_queue import queue_audio
from .audio_player import play_clip
from .constants import SOUND_FOLDER, ENTRANCE_DATA

log = logging.getLogger(__name__)

# --- Idle timeout settings (defaults) ---
IDLE_TIMEOUT_DEFAULT = 600  # seconds
IDLE_TIMEOUT_ENABLED = True

# In-memory state (per guild)
_idle_config = {}      # guild_id -> {"enabled": bool, "seconds": int}
_last_activity = {}    # guild_id -> timestamp
_idle_tasks = {}       # guild_id -> asyncio.Task

# Simple in-memory cache with auto-reload on file change
class EntranceDataCache:
    def __init__(self, data_path):
        self.data_path = data_path
        self._data = {}
        self._last_mtime = 0

    def _reload(self):
        mtime = os.path.getmtime(self.data_path)
        if mtime != self._last_mtime:
            with open(self.data_path, "r") as f:
                self._data = json.load(f)
            self._last_mtime = mtime

    def get(self, user_id):
        if not os.path.exists(self.data_path):
            return None
        self._reload()
        return self._data.get(user_id)

# Instantiate the cache
entrance_cache = EntranceDataCache(ENTRANCE_DATA)

def get_guild_config(guild_id):
    # Get config or defaults
    conf = _idle_config.get(guild_id)
    if not conf:
        conf = {"enabled": IDLE_TIMEOUT_ENABLED, "seconds": IDLE_TIMEOUT_DEFAULT}
        _idle_config[guild_id] = conf
    return conf

def update_last_activity(guild_id):
    import time
    _last_activity[guild_id] = time.time()

async def idle_monitor(guild: discord.Guild):
    import time
    conf = get_guild_config(guild.id)
    while True:
        await asyncio.sleep(5)
        # Only run if enabled and bot is in voice
        if not conf["enabled"] or not guild.voice_client:
            break
        last = _last_activity.get(guild.id, time.time())
        elapsed = time.time() - last
        if elapsed >= conf["seconds"]:
            try:
                await guild.voice_client.disconnect(force=True)
            except Exception:
                pass
            break

async def on_voice_state_update(member: discord.Member, before, after):
    # Ignore bots
    if member.bot:
        return

    guild = member.guild

    # --- JOIN LOGIC ---
    if before.channel is None and after.channel is not None:
        vc = after.channel
        # --- CHECK IF ENTRANCE IS CONFIGURED ---
        user_id = str(member.id)
        user_data = entrance_cache.get(user_id)
        has_entrance = user_data and user_data.get("file")
        # Only join if user has an entrance file set!
        if has_entrance:
            if not guild.voice_client:
                try:
                    await vc.connect()
                except Exception:
                    log.error("[VOICE JOIN ERROR]", exc_info=True)

            filename = user_data["file"]
            volume = user_data.get("volume", 1.0)
            path = os.path.join(SOUND_FOLDER, filename)
            if os.path.exists(path):
                await queue_audio(vc, member, path, volume, None, play_clip)
        
        # Start idle timer
        update_last_activity(guild.id)
        await maybe_start_idle_task(guild)

    # --- LEAVE LOGIC ---
    if before.channel is not None:
        channel = before.channel
        # Real users left in this channel
        real_users = [m for m in channel.members if not m.bot]
        bot_in_channel = (
            guild.voice_client and
            guild.voice_client.channel and
            guild.voice_client.channel.id == channel.id
        )
        # If no real users are left and bot is in that channel, leave
        if bot_in_channel and len(real_users) == 0:
            try:
                await guild.voice_client.disconnect(force=True)
            except Exception:
                log.error("[VOICE LEAVE ERROR]", exc_info=True)
            # Cancel idle timer for this guild
            await maybe_cancel_idle_task(guild.id)

async def maybe_start_idle_task(guild: discord.Guild):
    # Only start if enabled, not already running, and bot is in voice
    conf = get_guild_config(guild.id)
    if not conf["enabled"]:
        return
    if guild.id in _idle_tasks and not _idle_tasks[guild.id].done():
        return
    if not guild.voice_client:
        return
    # Start new idle monitor task
    task = asyncio.create_task(idle_monitor(guild))
    _idle_tasks[guild.id] = task

async def maybe_cancel_idle_task(guild_id):
    task = _idle_tasks.get(guild_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _idle_tasks.pop(guild_id, None)

def signal_activity(guild_id):
    # Call this from entrance/beep commands when playing a sound
    update_last_activity(guild_id)

async def setup(bot):
    bot.add_listener(on_voice_state_update)
