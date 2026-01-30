import os
import sys
import asyncio
from types import SimpleNamespace

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme
from memer.reddit_meme import SubredditUnavailableError

def test_r_subreddit_unavailable(monkeypatch):
    meme_cog = Meme.__new__(Meme)
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)
    meme_cog.reddit = SimpleNamespace()

    async def fake_subreddit(name, fetch=True):
        return SimpleNamespace(display_name=name, over18=False)

    meme_cog.reddit.subreddit = fake_subreddit

    async def fake_fetch_meme_util(**kwargs):
        return None

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)

    async def fake_simple_random_meme(reddit, sub):
        raise SubredditUnavailableError(sub)

    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)

    async def fake_get_recent_post_ids(*args, **kwargs):
        return []

    monkeypatch.setattr(meme_mod, 'get_recent_post_ids', fake_get_recent_post_ids)

    captured = {}

    async def fake_defer():
        pass

    async def fake_send(msg, **kwargs):
        captured['msg'] = msg

    async def fake_reply(msg, **kwargs):
        captured['reply'] = msg

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=None,
    )

    ctx.defer = fake_defer
    ctx.send = fake_send
    ctx.reply = fake_reply

    asyncio.run(Meme.r_(meme_cog, ctx, 'python'))

    assert captured['msg'] == 'r/python is not available :/'
