"""Asynchronous meme statistics storage.

This module provides helpers for tracking meme usage, user leaderboards, and
reaction counts.  All database operations use a shared ``aiosqlite``
connection so callers can await the functions without blocking the event
loop.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

import aiosqlite

# Path to the SQLite database.  By default we store it under the writable
# ``data`` directory.  This can be overridden via the ``MEME_STATS_DB``
# environment variable.
DB_PATH = os.getenv("MEME_STATS_DB", os.path.join("data", "meme_stats.db"))

# Module level connection reused by all helpers
_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()


async def init() -> None:
    """Initialise the shared database connection and ensure tables exist."""
    global _conn

    async with _lock:
        if _conn is not None:
            return

        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        _conn = await aiosqlite.connect(DB_PATH)
        await _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stats (
                key   TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_counts (
                user_id TEXT PRIMARY KEY,
                count   INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS keyword_counts (
                keyword TEXT PRIMARY KEY,
                count   INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS subreddit_counts (
                subreddit TEXT PRIMARY KEY,
                count     INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS meme_msgs (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT,
                guild_id   TEXT,
                url        TEXT,
                title      TEXT
            );
            CREATE TABLE IF NOT EXISTS meme_reactions (
                message_id TEXT,
                emoji      TEXT,
                count      INTEGER DEFAULT 0,
                PRIMARY KEY (message_id, emoji)
            );
            """
        )
        await _conn.commit()


async def close() -> None:
    """Close the shared database connection."""
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


def _require_conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized; call meme_stats.init() first")
    return _conn


# --- Stats helpers -------------------------------------------------------

async def get_stat(key: str) -> int:
    conn = _require_conn()
    async with conn.execute("SELECT value FROM stats WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def set_stat(key: str, value: int) -> None:
    conn = _require_conn()
    await conn.execute(
        "INSERT OR REPLACE INTO stats (key, value) VALUES (?, ?)", (key, value)
    )
    await conn.commit()


async def inc_stat(key: str, by: int = 1) -> None:
    conn = _require_conn()
    await conn.execute(
        "INSERT INTO stats (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
        (key, by),
    )
    await conn.commit()


async def get_all_stats() -> Dict[str, int]:
    conn = _require_conn()
    stats: Dict[str, int] = {}
    async with conn.execute("SELECT key, value FROM stats") as cur:
        async for k, v in cur:
            stats[k] = v
    return stats


# --- Update stats (main entry point for bot) -----------------------------

async def update_stats(user_id: int, keyword: str, subreddit: Any, nsfw: bool = False) -> None:
    """Record usage statistics for a meme command.

    ``subreddit`` may be provided as either a string or a PRAW ``Subreddit``
    object.  We normalise it to the subreddit display name so the database
    always stores plain strings, avoiding ``sqlite3.ProgrammingError`` when a
    non-string object is passed in.
    """

    await inc_stat("total_memes", 1)
    if nsfw:
        await inc_stat("nsfw_memes", 1)

    keyword = (keyword or "").lower()
    subreddit = getattr(subreddit, "display_name", subreddit)
    subreddit = str(subreddit or "")

    conn = _require_conn()
    await conn.execute(
        "INSERT INTO keyword_counts (keyword, count) VALUES (?, 1) "
        "ON CONFLICT(keyword) DO UPDATE SET count = count + 1",
        (keyword,),
    )
    await conn.execute(
        "INSERT INTO user_counts (user_id, count) VALUES (?, 1) "
        "ON CONFLICT(user_id) DO UPDATE SET count = count + 1",
        (str(user_id),),
    )
    await conn.execute(
        "INSERT INTO subreddit_counts (subreddit, count) VALUES (?, 1) "
        "ON CONFLICT(subreddit) DO UPDATE SET count = count + 1",
        (subreddit,),
    )
    await conn.commit()


# --- User, keyword, and subreddit leaderboards ---------------------------

async def get_top_users(limit: int = 5) -> List[Tuple[str, int]]:
    conn = _require_conn()
    async with conn.execute(
        "SELECT user_id, count FROM user_counts ORDER BY count DESC LIMIT ?",
        (limit,),
    ) as cur:
        return await cur.fetchall()


async def get_top_keywords(limit: int = 5) -> List[Tuple[str, int]]:
    conn = _require_conn()
    async with conn.execute(
        "SELECT keyword, count FROM keyword_counts ORDER BY count DESC LIMIT ?",
        (limit,),
    ) as cur:
        return await cur.fetchall()


async def get_top_subreddits(limit: int = 5) -> List[Tuple[str, int]]:
    conn = _require_conn()
    async with conn.execute(
        "SELECT subreddit, count FROM subreddit_counts ORDER BY count DESC LIMIT ?",
        (limit,),
    ) as cur:
        return await cur.fetchall()


# --- Meme message and reaction tracking ----------------------------------

async def get_meme_msgs() -> List[aiosqlite.Row]:
    conn = _require_conn()
    async with conn.execute("SELECT * FROM meme_msgs") as cur:
        return await cur.fetchall()


async def register_meme_message(
    message_id: int,
    channel_id: int,
    guild_id: int,
    url: str,
    title: str,
) -> None:
    conn = _require_conn()
    await conn.execute(
        """
        INSERT OR REPLACE INTO meme_msgs (message_id, channel_id, guild_id, url, title)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(message_id), str(channel_id), str(guild_id), url, title),
    )
    await conn.commit()


async def track_reaction(message_id: int, user_id: int, emoji: str) -> None:
    conn = _require_conn()
    await conn.execute(
        """
        INSERT INTO meme_reactions (message_id, emoji, count) VALUES (?, ?, 1)
        ON CONFLICT(message_id, emoji) DO UPDATE SET count = count + 1
        """,
        (str(message_id), emoji),
    )
    await conn.commit()


async def get_reactions_for_message(message_id: int) -> Dict[str, int]:
    conn = _require_conn()
    async with conn.execute(
        "SELECT emoji, count FROM meme_reactions WHERE message_id = ?",
        (str(message_id),),
    ) as cur:
        rows = await cur.fetchall()
    return dict(rows)


async def get_top_reacted_memes(limit: int = 5) -> List[Tuple[Any, ...]]:
    conn = _require_conn()
    async with conn.execute(
        """
        SELECT m.message_id, m.url, m.title, m.guild_id, m.channel_id,
               IFNULL(SUM(r.count), 0) as total_reactions
        FROM meme_msgs m
        LEFT JOIN meme_reactions r ON m.message_id = r.message_id
        GROUP BY m.message_id
        HAVING total_reactions > 0
        ORDER BY total_reactions DESC
        LIMIT ?
        """,
        (limit,),
    ) as cur:
        return await cur.fetchall()


# --- Export for dashboard etc. -----------------------------------------

async def get_dashboard_stats() -> Dict[str, Any]:
    stats = await get_all_stats()
    users = dict(await get_top_users(100))
    subs = dict(await get_top_subreddits(100))
    kws = dict(await get_top_keywords(100))
    return {
        "total_memes": stats.get("total_memes", 0),
        "nsfw_memes": stats.get("nsfw_memes", 0),
        "user_counts": users,
        "subreddit_counts": subs,
        "keyword_counts": kws,
    }

