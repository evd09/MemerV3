# Changelog

## Version 3.8.0 (Storage Management & Security Fix) - 2026-02-05

**💾 Storage Management Tool:**
- **Manual Cleanup Dashboard**: New admin panel for managing disk space
  - **Storage Stats**: Real-time overview of total/original/converted file sizes
  - **Cleanup Candidates**: Lists files with both original and converted versions (mp3→opus, png→webp)
  - **Selective Deletion**: Checkbox selection for files to delete
  - **Bulk Actions**: Select All, Deselect All, and Delete Selected buttons
  - **Safety Features**: Confirmation dialogs, error handling, and logging
  - **Potential Savings**: Shows how much space can be reclaimed
- **Smart File Detection**:
  - Identifies audio files (`.mp3`, `.wav`, `.m4a`) with `.opus` versions
  - Identifies images (`.png`, `.jpg`, `.jpeg`, `.gif`) with `_thumb.webp` versions
  - Sorts by file size (biggest files first)
- **API Endpoints**:
  - `GET /api/admin/storage/stats` - Disk usage statistics
  - `GET /api/admin/storage/cleanup-candidates` - List files that can be deleted
  - `POST /api/admin/storage/delete-originals` - Delete selected original files

**🔒 Security Fix (Critical):**
- **Blocklist JavaScript Number Precision Bug**: Fixed Discord ID corruption when blocking/unblocking users
  - **Root Cause**: JavaScript's 53-bit number precision couldn't handle 64-bit Discord Snowflake IDs
  - **Symptoms**: User IDs like `499388705002487818` were truncated to `499388705002487800`
  - **Fix**: Backend API now returns user IDs as strings instead of integers
  - **Impact**: Blocklist unblock functionality now works correctly

**⚙️ Technical:**
- Backend returns `user_id` as string in `GET /api/admin/blocklist` to prevent precision loss
- Storage management endpoints are bot-owner-only with security path validation
- All file deletions are logged with user ID and file size

---

## Version 3.7.4 (Database Migration & Analytics Fix) - 2026-02-04

**🗄️ JSON to Database Migration:**
- **Guild Subreddits**: Migrated from `guild_subreddits.json` to `guild_subreddits` database table.
- **Sound Play Stats**: Migrated from `sound_stats.json` to `sounds.play_count` column.
- **User Favorites**: Migrated from `user_settings.json` to `user_favorites` database table.
- **Auto-Init**: New guilds automatically get default subreddits when bot joins.
- **Migration Script**: Added `migrate_json_to_db_v3_7_1.py` to safely migrate existing data.

**📊 Analytics Fixes:**
- **Entrance Analytics**: Fixed "Total Entrances Configured" showing 0 - now queries `user_entrance_v2` table correctly.
- **Type Distribution**: Added real entrance type breakdown (Single, Random, Combo, Scheduled).

**🎨 UX Improvements:**
- **Admin Panel**: Changed "MULTIPLE" label to "RANDOM" for better clarity.
- **Schedule Rules**: Added validation warning - rules require at least one day and sound selected.
- **Combo Sequences**: Fixed cooldown blocking - all sounds now play in sequence.

**⚙️ Technical:**
- Database-backed subreddit management with async functions.
- Added `tags TEXT` column to `sounds` table for future metadata.
- Removed dependency on JSON file writes for runtime data.
- Kept `fallback_memes/*.json` as static emergency cache.

**🗑️ JSON File Cleanup:**
- **entrance_sounds.json**: No longer auto-created on startup. All entrance data now lives in database.
- **guild_subreddits.json**: Migrated to database - file can be safely removed after migration.
- **sound_stats.json**: Play counts now stored in `sounds.play_count` column.
- **user_settings.json**: User favorites now stored in `user_favorites` table - file can be removed.
- Legacy `save_data()` and `reload_cache()` methods preserved for backwards compatibility but are no-ops.

---

## Version 3.5.1 (Admin Polish) - 2026-02-03

**✨ Admin Page Refinements:**
- **Deduplicated Sound Selector**: Now correctly merges `.mp3` and `.opus` formats, preferring the higher quality `.opus` version.
- **Friendly Names**: 
    - Replaced raw filenames with **Display Names** (e.g., "Six-Nine") in the sound selector.
    - Updated **Analytics Dashboard** and **Current Entrances** table to show friendly names.
