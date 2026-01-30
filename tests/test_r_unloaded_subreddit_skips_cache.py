import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme
from memer.helpers.reddit_cache import NoopCacheManager


def test_r_unloaded_subreddit_skips_cache(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr="real")
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    post = SimpleNamespace(
        id="abc123",
        title="cat meme",
        permalink="/r/python/comments/abc123/cat_meme",
        url="https://example.com/cat.jpg",
        author="tester",
    )

    captured = {}

    async def fake_fetch_meme_util(**kwargs):
        captured["cache_mgr"] = kwargs.get("cache_mgr")
        return SimpleNamespace(post=post, source_subreddit="python", picked_via="live")

    monkeypatch.setattr(meme_mod, "fetch_meme_util", fake_fetch_meme_util)
    async def fake_get_recent_post_ids(*a, **k):
        return []

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, "get_image_url", lambda p: p.url)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)
    monkeypatch.setattr(meme_mod, "update_stats", lambda *a, **k: None)
    monkeypatch.setattr(meme_mod, "simple_random_meme", lambda *a, **k: post)
    async def fake_send_meme(ctx, url, content=None, embed=None):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, "send_meme", fake_send_meme)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    async def fake_defer():
        pass

    async def fake_send(*a, **k):
        pass

    ctx.defer = fake_defer
    ctx.send = fake_send

    asyncio.run(Meme.r_(meme_cog, ctx, "python", keyword="cat"))

    assert isinstance(captured["cache_mgr"], NoopCacheManager)
