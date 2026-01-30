import os
import json

# Cache for guild subreddit data loaded from disk once at module import
_CACHE = None
_DIRTY = False

DATA_FILE = "data/guild_subreddits.json"
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


def _load_from_disk():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def _ensure_loaded():
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_from_disk()


def _save_to_disk():
    global _DIRTY
    if not _DIRTY:
        return
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(_CACHE, f, indent=2)
    _DIRTY = False


def get_guild_subreddits(guild_id, category):
    _ensure_loaded()
    gid = str(guild_id)
    if gid in _CACHE:
        return _CACHE[gid].get(category, DEFAULTS[category].copy())
    return DEFAULTS[category].copy()


def add_guild_subreddit(guild_id, name, category):
    global _DIRTY
    _ensure_loaded()
    gid = str(guild_id)
    if gid not in _CACHE:
        _CACHE[gid] = {
            "sfw": DEFAULTS["sfw"].copy(),
            "nsfw": DEFAULTS["nsfw"].copy(),
        }
    if name not in _CACHE[gid][category]:
        _CACHE[gid][category].append(name)
        _DIRTY = True


def remove_guild_subreddit(guild_id, name, category):
    global _DIRTY
    _ensure_loaded()
    gid = str(guild_id)
    if gid in _CACHE and name in _CACHE[gid][category]:
        _CACHE[gid][category].remove(name)
        _DIRTY = True


def list_guild_subreddits(guild_id, category):
    return get_guild_subreddits(guild_id, category)


def refresh_cache():
    """Reload cache from disk and reset dirty flag."""
    global _CACHE, _DIRTY
    _CACHE = _load_from_disk()
    _DIRTY = False


def persist_cache():
    """Persist cache to disk if there were modifications."""
    _save_to_disk()
