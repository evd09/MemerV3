import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme
from memer.reddit_meme import fetch_meme as real_fetch_meme


class DummyCache:
    def get_from_ram(self, *a, **k):
        return []

    async def get_from_disk(self, *a, **k):
        return []

    def is_disabled(self, *a, **k):
        return False

    def cache_to_ram(self, *a, **k):
        pass

    async def save_to_disk(self, *a, **k):
        pass

    def record_failure(self, *a, **k):
        pass


def test_r_keyword_uses_subreddit_search(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=DummyCache())
    meme_cog.reddit = SimpleNamespace()

    class FakeSubreddit:
        display_name = "python"
        over18 = False

        async def search(self, query, limit=75):
            yield SimpleNamespace(
                id="abc123",
                title="cat meme",
                permalink="/r/python/comments/abc123/cat_meme",
                url="https://example.com/cat.jpg",
                author="tester",
                subreddit=SimpleNamespace(display_name="python"),
            )

        async def hot(self, limit=75):
            if False:
                yield None

        async def new(self, limit=75):
            if False:
                yield None

        async def top(self, limit=75):
            if False:
                yield None

    async def fake_subreddit(name, fetch=True):
        return FakeSubreddit()

    meme_cog.reddit.subreddit = fake_subreddit

    async def fake_get_recent_post_ids(*a, **k):
        return []

    monkeypatch.setattr(meme_mod, "get_recent_post_ids", fake_get_recent_post_ids)
    monkeypatch.setattr(meme_mod, "get_image_url", lambda post: post.url)
    monkeypatch.setattr(meme_mod, "register_meme_message", lambda *a, **k: None)
    async def fake_update(*a, **k):
        pass
    monkeypatch.setattr(meme_mod, "update_stats", fake_update)

    captured_result = {}

    async def wrapper_fetch_meme(**kwargs):
        kwargs["extract_fn"] = lambda post: {
            "post_id": post.id,
            "subreddit": post.subreddit.display_name,
            "title": post.title,
            "url": post.url,
            "media_url": post.url,
            "permalink": post.permalink,
            "author": post.author,
        }
        res = await real_fetch_meme(**kwargs)
        captured_result["result"] = res
        return res

    monkeypatch.setattr(meme_mod, "fetch_meme_util", wrapper_fetch_meme)

    captured = {}

    async def fake_send_meme(ctx, url, content=None, embed=None):
        captured["embed"] = embed
        return SimpleNamespace(id=42)

    monkeypatch.setattr(meme_mod, "send_meme", fake_send_meme)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    async def fake_defer():
        pass

    ctx.defer = fake_defer
    async def fake_send(*a, **k):
        pass
    ctx.send = fake_send

    asyncio.run(Meme.r_(meme_cog, ctx, "python", keyword="cat"))

    assert captured_result["result"].listing == "search"
    assert captured["embed"].footer.text == "via LIVE"
