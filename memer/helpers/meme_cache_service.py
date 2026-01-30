import asyncio
from discord.ext import tasks
from discord import app_commands
from discord.ext.commands import Context
from .reddit_cache import RedditCacheManager
from .meme_utils import extract_post_data
from memer.helpers.guild_subreddits import DEFAULTS as SUB_DEFAULTS
import yaml
import os
import logging

log = logging.getLogger(__name__)

CONFIG_PATH = "config/cache.yml"
DEFAULTS = {
    "ram_cache_ttl": 900,
    "disk_cache_ttl": 3600,
    "keyword_disable_after": 1,
    "keyword_disable_ttl": 900,
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            try:
                cfg = {**DEFAULTS, **yaml.safe_load(f)}
                log.info(f"Loaded cache config from {CONFIG_PATH}")
                return cfg
            except Exception as e:
                log.error(f"Failed to load {CONFIG_PATH}: {e}")
                return DEFAULTS
    log.info(f"No cache config found at {CONFIG_PATH}, using defaults")
    return DEFAULTS

CONFIG = load_config()

class MemeCacheService:
    def __init__(self, reddit, config=None):
        config = config or {}

        self.max_ram_posts = config.get("max_ram_posts", 100)
        self.refresh_minutes = config.get("refresh_minutes", 15)
        self.disk_file = config.get("disk_file", "cache/meme_cache.db")

        self.reddit = reddit
        self.cache_mgr = RedditCacheManager(
            ram_ttl=config.get("ram_cache_ttl", 900),
            disk_ttl=config.get("disk_cache_ttl", 3600),
            keyword_failures=config.get("keyword_disable_after", 1),
            keyword_ttl=config.get("keyword_disable_ttl", 900),
        )
        self._fetch_semaphore = asyncio.Semaphore(2)
        self._fallback_subs = SUB_DEFAULTS  # {"sfw": [...], "nsfw": [...]} 
        self._started = False

    async def init(self):
        if self._started:
            return
        await self.cache_mgr.init()
        self.cache_refresh_loop.start()
        self.disk_flush_loop.start()
        self._started = True
        log.info("MemeCacheService initialized")

    async def close(self):
        if not self._started:
            return
        self.cache_refresh_loop.cancel()
        self.disk_flush_loop.cancel()
        await self.cache_mgr.close()
        self._started = False
        log.info("MemeCacheService closed")

    async def get_cache_info(self) -> str:
        ram_sfw_kw = [k for k, nsfw in self.cache_mgr.ram_cache.keys() if not nsfw]
        ram_nsfw_kw = [k for k, nsfw in self.cache_mgr.ram_cache.keys() if nsfw]
        ram_sfw_posts = sum(
            len(v["posts"]) for (k, nsfw), v in self.cache_mgr.ram_cache.items() if not nsfw
        )
        ram_nsfw_posts = sum(
            len(v["posts"]) for (k, nsfw), v in self.cache_mgr.ram_cache.items() if nsfw
        )
        async with self.cache_mgr.conn.execute(
            "SELECT is_nsfw, COUNT(*) FROM meme_cache GROUP BY is_nsfw"
        ) as cur:
            rows = await cur.fetchall()
        disk_counts = {row[0]: row[1] for row in rows}
        disk_sfw = disk_counts.get(0, 0)
        disk_nsfw = disk_counts.get(1, 0)
        disabled = len(self.cache_mgr.disabled_keywords)

        # Recent Keywords (Sort by timestamp desc)
        recent_items = sorted(
            self.cache_mgr.ram_cache.items(), 
            key=lambda x: x[1]["timestamp"], 
            reverse=True
        )[:10]
        recent_kws = [f"{k} ({'NSFW' if nsfw else 'SFW'})" for (k, nsfw), v in recent_items]
        recent_str = ", ".join(recent_kws) if recent_kws else "None"

        return (
            f"🧠 RAM cache: SFW {len(ram_sfw_kw)} keywords, {ram_sfw_posts} posts | "
            f"NSFW {len(ram_nsfw_kw)} keywords, {ram_nsfw_posts} posts\n"
            f"💾 Disk cache: SFW {disk_sfw} posts | NSFW {disk_nsfw} posts\n"
            f"⛔ Disabled keywords: {disabled}\n\n"
            f"🕒 Recent Keywords: {recent_str}"
        )

    async def _fetch_keyword_posts(self, keyword, nsfw):
        subs = self._fallback_subs["nsfw" if nsfw else "sfw"]

        async def fetch_sub(sub_name):
            async with self._fetch_semaphore:
                try:
                    sub = await self.reddit.subreddit(sub_name)
                    sub_results = []
                    async for post in sub.hot(limit=25):
                        if (
                            keyword.lower() in (post.title or "").lower()
                            and bool(post.over_18) == nsfw
                        ):
                            sub_results.append(await extract_post_data(post))
                    return sub_results
                except Exception as e:
                    log.error(f"Error fetching {sub_name} for keyword {keyword}: {e}")
                    return []

        results = await asyncio.gather(*(fetch_sub(name) for name in subs))
        return [item for sublist in results for item in sublist]

    @tasks.loop(seconds=600)
    async def cache_refresh_loop(self):
        keywords = self.cache_mgr.get_all_cached_keywords()
        if not keywords:
            return
        await self.cache_mgr.refresh_keywords(keywords, self._fetch_keyword_posts)

    @tasks.loop(seconds=3600)
    async def disk_flush_loop(self):
        await self.cache_mgr.flush_expired_disk(ttl_seconds=CONFIG["disk_cache_ttl"])
        log.info("[Disk Flush] Expired disk entries cleaned up.")
