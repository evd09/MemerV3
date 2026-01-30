# File: bot.py
import os
import sys
import asyncio
import pathlib
import discord
import logging
import importlib
import yaml
from types import SimpleNamespace
from dotenv import load_dotenv
from discord.ext import commands
from discord import Object

try:
    load_dotenv()
except UnicodeDecodeError:
    load_dotenv(encoding="latin-1")

from memer.helpers.guild_subreddits import persist_cache
from memer.helpers import db
from memer import meme_stats
from memer.web.stats_server import start_stats_server
import aiohttp

DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0"))
DISABLE_GLOBAL_COMMANDS = os.getenv("DISABLE_GLOBAL_COMMANDS", "0") == "1"
TOKEN = os.getenv("DISCORD_TOKEN")
LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)-15s %(message)s",
)
log = logging.getLogger(__name__)

class MemeBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="/",
            help_command=None,
            intents=discord.Intents.all(),
        )

    async def on_raw_reaction_add(self, payload):
        # Global listener removed after debugging
        pass

    def __init__(self):
        super().__init__(
            command_prefix="/",
            help_command=None,
            intents=discord.Intents.all(),
        )
        self.session: aiohttp.ClientSession = None

        # Load config
        MEME_CACHE_CONFIG = self.load_yaml_config().get("meme_cache", {})
        self.config = SimpleNamespace(
            DEV_GUILD_ID=DEV_GUILD_ID,
            MEME_CACHE=MEME_CACHE_CONFIG,
            DISABLE_GLOBAL_COMMANDS=DISABLE_GLOBAL_COMMANDS,
        )

    def load_yaml_config(self, path="config/cache.yml"):
        if os.path.exists(path):
            with open(path, "r") as f:
                return yaml.safe_load(f)
        return {}

    async def setup_hook(self):
        # 1. Init Session
        self.session = aiohttp.ClientSession()
        log.info("✅ aiohttp session initialized")

        # 2. Directories
        self.ensure_audio_dirs()

        # 3. DB & Stats
        await db.init()
        await db.prune_old_records(days=30)
        await meme_stats.init()
        asyncio.create_task(start_stats_server())

        # 4. Load Extensions
        await self.load_extensions()

        # 5. Sync Commands
        if self.config.DEV_GUILD_ID:
            guild = Object(id=self.config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Slash commands synced to guild {guild.id}")
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally")

        # 6. Cache
        # usage of persist_cache is manual save on exit, no init needed for simple JSON implementation

    async def close(self):
        await super().close()
        if self.session:
            await self.session.close()
        await db.close()
        await meme_stats.close()
        persist_cache()
        log.info("Bot closed gracefully")

    def ensure_audio_dirs(self):
        os.makedirs("./sounds", exist_ok=True)
        os.makedirs("./data", exist_ok=True)
        os.makedirs("./logs", exist_ok=True)

    async def load_extensions(self):
        log.info("🔍 Loading extensions...")
        COGS_DIR = pathlib.Path(__file__).parent / "cogs"
        module_paths = []
        for file in COGS_DIR.rglob("*.py"):
            if file.name == "__init__.py" or file.stem in (
                "store", "audio_player", "audio_queue", "audio_events", "voice_error_manager", "constants"
            ):
                continue
            relative = file.relative_to(COGS_DIR).with_suffix("")
            module_paths.append(".".join(["memer", "cogs", *relative.parts]))

        for path in module_paths:
            try:
                await self.load_extension(path)
                log.info("✅ Loaded cog: %s", path)
            except Exception as e:
                log.warning("⚠️ Failed to load cog %s: %s", path, e)
                
        # Manually load audio events as it was done in main() previously
        try:
             events = importlib.import_module("memer.cogs.audio.audio_events")
             await events.setup(self)
        except Exception as e:
             log.warning("Failed to setup audio_events: %s", e)


bot = MemeBot()

async def main():
    try:
        if not TOKEN:
            log.error("Missing DISCORD_TOKEN")
            return
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        log.exception("Fatal error starting bot")

if __name__ == "__main__":
    asyncio.run(main())
