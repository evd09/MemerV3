# cogs/audio/beep.py
import os
import random
import logging
from pathlib import Path
import discord
from discord.ext import commands
from discord import app_commands
from .audio_player import play_clip  # does NOT manage cooldowns/locks
from .audio_queue import queue_audio  # all logic for cooldown/locks/4006 is here
from memer.config import SOUND_FOLDER, AUDIO_EXTS
from memer.helpers import db
from memer.utils.logger_setup import setup_logger

logger = setup_logger("beep", "beep.log")

beep_cache: list[str] = []


def load_beeps() -> list[str]:
    """Load available beep files into cache, preferring .opus over .mp3."""
    os.makedirs(SOUND_FOLDER, exist_ok=True)
    global beep_cache
    
    # Get all audio files
    all_files = [
        f for f in os.listdir(SOUND_FOLDER)
        if f.lower().endswith(AUDIO_EXTS)
    ]
    
    # Deduplicate: prefer .opus over other formats
    audio_files = {}  # stem -> filename
    for f in all_files:
        stem = Path(f).stem.lower()
        ext = Path(f).suffix.lower()
        
        # If we haven't seen this stem, or current file is .opus and existing is not
        if stem not in audio_files:
            audio_files[stem] = f
        elif ext == '.opus' and Path(audio_files[stem]).suffix.lower() != '.opus':
            # Prefer .opus over other formats
            audio_files[stem] = f
    
    beep_cache = list(audio_files.values())
    return beep_cache


async def get_sound_metadata(filename: str) -> dict:
    """Get display name and thumbnail for a sound file (V3.7.4: from database)."""
    # Get display name from database
    sound_info = await db.get_sound_by_filename(filename)
    display_name = sound_info["display_name"] if sound_info else filename

    # Find thumbnail
    sound_folder = Path(SOUND_FOLDER)
    stem = Path(filename).stem.lower()
    thumbnail_url = None

    # Check for thumbnail image
    for ext in ['.png', '.jpg', '.jpeg', '.gif']:
        thumb_path = sound_folder / f"{stem}_thumb{ext}"
        if thumb_path.exists():
            thumbnail_url = f"{os.getenv('DASHBOARD_URL', 'http://your-bot-url')}/sounds/{stem}_thumb{ext}"
            break

    # Fallback to regular image
    if not thumbnail_url:
        for ext in ['.png', '.jpg', '.jpeg', '.gif']:
            img_path = sound_folder / f"{stem}{ext}"
            if img_path.exists():
                thumbnail_url = f"{os.getenv('DASHBOARD_URL', 'http://your-bot-url')}/sounds/{stem}{ext}"
                break

    return {
        "display_name": display_name,
        "thumbnail_url": thumbnail_url
    }

