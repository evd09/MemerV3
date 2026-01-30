# cogs/socials.py
import re
import os
import glob
import asyncio
import logging
import tempfile
import discord
from discord.ext import commands
from discord import app_commands
from deep_translator import GoogleTranslator

from memer.helpers.db import (
    get_social_settings, 
    get_cached_social, 
    cache_social
)

# Configure logging
log = logging.getLogger("socials")

# Link patterns
TIKTOK_REGEX = re.compile(r"https?://(www\.)?(vm\.)?tiktok\.com/\S+")
INSTA_REGEX  = re.compile(r"https?://(www\.)?instagram\.com/(reel|p)/\S+")
TWITTER_REGEX = re.compile(r"https?://(www\.)?(twitter|x)\.com/\S+")

class Socials(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Context menu command
        self.ctx_menu = app_commands.ContextMenu(
            name="Translate to English",
            callback=self.translate_message,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        content = message.content
        # Check for matching links
        url = None
        if match := TIKTOK_REGEX.search(content):
            url = match.group(0)
        elif match := INSTA_REGEX.search(content):
            url = match.group(0)
        elif match := TWITTER_REGEX.search(content):
            url = match.group(0) 
        
        if not url:
            return

        # Check DB config
        enabled, allowed_channels = await get_social_settings(message.guild.id)
        
        if not enabled:
            return
        
        if allowed_channels and message.channel.id not in allowed_channels:
             return
        if not allowed_channels: 
             return

        # Proceed to Fix
        try:
           await self.process_link(message, url)
        except Exception as e:
           log.error(f"Failed to process link {url}: {e}")

    async def process_link(self, message: discord.Message, url: str):
        # Indicate work
        await message.add_reaction("⏳")
        
        # 1. Clean URL for caching (remove query params)
        # Simple split by ? works for most social sites
        clean_url = url.split("?")[0]
        
        # 2. Check Cache
        cached_url = await get_cached_social(clean_url)
        if cached_url:
            await message.reply(
                content=f"🎥 **Embed Fixed** (via Cache) — [Source]({url})\n{cached_url}",
                mention_author=False
            )
            await message.remove_reaction("⏳", self.bot.user)
            await message.add_reaction("✅")
            try:
                await message.edit(suppress=True)
            except discord.Forbidden:
                pass
            return
        
        file_path = None
        try:
            # Create a localized temp filename inside the system temp directory
            temp_dir = tempfile.gettempdir()
            temp_name = f"social_{message.id}" 
            # Output template for yt-dlp
            out_tmpl = os.path.join(temp_dir, f"{temp_name}.%(ext)s")
            
            cmd = [
                "yt-dlp",
                "-f", "b[filesize<25M] / w[filesize<25M]",  # Try to grab under 25MB for Discord limit
                "-o", out_tmpl,
                "--no-playlist",
                url
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                log.warning(f"yt-dlp failed for {url}: {stderr.decode()}")
                await message.remove_reaction("⏳", self.bot.user)
                return

            # Find the file (yt-dlp adds extension)
            search_path = os.path.join(temp_dir, f"{temp_name}.*")
            files = glob.glob(search_path)
            if not files:
                log.warning("yt-dlp finished but no file found at %s", search_path)
                await message.remove_reaction("⏳", self.bot.user)
                return
                
            file_path = files[0]
            
            # Reply with the file
            with open(file_path, "rb") as f:
                dfile = discord.File(f, filename=os.path.basename(file_path))
            
            sent_msg = await message.reply(
                content=f"🎥 **Embed Fixed** (by {message.author.mention})",
                file=dfile,
                mention_author=False
            )
            
            # Cache the Attachment URL
            if sent_msg.attachments:
                new_url = sent_msg.attachments[0].url
                await cache_social(clean_url, new_url)
            
            # Cleanup UI
            await message.remove_reaction("⏳", self.bot.user)
            await message.add_reaction("✅")
            
            # Suppress original
            try:
                await message.edit(suppress=True)
            except discord.Forbidden:
                pass # Can't manage messages

        except Exception as e:
            log.error(f"Error in process_link: {e}")
            await message.remove_reaction("⏳", self.bot.user)
        finally:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

    async def translate_message(self, interaction: discord.Interaction, message: discord.Message):
        if not message.content:
            await interaction.response.send_message("❌ Message has no text to translate.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        try:
            translator = GoogleTranslator(source='auto', target='en')
            translation = translator.translate(message.content)
            
            embed = discord.Embed(title="Translation (to English)", color=discord.Color.blue())
            embed.description = translation
            embed.set_footer(text="Translated via Google Translate")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            log.error(f"Translation failed: {e}")
            await interaction.followup.send("❌ Translation failed.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Socials(bot))
