# cogs/audio/voice_error_manager.py

import time
import asyncio
from collections import defaultdict, deque

# ---- Configurable Parameters ----
MAX_FAILURES = 2           # 4006 attempts before cooldown
COOLDOWN_SEC = 60          # 1 minute cooldown for 4006
MAX_TOTAL_FAILURES = 5    # Total failures before "give up" for this guild

# Tracks per-guild error state
_voice_error_data = defaultdict(lambda: {
    "failures": 0,
    "cooldown_until": 0,
    "queue": deque(),
    "total_failures": 0,
    "gave_up": False,
})

def is_on_cooldown(guild_id):
    """True if this guild is currently on voice (4006) cooldown."""
    data = _voice_error_data[guild_id]
    return time.time() < data["cooldown_until"]

def get_cooldown_until(guild_id):
    """Unix timestamp (float) when cooldown will expire for this guild."""
    return _voice_error_data[guild_id]["cooldown_until"]

def get_queue(guild_id):
    """Returns the guild's retry queue (deque of args for audio_queue)."""
    return _voice_error_data[guild_id]["queue"]

def reset(guild_id):
    """Reset the cooldown and per-cooldown failure counter (not total)."""
    _voice_error_data[guild_id]["failures"] = 0
    _voice_error_data[guild_id]["cooldown_until"] = 0

def add_failure(guild_id):
    """
    Increments the 4006 failure counter for this guild.
    If MAX_FAILURES reached, starts a cooldown and resets this counter.
    If MAX_TOTAL_FAILURES reached, sets gave_up flag.
    Returns True if entering cooldown, False if still under limit.
    """
    data = _voice_error_data[guild_id]
    data["failures"] += 1
    data["total_failures"] += 1
    if data["total_failures"] >= MAX_TOTAL_FAILURES:
        data["gave_up"] = True
    if data["failures"] >= MAX_FAILURES:
        data["cooldown_until"] = time.time() + COOLDOWN_SEC
        data["failures"] = 0
        return True
    return False

async def wait_for_cooldown(guild_id):
    """Async-sleeps until cooldown for this guild expires."""
    cooldown_until = _voice_error_data[guild_id]["cooldown_until"]
    wait = max(0, cooldown_until - time.time())
    if wait > 0:
        await asyncio.sleep(wait)

def gave_up(guild_id):
    """Returns True if this guild has hit too many failures and is 'down' until manually reset."""
    return _voice_error_data[guild_id]["gave_up"]

def reset_total_failures(guild_id):
    """Admin reset for total failure counter and 'gave_up' flag."""
    _voice_error_data[guild_id]["total_failures"] = 0
    _voice_error_data[guild_id]["gave_up"] = False

async def process_retry_queue(guild_id):
    """
    After a cooldown, attempts all queued audio for this guild.
    (audio_queue should call this after wait_for_cooldown and check not gave_up)
    """
    while _voice_error_data[guild_id]["queue"]:
        vc_channel, user, file_path, volume, context, play_func = _voice_error_data[guild_id]["queue"].popleft()
        try:
            await play_func(vc_channel, file_path, volume=volume, context=context)
            reset(guild_id)
            reset_total_failures(guild_id)
        except Exception:
            # If 4006 again, main queue will handle (queue, cooldown, gave_up, etc.)
            pass
