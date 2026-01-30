import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme

MEDIA_URL = "https://v.redd.it/video.mp4"
PERMALINK = "/r/testsub/comments/abc123/test_post"


def make_post():
    async def load():
        pass
    return SimpleNamespace(
        id="abc123",
        title="test post",
        permalink=PERMALINK,
        author="author",
        load=load,
    )


class DummyCtx:
    def __init__(self, *, nsfw=False):
        self.guild = SimpleNamespace(id=1)
        self.author = SimpleNamespace(id=2)
        self.channel = SimpleNamespace(id=3, is_nsfw=lambda: nsfw)
        self.interaction = None
        self.sends = []

    async def defer(self):
        pass

    async def send(self, content=None, embed=None):
        self.sends.append((content, embed))
        return SimpleNamespace(id=123)


def common_patches(monkeypatch, post):
    async def fake_get_recent_post_ids(*a, **k):
        return []

    async def fake_has_post_been_sent(*a, **k):
        return False

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, "has_post_been_sent", fake_has_post_been_sent)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)

    async def fake_update_stats(*a, **k):
        return None

    monkeypatch.setattr(meme_mod, "update_stats", fake_update_stats)
    monkeypatch.setattr(meme_mod, "get_image_url", lambda p: MEDIA_URL)
    monkeypatch.setattr(meme_mod, "get_reddit_url", lambda url: url)

def test_meme_non_image_includes_embed_and_media_url(monkeypatch):
    post = make_post()
    meme_cog = Meme.__new__(Meme)
    meme_cog.reddit = SimpleNamespace()
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)

    async def fake_simple_random_meme(reddit, sub):
        return post

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)
    monkeypatch.setattr(meme_mod, "get_guild_subreddits", lambda guild_id, kind: ["testsub"])
    common_patches(monkeypatch, post)

    ctx = DummyCtx()
    asyncio.run(Meme.meme(meme_cog, ctx))
    assert len(ctx.sends) == 2
    (content1, embed1), (content2, embed2) = ctx.sends
    assert content1 is None
    assert embed1.url == f"https://reddit.com{PERMALINK}"
    assert content2 == MEDIA_URL
    assert embed2 is None


def test_nsfwmeme_non_image_includes_embed_and_media_url(monkeypatch):
    post = make_post()
    meme_cog = Meme.__new__(Meme)
    meme_cog.reddit = SimpleNamespace()
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)

    async def fake_simple_random_meme(reddit, sub):
        return post

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)
    monkeypatch.setattr(meme_mod, "get_guild_subreddits", lambda guild_id, kind: ["testsub"])
    common_patches(monkeypatch, post)

    ctx = DummyCtx(nsfw=True)
    asyncio.run(Meme.nsfwmeme(meme_cog, ctx))
    assert len(ctx.sends) == 2
    (content1, embed1), (content2, embed2) = ctx.sends
    assert content1 is None
    assert embed1.url == f"https://reddit.com{PERMALINK}"
    assert content2 == MEDIA_URL
    assert embed2 is None


def test_r_non_image_includes_embed_and_media_url(monkeypatch):
    post = make_post()
    meme_cog = Meme.__new__(Meme)

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit = SimpleNamespace(subreddit=fake_subreddit)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)

    async def fake_simple_random_meme(reddit, sub):
        return post

    monkeypatch.setattr(meme_mod, "simple_random_meme", fake_simple_random_meme)
    common_patches(monkeypatch, post)

    ctx = DummyCtx()
    asyncio.run(Meme.r_(meme_cog, ctx, "testsub"))
    assert len(ctx.sends) == 2
    (content1, embed1), (content2, embed2) = ctx.sends
    assert content1 == "Random pick 🎲"
    assert embed1.url == f"https://reddit.com{PERMALINK}"
    assert content2 == MEDIA_URL
    assert embed2 is None
