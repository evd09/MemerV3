# 🐸 MemerV3 - The Ultimate Meme & Music Bot

**MemerV3** is a high-performance, containerized Discord bot built for memes, music, and community interaction. It features a robust **Web Dashboard**, **Entrance Sounds**, **VPN Support** (for bypassing restrictions), and smart caching for blazing fast meme delivery.

---

## ✨ Key Features
- **Meme Engine**: 
    - Fetches content from Reddit with smart fallback logic.
    - **Smart Caching**: RAM & Disk caching (Hot/New/Top) ensures instant replies.
    - **Video Support**: Intelligent handling of RedGifs, MP4s, and Reddit Galleries.
    - **VPN Integration**: Optionally route traffic through a VPN to bypass geographic blocks on NSFW content.
- **Media & Music**: 
    - High-quality audio player (YT-DLP based) with queue system.
    - **Entrance Sounds**: Personalized theme music when users join voice channels.
- **Web Portal**:
    - **Dashboard**: View meme statistics, top users, leaderboard, and top reactions.
    - **Entrance Manager**: Users can upload and manage their own entrance sounds.
    - **Audio Board**: Play sound clips directly from the web interface.
    - **Storage Management** (Bot Owner): Manual cleanup tool for reclaiming disk space by deleting original files after conversion.

---

## 🛠️ File Structure
```
MEMERv3/
├── 📁 config/              # Configuration files (cache, reddit)
├── 📁 data/                # Persistent data (DBs, json)
├── 📁 docker-compose.yml   # Standard deployment
├── 📁 docker-compose.vpn.yml # VPN-enabled deployment
├── 📁 gluetun/             # OpenVPN/Gluetun config storage
├── 📁 logs/                # Bot logs
├── 📁 memer/               # Source code
│   ├── 📁 cogs/            # Bot modules (meme, audio, web)
│   ├── 📁 helpers/         # Utilities (db, cache, reddit)
│   └── 📁 web/             # Flask/Quart web server templates
├── 📁 sounds/              # Audio clips storage
└── 📄 .env                 # Environment variables
```

---

## 📋 Commands

### 🎭 Meme Commands
| Command | Description |
| :--- | :--- |
| `/meme [keyword]` | Fetch a random SFW meme (optionally matching a keyword). |
| `/nsfwmeme [keyword]` | Fetch a random NSFW meme (requires NSFW channel). |
| `/r_ [subreddit] [keyword]` | Fetch a meme from a specific subreddit. |
| `/dashboard` | View the top users, subreddits, and keyword stats. |

### 🎵 Audio & Voice
| Command | Description |
| :--- | :--- |
| `/join` | Summon the bot to your voice channel. |
| `/leave` | Dismiss the bot. |
| `/play [query/url]` | Play audio from YouTube, SoundCloud, etc. |
| `/stop` | Stop playback and clear the queue. |
| `/skip` | Skip the current track. |
| `/queue` | Display the current song queue. |
| `/entrance` | Check your current entrance sound. |
| `/beep` | Test sound playback instantly. |

---

## ⚙️ Installation & Setup
1. **Create required directories** (to avoid permission issues):
   ```bash
   mkdir -p data sounds logs config
   ```

2. **Configuration (.env)**
   Create a `.env` file in the root directory with the following settings:
   *(See `.env.exp` for a template)*

```ini
# --- Discord Bot ---
DISCORD_TOKEN=your_bot_token_here
LOG_LEVEL=INFO

# --- Reddit API (Required for Memes) ---
# Create an app at https://www.reddit.com/prefs/apps
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_secret

# --- Web Dashboard (OAuth2) ---
# Discord Developer Portal -> OAuth2 -> Redirects
# Redirect URI should be: http://<YOUR_IP>:3000/callback
DISCORD_CLIENT_ID=your_app_id
DISCORD_CLIENT_SECRET=your_app_secret
DISCORD_REDIRECT_URI=http://<YOUR_IP>:3000/callback

# --- Security ---
# Random string for web session encryption
SECRET_KEY=random_super_secret_string
# Required if using a reverse proxy (Cloudflare/Nginx) to terminate HTTPS
OAUTHLIB_INSECURE_TRANSPORT=1

# --- VPN Settings (Optional) ---
# Used if running docker-compose.vpn.yml
VPN_PROVIDER=protonvpn    # or mullvad, surfshark, etc.
VPN_USER=your_openvpn_user
VPN_PASSWORD=your_openvpn_password
VPN_COUNTRY=United States
```

