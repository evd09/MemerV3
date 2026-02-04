
import asyncio
import json
import os
import uuid
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memer.config import SOUND_FOLDER, SOUND_META_FILE, AUDIO_EXTS
from memer.helpers import db

async def migrate():
    print("🚀 Starting V3.6.0 Migration: JSON -> SQLite")
    
    # Initialize DB
    await db.init()
    
    # Load JSON metadata
    meta = {}
    if os.path.exists(SOUND_META_FILE):
        with open(SOUND_META_FILE, 'r') as f:
            meta = json.load(f)
    print(f"Loaded {len(meta)} metadata entries from sounds.json")

    # Scan directory
    files = [f for f in os.listdir(SOUND_FOLDER) if Path(f).suffix.lower() in AUDIO_EXTS]
    print(f"Found {len(files)} audio files in {SOUND_FOLDER}")

    # Deduplicate logic: group by stem, prefer opus
    sound_map = {} # stem -> filename
    for f in files:
        stem = Path(f).stem.lower()
        ext = Path(f).suffix.lower()
        
        if stem not in sound_map:
            sound_map[stem] = f
        else:
            current_ext = Path(sound_map[stem]).suffix.lower()
            if ext == '.opus' and current_ext != '.opus':
                sound_map[stem] = f
                
    unique_files = list(sound_map.values())
    print(f"Identified {len(unique_files)} unique sounds (deduplicated versions)")

    count = 0
    skipped = 0
    
    # We need to access the raw connection to execute inserts
    # db._conn is the connection object
    
    # Check if DB is dirty from previous run and clear it (Development mode!)
    # Ideally we wouldn't delete, but for this specific migration task it's safer to start clean
    # if we detect we are re-running for v3.6
    async with db._conn.execute("SELECT COUNT(*) FROM sounds") as cursor:
        row = await cursor.fetchone()
        if row[0] > 0:
            print(f"⚠️  Database has {row[0]} entries. Purging for clean V3.6 migration...")
            await db._conn.execute("DELETE FROM sounds")
            await db._conn.commit()

    for filename in unique_files:
        stem = Path(filename).stem.lower()
        
        # Get metadata
        m = meta.get(filename, {})
        display_name = m.get("name", stem) # Default to stem if no name
        
        # Generate UUID for the ID (Primary Key)
        sound_id = str(uuid.uuid4())
        
        # Insert into DB
        # proper parametized query
        try:
            await db._conn.execute(
                """
                INSERT INTO sounds (id, guild_id, filename, display_name, created_at, play_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sound_id, None, filename, display_name, int(sys.time.time() if hasattr(sys, 'time') else 0), 0)
            )
            count += 1
        except Exception as e:
            print(f"❌ Error inserting {filename}: {e}")
            skipped += 1

    await db._conn.commit()
    print(f"✅ Migration Complete! Imported {count} sounds. Skipped {skipped}.")
    await db.close()

if __name__ == "__main__":
    # Fix for timestamp
    import time
    sys.time = time
    
    asyncio.run(migrate())
