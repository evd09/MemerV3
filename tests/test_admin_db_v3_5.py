
import pytest
import pytest_asyncio
import tempfile
import os
import aiosqlite
from memer.helpers import db

@pytest_asyncio.fixture
async def db_setup():
    # Setup temp DB
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    os.environ["MEME_CACHE_DB"] = db_path
    
    # Init DB
    await db.init()
    
    yield db_path
    
    # Cleanup
    await db.close()
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.mark.asyncio
async def test_admin_logging_logic(db_setup):
    # Log Action
    await db.log_admin_action(
        guild_id=123, 
        admin_id=1, 
        admin_username="Admin", 
        action_type="test_action", 
        details={"foo": "bar"},
        target_id=2,
        target_username="User"
    )
    
    # Retrieve Log
    logs = await db.get_admin_activity_log(123)
    assert logs['total'] == 1
    entry = logs['logs'][0]
    assert entry['action_type'] == "test_action"
    assert entry['admin_username'] == "Admin"
    assert "foo" in entry['details']

@pytest.mark.asyncio
async def test_entrance_analytics(db_setup):
    # Log plays
    await db.log_entrance_play(123, 2, "funny.mp3")
    await db.log_entrance_play(123, 2, "funny.mp3") # 2nd play
    await db.log_entrance_play(123, 1, "alert.mp3")
    
    # Check Analytics
    stats = await db.get_entrance_analytics(123)
    
    # Verify counts
    assert stats['total_plays'] == 3
    
    pop = stats['most_popular_sounds']
    assert len(pop) >= 2
    assert pop[0]['file'] == "funny.mp3"
    assert pop[0]['play_count'] == 2
    assert pop[0]['unique_users'] == 1
