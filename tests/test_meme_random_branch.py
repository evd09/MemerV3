import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme


def test_meme_no_keyword_uses_random(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    monkeypatch.setattr(meme_mod, "get_guild_subreddits", lambda guild_id, kind: ["memes"])

    calls = {"count": 0}
    ids = ["recent", "fresh"]

    async def fake_simple_random_meme(reddit, sub):
        calls["count"] += 1
        return SimpleNamespace(
            id=ids.pop(0),
            title="meme",
            permalink="/r/memes/comments/abc/meme",
            url="https://example.com/meme.jpg",
            author="tester",
        )

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)

    async def fake_get_recent_post_ids(*a, **k):
        return ["recent"]

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids)

    monkeypatch.setattr(meme_mod, "get_image_url", lambda post: post.url)
    monkeypatch.setattr(meme_mod, "get_reddit_url", lambda url: url)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        pass

    monkeypatch.setattr(meme_mod, "update_stats", fake_update_stats)
    monkeypatch.setattr(meme_mod.random, "choice", lambda seq: seq[0])

    async def fake_send_meme(ctx, url, content=None, embed=None):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, "send_meme", fake_send_meme)

    async def fake_defer():
        pass

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )
    ctx.defer = fake_defer

    asyncio.run(Meme.meme(meme_cog, ctx))

    assert calls["count"] == 2


def test_meme_keyword_no_results_message(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    keyword = "cats"

    class Result(SimpleNamespace):
        post = None
        picked_via = "none"
        source_subreddit = None

    async def fake_fetch_meme_util(**kwargs):
        return Result()

    monkeypatch.setattr(meme_mod, "fetch_meme_util", fake_fetch_meme_util)
    monkeypatch.setattr(meme_mod, "get_guild_subreddits", lambda guild_id, kind: ["memes"])

    async def fake_simple_random_meme(reddit, sub):
        return SimpleNamespace(
            id="fresh",
            title="meme",
            permalink="/r/memes/comments/abc/meme",
            url="https://example.com/meme.jpg",
            author="tester",
        )

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)

    async def fake_get_recent_post_ids2(*a, **k):
        return []

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids2)
    monkeypatch.setattr(meme_mod, "get_image_url", lambda post: post.url)
    monkeypatch.setattr(meme_mod, "get_reddit_url", lambda url: url)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)

    async def fake_update_stats2(*a, **k):
        pass

    monkeypatch.setattr(meme_mod, "update_stats", fake_update_stats2)

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured["content"] = content
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, "send_meme", fake_send_meme)
    monkeypatch.setattr(meme_mod.random, "choice", lambda seq: seq[0])

    async def fake_defer():
        pass

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )
    ctx.defer = fake_defer

    asyncio.run(Meme.meme(meme_cog, ctx, keyword=keyword))

    assert captured["content"] == f"No results for {keyword}; serving a random one."


def test_nsfwmeme_no_keyword_uses_random(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    monkeypatch.setattr(meme_mod, "get_guild_subreddits", lambda guild_id, kind: ["nsfwmeme"])

    calls = {"count": 0}
    ids = ["recent", "fresh"]

    async def fake_simple_random_meme(reddit, sub):
        calls["count"] += 1
        return SimpleNamespace(
            id=ids.pop(0),
            title="meme",
            permalink="/r/nsfwmeme/comments/abc/meme",
            url="https://example.com/meme.jpg",
            author="tester",
        )

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)

    async def fake_get_recent_post_ids(*a, **k):
        return ["recent"]

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, "get_image_url", lambda post: post.url)
    monkeypatch.setattr(meme_mod, "get_reddit_url", lambda url: url)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        pass

    monkeypatch.setattr(meme_mod, "update_stats", fake_update_stats)
    monkeypatch.setattr(meme_mod.random, "choice", lambda seq: seq[0])

    async def fake_send_meme(ctx, url, content=None, embed=None):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, "send_meme", fake_send_meme)

    async def fake_defer():
        pass

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3, is_nsfw=lambda: True),
        interaction=None,
    )
    ctx.defer = fake_defer

    asyncio.run(Meme.nsfwmeme(meme_cog, ctx))

    assert calls["count"] == 2


def test_nsfwmeme_keyword_no_results_message(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    keyword = "cats"

    class Result(SimpleNamespace):
        post = None
        picked_via = "none"
        source_subreddit = None

    async def fake_fetch_meme_util(**kwargs):
        return Result()

    monkeypatch.setattr(meme_mod, "fetch_meme_util", fake_fetch_meme_util)
    monkeypatch.setattr(meme_mod, "get_guild_subreddits", lambda guild_id, kind: ["nsfwmeme"])

    async def fake_simple_random_meme(reddit, sub):
        return SimpleNamespace(
            id="fresh",
            title="meme",
            permalink="/r/nsfwmeme/comments/abc/meme",
            url="https://example.com/meme.jpg",
            author="tester",
        )

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)

    async def fake_get_recent_post_ids2(*a, **k):
        return []

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids2)
    monkeypatch.setattr(meme_mod, "get_image_url", lambda post: post.url)
    monkeypatch.setattr(meme_mod, "get_reddit_url", lambda url: url)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)

    async def fake_update_stats2(*a, **k):
        pass

    monkeypatch.setattr(meme_mod, "update_stats", fake_update_stats2)

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured["content"] = content
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, "send_meme", fake_send_meme)
    monkeypatch.setattr(meme_mod.random, "choice", lambda seq: seq[0])

    async def fake_defer():
        pass

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3, is_nsfw=lambda: True),
        interaction=None,
    )
    ctx.defer = fake_defer

    asyncio.run(Meme.nsfwmeme(meme_cog, ctx, keyword=keyword))

    assert captured["content"] == f"No results for {keyword}; serving a random one."
