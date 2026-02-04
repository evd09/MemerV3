#!/usr/bin/env python3
"""
Migration Script V3.7.1: JSON to Database
Migrates data from JSON files to database tables:
- sound_stats.json → sounds.play_count
- guild_subreddits.json → guild_subreddits table
"""

import sys
import os
import json
import asyncio
import aiosqlite

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.config import DATA_DIR, DB_PATH

STATS_FILE = os.path.join(DATA_DIR, "sound_stats.json")
SUBREDDITS_FILE = os.path.join(DATA_DIR, "guild_subreddits.json")

def load_json(filepath):
    """Load JSON file."""
    if not os.path.exists(filepath):
        print(f"⚠️  File not found: {filepath}")
        return {}

    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading {filepath}: {e}")
        return {}

async def migrate_sound_stats(conn):
    """Migrate sound_stats.json to sounds.play_count column."""
    print("\n🔄 Migrating sound_stats.json...")

    stats = load_json(STATS_FILE)

    if not stats:
        print("  ℹ️  No sound stats to migrate (file empty or missing)")
        return

    migrated = 0
    skipped = 0

    for filename, play_count in stats.items():
        # Find sound by filename
        async with conn.execute(
            "SELECT id FROM sounds WHERE filename = ?",
            (filename,)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            # Update play count
            await conn.execute(
                "UPDATE sounds SET play_count = ? WHERE id = ?",
                (play_count, row[0])
            )
            migrated += 1
        else:
            print(f"  ⚠️  Sound not found in database: {filename}")
            skipped += 1

    await conn.commit()
    print(f"  ✅ Migrated {migrated} play counts, {skipped} skipped (sound not in DB)")

async def migrate_guild_subreddits(conn):
    """Migrate guild_subreddits.json to guild_subreddits table."""
    print("\n🔄 Migrating guild_subreddits.json...")

    data = load_json(SUBREDDITS_FILE)

    if not data:
        print("  ℹ️  No guild subreddits to migrate (file empty or missing)")
        return

    total_entries = 0

    for guild_id_str, categories in data.items():
        guild_id = int(guild_id_str)

        for category in ["sfw", "nsfw"]:
            subreddits = categories.get(category, [])

            for subreddit in subreddits:
                # Insert into database
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO guild_subreddits (guild_id, subreddit, category)
                    VALUES (?, ?, ?)
                    """,
                    (guild_id, subreddit, category)
                )
                total_entries += 1

    await conn.commit()
    print(f"  ✅ Migrated {total_entries} subreddit entries for {len(data)} guilds")

async def backup_json_files():
    """Create backups of JSON files before migration."""
    print("\n💾 Creating backups...")

    for filepath in [STATS_FILE, SUBREDDITS_FILE]:
        if os.path.exists(filepath):
            backup_path = f"{filepath}.backup"
            try:
                with open(filepath, 'r') as src:
                    data = src.read()
                with open(backup_path, 'w') as dst:
                    dst.write(data)
                print(f"  ✅ Backed up: {backup_path}")
            except Exception as e:
                print(f"  ❌ Failed to backup {filepath}: {e}")

async def main():
    print("=" * 60)
    print("V3.7.1 Migration: JSON to Database")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        print("  Please ensure the bot has been run at least once to create the database.")
        return

    # Create backups
    await backup_json_files()

    # Connect to database
    print(f"\n🔌 Connecting to database: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Migrate sound stats
        await migrate_sound_stats(conn)

        # Migrate guild subreddits
        await migrate_guild_subreddits(conn)

    print("\n" + "=" * 60)
    print("✅ Migration Complete!")
    print("=" * 60)
    print("\n📝 Next Steps:")
    print("  1. Restart the bot")
    print("  2. Verify data appears correctly in admin panel")
    print("  3. If everything works, you can delete the JSON files:")
    print(f"     - {STATS_FILE}")
    print(f"     - {SUBREDDITS_FILE}")
    print("  4. Backups are saved with .backup extension")
    print()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
