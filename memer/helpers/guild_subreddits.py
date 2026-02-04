"""
V3.7.1: Guild Subreddits - Database Backend
Async wrapper functions for database-backed subreddit management.
Replaces JSON file storage with database.
"""

from memer.helpers import db

# Default subreddits - exported for backwards compatibility with meme.py and meme_cache_service.py
DEFAULTS = {
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

# Async pass-through functions to database
async def get_guild_subreddits(guild_id, category):
    """Get subreddit list for a guild."""
    return await db.get_guild_subreddits_db(int(guild_id), category)

async def add_guild_subreddit(guild_id, name, category):
    """Add a subreddit to guild's list."""
    return await db.add_guild_subreddit_db(int(guild_id), name, category)

async def remove_guild_subreddit(guild_id, name, category):
    """Remove a subreddit from guild's list."""
    return await db.remove_guild_subreddit_db(int(guild_id), name, category)

async def list_guild_subreddits(guild_id, category):
    """Alias for get_guild_subreddits."""
    return await get_guild_subreddits(guild_id, category)

def refresh_cache():
    """No-op for backwards compatibility (database is always fresh)."""
    pass

def persist_cache():
    """No-op for backwards compatibility (database auto-commits)."""
    pass
