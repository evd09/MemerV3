# cogs/audio/audio_player.py

import json
import asyncio
from pathlib import Path
import discord
from discord import opus

from memer.utils.logger_setup import setup_logger
from .constants import SOUND_FOLDER, AUDIO_EXTS

logger = setup_logger("audio", "audio.log")

if not opus.is_loaded():
    for lib in ("libopus.so.0", "libopus.so", "libopus-0.dll"):
        try:
            opus.load_opus(lib)
            logger.info(f"[OPUS] Loaded {lib}")
            break
        except OSError:
            continue
    else:
        logger.error("[OPUS] Could not load libopus — voice will NOT work.")


# No more RAM cache needed for disk streaming
def preload_audio_clips():
    # Only verify files exist/log count
    count = 0
    for file in Path(SOUND_FOLDER).glob("*"):
        if file.suffix.lower() in AUDIO_EXTS:
            count += 1
    logger.info(f"[AUDIO] Found {count} audio files available for streaming.")

async def play_clip(
    vc_channel: discord.VoiceChannel,
    file_path: str,
    volume: float = 1.0,
    context=None,
    fallback_label: str = "audio",
    hold_after_play: bool = False,
):
    guild = vc_channel.guild
    voice_client = guild.voice_client
    
    try:
        # 1. Connection Logic
        if voice_client is None or not voice_client.is_connected():
            voice_client = await vc_channel.connect()
            logger.info("[AUDIO] Joined voice channel. Waiting 2s for handshake...")
            await asyncio.sleep(2) # Reduced from 5s
            
        elif voice_client.channel.id != vc_channel.id:
            await voice_client.move_to(vc_channel)
            logger.info("[AUDIO] Moved channel. Waiting 2s for handshake...")
            await asyncio.sleep(2)
        else:
            # Already connected to correct channel - NO WAIT!
            pass

        # 2. Stop current playback if needed
        if voice_client.is_playing():
            voice_client.stop()

        # 3. Stream from Disk with Normalization
        # FFmpegPCMAudio handles the file opening/streaming efficiently
        # Normalization: Target -14 LUFS (Standard), True Peak -1.0dB
        ffmpeg_opts = {'options': '-af loudnorm=I=-14:TP=-1.0:LRA=11'}
        
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(file_path, **ffmpeg_opts), 
            volume=volume
        )

        voice_client.play(source)

        # 4. Wait for playback to finish
        while voice_client.is_playing():
            await asyncio.sleep(0.1)

        # 5. Only disconnect if requested for UI preview mode!
        if hold_after_play:
            pass 

    except Exception as e:
        logger.error(f"Failed to play clip: {e}")
        if context:
            try:
                # Basic error reporting
                msg = f"⚠️ Failed to play {fallback_label}: {e}"
                if hasattr(context, "followup"):
                    await context.followup.send(msg, ephemeral=True)
                elif hasattr(context, "response"):
                    if not context.response.is_done():
                        await context.response.send_message(msg, ephemeral=True)
                    else:
                        await context.edit_original_response(content=msg)
                elif hasattr(context, "send"):
                    await context.send(msg, ephemeral=True)
            except Exception:
                pass
        
        # Cleanup if we failed hard (e.g. broken pipe) and still connected
        if voice_client and not voice_client.is_connected():
             try:
                 await voice_client.disconnect(force=True)
             except:
                 pass

async def disconnect_voice(guild: discord.Guild):
    vc = guild.voice_client
    if vc and vc.is_connected():
        await vc.disconnect(force=True)
