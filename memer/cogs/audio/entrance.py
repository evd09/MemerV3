# cogs/audio/entrance.py
import os
import json 
from pathlib import Path
import discord
import asyncio
from discord.ui import View, Select, Button
from discord.ext import commands
from discord import app_commands   
from .audio_events import signal_activity
from .audio_player import play_clip
from .audio_queue import queue_audio
from memer.config import SOUND_FOLDER, ENTRANCE_DATA, AUDIO_EXTS

class EntranceView(View):
    def __init__(self, cog, user, files, current_file, current_volume, channel, page=0):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.files = files # List of dicts: {'filename': str, 'display_name': str}
        # Safely get first filename
        first_file = files[0]['filename'] if files and isinstance(files[0], dict) else (files[0] if files else None)
        self.selected_file = current_file or first_file
        self.volume = current_volume
        self.saved_file = current_file
        self.saved_volume = current_volume
        self.channel = channel
        self.message: discord.Message = None
        self._voice_monitor_task = None

        self.page = page
        self.page_size = 25
        self.max_page = (len(files) - 1) // self.page_size

        # Add selects
        self.add_selects()

        # Add pagination buttons on row 3 if needed
        self.add_pagination()

    def format_message(self, prefix: str) -> str:
        # Resolve display name for saved file
        saved_name = self.saved_file
        if self.saved_file:
            # Try to find in files list
            found = next((f for f in self.files if f['filename'] == self.saved_file), None)
            if found:
                saved_name = found['display_name']
        
        status = (
            f"Current entrance: `{saved_name}` — Volume: {int(self.saved_volume*100)}%"
            if self.saved_file else "Current entrance: none set."
        )
        return f"{prefix}\n{status}"

    def add_selects(self):
        # Always remove selects if already present
        for child in list(self.children):
            if isinstance(child, Select):
                self.remove_item(child)
        start = self.page * self.page_size
        end = start + self.page_size
        current_page_files = self.files[start:end]
        
        # Build options using display_name for label, filename for value
        file_options = []
        for f in current_page_files:
            # Truncate label to 100 chars
            label = (f['display_name'][:98] + "..") if len(f['display_name']) > 100 else f['display_name']
            file_options.append(discord.SelectOption(label=label, value=f['filename']))
            
        file_select = Select(placeholder="Select file", options=file_options, custom_id="file_select", row=0)
        file_select.callback = self.on_file_select
        self.add_item(file_select)

        vol_options = [discord.SelectOption(label=f"{i*10}%", value=str(i/10)) for i in range(1, 11)]
        vol_select = Select(placeholder="Select volume", options=vol_options, custom_id="volume_select", row=1)
        vol_select.callback = self.on_volume_select
        self.add_item(vol_select)

    def add_pagination(self):
        # Always remove old pagers if present
        for child in list(self.children):
            if isinstance(child, Button) and getattr(child, "custom_id", None) in ("prev_page", "next_page"):
                self.remove_item(child)
        if self.max_page > 0:
            prev = Button(
                label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_page", row=3,
                disabled=(self.page == 0)
            )
            prev.callback = self.prev_page
            self.add_item(prev)

            nextb = Button(
                label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="next_page", row=3,
                disabled=(self.page == self.max_page)
            )
            nextb.callback = self.next_page
            self.add_item(nextb)

    async def change_page(self, interaction, new_page):
        self.page = new_page
        self.max_page = (len(self.files) - 1) // self.page_size
        self.add_selects()
        self.add_pagination()
        await interaction.response.edit_message(
            content=self.format_message(
                f"🎛️ Manage your entrance (Page {self.page+1}/{self.max_page+1}):"
            ),
            view=self
        )

    async def on_file_select(self, interaction: discord.Interaction):
        self.selected_file = interaction.data["values"][0]
        
        # Resolve display name
        display_name = self.selected_file
        found = next((f for f in self.files if f['filename'] == self.selected_file), None)
        if found:
            display_name = found['display_name']

        await interaction.response.edit_message(
            content=self.format_message(
                f"✅ Selected `{display_name}` — Volume: {int(self.volume*100)}%"
            ),
            view=self
        )

    async def on_volume_select(self, interaction: discord.Interaction):
        self.volume = float(interaction.data["values"][0])
        await interaction.response.edit_message(
            content=self.format_message(
                f"✅ Volume set to {int(self.volume*100)}% — File: `{self.selected_file}`"
            ),
            view=self
        )

    @discord.ui.button(label="🔊 Preview", style=discord.ButtonStyle.primary, custom_id="preview", row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.selected_file:
            path = os.path.join(SOUND_FOLDER, self.selected_file)
            success = await queue_audio(self.channel, interaction.user, path, self.volume, interaction, play_clip)
            if not success:
                return
            signal_activity(interaction.guild.id)
            msg = self.format_message(
                f"🎧 Previewing `{self.selected_file}` at {int(self.volume*100)}%\n(You can keep changing file/volume and preview as much as you want before saving!)"
            )
            if self.message:
                await self.message.edit(content=msg, view=self)
            else:
                await interaction.edit_original_response(content=msg, view=self)
        else:
            await interaction.edit_original_response(
                content=self.format_message("❌ No entrance file selected."),
                view=self
            )

    @discord.ui.button(label="💾 Save", style=discord.ButtonStyle.success, custom_id="save", row=2)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # Save to DB (Per-Guild)
        from memer.helpers import db
        await db.set_entrance_sound(interaction.user.id, interaction.guild.id, self.selected_file, self.volume)
        
        self.saved_file = self.selected_file
        self.saved_volume = self.volume
        
        for child in self.children:
            child.disabled = True
            
        msg = self.format_message("✅ Entrance saved! (For this server)")
        if self.message:
            await self.message.edit(content=msg, view=self)
        else:
            await interaction.edit_original_response(content=msg, view=self)
        self.stop()
    
    @discord.ui.button(label="❌ Remove", style=discord.ButtonStyle.danger, custom_id="remove", row=2)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # Remove from DB (Per-Guild)
        from memer.helpers import db
        await db.delete_entrance_sound(interaction.user.id, interaction.guild.id)
        
        self.saved_file = None
        self.saved_volume = 1.0
        msg = self.format_message("🗑️ Entrance removed for this server.")
        
        if self.message:
            await self.message.edit(content=msg, view=self)
        else:
            await interaction.edit_original_response(content=msg, view=self)

    async def prev_page(self, interaction: discord.Interaction):
        await self.change_page(interaction, self.page - 1)

    async def next_page(self, interaction: discord.Interaction):
        await self.change_page(interaction, self.page + 1)

    async def start_voice_monitor(self, interaction: discord.Interaction):
        await asyncio.sleep(1)
        guild = interaction.guild
        user_id = self.user.id
        while not self.is_finished():
            await asyncio.sleep(2)
            if self.is_finished() or not self.message:
                break
            member = guild.get_member(user_id)
            if not member or not member.voice or not member.voice.channel:
                for child in self.children:
                    child.disabled = True
                await self.message.edit(
                    content="❌ You are no longer in a voice channel. Please join a voice channel and run `/entrance` again to set your entrance.",
                    view=self
                )
                self.stop()
                break

    async def interaction_check(self, interaction):
        if not self._voice_monitor_task:
            self._voice_monitor_task = asyncio.create_task(self.start_voice_monitor(interaction))
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(
                content="⏳ Sorry, this session timed out. Nothing was saved. Please run `/entrance` again.",
                view=self
            )

class Entrance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reload_cache()

    def load_data(self):
        """Load entrance data from JSON file (legacy, for backwards compatibility only).
        V3.7.4: No longer auto-creates JSON file - all data now lives in database.
        """
        if not os.path.exists(ENTRANCE_DATA):
            return {}  # Return empty dict instead of creating file
        try:
            with open(ENTRANCE_DATA, "r") as f:
                data = json.load(f)
            return self._migrate_data(data)
        except (json.JSONDecodeError, IOError):
            return {}  # Return empty on error instead of crashing

    def _migrate_data(self, data):
        """Migrate old entrance format to new V3.4 format."""
        migrated = {}
        for user_id, config in data.items():
            # Check if already in new format
            if isinstance(config, dict) and "type" in config:
                migrated[user_id] = config
            # Old format: {"file": "x", "volume": 1.0}
            elif isinstance(config, dict) and "file" in config:
                migrated[user_id] = {
                    "type": "single",
                    "single": {
                        "file": config["file"],
                        "volume": config.get("volume", 1.0)
                    },
                    "admin_override": {
                        "enabled": False,
                        "file": None,
                        "volume": None,
                        "set_by": None,
                        "timestamp": None
                    }
                }
            else:
                # Unknown format, skip
                continue
        return migrated

    def save_data(self):
        """Legacy save method - V3.7.4: No-op, all data now saved to database."""
        pass  # No longer writes to JSON file

    def reload_cache(self):
        """Reload entrance data cache (legacy, for backwards compatibility).
        V3.7.4: This cache is deprecated - all operations use database directly.
        """
        self.entrance_data = self.load_data()

    def get_valid_files(self):
        """Get valid entrance files, preferring .opus over .mp3."""
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
        
        return list(audio_files.values())

    # === V3.6.2 DB Methods (Removed - see lines 398+ for V3.7 implementations) ===

    def get_admin_override(self, user_id: str, guild_id: int = None) -> dict:
        """Check if admin has overridden user's entrance."""
        config = self.entrance_data.get(user_id, {})
        override = config.get("admin_override", {"enabled": False})
        return override
    
    async def clear_entrance(self, user_id: str, guild_id: int):
        """Clear entrance configuration for a user in a specific guild (V3.7)."""
        from memer.helpers import db
        await db.delete_entrance_sound(int(user_id), guild_id)

    @app_commands.command(name="entrance", description="Manage your entrance sound.")
    async def entrance(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ You must be in a voice channel.", ephemeral=True
            )
            return
        channel = interaction.user.voice.channel
        uid = str(interaction.user.id)
        
        # Defer fetching
        await interaction.response.defer(ephemeral=True)

        # Get per-guild config
        user_data = await self.get_entrance_config(uid, interaction.guild.id)
        current_file = user_data.get("single", {}).get("file")
        current_volume = user_data.get("single", {}).get("volume", 1.0)
        
        # V3.6: Fetch from DB (Global + Guild)
        from memer.helpers import db
        files = await db.get_sounds_for_guild(interaction.guild.id)
        
        if not files:
            await interaction.followup.send("⚠️ No entrance sounds available.", ephemeral=True)
            return

        # Only continue if NOT on cooldown/etc.
        success = await queue_audio(channel, interaction.user, "", 1.0, interaction, play_clip)
        if not success:
            return

        signal_activity(interaction.guild.id)
        view = EntranceView(
            self,
            interaction.user,
            files,
            current_file,
            current_volume,
            channel,
            page=0,
        )
        await interaction.followup.send(
            view.format_message("🎛️ Manage your entrance:\n*(You can also use the Web Portal for this)*"),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


    async def get_entrance_config(self, user_id: str, guild_id: int) -> dict:
        """Fetch V3.7+ per-guild entrance config."""
        from memer.helpers import db
        data = await db.get_entrance_sound(int(user_id), guild_id)

        print(f"[ENTRANCE COG DEBUG] get_entrance_config called for user {user_id}, guild {guild_id}")
        print(f"[ENTRANCE COG DEBUG] Raw DB data: {data}")

        # Default empty structure if nothing found
        if not data:
            print(f"[ENTRANCE COG DEBUG] No data found, returning empty config")
            return {
                "type": "single",
                "single": {"file": None, "volume": 1.0},
                "multiple": [],
                "combo": [],
                "scheduled": {"default": {"file": None, "volume": 1.0}, "rules": []}
            }

        # Parse based on type
        conf = {
            "type": data.get("type", "single"),
            "single": {"file": None, "volume": 1.0},
            "multiple": [],
            "combo": [],
            "scheduled": {"default": {"file": None, "volume": 1.0}, "rules": []}
        }

        raw_data = data.get("data", {})
        print(f"[ENTRANCE COG DEBUG] raw_data type: {type(raw_data)}, value: {raw_data}")

        # Safety net: Ensure raw_data is a dict
        if isinstance(raw_data, str):
            try:
                import json
                raw_data = json.loads(raw_data)
                print(f"[ENTRANCE COG DEBUG] Parsed JSON once: {raw_data}")
                # Triple safety check
                if isinstance(raw_data, str):
                     try:
                         raw_data = json.loads(raw_data)
                         print(f"[ENTRANCE COG DEBUG] Parsed JSON twice: {raw_data}")
                     except: pass
            except:
                raw_data = {}

        if conf["type"] == "single":
            conf["single"] = raw_data
        elif conf["type"] == "multiple":
            conf["multiple"] = raw_data
        elif conf["type"] == "combo":
            conf["combo"] = raw_data
        elif conf["type"] == "scheduled":
            conf["scheduled"] = raw_data

        print(f"[ENTRANCE COG DEBUG] Final config: {conf}")
        return conf

    async def set_entrance_single(self, user_id: str, guild_id: int, file: str, volume: float):
        from memer.helpers import db
        # V3.7: type='single', data={'file': ..., 'volume': ...}
        print(f"[ENTRANCE COG DEBUG] set_entrance_single: user={user_id}, guild={guild_id}, file={file}, volume={volume}")
        await db.set_entrance_config(int(user_id), guild_id, 'single', {'file': file, 'volume': volume})

    async def set_entrance_multiple(self, user_id: str, guild_id: int, sounds: list):
        from memer.helpers import db
        # V3.7: type='multiple', data=[{'file':..., 'volume':...}, ...]
        print(f"[ENTRANCE COG DEBUG] set_entrance_multiple: user={user_id}, guild={guild_id}, sounds={sounds}")
        await db.set_entrance_config(int(user_id), guild_id, 'multiple', sounds)

    async def set_entrance_combo(self, user_id: str, guild_id: int, sounds: list):
        from memer.helpers import db
        # V3.7: type='combo', data=[{'file':..., 'volume':..., 'delay':...}, ...]
        print(f"[ENTRANCE COG DEBUG] set_entrance_combo: user={user_id}, guild={guild_id}, sounds={sounds}")
        await db.set_entrance_config(int(user_id), guild_id, 'combo', sounds)

    async def set_entrance_scheduled(self, user_id: str, guild_id: int, config: dict):
        from memer.helpers import db
        # V3.7: type='scheduled', data={'default':..., 'rules':...}
        print(f"[ENTRANCE COG DEBUG] set_entrance_scheduled: user={user_id}, guild={guild_id}, config={config}")
        await db.set_entrance_config(int(user_id), guild_id, 'scheduled', config)


    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Play entrance sound when a user joins a voice channel."""
        if member.bot: return
        
        # Strictly on fresh join for now
        if before.channel is not None or after.channel is None:
            return

        # 2. Get Per-Guild Config from DB
        from memer.helpers import db
        row = await db.get_entrance_sound(member.id, member.guild.id)
        if not row: return

        e_type = row.get("type", "single")
        data = row.get("data", {})
        
        files_to_play = [] # List of (path, volume, delay_ms)

        if e_type == "single":
            f = data.get("file")
            v = data.get("volume", 1.0)
            if f: files_to_play.append((f, v, 0))

        elif e_type == "multiple":
            # Pick one random
            if isinstance(data, list) and len(data) > 0:
                import random
                choice = random.choice(data)
                if choice.get("file"):
                    files_to_play.append((choice["file"], choice.get("volume", 1.0), 0))

        elif e_type == "combo":
            # Play sequence
            if isinstance(data, list):
                for item in data:
                    if item.get("file"):
                        files_to_play.append((item["file"], item.get("volume", 1.0), item.get("delay", 0)))

        elif e_type == "scheduled":
            # Check rules
            import datetime
            now = datetime.datetime.now() # Local time? Or UTC? Ideally UTC but user might expect server time.
            # Using server local time if possible or just bot system time.
            # Rules: days (0-6), hours (0-23)
            current_day = now.weekday() # 0=Mon, 6=Sun
            current_hour = now.hour
            
            matched = False
            rules = data.get("rules", [])
            default = data.get("default", {})
            
            for r in rules:
                if current_day in r.get("days", []) and r["hours"][0] <= current_hour <= r["hours"][1]:
                    if r.get("file"):
                        files_to_play.append((r["file"], r.get("volume", 1.0), 0))
                        matched = True
                        break
            
            if not matched and default.get("file"):
                files_to_play.append((default["file"], default.get("volume", 1.0), 0))

        # 3. Queue Audio
        # For multi-sound entrance types (combo, multiple), skip cooldown to allow sequential queueing
        skip_cooldown = len(files_to_play) > 1

        for fname, vol, delay in files_to_play:
            file_path = os.path.join(SOUND_FOLDER, fname)
            if os.path.exists(file_path):
                # If delay involved (for combo), we might need a better player.
                # For now, queue_audio queues them back-to-back.
                # To support 'delay', we unfortunately can't block here easily without holding up the event loop too much?
                # But 'queue_audio' is async.
                # Actually, queue_audio puts it in a queue. If we just queue them all, they play back to back.
                # The 'delay' param in combo is intended to be a pause BETWEEN sounds.
                # Since audio_queue doesn't support 'pause duration' items, we might ignore delay for now or implement a 'sleep' sound?
                # For V3.7 MVP, we'll ignore delay or just resolve to queueing.

                # To truly support delays, we'd need to modify audio_queue to accept 'Pause' items.
                # Skipping delay implementation for this step to ensure basic functionality first.

                await queue_audio(
                    after.channel,
                    member,
                    file_path,
                    vol,
                    None,
                    play_clip,
                    skip_cooldown=skip_cooldown
                )

        # 4. Signal Activity
        if files_to_play:
            signal_activity(member.guild.id)


async def setup(bot):
    await bot.add_cog(Entrance(bot))