class BeepPickerView(discord.ui.View):
    """Paginated beep picker. Selecting a file immediately plays it and locks the UI."""
    def __init__(self, user: discord.User, files: list[str], channel: discord.VoiceChannel, page: int = 0):
        super().__init__(timeout=30)
        self.user = user
        self.files = files
        self.channel = channel
        self.page = page
        self.page_size = 25
        self.max_page = (max(1, len(files)) - 1) // self.page_size
        self.message: discord.Message | None = None
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        self._add_select()
        self._add_random_button()
        self._add_pagination()

    def _add_select(self):
        # Remove any prior select
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)

        start = self.page * self.page_size
        end = start + self.page_size
        options = [discord.SelectOption(label=f) for f in self.files[start:end]]

        selector = discord.ui.Select(
            placeholder="Select or search a beep to play",
            options=options,
            custom_id="beep_file_select",
            min_values=1,
            max_values=1,
            row=0
        )

        async def on_select(interaction: discord.Interaction):
            # Immediately play and then lock UI
            await interaction.response.defer()  # we'll edit the original message after play
            filename = interaction.data["values"][0]
            path = os.path.join(SOUND_FOLDER, filename)

            ok = await queue_audio(self.channel, interaction.user, path, 1.0, interaction, play_clip)

            # Disable everything
            for child in self.children:
                child.disabled = True

            # Update the original ephemeral message
            if ok:
                from .audio_events import signal_activity
                signal_activity(interaction.guild.id)
                metadata = await get_sound_metadata(filename)
                embed = discord.Embed(
                    title="🔊 Now Playing",
                    description=f"**{metadata['display_name']}**",
                    color=discord.Color.green()
                )
                if metadata['thumbnail_url']:
                    embed.set_thumbnail(url=metadata['thumbnail_url'])
                dashboard_url = os.getenv("DASHBOARD_URL", "http://your-bot-url")
                embed.add_field(name="💡 Tip", value=f"Want more control? Visit the **[MemeBoard]({dashboard_url})**!", inline=False)
            else:
                embed = discord.Embed(
                    title="⚠️ Playback Failed",
                    description="Could not play right now (cooldown or voice issue). Try again in a few seconds.",
                    color=discord.Color.red()
                )

            if self.message:
                await self.message.edit(content=None, embed=embed, view=self)
            else:
                await interaction.edit_original_response(content=None, embed=embed, view=self)

            # End the view lifecycle
            self.stop()

        selector.callback = on_select
        self.add_item(selector)

    def _add_random_button(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and getattr(child, "custom_id", None) == "random_beep":
                self.remove_item(child)

        randb = discord.ui.Button(
            label="Random",
            style=discord.ButtonStyle.primary,
            custom_id="random_beep",
            row=1
        )

        async def do_random(interaction: discord.Interaction):
            await interaction.response.defer()
            filename = random.choice(self.files)
            path = os.path.join(SOUND_FOLDER, filename)

            ok = await queue_audio(self.channel, interaction.user, path, 1.0, interaction, play_clip)

            for child in self.children:
                child.disabled = True

            if ok:
                from .audio_events import signal_activity
                signal_activity(interaction.guild.id)
                metadata = await get_sound_metadata(filename)
                embed = discord.Embed(
                    title="🎲 Random Beep",
                    description=f"**{metadata['display_name']}**",
                    color=discord.Color.blue()
                )
                if metadata['thumbnail_url']:
                    embed.set_thumbnail(url=metadata['thumbnail_url'])
                dashboard_url = os.getenv("DASHBOARD_URL", "http://your-bot-url")
                embed.add_field(name="💡 Tip", value=f"Visit the **[MemeBoard]({dashboard_url})** for more sounds!", inline=False)
            else:
                embed = discord.Embed(
                    title="⚠️ Playback Failed",
                    description="Could not play right now (cooldown or voice issue). Try again in a few seconds.",
                    color=discord.Color.red()
                )

            if self.message:
                await self.message.edit(content=None, embed=embed, view=self)
            else:
                await interaction.edit_original_response(content=None, embed=embed, view=self)

            self.stop()

        randb.callback = do_random
        self.add_item(randb)

    def _add_pagination(self):
        # Clear existing pagers
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and getattr(child, "custom_id", None) in ("prev_page", "next_page"):
                self.remove_item(child)

        if self.max_page > 0:
            prevb = discord.ui.Button(
                label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_page", row=2,
                disabled=(self.page == 0)
            )
            nextb = discord.ui.Button(
                label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="next_page", row=2,
                disabled=(self.page == self.max_page)
            )

            async def do_prev(interaction: discord.Interaction):
                await self._change_page(interaction, self.page - 1)

            async def do_next(interaction: discord.Interaction):
                await self._change_page(interaction, self.page + 1)

            prevb.callback = do_prev
            nextb.callback = do_next
            self.add_item(prevb)
            self.add_item(nextb)

    async def _change_page(self, interaction: discord.Interaction, new_page: int):
        self.page = max(0, min(self.max_page, new_page))
        self._add_select()
        self._add_pagination()
        await interaction.response.edit_message(
            content=f"🎛️ Pick a beep (Page {self.page+1}/{self.max_page+1})",
            view=self
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(content="⏳ Picker timed out. Run `/beeps` again.", view=self)

class Beep(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        load_beeps()

    def reload(self):
        """Reloads the beep cache."""
        load_beeps()

    def get_valid_files(self):
        return beep_cache

    @app_commands.command(name="beeps", description="Play a random beep.")
    async def beeps(self, interaction: discord.Interaction):
        channel = getattr(interaction.user.voice, "channel", None)
        if not channel:
            return await interaction.response.send_message("❌ You must be in a voice channel.", ephemeral=True)

        # Defer immediately since DB fetch + logic might take a moment
        await interaction.response.defer(ephemeral=True)

        # V3.6: Fetch from DB (Global + Guild)
        from memer.helpers import db
        sounds = await db.get_sounds_for_guild(interaction.guild.id)
        
        if not sounds:
            return await interaction.followup.send("⚠️ No beep sounds available in this server.", ephemeral=True)

        # Random Only Logic
        sound = random.choice(sounds)
        filename = sound['filename']
        display_name = sound['display_name']
        path = os.path.join(SOUND_FOLDER, filename)

        ok = await queue_audio(channel, interaction.user, path, 1.0, interaction, play_clip)
        
        if ok:
            from .audio_events import signal_activity
            signal_activity(interaction.guild.id)
            
            # Get sound metadata (Use DB data!)
            # metadata = get_sound_metadata(filename) # V3.6: Deprecated for this flow
            # We already have display_name from DB
            
            # Find thumbnail (still need helper or path check)
            thumbnail_url = None
            stem = Path(filename).stem.lower()
            dashboard_url = os.getenv('DASHBOARD_URL', 'http://your-bot-url')
            # Quick check for thumb
            for ext in ['.png', '.jpg', '.jpeg', '.gif']:
                if os.path.exists(os.path.join(SOUND_FOLDER, f"{stem}_thumb{ext}")):
                   thumbnail_url = f"{dashboard_url}/sounds/{stem}_thumb{ext}"
                   break
            
            # Create rich embed with thumbnail
            embed = discord.Embed(
                title="🔊 Now Playing",
                description=f"**{display_name}**",
                color=discord.Color.green()
            )
            
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
            
            dashboard_url = os.getenv("DASHBOARD_URL", "http://your-bot-url")
            embed.add_field(
                name="💡 Want to pick a specific sound?",
                value=f"Visit the **[MemeBoard]({dashboard_url})**!",
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="⚠️ Playback Failed",
                description="Could not play right now (cooldown or voice issue). Try again in a few seconds.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Beep(bot))

