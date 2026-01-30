import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme

class DummyResponse:
    async def send_message(self, *args, **kwargs):
        pass

class DummyFollowup:
    async def send(self, *args, **kwargs):
        pass

class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()

def test_nsfwmeme_in_sfw_channel_sets_no_reward():
    meme_cog = Meme.__new__(Meme)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(is_nsfw=lambda: False),
        interaction=DummyInteraction(),
    )
    async def fake_get_recent_post_ids(*args, **kwargs):
        return []

    meme_mod.get_recent_post_ids = fake_get_recent_post_ids
    asyncio.run(Meme.nsfwmeme(meme_cog, ctx))
    assert getattr(ctx, "_no_reward", False) is True


def test_r_blocks_nsfw_subreddit_in_sfw_channel():
    meme_cog = Meme.__new__(Meme)
    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=True)

    meme_cog.reddit = SimpleNamespace(subreddit=fake_subreddit)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(is_nsfw=lambda: False),
        interaction=DummyInteraction(),
    )

    async def fake_defer():
        pass

    ctx.defer = fake_defer

    asyncio.run(Meme.r_(meme_cog, ctx, "python"))
    assert getattr(ctx, "_no_reward", False) is True

def test_meme_uses_local_fallback_when_no_posts(monkeypatch):
    meme_cog = Meme.__new__(Meme)

    async def fake_fetch_meme_util(**kwargs):
        return SimpleNamespace(post=None, picked_via='cache')

    async def fake_simple_random_meme(reddit, sub):
        return None

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)
    monkeypatch.setattr(meme_mod, 'get_guild_subreddits', lambda guild_id, kind: ['a'])
    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)
    meme_mod.WARM_CACHE.clear()

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured['url'] = url
        captured['embed'] = embed
        return SimpleNamespace(id=123)

    monkeypatch.setattr(meme_mod, 'send_meme', fake_send_meme)
    monkeypatch.setattr(meme_mod, 'register_meme_message', lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        return None

    monkeypatch.setattr(meme_mod, 'update_stats', fake_update_stats)

    meme_cog.reddit = SimpleNamespace()
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.bot = SimpleNamespace(config=SimpleNamespace(MEME_CACHE={'fallback_dir': 'data/fallback_memes'}))

    async def fake_get_recent_post_ids(*args, **kwargs):
        return []

    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', fake_get_recent_post_ids)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    async def dummy_defer():
        pass

    ctx.defer = dummy_defer

    asyncio.run(Meme.meme(meme_cog, ctx))

    assert captured['embed'].footer.text == 'via LOCAL'
    assert getattr(ctx, "_no_reward", False) is False
