import os
import sys
from types import SimpleNamespace

# Ensure project root on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.helpers.meme_utils import get_image_url


def test_get_image_url_returns_first_gallery_image():
    post = SimpleNamespace(
        id="abc123",
        url="https://www.reddit.com/gallery/abc123",
        is_gallery=True,
        gallery_data={"items": [{"media_id": "def456"}]},
        media_metadata={"def456": {"status": "valid", "s": {"u": "https://i.redd.it/example.jpg"}}},
        media=None,
        secure_media=None,
        preview={},
    )
    assert get_image_url(post) == "https://i.redd.it/example.jpg"
