import os
import asyncio
import time
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import aiosqlite
import logging

log = logging.getLogger(__name__)

DB_PATH = os.getenv("MEME_CACHE_DB", "data/meme_cache.db")


class RedditCacheManager:
    def __init__(self, ram_ttl=900, disk_ttl=3600, keyword_failures=1, keyword_ttl=900):
        self.ram_ttl = ram_ttl
        self.disk_ttl = disk_ttl
        self.keyword_failures = keyword_failures
        self.keyword_ttl = keyword_ttl

        self.ram_cache: Dict[Tuple[str, bool], Dict] = {}
        self.disabled_keywords: Dict[Tuple[str, bool], float] = {}
        self.failed_count: Dict[Tuple[str, bool], int] = defaultdict(int)
        self.lock = asyncio.Lock()
        self.conn: Optional[aiosqlite.Connection] = None

    async def init(self):
        self.conn = await aiosqlite.connect(DB_PATH)
        self.conn.row_factory = aiosqlite.Row
        await self._setup_db()

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def _setup_db(self):
        await self.conn.execute(
            '''
                CREATE TABLE IF NOT EXISTS meme_cache (
                    keyword TEXT NOT NULL,
                    subreddit TEXT NOT NULL,
                    post_id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    media_url TEXT,
                    author TEXT,
                    is_nsfw BOOLEAN,
                    created_utc INTEGER,
                    cached_at INTEGER
                )
            '''
        )
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword ON meme_cache(keyword)")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_at ON meme_cache(cached_at)")
        await self.conn.commit()

    def is_disabled(self, keyword: str, nsfw: bool = False) -> bool:
        key = (keyword, nsfw)
        ts = self.disabled_keywords.get(key)
        if ts and (time.time() - ts < self.keyword_ttl):
            return True
        self.disabled_keywords.pop(key, None)
        return False

    def disable_keyword(self, keyword: str, nsfw: bool = False):
        self.disabled_keywords[(keyword, nsfw)] = time.time()

    def cache_to_ram(self, keyword: str, posts: List[dict], nsfw: bool = False):
        self.ram_cache[(keyword, nsfw)] = {
            "posts": posts,
            "timestamp": time.time()
        }

    def get_from_ram(self, keyword: str, nsfw: bool = False) -> Optional[List[dict]]:
        entry = self.ram_cache.get((keyword, nsfw))
        if entry:
            age = time.time() - entry["timestamp"]
            if age <= self.ram_ttl:
                log.debug(f"[cache:RAM] HIT for {keyword!r} (age={age:.0f}s)")
                return entry["posts"]
            else:
                log.debug(f"[cache:RAM] EXPIRED for {keyword!r} (age={age:.0f}s)")
                del self.ram_cache[(keyword, nsfw)]
        else:
            log.debug(f"[cache:RAM] MISS for {keyword!r}")
        return None

    async def get_from_disk(self, keyword: str, nsfw: bool = False) -> Optional[List[dict]]:
        async with self.conn.execute(
            "SELECT * FROM meme_cache WHERE keyword = ? AND is_nsfw = ?",
            (keyword, int(nsfw)),
        ) as cursor:
            rows = await cursor.fetchall()
        if rows:
            log.debug(f"[cache:DISK] HIT for {keyword!r} ({len(rows)} rows)")
            posts = [dict(row) for row in rows]
            # refill RAM after a disk‐hit
            self.cache_to_ram(keyword, posts, nsfw=nsfw)
            return posts
        else:
            log.debug(f"[cache:DISK] MISS for {keyword!r}")
        return None

    async def save_to_disk(self, keyword: str, posts: List[dict], nsfw: bool = False):
        now = int(time.time())

        rows = []
        for post in posts:
            rows.append((
                keyword,
                post.get("subreddit"),
                post.get("post_id"),
                post.get("title"),
                post.get("url"),
                post.get("media_url"),
                post.get("author"),
                int(post.get("is_nsfw", nsfw)),
                int(post.get("created_utc", now)),
                now
            ))

        cur = await self.conn.cursor()
        try:
            await cur.executemany(
                '''
                INSERT OR REPLACE INTO meme_cache
                (keyword, subreddit, post_id, title, url, media_url, author, is_nsfw, created_utc, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                rows,
            )
            await self.conn.commit()
        except Exception as e:
            log.warning("Bulk insert failed: %s; retrying individually", e)
            await self.conn.rollback()
            for row in rows:
                try:
                    await cur.execute(
                        '''
                        INSERT OR REPLACE INTO meme_cache
                        (keyword, subreddit, post_id, title, url, media_url, author, is_nsfw, created_utc, cached_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        row,
                    )
                except Exception as ex:
                    log.error("Failed to cache post %s: %s", row[2], ex)
            await self.conn.commit()

    def record_failure(self, keyword: str, nsfw: bool = False) -> bool:
        key = (keyword, nsfw)
        self.failed_count[key] += 1
        if self.failed_count[key] >= self.keyword_failures:
            self.disable_keyword(keyword, nsfw)
            return True
        return False

    def clear_disabled(self):
        self.disabled_keywords.clear()
        self.failed_count.clear()

    async def flush_expired_disk(self, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds or self.disk_ttl
        log.debug("[Cache] Flushing expired disk entries older than %ds", ttl)
        now = int(time.time())
        cutoff = now - ttl

        cur = await self.conn.cursor()
        await cur.execute("DELETE FROM meme_cache WHERE cached_at < ?", (cutoff,))
        await self.conn.commit()  # ✅ commit delete transaction first

        # Now we can VACUUM
        try:
            await self.conn.execute("VACUUM")
        except aiosqlite.OperationalError as e:
            log.warning("VACUUM failed: %s", e)

    async def refresh_keywords(self, keyword_list: List[Tuple[str, bool]], fetch_fn):
        async with self.lock:
            sem = asyncio.Semaphore(5)

            async def refresh_one(keyword: str, nsfw: bool):
                async with sem:
                    new_posts = await fetch_fn(keyword, nsfw)
                    if new_posts:
                        self.cache_to_ram(keyword, new_posts, nsfw)
                        await self.save_to_disk(keyword, new_posts, nsfw)

            tasks = [
                asyncio.create_task(refresh_one(keyword, nsfw))
                for keyword, nsfw in keyword_list
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (keyword, nsfw), result in zip(keyword_list, results):
                if isinstance(result, Exception):
                    log.warning(
                        "[Refresh] Failed to refresh %s (%s): %s",
                        keyword,
                        "NSFW" if nsfw else "SFW",
                        result,
                    )

            self.clear_disabled()

    def get_all_cached_keywords(self) -> List[Tuple[str, bool]]:
        return list(self.ram_cache.keys())


class NoopCacheManager:
    """Minimal cache manager that effectively disables caching.

    Provides the same interface as :class:`RedditCacheManager` but all
    operations are no-ops.  Used when a subreddit is not part of the loaded
    list and we want to bypass cache lookups entirely.
    """

    async def init(self):  # pragma: no cover - interface compatibility
        return None

    def get_from_ram(self, *args, **kwargs):
        return None

    async def get_from_disk(self, *args, **kwargs):
        return None

    def is_disabled(self, *args, **kwargs):
        return False

    def cache_to_ram(self, *args, **kwargs):
        return None

    async def save_to_disk(self, *args, **kwargs):
        return None

    def record_failure(self, *args, **kwargs):
        return False

    def clear_disabled(self):
        return None

    async def flush_expired_disk(self, *args, **kwargs):  # pragma: no cover
        return None

    async def refresh_keywords(self, *args, **kwargs):  # pragma: no cover
        return None

    def get_all_cached_keywords(self):
        return []
