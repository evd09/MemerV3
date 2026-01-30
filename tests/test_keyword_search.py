import os
import sys
import asyncio
from types import SimpleNamespace

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme
from memer.reddit_meme import MemeResult


def test_r_subreddit_keyword_uses_matched_post(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    post = SimpleNamespace(
        id="abc123",
        title="A cat meme",
        permalink="/r/python/comments/abc123/a_cat_meme",
        author="tester",
    )

    result = MemeResult(
        post=post,
        source_subreddit="python",
        listing="hot",
        tried_subreddits=["python"],
        errors=[],
        picked_via="cache",
    )

    async def fake_fetch_meme_util(**kwargs):
        return result

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)

    called = {'random': False}

    async def fake_simple_random_meme(reddit, sub):
        called['random'] = True
        return None

    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)

    async def fake_get_recent_post_ids(*args, **kwargs):
        return []

    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, 'get_image_url', lambda post: 'https://example.com/image.jpg')
    monkeypatch.setattr(meme_mod, 'register_meme_message', lambda *a, **k: None)
    async def fake_update_stats(*a, **k):
        return None

    monkeypatch.setattr(meme_mod, 'update_stats', fake_update_stats)

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured['content'] = content
        captured['embed'] = embed
        return SimpleNamespace(id=456)

    monkeypatch.setattr(meme_mod, 'send_meme', fake_send_meme)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    async def fake_defer():
        pass

    ctx.defer = fake_defer

    asyncio.run(Meme.r_(meme_cog, ctx, 'python', keyword='cat'))

    assert called['random'] is False
    assert captured['content'] is None
    assert captured['embed'].footer.text == 'via CACHE'


def test_r_subreddit_no_keyword_uses_random(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    called = {'fetch': False, 'random': False}

    async def fake_fetch_meme_util(**kwargs):
        called['fetch'] = True
        return None

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)

    async def fake_simple_random_meme(reddit, sub):
        called['random'] = True
        return SimpleNamespace(
            id='xyz',
            title='rand',
            permalink='/r/python/comments/xyz/rand',
            url='https://example.com/rand.jpg',
            author='tester',
        )

    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)

    async def fake_get_recent_post_ids(*a, **k):
        return []

    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, 'get_image_url', lambda post: post.url)
    monkeypatch.setattr(meme_mod, 'register_meme_message', lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        return None

    monkeypatch.setattr(meme_mod, 'update_stats', fake_update_stats)

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured['content'] = content
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, 'send_meme', fake_send_meme)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    async def fake_defer():
        pass

    ctx.defer = fake_defer

    asyncio.run(Meme.r_(meme_cog, ctx, 'python'))

    assert called['random'] is True
    assert called['fetch'] is False
    assert captured['content'] == 'Random pick 🎲'


def test_r_subreddit_keyword_no_results_message(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    keyword = 'cats'

    class Result(SimpleNamespace):
        post = None

    async def fake_fetch_meme_util(**kwargs):
        return Result()

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)
    monkeypatch.setattr(meme_mod, 'get_guild_subreddits', lambda guild_id, kind: ['python'])

    async def fake_simple_random_meme(reddit, sub):
        return SimpleNamespace(
            id='fresh',
            title='meme',
            permalink='/r/python/comments/abc/meme',
            url='https://example.com/meme.jpg',
            author='tester',
        )

    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)

    async def fake_get_recent_post_ids(*a, **k):
        return []

    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, 'get_image_url', lambda post: post.url)
    monkeypatch.setattr(meme_mod, 'get_reddit_url', lambda url: url)
    monkeypatch.setattr(meme_mod, 'register_meme_message', lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        pass

    monkeypatch.setattr(meme_mod, 'update_stats', fake_update_stats)

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured['content'] = content
        return SimpleNamespace(id=1)

    monkeypatch.setattr(meme_mod, 'send_meme', fake_send_meme)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    async def fake_defer():
        pass

    ctx.defer = fake_defer

    asyncio.run(Meme.r_(meme_cog, ctx, 'python', keyword=keyword))

    assert captured['content'] == f"No results for {keyword}; serving a random one."
