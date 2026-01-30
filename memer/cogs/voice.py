# cogs/voice.py
import os
import asyncio
import tempfile
import discord
from discord import app_commands
from discord.ext import commands
import edge_tts

from memer.utils.logger_setup import setup_logger
from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.cogs.audio.audio_events import signal_activity
from memer.helpers.db import get_voice_settings

logger = setup_logger("voice", "voice.log")

# Voice Mapping
VOICES = {
    "Guy (US)": "en-US-GuyNeural",
    "Girl (US)": "en-US-AriaNeural",
    "Guy (UK)": "en-GB-RyanNeural",
    "Girl (UK)": "en-GB-SoniaNeural",
    "Guy (AU)": "en-AU-WilliamNeural",
    "Girl (AU)": "en-AU-NatashaNeural",
    "Guy (FR)": "fr-FR-HenriNeural",
    "Girl (FR)": "fr-FR-DeniseNeural",
    "Guy (DE)": "de-DE-ConradNeural", 
    "Girl (DE)": "de-DE-KatjaNeural",
    "Guy (ES)": "es-ES-AlvaroNeural",
    "Girl (ES)": "es-ES-ElviraNeural",
    "Guy (IT)": "it-IT-DiegoNeural",
    "Girl (IT)": "it-IT-ElsaNeural",
    "Guy (JP)": "ja-JP-KeitaNeural",
    "Girl (JP)": "ja-JP-NanamiNeural",
}

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="say", description="Read text aloud in your voice channel.")
    @app_commands.describe(
        text="The text to speak",
        voice="Select a voice style"
    )
    @app_commands.choices(voice=[
        app_commands.Choice(name=k, value=v) for k, v in list(VOICES.items())[:25] # Limit to 25 choices
    ])
    async def say(self, interaction: discord.Interaction, text: str, voice: str = "en-US-GuyNeural"):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "❌ You must be in a voice channel.", ephemeral=True
            )
        
        # Check Visibility Settings
        is_public = await get_voice_settings(interaction.guild.id)
        
        # Defer based on visibility
        # If is_public=False (Private), defer ephemeral=True
        # Logic: ephemeral = NOT is_public
        await interaction.response.defer(ephemeral=not is_public)
        
        channel = interaction.user.voice.channel

        # Generate unique temp file
        try:
            # We use a named temporary file that persists until we delete it
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                temp_path = tf.name
            
            # Generate Audio using Edge-TTS
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(temp_path)
            
            # Queue it
            async def play_and_cleanup(vc, path, volume, context):
                try:
                    await play_clip(vc, path, volume, context, fallback_label="TTS")
                finally:
                    # Clean up file
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except:
                            pass

            success = await queue_audio(
                channel, 
                interaction.user, 
                temp_path, 
                1.0, 
                interaction, 
                play_and_cleanup
            )

            if success:
                signal_activity(interaction.guild.id)
                # This followup will inherit the ephemeral state from defer()
                await interaction.followup.send(f"🗣️ **{interaction.user.display_name}** says: \"{text}\"")
            else:
                # If failed to queue, clean up immediately
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception as e:
            logger.error(f"TTS Error: {e}")
            await interaction.followup.send("❌ Failed to generate speech.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Voice(bot))
