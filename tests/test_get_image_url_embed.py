import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.helpers.meme_utils import get_image_url


def _make_post(attr: str):
    html = '<iframe src="https://example.com/video.mp4"></iframe>'
    post = SimpleNamespace(
        id="abc123",
        url="https://reddit.com/r/test/comments/abc123/embed",
        media=None,
        secure_media=None,
        preview={},
        media_embed={},
        secure_media_embed={},
    )
    setattr(post, attr, {"content": html})
    return post, "https://example.com/video.mp4"


def test_get_image_url_returns_embed_src():
    for attr in ("media_embed", "secure_media_embed"):
        post, expected = _make_post(attr)
        assert get_image_url(post) == expected
