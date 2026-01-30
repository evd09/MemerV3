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

## 🚀 deployment

### Option A: Standard (No VPN)
Best for general use if your server IP is not blocked by Reddit/RedGifs.
```bash
docker compose up -d --build
```
The bot will listen on port `3000` for the web interface.

### Option B: VPN Mode (Bypass Blocks)
Routes all bot traffic through a secure VPN container (Gluetun). Features auto-healing and strict firewall.
**Note:** You must configure `VPN_*` variables in `.env` first.

```bash
docker compose -f docker-compose.vpn.yml up -d --build
```

**Troubleshooting VPN:**
- If the bot fails to connect, ensure your `VPN_USER` and `VPN_PASSWORD` are correct (OpenVPN credentials often differ from account login!).
- The container waits for the VPN to be "Healthy" before starting the bot.

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
- **Logs**: `docker compose logs -f MemerV2`
- **Restart**: `docker compose restart MemerV2`
- **Update**: `git pull && docker compose build && docker compose up -d`
