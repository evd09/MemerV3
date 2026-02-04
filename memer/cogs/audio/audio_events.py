# cogs/audio/audio_events.py
import os
import json
import time
import asyncio
import logging
import random
from datetime import datetime
import discord
from .audio_queue import queue_audio
from .audio_player import play_clip
from memer.config import SOUND_FOLDER, ENTRANCE_DATA
from memer.helpers import db

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

def select_entrance_sound(user_data: dict) -> dict:
    """Select entrance sound based on type (V3.4).
    Returns: {"file": str, "volume": float, "is_combo": bool, "combo_sounds": list}
    """
    if not user_data:
        return None
    
    entrance_type = user_data.get("type", "single")
    
    # Single sound
    if entrance_type == "single":
        single = user_data.get("single", {})
        if single.get("file"):
            return {
                "file": single["file"],
                "volume": single.get("volume", 1.0),
                "is_combo": False
            }
    
    # Multiple sounds (random selection)
    elif entrance_type == "multiple":
        sounds = user_data.get("multiple", [])
        if sounds:
            selected = random.choice(sounds)
            return {
                "file": selected["file"],
                "volume": selected.get("volume", 1.0),
                "is_combo": False
            }
    
    # Combo sequence
    elif entrance_type == "combo":
        combo = user_data.get("combo", {})
        sounds = combo.get("sounds", [])
        if sounds:
            return {
                "is_combo": True,
                "combo_sounds": sounds
            }
    
    # Scheduled entrance
    elif entrance_type == "scheduled":
        scheduled = user_data.get("scheduled", {})
        rules = scheduled.get("rules", [])
        default = scheduled.get("default", {})
        
        # Get current day of week (0=Monday, 6=Sunday)
        now = datetime.now()
        current_day = now.weekday()
        current_hour = now.hour
        
        # Check rules
        for rule in rules:
            days = rule.get("days", [])
            hours = rule.get("hours", [0, 23])
            
            # Check if current day/hour matches
            if current_day in days:
                if len(hours) == 2 and hours[0] <= current_hour <= hours[1]:
                    return {
                        "file": rule["file"],
                        "volume": rule.get("volume", 1.0),
                        "is_combo": False
                    }
        
        # No rule matched, use default
        if default.get("file"):
            return {
                "file": default["file"],
                "volume": default.get("volume", 1.0),
                "is_combo": False
            }
    
    return None

async def play_combo_sequence(vc, member, combo_sounds):
    """Play a combo sequence with delays."""
    for sound_config in combo_sounds:
        filename = sound_config.get("file")
        volume = sound_config.get("volume", 1.0)
        delay = sound_config.get("delay", 0) / 1000.0  # Convert ms to seconds
        
        if delay > 0:
            await asyncio.sleep(delay)
        
        path = os.path.join(SOUND_FOLDER, filename)
        if os.path.exists(path):
            await queue_audio(vc, member, path, volume, None, play_clip)

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
        
        # V3.4: Use new entrance selection logic
        entrance = select_entrance_sound(user_data)
        
        if entrance:
            if not guild.voice_client:
                try:
                    await vc.connect()
                except Exception:
                    log.error("[VOICE JOIN ERROR]", exc_info=True)

            # Handle combo vs single/multiple/scheduled
            if entrance.get("is_combo"):
                # Log all sounds in combo
                for sound in entrance["combo_sounds"]:
                    if sound.get("file"):
                        await db.log_entrance_play(guild.id, int(user_id), sound["file"])
                await play_combo_sequence(vc, member, entrance["combo_sounds"])
            else:
                filename = entrance["file"]
                volume = entrance["volume"]
                path = os.path.join(SOUND_FOLDER, filename)
                if os.path.exists(path):
                    await db.log_entrance_play(guild.id, int(user_id), filename)
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
