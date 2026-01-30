import asyncio
from types import SimpleNamespace

from asyncprawcore import BadRequest

from memer.reddit_meme import simple_random_meme


class FakeSubreddit:
    display_name = "target"

    async def random(self):
        raise BadRequest(SimpleNamespace(status=400))

    async def hot(self, limit=50):
        yield SimpleNamespace(
            id="target1",
            url="https://example.com/target.png",
            subreddit=SimpleNamespace(display_name="target"),
        )


class FakeReddit:
    async def subreddit(self, name):
        assert name == "target"
        return FakeSubreddit()


def test_simple_random_meme_bad_request_fallback():
    async def run():
        reddit = FakeReddit()
        post = await simple_random_meme(reddit, "target")
        assert post.id == "target1"
        assert post.subreddit.display_name == "target"

    asyncio.run(run())
