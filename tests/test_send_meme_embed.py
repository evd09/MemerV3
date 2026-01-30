import os
import sys
import asyncio
from types import SimpleNamespace
from discord import Embed

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.helpers.meme_utils import send_meme


class DummyCtx:
    def __init__(self):
        self.sends = []
        self.interaction = None

    async def send(self, content=None, embed=None):
        self.sends.append((content, embed))
        return SimpleNamespace(id=123)


def test_send_meme_handles_query_params_for_images():
    ctx = DummyCtx()
    embed = Embed(title="test")
    url = "https://example.com/image.png?width=200&height=200"
    asyncio.run(send_meme(ctx, url=url, embed=embed))

    assert len(ctx.sends) == 1
    content, returned_embed = ctx.sends[0]
    assert content is None
    assert returned_embed is embed
    assert embed.image.url == url


def test_send_meme_non_image_sends_embed_then_url():
    ctx = DummyCtx()
    embed = Embed(title="test")
    url = "https://v.redd.it/video"
    asyncio.run(send_meme(ctx, url=url, embed=embed))

    assert len(ctx.sends) == 2
    (content1, embed1), (content2, embed2) = ctx.sends
    assert content1 is None
    assert embed1 is embed
    assert content2 == url
    assert embed2 is None
