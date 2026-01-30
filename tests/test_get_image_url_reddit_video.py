import os
import sys
from types import SimpleNamespace

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.helpers.meme_utils import get_image_url


def _make_post(attr: str):
    rv = {"fallback_url": "https://v.redd.it/test_video/DASH_720.mp4"}
    post = SimpleNamespace(
        id="abc123",
        url="https://reddit.com/r/test/comments/abc123/video",
        media=None,
        secure_media=None,
        preview={},
    )
    setattr(post, attr, {"reddit_video": rv})
    return post, rv["fallback_url"]


def test_get_image_url_returns_reddit_video_fallback():
    for attr in ("media", "secure_media"):
        post, expected = _make_post(attr)
        assert get_image_url(post) == expected
