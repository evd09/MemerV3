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
    "get_recent_post_ids",
    "has_post_been_sent",
    "log_admin_action",
    "get_admin_activity_log",
    "log_entrance_play",
    "get_entrance_analytics",
]
import json

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
        
        # V3.5 Admin Tables
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS admin_activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                admin_user_id INTEGER NOT NULL,
                admin_username TEXT,
                action_type TEXT NOT NULL,
                target_user_id INTEGER,
                target_username TEXT,
                details TEXT,
                timestamp INTEGER NOT NULL
              )
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_admin_log_guild_time 
              ON admin_activity_log(guild_id, timestamp)
            """
        )
        
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS entrance_play_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                file TEXT NOT NULL,
                timestamp INTEGER NOT NULL
              )
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_entrance_log_guild_time
              ON entrance_play_log(guild_id, timestamp)
            """
        )
        


        # V3.6 Guild Sounds
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS sounds (
                id TEXT PRIMARY KEY,
                guild_id INTEGER,
                filename TEXT NOT NULL,
                display_name TEXT NOT NULL,
                added_by INTEGER,
                created_at INTEGER,
                play_count INTEGER DEFAULT 0
              )
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_sounds_guild
              ON sounds(guild_id)
            """
        )

        # V3.7.1: Add tags column to sounds table (for metadata migration)
        try:
            await _conn.execute("ALTER TABLE sounds ADD COLUMN tags TEXT")
        except Exception:
            pass  # Column already exists

        # V3.7.5: Add shortcut column to sounds table (for keyboard shortcuts)
        try:
            await _conn.execute("ALTER TABLE sounds ADD COLUMN shortcut TEXT")
        except Exception:
            pass  # Column already exists

        # V3.7.1: Guild Subreddits Table (replaces guild_subreddits.json)
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS guild_subreddits (
                guild_id INTEGER NOT NULL,
                subreddit TEXT NOT NULL,
                category TEXT NOT NULL,
                PRIMARY KEY (guild_id, subreddit, category)
              )
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_guild_subs_guild
              ON guild_subreddits(guild_id)
            """
        )

        # V3.7: Per-Guild Entrance Sounds (Recreate for Schema Change)
        # Drop old table if exists (User accepted wiping logic)
        await _conn.execute("DROP TABLE IF EXISTS user_entrance_v2_old_backup")
        
        # Check if table exists and has old schema (check column)
        try:
             async with _conn.execute("SELECT filename FROM user_entrance_v2 LIMIT 1") as cursor:
                 # If this succeeds, it's the old schema. Drop it.
                 await _conn.execute("DROP TABLE user_entrance_v2")
        except Exception:
             pass # Column doesn't exist or table doesn't exist, safe to proceed
             
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS user_entrance_v2 (
                user_id INTEGER,
                guild_id INTEGER,
                type TEXT DEFAULT 'single',
                data TEXT,
                created_at INTEGER,
                PRIMARY KEY (user_id, guild_id)
              )
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_entrance_user
              ON user_entrance_v2(user_id)
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_entrance_guild
              ON user_entrance_v2(guild_id)
            """
        )

        # V3.7.5: User Favorites Table (replaces user_settings.json)
        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS user_favorites (
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                created_at INTEGER,
                PRIMARY KEY (user_id, filename)
              )
            """
        )
        await _conn.execute(
            """
              CREATE INDEX IF NOT EXISTS idx_favorites_user
              ON user_favorites(user_id)
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

    
# ... (rest of file) ...


# ============================================================================
# V3.7: Per-Guild Entrance Sounds (Advanced)
# ============================================================================

async def set_entrance_config(user_id: int, guild_id: int, entrance_type: str, data: dict):
    """Set entrance configuration (generic)."""
    if _conn is None: return
    json_data = json.dumps(data)
    print(f"[DB DEBUG] set_entrance_config: user={user_id}, guild={guild_id}, type={entrance_type}")
    print(f"[DB DEBUG] data={data}, json_data={json_data}")
    await _conn.execute(
        """
        INSERT OR REPLACE INTO user_entrance_v2 (user_id, guild_id, type, data, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, guild_id, entrance_type, json_data, int(time.time()))
    )
    await _conn.commit()
    print(f"[DB DEBUG] Committed to database")

# Deprecated - for backward compat with old code calls if any remain
async def set_entrance_sound(user_id: int, guild_id: int, filename: str, volume: float = 1.0):
    await set_entrance_config(user_id, guild_id, 'single', {'file': filename, 'volume': volume})

