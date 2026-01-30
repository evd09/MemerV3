import os
import sys
import asyncio
from types import SimpleNamespace
import discord

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.helpers.meme_utils import send_meme


class DummyResponse:
    def is_done(self):
        return True

    async def defer(self):
        pass


class DummyFollowup:
    async def send(self, *args, **kwargs):
        raise discord.errors.NotFound()


class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()


class DummyChannel:
    def __init__(self):
        self.sent = None

    async def send(self, content=None, embed=None):
        self.sent = (content, embed)
        return SimpleNamespace(id=789)


class DummyCtx:
    def __init__(self):
        self.interaction = DummyInteraction()
        self.channel = DummyChannel()


def test_send_meme_falls_back_to_channel_send_when_interaction_missing():
    ctx = DummyCtx()
    url = "https://example.com/image.png"
    asyncio.run(send_meme(ctx, url=url))
    assert ctx.channel.sent == (url, None)
