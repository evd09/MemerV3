import os
import sys
import asyncio
import random
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme
from memer.reddit_meme import fetch_meme as real_fetch_meme


class DummyCache:
    def __init__(self, posts):
        self.posts = posts

    def get_from_ram(self, keyword, nsfw=False):
        return []

    async def get_from_disk(self, keyword, nsfw=False):
        return self.posts if keyword == 'cat' else []

    def is_disabled(self, keyword, nsfw=False):
        return False

    def cache_to_ram(self, *args, **kwargs):
        pass

    async def save_to_disk(self, *args, **kwargs):
        pass

    def record_failure(self, *args, **kwargs):
        pass


def test_r_subreddit_keyword_filters_cached_posts(monkeypatch):
    posts = []

    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=DummyCache(posts))
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    async def fake_get_recent_post_ids(*args, **kwargs):
        return []

    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, 'get_image_url', lambda post: post.url)
    monkeypatch.setattr(meme_mod, 'register_meme_message', lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        return None

    monkeypatch.setattr(meme_mod, 'update_stats', fake_update_stats)

    captured = {}
    cache_mgr_type = {}

    async def fake_fetch_meme_util(**kwargs):
        cache_mgr_type['type'] = type(kwargs.get('cache_mgr'))
        return None

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)

    async def fake_simple_random_meme(reddit, sub):
        return SimpleNamespace(
            id='fresh',
            title='meme',
            permalink='/r/memes/comments/fresh/meme',
            url='https://example.com/meme.jpg',
            author='tester',
        )

    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured['embed'] = embed
        return SimpleNamespace(id=123)

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

    random.seed(0)
    asyncio.run(Meme.r_(meme_cog, ctx, 'memes', keyword='cat'))

    assert cache_mgr_type['type'] is meme_mod.NoopCacheManager
    assert captured['embed'] is not None
