# cogs/audio/beep.py
import os
import random
import logging
import discord
from discord.ext import commands
from discord import app_commands
from .audio_player import play_clip  # does NOT manage cooldowns/locks
from .audio_queue import queue_audio  # all logic for cooldown/locks/4006 is here
from .constants import SOUND_FOLDER, AUDIO_EXTS
from memer.utils.logger_setup import setup_logger

logger = setup_logger("beep", "beep.log")

beep_cache: list[str] = []


def load_beeps() -> list[str]:
    """Load available beep files into cache."""
    os.makedirs(SOUND_FOLDER, exist_ok=True)
    global beep_cache
    beep_cache = [
        f for f in os.listdir(SOUND_FOLDER)
        if f.lower().endswith(AUDIO_EXTS)
    ]
    return beep_cache

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
                text = f"🔊 Playing `{filename}`."
            else:
                text = "⚠️ Could not play right now (cooldown or voice issue). Try again in a few seconds."

            if self.message:
                await self.message.edit(content=text, view=self)
            else:
                await interaction.edit_original_response(content=text, view=self)

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
                text = f"🔊 Playing `{filename}`."
            else:
                text = "⚠️ Could not play right now (cooldown or voice issue). Try again in a few seconds."

            if self.message:
                await self.message.edit(content=text, view=self)
            else:
                await interaction.edit_original_response(content=text, view=self)

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

    def get_valid_files(self):
        return beep_cache

    @app_commands.command(name="beeps", description="Play a random beep.")
    async def beeps(self, interaction: discord.Interaction):
        channel = getattr(interaction.user.voice, "channel", None)
        if not channel:
            return await interaction.response.send_message("❌ You must be in a voice channel.", ephemeral=True)

        files = self.get_valid_files()
        if not files:
            return await interaction.response.send_message("⚠️ No beep sounds available.", ephemeral=True)

        # Random Only Logic
        filename = random.choice(files)
        path = os.path.join(SOUND_FOLDER, filename)

        # Defer immediately since we might process audio
        await interaction.response.defer(ephemeral=True)

        ok = await queue_audio(channel, interaction.user, path, 1.0, interaction, play_clip)
        
        if ok:
            from .audio_events import signal_activity
            signal_activity(interaction.guild.id)
            
            # Inform user they can choose specific sounds on the dashboard
            dashboard_url = os.getenv("DASHBOARD_URL", "http://your-bot-url") 
            msg = (
                f"🔊 Playing `{filename}`.\n\n"
                f"💡 Want to pick a specific sound? Visit the **[MemeBoard]({dashboard_url})**!"
            )
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Could not play right now (cooldown or voice issue).", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Beep(bot))

