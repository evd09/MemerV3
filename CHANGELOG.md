# Changelog

# Version 3.1.1 (The "Web Interface Polish" Update) - 2026-02-02

**🌐 Web Interface Fixes:**
- **Static File Serving**: Fixed critical 404 errors preventing JavaScript from loading
    - Configured Quart `static_folder` parameter for proper file serving
    - Sound cards now render correctly on first page load
- **Sound Deduplication**: Eliminated duplicate sound cards when multiple formats exist
    - Automatically prefers `.opus` files over `.mp3` fallbacks
    - Provides cleaner, more organized sound library
- **Display Names**: Full sound names now visible on sound cards
    - Removed text truncation that cut off longer names
    - Names now wrap to multiple lines as needed
- **Live Ticker Enhancement**: Ticker now displays friendly sound names
    - Shows "chilidog sauce" instead of "chilidog-short.opus"
    - Improves readability for all users

**🎲 Enhanced /beeps Command:**
- **Rich Discord Embeds**: Beautiful embed messages with color-coded status
- **Display Names**: Shows friendly sound names instead of filenames
- **Thumbnail Support**: Displays sound artwork when available
- **Better UX**: Clear success/failure states with helpful tips

**🐛 Bug Fixes:**
- Fixed stats tracking error (`'WebBox' object has no attribute '_write_json_sync'`)
- Play counts now increment correctly without console errors
- Improved metadata loading reliability

**⚡ Performance:**
- Optimized sound loading with deduplication
- Reduced duplicate file processing

---

# Version 3.1.0 (The "Stats & Fixes" Update)

**📊 Per-Server Statistics:**
- **Guild-Specific Tracking**: Memer now tracks user interactions and top keywords separately for each server!
- **Dashboard Upgrade**: 
    - Added a **Server Selector** dropdown to switch between Global and Server-specific views.
    - **Global View**: Shows aggregated stats from all servers.
    - **Server View**: Shows stats exclusive to that community.

**🏆 Hall of Fame Updates:**
- **Privacy First**: The Hall of Fame is now **hidden** on the Global view to respect server privacy.
- **Server-Exclusive**: Select a specific server to view its unique Hall of Fame.
- **Direct Image Fixing**:
    - **New Admin Tool**: Added "Fix Broken Images 🖼️" button to `/memeadmin`.
        - Scans your entire meme history for broken links.
        - Automatically repairs them using cached data or by re-fetching from Reddit.
    - **Database Patch**: Retroactively updates old database entries to store direct image URLs, fixing 500 errors and broken previews.

**🐛 Bug Fixes:**
- Fixed a **500 Internal Server Error** when viewing the Hall of Fame caused by cross-database JOINs.
- Fixed "Command Not Found" crash in `memeadmin`.
- Improved image loading performance by using direct media URLs.

---

# Version 3.0.0 (The "MemerV3 Major Overhaul")

**🚀 The Cool Stuff:**
- **Web Dashboard 2.0**: 
    - **Admin Control**: Manage SFW/NSFW subreddits directly from the web—no more clunky commands!
    - **Live Stats**: Visualize cache hits, RAM/Disk usage, and see the **10 most recently cached keywords** in real-time.
    - **Entrance Manager**: Upload your own 5MB entrance themes, preview them, and set volume levels instantly.
    - **Secure Access**: Protected by Discord OAuth2; only admins can touch sensitive settings.

- **Infrastructure & Speed**:
    - **Smart Caching**: Hybid RAM + Disk caching system ensures memes load instantly while persisting across restarts.
    - **Docker Native**: Fully containerized with a `docker-compose` setup that supports hot-reloading for devs.
    - **VPN Integration**: Built-in support for **Gluetun** to route traffic through VPNs, bypassing ISP blocks on Reddit/RedGifs.
    - **Optimization**: Zero-copy ffmpeg audio processing for lag-free music and sound effects.

- **Quality of Life**:
    - **Global Entrance Sounds**: Your entrance theme now follows you across *any* server the bot is in.
    - **Cleaner Discord UI**: Moved complex config to the Web Dashboard, keeping chat clean.
    - **Resilient Audio**: Auto-recovery system for voice connection errors.

---

# Version 5.1 (Legacy) #

- `/entrance` UI now displays your current entrance and updates when changed.
- Removed standalone `/myentrance` command; resync global commands after updating.

# Version 5.0 #

- Removed standalone `/ping` and `/uptime` commands; their functionality now lives in the `/memeadmin` interface.
- After upgrading, resync your global commands so the changes take effect.
