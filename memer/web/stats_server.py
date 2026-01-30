import asyncio
import json
import os
from aiohttp import web

STATS_FILE = "stats.json"

_stats_cache = {}
_stats_mtime = 0.0

def _load_stats() -> None:
    """Load stats from STATS_FILE if it has changed."""
    global _stats_cache, _stats_mtime
    try:
        mtime = os.path.getmtime(STATS_FILE)
        if mtime != _stats_mtime:
            with open(STATS_FILE, "r") as f:
                _stats_cache = json.load(f)
            _stats_mtime = mtime
    except Exception:
        _stats_cache = {}

async def _refresh_stats(interval: int = 60) -> None:
    """Background task to refresh stats cache."""
    while True:
        _load_stats()
        await asyncio.sleep(interval)

async def stats_handler(request: web.Request) -> web.Response:
    """Return cached stats as JSON."""
    return web.json_response(_stats_cache)

async def start_stats_server() -> None:
    """Start the stats HTTP server and refresh task."""
    _load_stats()
    app = web.Application()
    app.router.add_get("/stats", stats_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    asyncio.create_task(_refresh_stats())
