import os
import sys
import importlib
import asyncio


def test_leaderboards_reflect_counts(tmp_path):
    db_path = tmp_path / "stats.db"
    os.environ["MEME_STATS_DB"] = str(db_path)

    if "memer.meme_stats" in sys.modules:
        del sys.modules["memer.meme_stats"]
    meme_stats = importlib.import_module("memer.meme_stats")

    asyncio.run(meme_stats.init())

    asyncio.run(meme_stats.update_stats(1, "python", "learnpython", False))
    asyncio.run(meme_stats.update_stats(1, "python", "learnpython", True))
    asyncio.run(meme_stats.update_stats(2, "java", "learnjava", False))

    total = asyncio.run(meme_stats.get_stat("total_memes"))
    nsfw = asyncio.run(meme_stats.get_stat("nsfw_memes"))
    assert total == 3
    assert nsfw == 1

    top_users = asyncio.run(meme_stats.get_top_users())
    assert top_users[0] == ("1", 2)

    top_keywords = asyncio.run(meme_stats.get_top_keywords())
    assert top_keywords[0] == ("python", 2)

    top_subreddits = asyncio.run(meme_stats.get_top_subreddits())
    assert top_subreddits[0] == ("learnpython", 2)

    asyncio.run(meme_stats.close())


def test_init_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "stats.db"
    os.environ["MEME_STATS_DB"] = str(db_path)

    if "memer.meme_stats" in sys.modules:
        del sys.modules["memer.meme_stats"]
    meme_stats = importlib.import_module("memer.meme_stats")

    asyncio.run(meme_stats.init())

    assert db_path.parent.exists()
    assert db_path.exists()

    asyncio.run(meme_stats.close())


def test_update_stats_handles_subreddit_objects(tmp_path):
    db_path = tmp_path / "stats.db"
    os.environ["MEME_STATS_DB"] = str(db_path)

    if "memer.meme_stats" in sys.modules:
        del sys.modules["memer.meme_stats"]
    meme_stats = importlib.import_module("memer.meme_stats")

    asyncio.run(meme_stats.init())

    class DummySubreddit:
        display_name = "dummysub"

    asyncio.run(meme_stats.update_stats(1, "python", DummySubreddit(), False))

    top_subreddits = asyncio.run(meme_stats.get_top_subreddits())
    assert top_subreddits[0] == ("dummysub", 1)

    asyncio.run(meme_stats.close())
