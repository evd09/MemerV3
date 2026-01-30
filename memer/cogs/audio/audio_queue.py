import asyncio
import time
import random
from collections import defaultdict, deque
import discord


from .voice_error_manager import (
    is_on_cooldown, add_failure, wait_for_cooldown,
    reset, get_queue, process_retry_queue, get_cooldown_until,
    gave_up, reset_total_failures
)

AUDIO_COOLDOWN = 10   # seconds between plays per channel
USER_COOLDOWN  = 10  # seconds per user

_last_channel_play = defaultdict(float)
_last_user_play   = defaultdict(float)
audio_queues = defaultdict(deque)        # channel_id -> queue of (user, file, volume, context, play_func)
audio_locks  = defaultdict(asyncio.Lock) # channel_id -> lock

COOLDOWN_MSGS = [
    "Hold up! I'm on a cooldown because Discord is lame. 😅",
    "Discord says: 'Whoa there, take a breather!' 💤",
    "Whoa, slow down! Cooldown time. Blame Discord, not me. 🙃",
    "I’d love to, but Discord police says NOPE (cooldown)! 🚓",
    "Oops, spamming not allowed. I'm cooling off... thanks Discord! 🧊",
]

def bot_in_voice(vc_channel):
    guild = vc_channel.guild
    return (
        guild.voice_client and
        guild.voice_client.is_connected() and
        guild.voice_client.channel.id == vc_channel.id
    )
    
def get_funny_cooldown():
    return random.choice(COOLDOWN_MSGS)

async def send_cooldown(context, msg, remaining=None):
    if remaining:
        msg = f"{msg} Wait {remaining}s."
    # Safely handle interactions
    if hasattr(context, "response") and not context.response.is_done():
        await context.response.send_message(msg, ephemeral=True)
    elif hasattr(context, "followup"):
        try:
            await context.followup.send(msg, ephemeral=True)
        except Exception:
            pass
    elif hasattr(context, "send"):
        await context.send(msg, ephemeral=True)


async def queue_audio(vc_channel, user, file_path, volume, context, play_func):
    gid = vc_channel.guild.id
    cid = vc_channel.id
    now = time.time()
    last_ch = _last_channel_play[cid]
    last_us = _last_user_play[user.id]

    # 0. Give up logic: Too many failures, voice is "down" for this guild
    if gave_up(gid):
        if context:
            await send_cooldown(
                context,
                "🚫 Sorry! The bot's voice system is down in this server due to repeated Discord errors. Please try again later or ask an admin to use /reset_voice_error.",
                None
            )
        return False

    # 1. Check 4006 global voice cooldown
    if is_on_cooldown(gid):
        if context:
            await send_cooldown(
                context,
                "⚠️ Bot is temporarily on voice error cooldown (Discord bug, 4006). I'll play your sound when ready!",
                int(get_cooldown_until(gid) - now)
            )
        get_queue(gid).append((vc_channel, user, file_path, volume, context, play_func))
        return False

    # 2. Normal cooldowns
    if now - last_ch < AUDIO_COOLDOWN:
        if bot_in_voice(vc_channel):
            # Already in voice; just queue their request silently.
            audio_queues[cid].append((user, file_path, volume, context, play_func))
            asyncio.create_task(process_queue(vc_channel))
            return True
        else:
            # Not in channel or true spam: send the cooldown message.
            if context:
                await send_cooldown(
                    context,
                    get_funny_cooldown(),
                    int(AUDIO_COOLDOWN - (now - last_ch))
                )
            return False

    # 3. Add to channel queue and update times
    _last_channel_play[cid] = now
    _last_user_play[user.id] = now
    audio_queues[cid].append((user, file_path, volume, context, play_func))
    asyncio.create_task(process_queue(vc_channel))
    return True

async def process_queue(vc_channel):
    cid = vc_channel.id
    gid = vc_channel.guild.id
    async with audio_locks[cid]:
        while audio_queues[cid]:
            user, file_path, volume, context, play_func = audio_queues[cid].popleft()
            try:
                await play_func(vc_channel, file_path, volume=volume, context=context)
                reset(gid)  # On any success, reset error counter/cooldown
                reset_total_failures(gid)
                await asyncio.sleep(0.3)
            except discord.errors.ConnectionClosed as e:
                if getattr(e, "code", None) == 4006:
                    # Add to guild queue and handle cooldown
                    if add_failure(gid):
                        # Cooldown started
                        if context:
                            await send_cooldown(
                                context,
                                "😬 Too many Discord voice errors (4006). I'll retry your sound in 1 min.",
                                60
                            )
                        get_queue(gid).appendleft((vc_channel, user, file_path, volume, context, play_func))
                        await wait_for_cooldown(gid)
                        if not gave_up(gid):
                            await process_retry_queue(gid)
                        else:
                            # Give up! Notify and clear the queue
                            if context:
                                await send_cooldown(
                                    context,
                                    "🚫 Sorry! The bot's voice system is down in this server due to repeated Discord errors. Please try again later or ask an admin to use /reset_voice_error.",
                                    None
                                )
                            get_queue(gid).clear()
                    else:
                        # Try again soon (still under MAX_FAILURES)
                        await asyncio.sleep(1)
                        audio_queues[cid].appendleft((user, file_path, volume, context, play_func))
                        await asyncio.sleep(0.5)
                    break
                else:
                    if context:
                        await send_cooldown(context, f"⚠️ Failed to play audio (error: {e})")
            except Exception as e:
                if context:
                    await send_cooldown(context, f"⚠️ Failed to play audio: {e}")