async def get_entrance_sound(user_id: int, guild_id: int):
    """Get entrance sound configuration."""
    if _conn is None: return None
    print(f"[DB DEBUG] get_entrance_sound: user={user_id}, guild={guild_id}")
    async with _conn.execute(
        "SELECT * FROM user_entrance_v2 WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id)
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            print(f"[DB DEBUG] No row found in database")
            return None

        # Parse JSON data
        d = dict(row)
        print(f"[DB DEBUG] Raw row from database: {d}")
        try:
            d['data'] = json.loads(d['data'])
            print(f"[DB DEBUG] Parsed JSON data: {d['data']}")
            # Double check for double-encoding (some rows might be double dumped)
            if isinstance(d['data'], str):
                 try:
                     d['data'] = json.loads(d['data'])
                     print(f"[DB DEBUG] Double-parsed JSON data: {d['data']}")
                 except: pass
        except Exception as e:
            print(f"[DB DEBUG] Error parsing JSON: {e}")
            d['data'] = {}
        print(f"[DB DEBUG] Returning: {d}")
        return d

async def delete_entrance_sound(user_id: int, guild_id: int):
    """Delete entrance sound for a specific user in a specific guild."""
    if _conn is None: return
    await _conn.execute(
        "DELETE FROM user_entrance_v2 WHERE user_id = ? AND guild_id = ?",
        (user_id, guild_id)
    )
    await _conn.commit()

async def get_all_entrance_sounds_for_user(user_id: int):
    """Get all entrance sounds for a user across all guilds."""
    if _conn is None: return []
    async with _conn.execute(
        "SELECT * FROM user_entrance_v2 WHERE user_id = ? ORDER BY guild_id",
        (user_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try: 
                d['data'] = json.loads(d['data'])
                if isinstance(d['data'], str):
                     try: d['data'] = json.loads(d['data'])
                     except: pass
            except: d['data'] = {}
            results.append(d)
        return results

async def get_all_entrance_sounds_for_guild(guild_id: int):
    """Get all entrance sounds configured for a specific guild."""
    if _conn is None: return {}
    async with _conn.execute(
        "SELECT * FROM user_entrance_v2 WHERE guild_id = ?",
        (guild_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        # Return as dict for easy O(1) lookup: {user_id: {data}}
        final_map = {}
        for r in rows:
            d = dict(r)
            try: d['data'] = json.loads(d['data'])
            except: d['data'] = {}
            
            # Legacy compatibility for admin view: map 'data' keys to root if single?
            # Or assume admin view will update.
            # For backward compat with my recent webbox edit:
            if d['type'] == 'single':
                d['filename'] = d['data'].get('file')
                d['volume'] = d['data'].get('volume', 1.0)
            
            final_map[d['user_id']] = d
        return final_map


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


async def log_admin_action(
    guild_id: int, 
    admin_user_id: int, 
    admin_username: str, 
    action_type: str, 
    details: dict,
    target_user_id: Optional[int] = None,
    target_username: Optional[str] = None
):
    """Log an admin action to the database."""
    if _conn is None:
        return

    await _conn.execute(
        """
        INSERT INTO admin_activity_log 
        (guild_id, admin_user_id, admin_username, action_type, target_user_id, target_username, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guild_id, 
            admin_user_id, 
            admin_username, 
            action_type, 
            target_user_id, 
            target_username, 
            json.dumps(details), 
            int(time.time())
        )
    )
    await _conn.commit()


async def get_admin_activity_log(
    guild_id: int, 
    limit: int = 50, 
    offset: int = 0, 
    action_type: Optional[str] = None
):
    """Get activity logs for a guild with optional filtering."""
    if _conn is None:
        return {"logs": [], "total": 0}

    query = "SELECT * FROM admin_activity_log WHERE guild_id = ?"
    params = [guild_id]

    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with _conn.execute(query, tuple(params)) as cursor:
        rows = await cursor.fetchall()

    # Get total count for pagination
    count_query = "SELECT COUNT(*) as count FROM admin_activity_log WHERE guild_id = ?"
    count_params = [guild_id]
    if action_type:
        count_query += " AND action_type = ?"
        count_params.append(action_type)
        
    async with _conn.execute(count_query, tuple(count_params)) as cursor:
        count_row = await cursor.fetchone()
        total = count_row["count"] if count_row else 0

    return {
        "logs": [dict(r) for r in rows],
        "total": total,
        "has_more": (offset + limit) < total
    }


async def log_entrance_play(guild_id: int, user_id: int, file: str):
    """Log an entrance sound play for analytics."""
    if _conn is None:
        return

    await _conn.execute(
        """
        INSERT INTO entrance_play_log (guild_id, user_id, file, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (guild_id, user_id, file, int(time.time()))
    )
    await _conn.commit()


async def get_entrance_analytics(guild_id: int, days: int = 30):
    """Get analytics for entrance sounds."""
    if _conn is None:
        return None

    cutoff = int(time.time()) - (days * 86400)

    # Most popular sounds
    async with _conn.execute(
        """
        SELECT file, COUNT(*) as play_count, COUNT(DISTINCT user_id) as unique_users
        FROM entrance_play_log
        WHERE guild_id = ? AND timestamp > ?
        GROUP BY file
        ORDER BY play_count DESC
        LIMIT 100
        """,
        (guild_id, cutoff)
    ) as cursor:
        popular_rows = await cursor.fetchall()

    # Get basic stats
    async with _conn.execute(
        """
        SELECT COUNT(*) as total_plays
        FROM entrance_play_log
        WHERE guild_id = ? AND timestamp > ?
        """,
        (guild_id, cutoff)
    ) as cursor:
        stats_row = await cursor.fetchone()
        total_plays = stats_row["total_plays"] if stats_row else 0

    # V3.7: Get users with entrance sounds configured
    async with _conn.execute(
        """
        SELECT DISTINCT user_id FROM user_entrance_v2
        WHERE guild_id = ?
        """,
        (guild_id,)
    ) as cursor:
        users_with_entrance_rows = await cursor.fetchall()
        users_with_entrance = {row["user_id"] for row in users_with_entrance_rows}

    # V3.7: Get entrance type distribution
    async with _conn.execute(
        """
        SELECT type, COUNT(*) as count
        FROM user_entrance_v2
        WHERE guild_id = ?
        GROUP BY type
        """,
        (guild_id,)
    ) as cursor:
        type_rows = await cursor.fetchall()
        entrance_type_distribution = {row["type"]: row["count"] for row in type_rows}

    return {
        "most_popular_sounds": [dict(r) for r in popular_rows],
        "total_plays": total_plays,
        "users_with_entrance": users_with_entrance,
        "entrance_type_distribution": entrance_type_distribution
    }

# --- V3.6 Sound Helpers ---

async def get_sounds_for_guild(guild_id: int):
    """Get all Global sounds + Guild specific sounds for a guild."""
    if _conn is None: return []
    
    async with _conn.execute(
        """
        SELECT * FROM sounds 
        WHERE guild_id IS NULL OR guild_id = ?
        ORDER BY display_name ASC
        """,
        (guild_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_all_global_sounds():
    """Get only Global sounds (for legacy json sync)."""
    if _conn is None: return []
    
    async with _conn.execute(
        "SELECT * FROM sounds WHERE guild_id IS NULL ORDER BY display_name ASC"
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def add_sound(sound_id: str, guild_id: int | None, filename: str, display_name: str, added_by: int):
    if _conn is None: return
    await _conn.execute(
        """
        INSERT INTO sounds (id, guild_id, filename, display_name, added_by, created_at, play_count)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (sound_id, guild_id, filename, display_name, added_by, int(time.time()))
    )
    await _conn.commit()

async def update_sound(sound_id: str, display_name: str, tags: str = None, shortcut: str = None):
    """Update sound metadata. Tags should be comma-separated string, shortcut is single char."""
    if _conn is None: return
    await _conn.execute(
        "UPDATE sounds SET display_name = ?, tags = ?, shortcut = ? WHERE id = ?",
        (display_name, tags, shortcut, sound_id)
    )
    await _conn.commit()

async def delete_sound(sound_id: str):
    if _conn is None: return
    await _conn.execute("DELETE FROM sounds WHERE id = ?", (sound_id,))
    await _conn.commit()

async def get_sound_by_filename(filename: str):
    if _conn is None: return None
    async with _conn.execute("SELECT * FROM sounds WHERE filename = ?", (filename,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None

async def increment_sound_play_count(filename: str):
    """Increment play count for a sound by filename."""
    if _conn is None: return
    await _conn.execute(
        "UPDATE sounds SET play_count = play_count + 1 WHERE filename = ?",
        (filename,)
    )
    await _conn.commit()

async def get_sounds_for_user(guild_ids: list[int]):
    """Get Global sounds + sounds for specific guilds."""
    if _conn is None: return []
    
    if not guild_ids:
        return await get_all_global_sounds()
        
    placeholders = ",".join("?" for _ in guild_ids)
    query = f"""
        SELECT * FROM sounds 
        WHERE guild_id IS NULL OR guild_id IN ({placeholders})
        ORDER BY display_name ASC
    """
    
    async with _conn.execute(query, tuple(guild_ids)) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

# ============================================================================
# V3.6.2: Per-Guild Entrance Sounds (Removed Duplicates - see lines 264-355)
# ============================================================================

# ============================================================================
# V3.7.1: Guild Subreddits (Database Migration from JSON)
# ============================================================================

# Default subreddits (fallback if guild has no custom list)
DEFAULT_SUBREDDITS = {
    "sfw": [
        "memes", "dankmemes", "funny", "wholesomememes",
        "MemeEconomy", "me_irl", "comedyheaven", "AdviceAnimals",
        "memesopdidnotlike", "trashy", "terriblefacebookmemes", "okbuddyretard"
    ],
    "nsfw": [
        "nsfwmemes", "dirtymemes", "gonewild", "NSFW_GIF",
        "SexySexymemes", "lewdanime", "EcchiMemes", "sexmemes",
        "Rule34LoL", "funhornymemes", "spicymemes"
    ]
}

async def get_guild_subreddits_db(guild_id: int, category: str):
    """Get subreddit list for a guild from database."""
    if _conn is None:
        return DEFAULT_SUBREDDITS[category].copy()

    async with _conn.execute(
        "SELECT subreddit FROM guild_subreddits WHERE guild_id = ? AND category = ? ORDER BY subreddit",
        (guild_id, category)
    ) as cursor:
        rows = await cursor.fetchall()

    if rows:
        return [row["subreddit"] for row in rows]
    else:
        # Return defaults if no custom list
        return DEFAULT_SUBREDDITS[category].copy()

async def add_guild_subreddit_db(guild_id: int, subreddit: str, category: str):
    """Add a subreddit to guild's list."""
    if _conn is None:
        return False

    try:
        await _conn.execute(
            "INSERT OR IGNORE INTO guild_subreddits (guild_id, subreddit, category) VALUES (?, ?, ?)",
            (guild_id, subreddit, category)
        )
        await _conn.commit()
        return True
    except Exception as e:
        print(f"[DB ERROR] Failed to add subreddit: {e}")
        return False

async def remove_guild_subreddit_db(guild_id: int, subreddit: str, category: str):
    """Remove a subreddit from guild's list."""
    if _conn is None:
        return False

    try:
        await _conn.execute(
            "DELETE FROM guild_subreddits WHERE guild_id = ? AND subreddit = ? AND category = ?",
            (guild_id, subreddit, category)
        )
        await _conn.commit()
        return True
    except Exception as e:
        print(f"[DB ERROR] Failed to remove subreddit: {e}")
        return False

async def init_guild_subreddits_from_defaults(guild_id: int):
    """Initialize a guild's subreddit lists with defaults."""
    if _conn is None:
        return

    for category in ["sfw", "nsfw"]:
        for subreddit in DEFAULT_SUBREDDITS[category]:
            await add_guild_subreddit_db(guild_id, subreddit, category)


# V3.7.5: User Favorites (Database Migration from JSON)

async def get_user_favorites(user_id: int) -> list:
    """Get list of favorited sound filenames for a user."""
    if _conn is None:
        return []

    async with _conn.execute(
        "SELECT filename FROM user_favorites WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ) as cursor:
        rows = await cursor.fetchall()

    return [row["filename"] for row in rows]


async def add_user_favorite(user_id: int, filename: str) -> bool:
    """Add a sound to user's favorites."""
    if _conn is None:
        return False

    try:
        await _conn.execute(
            "INSERT OR IGNORE INTO user_favorites (user_id, filename, created_at) VALUES (?, ?, ?)",
            (user_id, filename, int(time.time()))
        )
        await _conn.commit()
        return True
    except Exception as e:
        print(f"[DB ERROR] Failed to add favorite: {e}")
        return False


async def remove_user_favorite(user_id: int, filename: str) -> bool:
    """Remove a sound from user's favorites."""
    if _conn is None:
        return False

    try:
        await _conn.execute(
            "DELETE FROM user_favorites WHERE user_id = ? AND filename = ?",
            (user_id, filename)
        )
        await _conn.commit()
        return True
    except Exception as e:
        print(f"[DB ERROR] Failed to remove favorite: {e}")
        return False


async def toggle_user_favorite(user_id: int, filename: str) -> str:
    """Toggle a sound in user's favorites. Returns 'added' or 'removed'."""
    if _conn is None:
        return "error"

    # Check if already favorited
    async with _conn.execute(
        "SELECT 1 FROM user_favorites WHERE user_id = ? AND filename = ?",
        (user_id, filename)
    ) as cursor:
        exists = await cursor.fetchone()

    if exists:
        await remove_user_favorite(user_id, filename)
        return "removed"
    else:
        await add_user_favorite(user_id, filename)
        return "added"
