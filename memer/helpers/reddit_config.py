import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "reddit_meme.config.yml"
)
CONFIG_PATH = Path(os.getenv("REDDIT_MEME_CONFIG") or DEFAULT_CONFIG_PATH)
CONFIG: Dict = {}

def get_blocked_domains():
    defaults = ["gfycat.com", "thumbs.gfycat.com"]
    return CONFIG.get("blocked_domains", defaults)

def load_config() -> None:
    global CONFIG
    try:
        with open(CONFIG_PATH, "r") as f:
            CONFIG = yaml.safe_load(f) or {}
        log.info("Loaded reddit_meme config from %s: %r", CONFIG_PATH, CONFIG)
    except Exception as e:
        log.warning("Failed to load config %s: %s", CONFIG_PATH, e)
        CONFIG = {}


class _ConfigHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if Path(event.src_path) == CONFIG_PATH:
            log.info("Config file changed, reloading...")
            load_config()


observer: Optional[Observer] = None

def start_observer() -> None:
    global observer
    if observer is not None:
        return
    observer = Observer()
    observer.schedule(_ConfigHandler(), path=str(CONFIG_PATH.parent), recursive=False)
    observer.daemon = True
    observer.start()


def stop_observer() -> None:
    global observer
    if observer is not None:
        observer.stop()
        observer = None


# Initial load on import
load_config()