---

## 🚀 Deployment

Since the `docker-compose` files are not included in the repo, create them manually based on your needs.

### Option A: Standard (No VPN)
Create a `docker-compose.yml` file:
```yaml
services:
  MemerV3:
    image: ghcr.io/evd09/memerv3:latest
    container_name: MemerV3
    env_file: .env
    restart: unless-stopped
    volumes:
      - .:/app
      - ./data:/app/data
      - ./sounds:/app/sounds
      - ./logs:/app/logs
    ports:
      - "${WEB_PORT:-3000}:3000"
```
Run with:
```bash
docker compose up -d
```

### Option B: VPN Mode (Bypass Blocks)
Create a `docker-compose.vpn.yml` file:
```yaml
services:
  vpn:
    image: qmcgaw/gluetun
    container_name: vpn
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    ports:
      - "3000:3000" # Web UI port moves here
    volumes:
      - ./gluetun:/gluetun
    environment:
      # GENERIC CONFIGURATION
      - VPN_SERVICE_PROVIDER=${VPN_PROVIDER}
      - OPENVPN_USER=${VPN_USER}
      - OPENVPN_PASSWORD=${VPN_PASSWORD}
      - SERVER_COUNTRIES=${VPN_COUNTRY:-Netherlands}
      # DNS CONFIGURATION
      - DOT=off
      - DNS_ADDRESS=1.1.1.1
    restart: always

  MemerV3:
    image: ghcr.io/evd09/memerv3:latest
    container_name: MemerV3
    env_file: .env
    restart: unless-stopped
    network_mode: service:vpn  # Routes traffic through VPN
    depends_on:
      vpn:
        condition: service_healthy
    volumes:
      - ./data:/app/data
      - ./sounds:/app/sounds
      - ./logs:/app/logs
    # Note: 'ports' are removed here because they serve via the 'vpn' service above.
```
Run with:
```bash
docker compose -f docker-compose.vpn.yml up -d
```

---

## 🌐 Exposing the Web Portal

To access the dashboard (`http://localhost:3000`) from outside your home network, you have two securely recommended options:

### Method 1: Cloudflare Tunnel (Recommended)
This method is secure, requires no port forwarding, and gives you a nice `https://bot.yourdomain.com` URL.

1.  Install `cloudflared` on your host machine.
2.  Login: `cloudflared tunnel login`.
3.  Create a tunnel: `cloudflared tunnel create memebot`.
4.  Route the DNS: `cloudflared tunnel route dns memebot bot.yourdomain.com`.
5.  Run the tunnel:
    ```bash
    cloudflared tunnel run --url http://localhost:3000 memebot
    ```

### Method 2: Router Port Forwarding
1.  Log into your router (usually `192.168.1.1` or `192.168.0.1`).
2.  Find **Port Forwarding**.
3.  Add rule: External Port `3000` -> Internal IP (of this server) Port `3000`.
4.  Access via: `http://<YOUR_PUBLIC_IP>:3000`.
    *   *Warning: This exposes the port directly to the internet.*

---

## 🛠️ Development

### Building Assets (V3.3.1+)
For production deployments, JavaScript assets are automatically minified during Docker build.

**Manual Build** (for testing):
```bash
# Inside container
docker compose exec MemerV3 ./scripts/build.sh

# Or locally with Node.js installed
./scripts/build.sh
```

This creates:
- `memer/cogs/web/static/js/app.min.js` (-35% size)
- `memer/cogs/web/static/sw.min.js` (-54% size)

### Generating Waveforms
After initial deployment or when adding sounds manually, generate waveform images:

```bash
docker compose exec MemerV3 python scripts/generate_waveforms.py
```

**What it does**:
- Scans all audio files in `/app/sounds`
- Generates 200x60px PNG waveforms (~0.7 KB each)
- Skips existing waveforms
- Shows progress and size statistics