- **Improved Analytics**: Aggregates statistics for sound variants (mp3/opus), ensuring accurate play counts.

---

## Version 3.5.0 (Admin Power & Analytics) - 2026-02-03

**🛠️ Admin Dashboard 2.0:**
- **Activity Logging**: Full audit trail of admin actions (entrance changes, subreddit edits) powered by a new SQLite log table.
- **Entrance Analytics**: 
    - Real-time dashboard showing **Most Popular Sounds** and **Adoption Rates**.
    - Tracks play counts and unique users for every entrance sound.
- **Entrance Overview**: 
    - Searchable table displaying ALL users' configurations.
    - **Quick Actions**: Remove entrances or preview sounds directly from the list.
- **Preview Button**: Admins can now **Pre-listen** to any entrance sound in their voice channel before assigning it.
- **Dynamic Updates**: Subreddit changes (add/remove) happen instantly without page reloads (AJAX + Toasts).

**⚙️ Technical Upgrades:**
- Updated **Ticker** version to V3.5.0 in all assets.
- Fixed data persistence bug where admin-set entrances were ignored by the new V3.4 system.

---

## Version 3.4.0 (The "Entrance Revolution") - 2026-02-03

**🎵 Complete Profile Overhaul:**
- **4 Entrance Modes**:
    - **Single**: Classic one-sound entrance.
    - **Random Pool**: Select multiple sounds; bot picks one at random on join.
    - **Combo Sequence**: Queue multiple sounds to play in order with custom delays.
    - **Scheduled**: Set different sounds for specific days/hours (e.g., "Friday Party Mode").
- **Visual Redesign**: 
    - Glassmorphism UI with smooth tab switching.
    - Live volume sliders and loading states.
    - Admin Override warning banner.

**🤖 Bot Logic:**
- **Smart Selection**: Audio engine now supports complex selection logic for all new modes.
- **Data Migration**: Automatically migrates lagacy V3.3 data to the new V3.4 schema on startup.

---

## Version 3.3.1 (Performance Optimizations) - 2026-02-03

**⚡ JavaScript Minification:**
- **Production Build Pipeline**: Automated minification with Terser
    - `app.min.js`: **34.9% smaller** (39KB → 26KB)
    - `sw.min.js`: **53.5% smaller** (4.3KB → 2.0KB)
- **Dockerfile Integration**: Build step runs automatically during Docker build
- **Faster Page Loads**: Reduced JavaScript bundle improves initial page load time

**📦 Build Tools:**
- Added `scripts/build.sh` for asset minification
- Node.js + Terser integrated into Docker image
- Automatic minification during production builds

---

## Version 3.3.0 (Waveforms & Long-Press) - 2026-02-03

**🎵 Pre-Generated Waveform Images:**
- **Server-Side Generation**: PNG waveforms created at upload time
    - Uses `soundfile` + `Pillow` for high-quality 200x60px images
    - **99% bandwidth savings** vs old client-side system (20MB → 200KB)
    - Average waveform size: **0.7 KB**
- **Always Visible**: Waveforms appear on every sound card
- **Offline Support**: Waveforms cached by service worker
- **Migration Tool**: `scripts/generate_waveforms.py` for existing sounds

**📱 Touch-Optimized Interaction:**
- **Hybrid Controls**: Different UX for mobile and desktop
    - **Mobile/PWA**: Long-press (500ms) triggers bottom sheet menu
    - **Desktop**: Right-click opens context menu
- **Clean UI**: Removed edit button clutter from cards
- **Menu Options**: Edit Sound, Add to Queue
- **Removed**: Delete option, drag-to-queue on mobile

**🐛 Bug Fixes:**
- Fixed favorite toggle not updating heart icon immediately
- Waveforms now display correctly on all devices
- Service worker updated to v3.3.0 with waveform caching

**⚙️ Technical Changes:**
- Added `soundfile` and `numpy` dependencies
- Updated service worker cache strategy for waveform PNGs
- Improved virtual scroller to handle favorite state changes

---

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
