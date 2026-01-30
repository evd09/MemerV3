import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme


class DummyCache:
    def __init__(self):
        self.disabled = False

    def get_from_ram(self, *a, **k):
        return []

    async def get_from_disk(self, *a, **k):
        return []

    def is_disabled(self, *a, **k):
        return self.disabled

    def cache_to_ram(self, *a, **k):
        pass

    async def save_to_disk(self, *a, **k):
        pass

    def record_failure(self, *a, **k):
        self.disabled = True


def test_r_keyword_cache_manager_never_disables(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=DummyCache())
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    # make subreddit 'python' appear loaded so cache is used
    monkeypatch.setattr(meme_mod, 'get_guild_subreddits', lambda guild_id, cat: ['python'])
    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', lambda *a, **k: [])
    monkeypatch.setattr(meme_mod, 'get_image_url', lambda p: p.url)
    monkeypatch.setattr(meme_mod, 'register_meme_message', lambda *a, **k: None)
    monkeypatch.setattr(meme_mod, 'update_stats', lambda *a, **k: None)

    post = SimpleNamespace(
        id='abc123',
        title='cat meme',
        permalink='/r/python/comments/abc123/cat_meme',
        url='https://example.com/cat.jpg',
        author='tester',
    )

    async def fake_fetch_meme(**kwargs):
        cm = kwargs['cache_mgr']
        cm.record_failure('cat', nsfw=False)
        assert cm.is_disabled('cat', nsfw=False) is False
        return SimpleNamespace(post=post, source_subreddit='python', picked_via='live')

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme)

    async def fake_send_meme(ctx, url, content=None, embed=None):
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

    async def fake_send(*a, **k):
        pass

    ctx.defer = fake_defer
    ctx.send = fake_send

    asyncio.run(Meme.r_(meme_cog, ctx, 'python', keyword='cat'))

    # underlying cache should not have been disabled
    assert meme_cog.cache_service.cache_mgr.disabled is False
