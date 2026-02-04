import asyncio
import json
import os
import sys
import discord
from discord.ext import commands

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memer.config import ENTRANCE_DATA
from memer.helpers import db
from dotenv import load_dotenv

load_dotenv()

async def migrate_entrances():
    print("🚀 Starting V3.6.2 Entrance Migration (JSON -> SQLite Per-Guild)")
    
    # Check if JSON exists
    if not os.path.exists(ENTRANCE_DATA):
        print("⚠️ No entrance_sounds.json found. Nothing to migrate.")
        return

    with open(ENTRANCE_DATA, 'r') as f:
        legacy_data = json.load(f)
    
    print(f"📄 Loaded {len(legacy_data)} user configurations from JSON.")

    # Initialize DB
    await db.init()

    # We need a Discord Client to resolve Guilds
    intents = discord.Intents.default()
    intents.members = True # Essential to see members
    intents.guilds = True
    
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"🤖 Bot connected as {bot.user}. Scanning guilds...")
        
        count = 0
        skipped = 0
        
        # Iterate through all legacy users
        for user_id_str, config in legacy_data.items():
            user_id = int(user_id_str)
            
            # Extract file/volume (Backwards compatibility logic)
            file_name = None
            volume = 1.0
            
            # Helper to parse old/new generic json formats
            if "type" in config:
                if config["type"] == "single":
                    file_name = config.get("single", {}).get("file")
                    volume = config.get("single", {}).get("volume", 1.0)
            elif "file" in config:
                file_name = config["file"]
                volume = config.get("volume", 1.0)
            
            if not file_name:
                print(f"⏩ Skipping User {user_id}: Invalid/Complex config (Combo/Scheduled not supported in DB migration yet)")
                skipped += 1
                continue

            # Find all guilds this user is in
            user_guilds = []
            for guild in bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    user_guilds.append(guild)
            
            if not user_guilds:
                print(f"⚠️ User {user_id} not found in any common guilds. Skipping.")
                skipped += 1
                continue
                
            print(f"👤 Migrating User {user_id} -> {len(user_guilds)} Guilds")
            
            # Insert for EACH guild
            for guild in user_guilds:
                await db.set_entrance_sound(user_id, guild.id, file_name, volume)
                count += 1
                
        print(f"✅ Migration Complete! Created {count} records. Skipped {skipped} users.")
        await db.close()
        await bot.close()

    try:
        await bot.start(os.getenv("DISCORD_TOKEN"))
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(migrate_entrances())
