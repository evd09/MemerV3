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
            CREATE TABLE IF NOT EXISTS user_counts_guild (
                guild_id TEXT,
                user_id  TEXT,
                count    INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS keyword_counts_guild (
                guild_id TEXT,
                keyword  TEXT,
                count    INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, keyword)
            );
            CREATE TABLE IF NOT EXISTS meme_msgs (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT,
                guild_id   TEXT,
                url        TEXT,
                title      TEXT,
                nsfw       INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS meme_reactions (
                message_id TEXT,
                emoji      TEXT,
                count      INTEGER DEFAULT 0,
                PRIMARY KEY (message_id, emoji)
            );
            """
        )
        
        # Migration: Add media_url to meme_msgs if not exists
        try:
            await _conn.execute("ALTER TABLE meme_msgs ADD COLUMN media_url TEXT")
        except aiosqlite.OperationalError:
            pass

        # Migration: Add nsfw column if missing (for existing DBs)
        try:
            await _conn.execute("ALTER TABLE meme_msgs ADD COLUMN nsfw INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass # Column likely already exists

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

async def update_stats(user_id: int, keyword: str, subreddit: Any, nsfw: bool = False, guild_id: int = None) -> None:
    """Record usage statistics for a meme command."""

    await inc_stat("total_memes", 1)
    if nsfw:
        await inc_stat("nsfw_memes", 1)

    keyword = (keyword or "").lower()
    subreddit = getattr(subreddit, "display_name", subreddit)
    subreddit = str(subreddit or "")

    conn = _require_conn()
    
    # Global Counts
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

    # Guild Specific Counts (if guild_id provided)
    if guild_id:
        gid = str(guild_id)
        await conn.execute(
            "INSERT INTO keyword_counts_guild (guild_id, keyword, count) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id, keyword) DO UPDATE SET count = count + 1",
            (gid, keyword),
        )
        await conn.execute(
            "INSERT INTO user_counts_guild (guild_id, user_id, count) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1",
            (gid, str(user_id)),
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
    nsfw: bool = False,
    media_url: str = None,
) -> None:
    conn = _require_conn()
    await conn.execute(
        """
        INSERT OR REPLACE INTO meme_msgs (message_id, channel_id, guild_id, url, title, nsfw, media_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (str(message_id), str(channel_id), str(guild_id), url, title, 1 if nsfw else 0, media_url),
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


async def get_top_reacted_memes(limit: int = 5, guild_id: str = None, nsfw_filter: bool = None) -> List[Tuple[Any, ...]]:
    conn = _require_conn()
    
    wheres = []
    params = []
    
    if guild_id:
        wheres.append("m.guild_id = ?")
        params.append(guild_id)
        
    if nsfw_filter is not None:
        wheres.append("m.nsfw = ?")
        params.append(1 if nsfw_filter else 0)
        
    where_clause = "WHERE " + " AND ".join(wheres) if wheres else ""
    params.append(limit)
    
    sql = f"""
        SELECT m.message_id, 
               COALESCE(m.media_url, m.url) as url, 
               m.title, m.guild_id, m.channel_id, m.nsfw,
               IFNULL(SUM(r.count), 0) as total_reactions
        FROM meme_msgs m
        LEFT JOIN meme_reactions r ON m.message_id = r.message_id
        {where_clause}
        GROUP BY m.message_id
        HAVING total_reactions > 0
        ORDER BY total_reactions DESC
        LIMIT ?
    """
    async with conn.execute(sql, tuple(params)) as cur:
        return await cur.fetchall()


async def get_all_meme_msgs() -> List[Tuple[Any, ...]]:
    conn = _require_conn()
    async with conn.execute("SELECT message_id, channel_id, guild_id, nsfw, url, media_url FROM meme_msgs") as cur:
        return await cur.fetchall()


async def update_nsfw_flag(message_id: str, nsfw: bool) -> None:
    conn = _require_conn()
    await conn.execute(
        "UPDATE meme_msgs SET nsfw = ? WHERE message_id = ?",
        (1 if nsfw else 0, message_id)
    )
    await conn.commit()


async def update_media_url(message_id: str, media_url: str) -> None:
    conn = _require_conn()
    await conn.execute(
        "UPDATE meme_msgs SET media_url = ? WHERE message_id = ?",
        (media_url, message_id)
    )
    await conn.commit()
    await conn.commit()


# --- Export for dashboard etc. -----------------------------------------

# --- Export for dashboard etc. -----------------------------------------
# Helpers for guild stats
async def get_top_users_guild(guild_id: str, limit: int = 5) -> List[Tuple[str, int]]:
    conn = _require_conn()
    async with conn.execute(
        "SELECT user_id, count FROM user_counts_guild WHERE guild_id = ? ORDER BY count DESC LIMIT ?",
        (guild_id, limit),
    ) as cur:
        return await cur.fetchall()

async def get_top_keywords_guild(guild_id: str, limit: int = 5) -> List[Tuple[str, int]]:
    conn = _require_conn()
    async with conn.execute(
        "SELECT keyword, count FROM keyword_counts_guild WHERE guild_id = ? ORDER BY count DESC LIMIT ?",
        (guild_id, limit),
    ) as cur:
        return await cur.fetchall()

async def get_dashboard_stats(guild_id: str = None) -> Dict[str, Any]:
    stats = await get_all_stats()
    
    if guild_id:
        users = dict(await get_top_users_guild(guild_id, 100))
        kws = dict(await get_top_keywords_guild(guild_id, 100))
        # Note: subreddit counts are global only for now in this schema, or could add table later
        subs = {} 
    else:
        users = dict(await get_top_users(100))
        subs = dict(await get_top_subreddits(100))
        kws = dict(await get_top_keywords(100))
        
    top_reactions = await get_top_reacted_memes(5, guild_id)

    return {
        "total_memes": stats.get("total_memes", 0),
        "nsfw_memes": stats.get("nsfw_memes", 0),
        "user_counts": users,
        "subreddit_counts": subs,
        "keyword_counts": kws,
        "top_reactions": top_reactions,
    }

