# memer/config.py
import os
from pathlib import Path

# --- Paths ---
# Use absolute paths or relative to the running directory (cwd is usually project root)
SOUND_FOLDER = "./sounds"
DATA_DIR = "./data"
ENTRANCE_DATA = os.path.join(DATA_DIR, "entrance_sounds.json")
SOUND_META_FILE = os.path.join(DATA_DIR, "sound_meta.json")
USER_SETTINGS_FILE = os.path.join(DATA_DIR, "user_settings.json")
STATS_FILE = os.path.join(DATA_DIR, "sound_stats.json")

# Ensure directories exist
Path(SOUND_FOLDER).mkdir(parents=True, exist_ok=True)
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

# --- Audio ---
AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".mp4", ".webm", ".opus")

# --- Web / Frontend ---
TICKER_SPEED = 80  # Pixels per second