**Expected output**:
```
Found 92 audio files
[1/92] ✓ Generated: sound.mp3 → 0.7 KB
...
✅ Waveform generation complete!
Total new waveforms: 31.24 KB
```

### Managing Storage (V3.8.0+)
The bot automatically converts uploaded files to optimized formats (opus for audio, webp for images). The **Storage Management Tool** helps you reclaim disk space by safely deleting original files.

**Access via Web Dashboard** (Bot Owner Only):
1. Navigate to **Admin Dashboard** (`http://localhost:3000/admin`)
2. Scroll to **💾 Storage Management** section
3. Click **🔄 Refresh** to scan for cleanup candidates

**What it shows**:
- **Total Storage**: Complete disk usage breakdown
- **Original Files**: Size of uncompressed files (mp3, wav, png, jpg)
- **Converted Files**: Size of optimized files (opus, webp)
- **Cleanup Candidates**: List of files with both versions

**Cleanup Process**:
1. Review the list of files (sorted by size, biggest first)
2. Select files to delete using checkboxes (or "Select All")
3. Click **🗑️ Delete Selected Originals**
4. Confirm deletion (action is permanent)

**Example Savings**:
```
sound.mp3 (5.2 MB) → sound.opus (1.1 MB) = 4.1 MB saved
image.png (2.8 MB) → image_thumb.webp (0.3 MB) = 2.5 MB saved
```

**Safety Features**:
- Converted files are verified to exist before deletion
- All deletions are logged with timestamp and user ID
- Confirmation dialog prevents accidental deletions
- Path validation prevents directory traversal attacks

### Common Development Tasks
- **View Logs**: `docker compose logs -f MemerV3`
- **Restart**: `docker compose restart MemerV3`
- **Update & Rebuild**: 
  ```bash
  git pull
  docker compose build
  docker compose up -d
  docker compose exec MemerV3 python scripts/generate_waveforms.py  # If new sounds added
  ```
- **Hard Refresh Web UI**: Clear browser cache or use Ctrl+Shift+R

### Upgrading from V3.6 or Earlier (V3.7+)
If upgrading from an older version, run the migration scripts to move JSON data to the database:

```bash
# Migrate entrance sounds to database (V3.6.2+)
docker compose exec MemerV3 python scripts/migrate_entrances_v3_6_2.py

# Migrate guild subreddits and sound stats (V3.7.1+)
docker compose exec MemerV3 python scripts/migrate_json_to_db_v3_7_1.py
```

**After migration**:
- JSON files in `data/` are no longer auto-created on startup
- All entrance, subreddit, and play count data now lives in `data/memer.db`
- Old JSON files can be safely removed after verifying migration success

---

## 🚀 Performance Features (V3.3.0+)

### Waveform Visualization
- **Pre-generated PNG waveforms** for all audio files
- **99% bandwidth savings** compared to client-side generation
- Automatic generation on upload
- Cached by service worker for offline access

### Mobile/Touch Optimizations
- **Long-press** (500ms) on mobile to open context menu
- **Right-click** on desktop for same menu
- Touch-friendly bottom sheet design
- Smooth animations with haptic feedback

### Asset Optimization
- **Minified JavaScript**: 35-54% smaller bundles
- **Service Worker Caching**: Instant repeat loads
- **Virtual Scrolling**: 60 FPS with thousands of sounds
- **WebP Thumbnails**: 70% smaller than PNG

---

## 📊 Performance Metrics

| Metric | Before V3.3 | After V3.3.1 | Improvement |
|--------|-------------|--------------|-------------|
| JavaScript Bundle | 43 KB | 28 KB | **35%** |
| Waveforms (100 sounds) | 20 MB | 200 KB | **99%** |
| Scroll FPS | 15-30 | 60 | **100%** |
| Offline Support | ❌ | ✅ | Full |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

## 📜 License

See [LICENSE](LICENSE) for details.

---

## 🙏 Credits

Built with ❤️ using:
- [discord.py](https://github.com/Rapptz/discord.py)
- [Quart](https://github.com/pallets/quart)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Pillow](https://python-pillow.org/)
- [soundfile](https://github.com/bastibe/python-soundfile)
