import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from memer import reddit_meme
from memer.helpers import rate_limit

class FakePost(SimpleNamespace):
    pass

class FakeSubreddit:
    def __init__(self, posts):
        self.posts = posts
        self.display_name = "testsub"

    async def hot(self, limit):
        for p in self.posts[:limit]:
            yield p


def collect(limit, total_posts):
    rate_limit._last_request = 0
    posts = [FakePost(id=i) for i in range(total_posts)]
    sub = FakeSubreddit(posts)

    async def _run():
        return [p async for p in reddit_meme._fetch_listing_with_retry(sub, "hot", limit)]

    return asyncio.run(_run())


def test_small_limit():
    result = collect(limit=1, total_posts=5)
    assert len(result) == 1
    assert result[0].id == 0


def test_large_limit():
    result = collect(limit=100, total_posts=150)
    assert len(result) == 100
    assert result[-1].id == 99
