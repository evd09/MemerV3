# File: helpers/db.py
import os
import time
import asyncio
import contextlib
from typing import List, Optional

__all__ = [
    "init",
    "close",
    "register_meme_message",
    "get_recent_post_ids",
    "has_post_been_sent",
]

import aiosqlite

# Path to the SQLite database. Can be overridden via env var.
DB_PATH = os.getenv("MEME_CACHE_DB", "data/meme_cache.db")

# Module level connection reused by all helpers
_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()
_queue: Optional[asyncio.Queue] = None
_flusher_task: Optional[asyncio.Task] = None

_FLUSH_INTERVAL = 5  # seconds


async def init() -> None:
    """Initialize the shared aiosqlite connection and ensure tables exist."""
    global _conn, _queue, _flusher_task

    async with _lock:
        if _conn is not None:
            return

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = await aiosqlite.connect(DB_PATH)
        _conn.row_factory = aiosqlite.Row

        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS meme_messages (
                message_id   TEXT PRIMARY KEY,
                channel_id   INTEGER,
                guild_id     INTEGER,
                url          TEXT,
                title        TEXT,
                post_id      TEXT,
                timestamp    INTEGER
              )
            """
        )
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS social_settings (
                guild_id         INTEGER PRIMARY KEY,
                enabled          INTEGER DEFAULT 0,
                allowed_channels TEXT
              )
            """
        )
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS social_cache (
                original_url TEXT PRIMARY KEY,
                discord_url  TEXT,
                timestamp    INTEGER
              )
            """
        )
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS voice_settings (
                guild_id         INTEGER PRIMARY KEY,
                say_public       INTEGER DEFAULT 1
              )
            """
        )
        await _conn.execute(
            """
              DELETE FROM meme_messages
              WHERE post_id IS NOT NULL
                AND rowid NOT IN (
                  SELECT MIN(rowid)
                  FROM meme_messages
                  WHERE post_id IS NOT NULL
                  GROUP BY channel_id, post_id
                )
            """
        )
        await _conn.execute(
            """
              CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_post
              ON meme_messages(channel_id, post_id)
            """
        )
        await _conn.commit()

        _queue = asyncio.Queue()
        _flusher_task = asyncio.create_task(_flusher())


async def close() -> None:
    """Flush pending records and close the shared aiosqlite connection."""
    global _conn, _flusher_task, _queue

    if _flusher_task is not None:
        _flusher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _flusher_task
        _flusher_task = None

    if _queue is not None:
        await _flush_once()
        _queue = None

    if _conn is not None:
        await _conn.close()
        _conn = None


def register_meme_message(
    message_id: str,
    channel_id: int,
    guild_id: int,
    url: str,
    title: str,
    post_id: Optional[str] = None,
) -> None:
    """Queue a meme message record for later insertion."""
    if _conn is None or _queue is None:
        raise RuntimeError("Database not initialized")

    _queue.put_nowait(
        (
            message_id,
            channel_id,
            guild_id,
            url,
            title,
            post_id,
            int(time.time()),
        )
    )


async def get_recent_post_ids(channel_id: int, limit: Optional[int] = None) -> List[str]:
    """Return recent post IDs for the given channel."""
    if _conn is None:
        raise RuntimeError("Database not initialized")

    query = (
        """
          SELECT post_id
          FROM meme_messages
          WHERE channel_id = ?
          ORDER BY timestamp DESC
        """
    )
    params: tuple = (channel_id,)
    if limit is not None:
        query += " LIMIT ?"
        params = (channel_id, limit)

    async with _conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()

    return [r["post_id"] for r in rows if r["post_id"]]


async def has_post_been_sent(channel_id: int, post_id: str) -> bool:
    """Return True if a post with ``post_id`` was sent in ``channel_id``."""
    if _conn is None:
        return False

    async with _conn.execute(
        """
          SELECT 1
          FROM meme_messages
          WHERE channel_id = ? AND post_id = ?
          LIMIT 1
        """,
        (channel_id, post_id),
    ) as cursor:
        row = await cursor.fetchone()

    return row is not None


async def get_social_settings(guild_id: int):
    """Return (enabled, left_allowed_channels_set)."""
    if _conn is None:
        return False, set()
    
    async with _conn.execute(
        "SELECT enabled, allowed_channels FROM social_settings WHERE guild_id = ?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return False, set()
    
    enabled = bool(row["enabled"])
    raw_channels = row["allowed_channels"] or ""
    try:
        if raw_channels:
            allowed = set(map(int, raw_channels.split(",")))
        else:
            allowed = set()
    except ValueError:
        allowed = set()
        
    return enabled, allowed


async def set_social_settings(guild_id: int, enabled: bool, allowed_channels: list[int]):
    """Update social settings for a guild."""
    if _conn is None:
        return
        
    chan_str = ",".join(map(str, allowed_channels))
    await _conn.execute(
        """
        INSERT INTO social_settings (guild_id, enabled, allowed_channels)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            enabled=excluded.enabled,
            allowed_channels=excluded.allowed_channels
        """,
        (guild_id, int(enabled), chan_str)
    )
    await _conn.commit()


async def get_voice_settings(guild_id: int) -> bool:
    """Return say_public boolean (default True)."""
    if _conn is None:
        return True
    
    async with _conn.execute(
        "SELECT say_public FROM voice_settings WHERE guild_id = ?",
        (guild_id,),
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return True
    
    return bool(row["say_public"])


async def set_voice_settings(guild_id: int, say_public: bool):
    """Update voice settings for a guild."""
    if _conn is None:
        return
        
    await _conn.execute(
        """
        INSERT INTO voice_settings (guild_id, say_public)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            say_public=excluded.say_public
        """,
        (guild_id, int(say_public))
    )
    await _conn.commit()
    await _conn.commit()


async def get_cached_social(url: str) -> Optional[str]:
    """Return cached Discord URL if it exists and is < 48h old."""
    if _conn is None:
        return None
    
    # Prune old cache first (lazy prune)
    # 48 hours = 172800 seconds
    cutoff = int(time.time()) - 172800
    
    async with _conn.execute(
        "SELECT discord_url, timestamp FROM social_cache WHERE original_url = ?",
        (url,),
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return None
    
    if row["timestamp"] < cutoff:
        return None
        
    return row["discord_url"]


async def cache_social(original_url: str, discord_url: str):
    """Cache a processed social media link."""
    if _conn is None:
        return
        
    await _conn.execute(
        """
        INSERT OR REPLACE INTO social_cache (original_url, discord_url, timestamp)
        VALUES (?, ?, ?)
        """,
        (original_url, discord_url, int(time.time()))
    )
    await _conn.commit()

async def _flush_once() -> None:
    """Flush all queued records in a single transaction."""
    if _conn is None or _queue is None:
        return

    batch = []
    while True:
        try:
            batch.append(_queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    if not batch:
        return

    await _conn.execute("BEGIN")
    await _conn.executemany(
        """
          INSERT OR REPLACE INTO meme_messages
            (message_id, channel_id, guild_id, url, title, post_id, timestamp)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )
    await _conn.commit()

    for _ in batch:
        _queue.task_done()


async def _flusher() -> None:
    """Background task that periodically flushes the queue."""
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL)
        await _flush_once()


async def prune_old_records(days: int = 30) -> int:
    """Delete records older than `days`. Returns number of deleted rows."""
    if _conn is None:
        return 0
    
    cutoff = int(time.time()) - (days * 86400)
    async with _conn.execute(
        "DELETE FROM meme_messages WHERE timestamp < ?", (cutoff,)
    ) as cursor:
        await _conn.commit()
        return cursor.rowcount

