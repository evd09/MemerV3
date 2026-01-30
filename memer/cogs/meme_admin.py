# cogs/meme_admin.py
import time
from typing import Optional
from pathlib import Path
import subprocess
import logging
import asyncio
import os

import discord
from discord.ext import commands
from discord import app_commands

from memer.helpers.guild_subreddits import (
    remove_guild_subreddit,
    get_guild_subreddits,
)
from memer.helpers.db import (
    get_social_settings, 
    set_social_settings,
    get_voice_settings,
    set_voice_settings
)

from .audio.audio_queue import reset as reset_queue, get_queue
from .audio.voice_error_manager import reset_total_failures
from .audio.audio_events import get_guild_config
from .audio.beep import load_beeps
from .audio.audio_player import preload_audio_clips
from .audio.constants import SOUND_FOLDER

log = logging.getLogger(__name__)

class AddSubredditModal(discord.ui.Modal, title="Add Subreddit"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.name = discord.ui.TextInput(label="Subreddit name")
        self.category = discord.ui.TextInput(label="Category (sfw/nsfw)")
        self.add_item(self.name)
        self.add_item(self.category)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_addsubreddit(
            interaction, self.name.value, self.category.value
        )


class RemoveSubredditView(discord.ui.View):
    def __init__(self, cog: "MemeAdmin", guild_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.category = "sfw"
        self.subreddits = get_guild_subreddits(guild_id, self.category)
        self.selected_subreddit = self.subreddits[0] if self.subreddits else None

        self.page = 0
        self.page_size = 25
        self.max_page = (len(self.subreddits) - 1) // self.page_size

        self.add_category_select()
        self.add_subreddit_select()
        self.add_pagination()

    def content(self) -> str:
        base = f"{self.category.upper()} — Page {self.page+1}/{self.max_page+1}"
        if self.selected_subreddit:
            return f"Selected `{self.selected_subreddit}` ({base})"
        return f"Select a subreddit to remove ({base})"

    def add_category_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select) and child.custom_id == "category_select":
                self.remove_item(child)
        options = [
            discord.SelectOption(label="SFW", value="sfw", default=self.category == "sfw"),
            discord.SelectOption(label="NSFW", value="nsfw", default=self.category == "nsfw"),
        ]
        select = discord.ui.Select(
            placeholder="Select category",
            options=options,
            custom_id="category_select",
            row=0,
        )
        select.callback = self.on_category_select
        self.add_item(select)

    def add_subreddit_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select) and child.custom_id == "sub_select":
                self.remove_item(child)
        start = self.page * self.page_size
        end = start + self.page_size
        current = self.subreddits[start:end]
        if current:
            if self.selected_subreddit not in current:
                self.selected_subreddit = current[0]
            options = [discord.SelectOption(label=s) for s in current]
            select = discord.ui.Select(
                placeholder="Select subreddit",
                options=options,
                custom_id="sub_select",
                row=1,
            )
            select.callback = self.on_subreddit_select
        else:
            self.selected_subreddit = None
            select = discord.ui.Select(
                placeholder="No subreddits",
                options=[discord.SelectOption(label="None", value="none")],
                custom_id="sub_select",
                row=1,
                disabled=True,
            )
        self.add_item(select)
        self.update_confirm_button()

    def add_pagination(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and getattr(child, "custom_id", None) in (
                "prev_page",
                "next_page",
            ):
                self.remove_item(child)
        if self.max_page > 0:
            prev = discord.ui.Button(
                label="⬅️ Prev",
                style=discord.ButtonStyle.secondary,
                custom_id="prev_page",
                row=3,
                disabled=self.page == 0,
            )
            prev.callback = self.prev_page
            self.add_item(prev)

            nextb = discord.ui.Button(
                label="Next ➡️",
                style=discord.ButtonStyle.secondary,
                custom_id="next_page",
                row=3,
                disabled=self.page == self.max_page,
            )
            nextb.callback = self.next_page
            self.add_item(nextb)

    def update_confirm_button(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and getattr(child, "custom_id", None) == "confirm_remove":
                child.disabled = self.selected_subreddit is None

    async def change_page(self, interaction: discord.Interaction, new_page: int):
        self.page = new_page
        self.max_page = (len(self.subreddits) - 1) // self.page_size
        self.add_subreddit_select()
        self.add_pagination()
        await interaction.response.edit_message(content=self.content(), view=self)

    async def on_category_select(self, interaction: discord.Interaction):
        self.category = interaction.data["values"][0]
        self.subreddits = get_guild_subreddits(self.guild_id, self.category)
        self.selected_subreddit = self.subreddits[0] if self.subreddits else None
        self.page = 0
        self.max_page = (len(self.subreddits) - 1) // self.page_size
        self.add_subreddit_select()
        self.add_pagination()
        await interaction.response.edit_message(content=self.content(), view=self)

    async def on_subreddit_select(self, interaction: discord.Interaction):
        self.selected_subreddit = interaction.data["values"][0]
        self.update_confirm_button()
        await interaction.response.edit_message(content=self.content(), view=self)

    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change_page(interaction, self.page - 1)

    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.change_page(interaction, self.page + 1)

    @discord.ui.button(
        label="Remove",
        style=discord.ButtonStyle.danger,
        custom_id="confirm_remove",
        row=2,
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_subreddit:
            await interaction.response.send_message("No subreddit selected.", ephemeral=True)
            return
        await self.cog.handle_removesubreddit(
            interaction, self.selected_subreddit, self.category
        )
        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass


class IdleTimeoutModal(discord.ui.Modal, title="Set Idle Timeout"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.enabled = discord.ui.TextInput(label="Enabled (true/false)")
        self.seconds = discord.ui.TextInput(label="Seconds", required=False)
        self.add_item(self.enabled)
        self.add_item(self.seconds)

    async def on_submit(self, interaction: discord.Interaction):
        enabled = self.enabled.value.lower() == "true"
        secs = int(self.seconds.value) if self.seconds.value else None
        await self.cog.handle_set_idle_timeout(interaction, enabled, secs)






class SocialSettingsView(discord.ui.View):
    def __init__(self, cog: "MemeAdmin", guild_id: int, enabled: bool, allowed_channels: set):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.enabled = enabled
        self.allowed_channels = allowed_channels
        self.update_components()

    def update_components(self):
        # 1. Toggle Button
        self.clear_items()
        
        status_label = "ENABLED" if self.enabled else "DISABLED"
        style = discord.ButtonStyle.success if self.enabled else discord.ButtonStyle.danger
        toggle_btn = discord.ui.Button(label=f"Status: {status_label}", style=style, custom_id="toggle_social", row=0)
        toggle_btn.callback = self.on_toggle
        self.add_item(toggle_btn)
        
        # 2. Channel Select
        # We need to list TextChannels. Discord limits select options to 25.
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild:
            channels = [c for c in guild.text_channels if c.permissions_for(guild.me).send_messages]
            # Sort by position
            channels.sort(key=lambda c: c.position)
            
            # chunking? Let's just take first 25 for UI simplicity
            options = []
            for ch in channels[:25]:
                is_selected = ch.id in self.allowed_channels
                options.append(
                    discord.SelectOption(
                        label=f"#{ch.name}", 
                        value=str(ch.id), 
                        default=is_selected,
                        description=str(ch.id)
                    )
                )
            
            if options:
                select = discord.ui.Select(
                    placeholder="Select Allow-List Channels (Max 25 shown)",
                    options=options,
                    min_values=0,
                    max_values=len(options),
                    custom_id="channel_select",
                    row=1
                )
                select.callback = self.on_channel_select
                self.add_item(select)

        # 3. Save Button
        save_btn = discord.ui.Button(label="Save Settings", style=discord.ButtonStyle.primary, row=2)
        save_btn.callback = self.on_save
        self.add_item(save_btn)

    async def on_toggle(self, interaction: discord.Interaction):
        self.enabled = not self.enabled
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def on_channel_select(self, interaction: discord.Interaction):
        selected_ids = set(map(int, interaction.data["values"]))
        self.allowed_channels = selected_ids
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def on_save(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await set_social_settings(self.guild_id, self.enabled, list(self.allowed_channels))
        
        # Confirm
        await interaction.followup.send("✅ Social settings saved!", ephemeral=True)
        # Disable
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(view=self)



class VoiceSettingsView(discord.ui.View):
    def __init__(self, cog: "MemeAdmin", guild_id: int, is_public: bool):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.is_public = is_public
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Toggle
        status_label = "PUBLIC (Everyone sees)" if self.is_public else "PRIVATE (Only sender sees)"
        style = discord.ButtonStyle.success if self.is_public else discord.ButtonStyle.secondary
        
        toggle_btn = discord.ui.Button(
            label=f"Mode: {status_label}", 
            style=style, 
            custom_id="toggle_voice", 
            row=0,
            emoji="🗣️" if self.is_public else "🔒"
        )
        toggle_btn.callback = self.on_toggle
        self.add_item(toggle_btn)
        
        # Note
        note_btn = discord.ui.Button(
            label="Note: Privacy applies to the text response. Audio is always public in VC.", 
            style=discord.ButtonStyle.gray, 
            disabled=True, 
            row=1
        )
        self.add_item(note_btn)

    async def on_toggle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.is_public = not self.is_public
        await set_voice_settings(self.guild_id, self.is_public)
        self.update_components()
        await interaction.edit_original_response(view=self)


class AdminUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_user = self.values[0]
        await interaction.response.defer()


class AdminFileSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Select file",
            options=options,
            custom_id="file_select",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_file = self.values[0]
        await interaction.response.defer()


class AdminSetEntranceView(discord.ui.View):
    def __init__(self, cog: "MemeAdmin", files):
        super().__init__(timeout=60)
        self.cog = cog
        self.files = files
        self.selected_user: Optional[discord.abc.User] = None
        self.selected_file: Optional[str] = None
        self.page = 0
        self.page_size = 25
        self.max_page = (len(self.files) - 1) // self.page_size

        self.add_item(AdminUserSelect())
        self.add_file_select()
        self.add_pagination()

    @property
    def content(self) -> str:
        return f"Select a user and entrance file (Page {self.page+1}/{self.max_page+1})"

    def add_file_select(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select) and getattr(child, "custom_id", None) == "file_select":
                self.remove_item(child)
        start = self.page * self.page_size
        end = start + self.page_size
        current = self.files[start:end]
        options = [discord.SelectOption(label=f) for f in current]
        self.add_item(AdminFileSelect(options))

    def add_pagination(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and getattr(child, "custom_id", None) in ("prev_page", "next_page"):
                self.remove_item(child)
        if self.max_page > 0:
            prev = discord.ui.Button(
                label="⬅️ Prev",
                style=discord.ButtonStyle.secondary,
                custom_id="prev_page",
                row=3,
                disabled=self.page == 0,
            )
            prev.callback = self.prev_page
            self.add_item(prev)

            nextb = discord.ui.Button(
                label="Next ➡️",
                style=discord.ButtonStyle.secondary,
                custom_id="next_page",
                row=3,
                disabled=self.page == self.max_page,
            )
            nextb.callback = self.next_page
            self.add_item(nextb)

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.add_file_select()
        self.add_pagination()
        await interaction.response.edit_message(content=self.content, view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.add_file_select()
        self.add_pagination()
        await interaction.response.edit_message(content=self.content, view=self)

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, row=2)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_user or not self.selected_file:
            await interaction.response.send_message(
                "Please select a user and a file.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog.handle_setentrance(
            interaction, self.selected_user, self.selected_file
        )
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()


class AdminView(discord.ui.View):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__(timeout=60)
        self.cog = cog
        self.message: discord.Message | None = None
        
        # Dashboard Link
        # Dashboard Link
        redirect_uri = os.getenv("DISCORD_REDIRECT_URI", "")
        # Remove /callback from the end to get the base URL
        dash_url = redirect_uri.replace("/callback", "")
        
        if dash_url:
            self.add_item(discord.ui.Button(label="Dashboard", url=f"{dash_url}/admin", emoji="🌐", row=2))

    @discord.ui.button(label="Ping", style=discord.ButtonStyle.primary, row=0)
    async def ping(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_ping(interaction)

    @discord.ui.button(label="Uptime", style=discord.ButtonStyle.primary, row=0)
    async def uptime(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_uptime(interaction)

    @discord.ui.button(label="Social Media", style=discord.ButtonStyle.primary, emoji="📱", row=0)
    async def social_media(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_social_settings(interaction)

    @discord.ui.button(label="Voice Settings", style=discord.ButtonStyle.primary, emoji="🗣️", row=0)
    async def voice_settings(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_voice_settings(interaction)

    # Row 1


    @discord.ui.button(label="Reset Voice Error", style=discord.ButtonStyle.secondary, row=1)
    async def reset_voice_error(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_reset_voice_error(interaction)

    @discord.ui.button(label="Set Idle Timeout", style=discord.ButtonStyle.secondary, row=1)
    async def set_idle_timeout(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(IdleTimeoutModal(self.cog))

    @discord.ui.button(label="Set Entrance", style=discord.ButtonStyle.secondary, row=1)
    async def set_entrance(self, interaction: discord.Interaction, _: discord.ui.Button):
        entrance_cog = self.cog.bot.get_cog("Entrance")
        if entrance_cog is None:
            await interaction.response.send_message(
                "Entrance cog not loaded.", ephemeral=True
            )
            return
        files = entrance_cog.get_valid_files()
        if not files:
            await interaction.response.send_message(
                "No entrance sounds available.", ephemeral=True
            )
            return
        view = AdminSetEntranceView(self.cog, files)
        await interaction.response.send_message(
            view.content, view=view, ephemeral=True
        )

    # Row 2 (Red/Danger)
    @discord.ui.button(label="Reload Sounds", style=discord.ButtonStyle.danger, row=2)
    async def reload_sounds(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_reloadsounds(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            log.exception("Failed to disable buttons on timeout in AdminView")


class MemeAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    @app_commands.command(name="memeadmin", description="Admin commands for MEMER")
    async def memeadmin(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            use_followup = True
        except discord.errors.NotFound:
            log.warning("memeadmin defer failed; interaction not found")
            use_followup = False

        if not interaction.user.guild_permissions.administrator:
            if use_followup:
                try:
                    await interaction.followup.send(
                        "❌ Only admins can use this command.", ephemeral=True
                    )
                except discord.errors.NotFound:
                    log.warning(
                        "memeadmin followup send failed; interaction not found"
                    )
                    await interaction.channel.send(
                        "❌ Only admins can use this command."
                    )
            else:
                await interaction.channel.send(
                    "❌ Only admins can use this command."
                )
            return

        view = AdminView(self)
        msg = "Select an admin action:\n*(Manage Subreddits and Cache on the Web Dashboard)*"
        if use_followup:
            try:
                msg = await interaction.followup.send(
                    msg, view=view, ephemeral=True
                )
            except discord.errors.NotFound:
                log.warning(
                    "memeadmin followup send failed; interaction not found"
                )
                msg = await interaction.channel.send(
                    msg, view=view
                )
        else:
            msg = await interaction.channel.send(
                msg, view=view
            )
        view.message = msg

    # ----- Handlers -----
    async def handle_ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! Latency is {latency_ms}ms", ephemeral=True
        )

    async def handle_uptime(self, interaction: discord.Interaction):
        elapsed = time.time() - self.start_time
        hours, rem = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(rem, 60)
        await interaction.response.send_message(
            f"⏱️ Uptime: {hours}h {minutes}m {seconds}s", ephemeral=True
        )

    async def handle_addsubreddit(
        self, interaction: discord.Interaction, name: str, category: str
    ):
        if category not in ("sfw", "nsfw"):
            await interaction.response.send_message(
                "Category must be 'sfw' or 'nsfw'.", ephemeral=True
            )
            return
        add_guild_subreddit(interaction.guild.id, name, category)
        count = len(get_guild_subreddits(interaction.guild.id, category))
        warning = ""
        if count >= 40:
            warning = (
                f"\n⚠️ **Warning:** {category.upper()} subreddits now has {count} entries. "
                "Too many may slow the bot or hit API limits!"
            )
        await interaction.response.send_message(
            f"✅ Added `{name}` to {category.upper()} subreddits for this server.{warning}",
            ephemeral=True,
        )

    async def handle_removesubreddit(
        self, interaction: discord.Interaction, name: str, category: str
    ):
        await interaction.response.defer(ephemeral=True)
        remove_guild_subreddit(interaction.guild.id, name, category)
        await interaction.followup.send(
            f"✅ Removed `{name}` from the {category.upper()} subreddits list for this server.",
            ephemeral=True,
        )

    async def handle_validatesubreddits(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        meme_cog = self.bot.get_cog("Meme")
        if meme_cog is None:
            await interaction.followup.send("❌ Meme cog not loaded.", ephemeral=True)
            return
        results = {"sfw": [], "nsfw": []}
        for cat in ["sfw", "nsfw"]:
            subs = get_guild_subreddits(interaction.guild.id, cat)
            for sub in subs:
                try:
                    await meme_cog.reddit.subreddit(sub, fetch=True)
                    status = "✅"
                except Exception:
                    status = "❌"
                results[cat].append((sub, status))
        lines = []
        for cat in ("sfw", "nsfw"):
            valids = sum(1 for _, st in results[cat] if st == "✅")
            total = len(results[cat])
            lines.append(f"**{cat.upper()}** ({valids}/{total} valid):")
            for name, status in results[cat]:
                lines.append(f"{status} {name}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def handle_reset_voice_error(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        reset_queue(gid)
        reset_total_failures(gid)
        get_queue(gid).clear()
        await interaction.response.send_message(
            "✅ Voice error status/cooldown for this server has been reset. Try your entrance or beep again!",
            ephemeral=True,
        )

    async def handle_set_idle_timeout(
        self, interaction: discord.Interaction, enabled: bool, seconds: Optional[int] = None
    ):
        conf = get_guild_config(interaction.guild.id)
        conf["enabled"] = enabled
        if seconds is not None and enabled:
            conf["seconds"] = max(10, int(seconds))
        await interaction.response.send_message(
            f"✅ Idle timeout is now {'ENABLED' if enabled else 'DISABLED'}"
            + (f" ({conf['seconds']}s)" if enabled else ""),
            ephemeral=True,
        )



    async def handle_setentrance(
        self, interaction: discord.Interaction, user: discord.User, filename: str
    ):
        entrance_cog = self.bot.get_cog("Entrance")
        send = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        if entrance_cog is None:
            await send("Entrance cog not loaded.", ephemeral=True)
            return
        files = entrance_cog.get_valid_files()
        if filename not in files:
            await send("That file doesn't exist!", ephemeral=True)
            return
        entrance_cog.entrance_data[str(user.id)] = {"file": filename, "volume": 1.0}
        entrance_cog.save_data()
        await send(
            f"Set `{filename}` as entrance for {user.mention}.", ephemeral=True
        )

    async def handle_cacheinfo(self, interaction: discord.Interaction):
        meme_cog = self.bot.get_cog("Meme")
        if meme_cog is None:
            await interaction.response.send_message(
                "Meme cog not loaded.", ephemeral=True
            )
            return
        stats = await meme_cog.cache_service.get_cache_info()
        await interaction.response.send_message(
            f"```\n{stats}\n```", ephemeral=True
        )

    async def handle_reloadsounds(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        sound_path = Path(SOUND_FOLDER)
        if sound_path.exists():
            for file in sound_path.iterdir():
                if file.suffix.lower() == ".mp3":
                    tmp_file = file.with_suffix(".tmp.mp3")
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(file),
                            "-c",
                            "copy",
                            str(tmp_file),
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        returncode = await proc.wait()
                        if returncode != 0:
                            raise subprocess.CalledProcessError(returncode, proc.args)
                        tmp_file.replace(file)
                    except subprocess.CalledProcessError:
                        ogg_file = file.with_suffix(".ogg")
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                "ffmpeg",
                                "-y",
                                "-i",
                                str(file),
                                str(ogg_file),
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                            )
                            returncode = await proc.wait()
                            if returncode != 0:
                                raise subprocess.CalledProcessError(returncode, proc.args)
                            file.unlink()
                        except subprocess.CalledProcessError:
                            if ogg_file.exists():
                                ogg_file.unlink()
        load_beeps()
        entrance_cog = self.bot.get_cog("Entrance")
        if entrance_cog and hasattr(entrance_cog, "reload_cache"):
            entrance_cog.reload_cache()
        # audio_cache.cache.clear() # RAM cache removed
        preload_audio_clips()
        await interaction.followup.send(
            "✅ Beep and entrance sounds reloaded.", ephemeral=True
        )

    async def handle_social_settings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        enabled, allowed = await get_social_settings(interaction.guild.id)
        view = SocialSettingsView(self, interaction.guild.id, enabled, allowed)
        await interaction.followup.send("📱 **Social Media Settings**", view=view, ephemeral=True)

    async def handle_voice_settings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        is_public = await get_voice_settings(interaction.guild.id)
        view = VoiceSettingsView(self, interaction.guild.id, is_public)
        await interaction.followup.send("🗣️ **Voice Settings**", view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MemeAdmin(bot))

