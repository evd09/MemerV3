import os
import asyncio
from pathlib import Path
from quart import Quart, render_template, request, redirect, url_for, jsonify, send_from_directory, websocket, session
from quart_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
from hypercorn.asyncio import serve
from hypercorn.config import Config
import datetime
import discord
from discord.ext import commands
import logging
from memer.utils.logger_setup import setup_logger

logger = setup_logger("webbox", "webbox.log")

import json
import uuid
from memer.config import SOUND_FOLDER, AUDIO_EXTS, USER_SETTINGS_FILE, TICKER_SPEED, STATS_FILE
from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.helpers.guild_subreddits import (
    get_guild_subreddits,
    add_guild_subreddit,
    remove_guild_subreddit,
    persist_cache
)
from memer.helpers import db
from memer.meme_stats import get_dashboard_stats, get_top_reacted_memes

# Define the template folder explicitly
TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__)) + "/web/templates"

# Helpers
def sanitize_filename(name):
    # Keep only alphanumeric and . _ -
    return "".join(c for c in name if c.isalnum() or c in "._-").strip()

# --- Stats Helpers ---
# moved to config




class WebBox(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        static_dir = os.path.join(os.path.dirname(TEMPLATE_DIR), "static")
        self.app = Quart(__name__, template_folder=TEMPLATE_DIR, static_folder=static_dir, static_url_path='/static')
        self.app.secret_key = os.getenv("SECRET_KEY", "super_secret_meme_key")
        
        # Security Config
        self.app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB Limit
        self.app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)
        
        # Configure Discord OAuth
        self.app.config["DISCORD_CLIENT_ID"] = os.getenv("DISCORD_CLIENT_ID", "")
        self.app.config["DISCORD_CLIENT_SECRET"] = os.getenv("DISCORD_CLIENT_SECRET", "")
        self.app.config["DISCORD_REDIRECT_URI"] = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:3000/callback")
        self.app.config["DISCORD_BOT_TOKEN"] = os.getenv("DISCORD_TOKEN", "")
        
        self.discord_oauth = DiscordOAuth2Session(self.app)
        
        # Setup middleware (cache headers, compression)
        self._setup_middleware()
        
        # Define Routes
        self.setup_routes()
        
        # Start Server
        self.server_task = None
        
        # Store clients as {websocket: user_id}
        self.ws_clients = {}

        # Caches (V3.7.4: user_settings and sound_stats moved to database)

        


    async def _generate_thumbnail(self, original_path):
        """Generate WebP thumbnail for image at 300x300px with quality 85"""
        try:
            from PIL import Image
            
            p = Path(original_path)
            # Create WebP thumbnail: name_thumb.webp
            thumb_path = p.with_name(f"{p.stem}_thumb.webp")
            
            # Run in thread pool to avoid blocking
            def generate():
                img = Image.open(original_path)
                
                # Convert RGBA to RGB if needed (WebP doesn't support transparency well)
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                
                # Resize maintaining aspect ratio, max 300x300
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                # Save as WebP with quality 85
                img.save(thumb_path, 'WebP', quality=85, method=6)
                logger.info(f"Generated thumbnail: {thumb_path}")
            
            # Run in executor to avoid blocking event loop
            await asyncio.get_event_loop().run_in_executor(None, generate)
            
        except Exception as e:
            logger.error(f"Thumbnail generation failed for {original_path}: {e}")

    async def _generate_waveform_image(self, audio_path):
        """Generate static waveform PNG from audio file (200x60px, 2-5KB)"""
        try:
            from PIL import Image, ImageDraw
            import soundfile as sf
            import numpy as np
            
            def generate():
                # Read audio file
                data, samplerate = sf.read(audio_path)
                
                # Convert stereo to mono
                if len(data.shape) > 1:
                    data = data.mean(axis=1)
                
                # Waveform dimensions
                width, height = 200, 60
                samples = width
                
                # Downsample audio data
                chunk_size = max(1, len(data) // samples)
                
                waveform = []
                for i in range(samples):
                    start = i * chunk_size
                    end = min(start + chunk_size, len(data))
                    chunk = data[start:end]
                    
                    if len(chunk) > 0:
                        min_val = float(chunk.min())
                        max_val = float(chunk.max())
                        waveform.append((min_val, max_val))
                    else:
                        waveform.append((0.0, 0.0))
                
                # Create image with transparency
                img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                
                #Draw waveform bars
                for i, (min_val, max_val) in enumerate(waveform):
                    # Normalize to image height
                    y_min = int((1 + min_val) * height / 2)
                    y_max = int((1 + max_val) * height / 2)
                    
                    # Clamp values
                    y_min = max(0, min(height - 1, y_min))
                    y_max = max(0, min(height - 1, y_max))
                    
                    # Draw vertical line (white with alpha)
                    if y_max > y_min:
                        draw.line([(i, y_min), (i, y_max)], 
                                 fill=(255, 255, 255, 180), width=1)
                    else:
                        # Draw at least 1 pixel for silence
                        draw.point((i, height // 2), fill=(255, 255, 255, 120))
                
                # Save as optimized PNG
                wave_path = Path(audio_path).with_name(f"{Path(audio_path).stem}_wave.png")
                img.save(wave_path, 'PNG', optimize=True)
                logger.info(f"Generated waveform: {wave_path}")
            
            # Run in executor
            await asyncio.get_event_loop().run_in_executor(None, generate)
            
        except Exception as e:
            logger.error(f"Waveform generation failed for {audio_path}: {e}")

    def _load_json_sync(self, path):
        if not os.path.exists(path): return {}
        try:
            with open(path, 'r') as f: return json.load(f)
        except: return {}

    async def _save_json_async(self, path, data):
        def write():
            # Write to temp then rename for atomicity
            tmp = path + ".tmp"
            dir_name = os.path.dirname(path)
            if dir_name: os.makedirs(dir_name, exist_ok=True)
            with open(tmp, 'w') as f: json.dump(data, f, indent=4)
            os.replace(tmp, path)
        try:
            await asyncio.to_thread(write)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")

    def _save_json_sync(self, path, data):
        # Generic sync save method
        try:
            with open(path, 'w') as f: json.dump(data, f, indent=4)
        except: pass
    


    def _setup_middleware(self):
        """Setup compression and cache headers"""
        
        @self.app.after_request
        async def add_cache_headers(response):
            """Add strategic cache headers for different resource types"""
            path = request.path
            
            # Versioned assets & thumbnails: Cache for 1 year (immutable)
            if '?v=' in path or '_thumb.webp' in path:
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            
            # Images (non-versioned): Cache for 1 day
            elif any(path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                response.headers['Cache-Control'] = 'public, max-age=86400'
            
            # Static assets with versioning: 1 year cache
            elif path.startswith('/static/') and '?v=' in path:
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            
            # API & HTML: No cache (always fresh)
            elif path.startswith('/api/') or path == '/' or path.endswith('.html'):
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
            
            # Add Vary header for proper caching with compression
            if 'Content-Encoding' in response.headers:
                response.headers['Vary'] = 'Accept-Encoding'
            
            return response



    def setup_routes(self):
        # --- Helpers ---
        @self.app.route("/manifest.json")
        async def manifest():
            return await send_from_directory(os.path.join(TEMPLATE_DIR, "../static"), "manifest.json")

        @self.app.route("/sw.js")
        async def service_worker():
            return await send_from_directory(os.path.join(TEMPLATE_DIR, "../static"), "sw.js")



        def sanitize_filename(filename):
            """Strict alphanumeric sanitization."""
            # Keep only alphanumeric, dashes, underscores, and dots
            clean = "".join(c for c in filename if c.isalnum() or c in "-_.")
            return clean

        @self.app.errorhandler(413)
        async def request_entity_too_large(error):
            return "File too large (Max 5MB)", 413

        @self.app.websocket("/ws")
        async def ws():
            # Authenticate via Session
            user_id = None
            try:
                # Read directly from session to avoid "Session modified during websocket" error
                # caused by fetch_user() potentially refreshing tokens.
                user_id = session.get("DISCORD_USER_ID")
            except:
                pass # Guest or unauth

            ws = websocket._get_current_object()
            self.ws_clients[ws] = user_id
            
            try:
                while True:
                    await websocket.receive()
            except asyncio.CancelledError:
                pass
            finally:
                if ws in self.ws_clients:
                    del self.ws_clients[ws]


        @self.app.errorhandler(Unauthorized)
        async def redirect_unauthorized(e):
            return redirect(url_for("login"))



        # V3.7.4: load_user_settings/save_user_settings removed - favorites now in database
        # V3.7.4: load_sound_stats/save_sound_stats removed - play counts now in sounds.play_count column

        def load_sound_stats():
            """Legacy no-op - V3.7.4: play counts now stored in database."""
            return {}

        def save_sound_stats(data):
            """Legacy no-op - V3.7.4: play counts now stored in database."""
            pass



        # --- Views ---
        @self.app.route("/sounds/<path:filename>")
        async def sound_static(filename):
            return await send_from_directory(SOUND_FOLDER, filename)

        @self.app.route("/")
        async def home():
            user = None
            try:
                user = await self.discord_oauth.fetch_user()
            except Unauthorized:
                pass


            stats = load_sound_stats()
            
            sounds = []
            files = sorted(Path(SOUND_FOLDER).iterdir(), key=lambda f: f.name.lower())
            
            # Pre-scan for images and waveforms
            # Map clean name -> full filename
            images = {}
            thumbs = {}
            waveforms = {}
            for f in files:
                if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
                    if "_thumb" in f.stem:
                        # Map base stem (remove _thumb) -> thumb filename
                        base = f.stem.replace("_thumb", "")
                        thumbs[base.lower()] = f.name
                    elif "_wave" in f.stem:
                        # Map base stem (remove _wave) -> waveform filename
                        base = f.stem.replace("_wave", "")
                        waveforms[base.lower()] = f.name
                    else:
                        images[f.stem.lower()] = f.name

            # Load User Favorites (V3.7.4: from database)
            user_favs = []
            if user:
                 user_favs = await db.get_user_favorites(user.id)

            # Fetch Sounds from DB (Global + Guilds)
            user_guilds_ids = []
            user_guilds_data = [] # For dropdown
            if user:
                 for g in self.bot.guilds:
                     if g.get_member(user.id):
                         user_guilds_ids.append(g.id)
                         icon_url = g.icon.url if g.icon else None
                         user_guilds_data.append({"id": str(g.id), "name": g.name, "icon": icon_url})
            
            raw_sounds = await db.get_sounds_for_user(user_guilds_ids)
            
            for s in raw_sounds:
                f_name = s["filename"]
                stem = Path(f_name).stem.lower()
                
                # Image/Thumb Resolution
                thumb_url = f"/sounds/{thumbs[stem]}" if stem in thumbs else None
                image_url = f"/sounds/{images[stem]}" if stem in images else None
                wave_url = f"/sounds/{waveforms[stem]}" if stem in waveforms else None
                
                # Parse tags from comma-separated string (V3.7.4: from database)
                tags_str = s.get("tags") or ""
                tags_list = [t.strip() for t in tags_str.split(",") if t.strip()]

                sounds.append({
                    "filename": f_name,
                    "display_name": s["display_name"],
                    "guild_id": str(s["guild_id"]) if s["guild_id"] is not None else None,
                    "is_global": s["guild_id"] is None,
                    "tags": tags_list,
                    "shortcut": s.get("shortcut") or "",
                    "is_favorite": f_name in user_favs,
                    "image_url": image_url,
                    "thumb_url": thumb_url,
                    "wave_url": wave_url,
                    "play_count": s.get("play_count", 0)
                })

            # Sort: Favorites first, then Alphabetical
            sounds.sort(key=lambda x: (not x['is_favorite'], x['display_name'].lower()))

            sounds_json = json.dumps(sounds)
            
            has_global_sounds = any(s['is_global'] for s in sounds)

            return await render_template("index.html", 
                user=user, 
                sounds=sounds, 
                sounds_json=sounds_json, 
                user_favs=user_favs, 
                bot=self.bot.user, 
                ticker_speed=TICKER_SPEED,
                user_guilds=user_guilds_data,
                has_global_sounds=has_global_sounds
            )
        @self.app.route("/stats")
        async def stats_page():
            guild_id = request.args.get("guild_id")
            
            # Fetch stats (global or guild specific)
            stats = await get_dashboard_stats(guild_id)
            
            # Resolve User IDs to Names
            # stats['user_counts'] is {id: count}
            resolved_users = {}
            for uid, count in stats.get("user_counts", {}).items():
                name = f"User {uid}"
                try:
                    # explicit int cast just in case
                    u = self.bot.get_user(int(uid))
                    if not u:
                        # try fetch? expensive if list is long. 
                        # For 'Top 100' maybe acceptable, but let's stick to cache first.
                        # If failed, maybe try fetching just top 5?
                        pass 
                    
                    if u: name = u.display_name
                    else: name = f"<@{uid}>" # Frontend might render this? No, it's canvas.
                except:
                    pass
                resolved_users[name] = count
            
            stats["user_counts"] = resolved_users
            
            # Get User's Guilds for Dropdown (if logged in)
            user_guilds = []
            current_guild_name = "Global"
            
            try:
                # Attempt to get user. If not logged in, we only show Global (or nothing).
                user = None
                if await self.discord_oauth.authorized:
                    try: 
                        user = await self.discord_oauth.fetch_user()
                    except: 
                        pass # Token invalid?

                for g in self.bot.guilds:
                    # Privacy: Only show guild if user is in it, OR if it's the requested guild (maybe?)
                    # No, strict privacy: Only show if user is Member.
                    
                    is_member = False
                    if user:
                        # get_member returns None if not found in chunked cache; fetch_member is async API call
                        # using get_member is safer for perf, assuming chunking. 
                        # IF intents are enabled.
                        mem = g.get_member(user.id)
                        if mem: is_member = True
                    
                    # If not logged in, we show NO guilds in dropdown (only Global).
                    if is_member:
                        user_guilds.append({"id": str(g.id), "name": g.name})
                        
                    if guild_id and str(g.id) == guild_id:
                        current_guild_name = g.name
            except Exception:
                pass

            # --- Fetch Top Memes (SFW vs NSFW) ---
            top_sfw = await get_top_reacted_memes(limit=5, guild_id=guild_id, nsfw_filter=False)
            top_nsfw = await get_top_reacted_memes(limit=5, guild_id=guild_id, nsfw_filter=True)
            
            # Helper to resolve extra data if needed (currently simple pass-through)
            top_sfw_resolved = []
            for msg_id, url, title, gid, cid, nsfw, reactions in top_sfw:
                top_sfw_resolved.append((msg_id, url, title, gid, cid, nsfw, reactions))
                
            top_nsfw_resolved = []
            for msg_id, url, title, gid, cid, nsfw, reactions in top_nsfw:
                top_nsfw_resolved.append((msg_id, url, title, gid, cid, nsfw, reactions))

            return await render_template(
                "stats.html", 
                stats=stats, 
                guilds=user_guilds, 
                current_guild_name=current_guild_name, 
                current_guild_id=guild_id,
                top_reactions_sfw=top_sfw_resolved,
                top_reactions_nsfw=top_nsfw_resolved
            )

        @self.app.route("/profile")
        @requires_authorization
        async def profile():
            user = await self.discord_oauth.fetch_user()

            # V3.6.1: Get user's guild IDs and Data for Selector
            user_guilds = []
            user_guild_ids = []
            for g in self.bot.guilds:
                if g.get_member(user.id):
                    user_guilds.append({
                        "id": str(g.id), 
                        "name": g.name, 
                        "icon": g.icon.url if g.icon else None
                    })
                    user_guild_ids.append(g.id)

            # V3.6.1: Get sounds from database filtered by user's guilds + global sounds
            available_sounds = await db.get_sounds_for_user(user_guild_ids)

            # Load user favorites (V3.7.4: from database)
            user_favs = await db.get_user_favorites(user.id)

            # Build list with display names from database
            sounds_list = []
            for sound in available_sounds:
                filename = sound['filename']
                display_name = sound['display_name']
                is_favorite = filename in user_favs
                sounds_list.append({
                    "filename": filename,
                    "display_name": display_name,
                    "is_favorite": is_favorite,
                    "guild_id": str(sound['guild_id']) if sound['guild_id'] else None,
                    "is_global": sound['guild_id'] is None
                })

            # Sort: favorites first (alphabetically), then non-favorites (alphabetically)
            sounds_list.sort(key=lambda s: (not s["is_favorite"], s["display_name"].lower()))

            return await render_template("profile.html", user=user, sounds=sounds_list, bot=self.bot.user, user_guilds=user_guilds)

        @self.app.route("/login")
        async def login():
            from quart import session
            # Enable insecure transport for local testing if not using HTTPS
            if "https" not in self.app.config["DISCORD_REDIRECT_URI"]:
                os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
                
            session.permanent = True
            return await self.discord_oauth.create_session(scope=["identify"])

        @self.app.route("/logout")
        async def logout():
            self.discord_oauth.revoke()
            return redirect(url_for("home"))

        @self.app.route("/callback")
        async def callback():
            try:
                await self.discord_oauth.callback()
            except Exception as e:
                self.bot.dispatch("error", e)
                return f"Callback Error: {e}", 500
            return redirect(url_for("home"))

        # --- API ---
        @self.app.route("/api/play/<filename>")
        @requires_authorization
        async def play_sound(filename):
            user_id = await self.discord_oauth.fetch_user()
            user_id = user_id.id

            
            # Find User in Voice
            target_vc = None
            user_member = None
            
            # Search all guilds to find where the user is connected
            for guild in self.bot.guilds:
                member = guild.get_member(user_id)
                if member and member.voice and member.voice.channel:
                    target_vc = member.voice.channel
                    user_member = member
                    break
            
            if not target_vc:
                return "You need to join a voice channel to play this sound!", 400

            # Security Check involved in path joining?
            # os.path.join handles directory traversal if sanitize is weak, 
            # but we should still be careful.
            clean_name = sanitize_filename(filename)
            if clean_name != filename:
                 return "Invalid filename", 400

            file_path = os.path.join(SOUND_FOLDER, clean_name)
            if not os.path.exists(file_path):
                return "File not found", 404

            # V3.6: Check Guild Permission
            sound_info = await db.get_sound_by_filename(clean_name)
            if sound_info and sound_info['guild_id']:
                if target_vc.guild.id != sound_info['guild_id']:
                    return "This sound is exclusive to another server!", 403

            # Queue Audio
            success = await queue_audio(
                target_vc,
                user_member,
                file_path,
                1.0,
                None, # No interaction context
                play_clip # The player function
            )
            
            if success:
                # Update Stats (V3.7.4: use database instead of JSON)
                await db.increment_sound_play_count(clean_name)

                # Notify Ticker (via WebSocket) if possible
                # We need to broadcast to all connected clients
                if self.ws_clients:
                    # V3.6.1: Get display name from database instead of JSON metadata
                    display_name = clean_name
                    play_count = 1
                    if sound_info:
                        if sound_info.get('display_name'):
                            display_name = sound_info['display_name']
                        play_count = (sound_info.get('play_count') or 0) + 1

                    msg = {
                        "type": "ticker_update",
                        "data": {
                            "filename": clean_name,
                            "play_count": play_count,
                            "message": f"Played: {display_name}"
                        }
                    }
                    # Simple broadcast loop
                    filtered_clients = [ws for ws in self.ws_clients.keys()]
                    for ws in filtered_clients:
                        try:
                            await ws.send(json.dumps(msg))
                        except:
                            pass

                return "Playing", 200
            else:
                return "Failed to queue", 500

        @self.app.route("/api/entrance", methods=["GET"])
        @requires_authorization
        async def get_entrance():
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
                
            data = entrance_cog.entrance_data.get(str(user.id), {})
            return jsonify({
                "file": data.get("file"),
                "volume": data.get("volume", 1.0)
            })

        @self.app.route("/api/entrance", methods=["POST"])
        @requires_authorization
        async def set_entrance():
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
            
            form = await request.form
            # Handle JSON or Form? Fetch uses JSON usually but let's support form for simplicity or JSON
            if not form:
                # Try JSON
                req_json = await request.json
                if req_json:
                    file_name = req_json.get("file")
                    volume = float(req_json.get("volume", 1.0))
                else:
                    return "No data", 400
            else:
                file_name = form.get("file")
                volume = float(form.get("volume", 1.0))
                
            if not file_name:
                # Remove entrance
                if str(user.id) in entrance_cog.entrance_data:
                    del entrance_cog.entrance_data[str(user.id)]
                    entrance_cog.save_data()
                return "Removed", 200

            # Validate file exists
            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return "File does not exist", 404
                
            # Cap volume
            volume = max(0.1, min(1.0, volume))
            
            entrance_cog.entrance_data[str(user.id)] = {
                "file": clean_name,
                "volume": volume
            }
            entrance_cog.save_data()
            return "Saved", 200

        # --- V3.4 Entrance API Endpoints ---
        
        @self.app.route("/api/entrance/config", methods=["GET"])
        @requires_authorization
        async def get_entrance_config():
            """Get full entrance configuration (V3.6.2 Per-Guild)."""
            user = await self.discord_oauth.fetch_user()
            guild_id = request.args.get("guild_id")

            if not guild_id:
                return jsonify({"error": "Missing guild_id"}), 400

            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503

            # Cog method is now async
            config = await entrance_cog.get_entrance_config(str(user.id), int(guild_id))

            # DEBUG: Log what we're returning
            print(f"[ENTRANCE CONFIG DEBUG] User: {user.id}, Guild: {guild_id}")
            print(f"[ENTRANCE CONFIG DEBUG] Returning config: {config}")

            return jsonify(config)
        
        @self.app.route("/api/entrance/single", methods=["POST"])
        @requires_authorization
        async def set_entrance_single():
            """Set single entrance sound (V3.6.2 Per-Guild)."""
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
            
            req = await request.json
            if not req:
                return "Invalid JSON", 400
            
            file_name = req.get("file")
            volume = float(req.get("volume", 1.0))
            guild_id = req.get("guild_id")
            
            if not guild_id:
                return "Missing guild_id", 400
            
            if not file_name:
                # If file is empty, treated as remove? Or strictly missing file error? 
                # Frontend usually sends file="" for remove or calls remove endpoint?
                # Let's assume remove if file is empty string
                from memer.helpers import db
                await db.delete_entrance_sound(user.id, int(guild_id))
                return "Removed", 200
            
            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return "File does not exist", 404
            
            # Cog method is now async
            await entrance_cog.set_entrance_single(str(user.id), int(guild_id), clean_name, max(0.1, min(1.0, volume)))
            return "Saved", 200
        
        @self.app.route("/api/entrance/multiple", methods=["POST"])
        @requires_authorization
        async def set_entrance_multiple():
            """Set multiple entrance sounds (V3.4)."""
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
            
            req = await request.json
            if not req:
                return "Invalid JSON", 400
            
            sounds = req.get("sounds", [])
            if not sounds or not isinstance(sounds, list):
                return "Invalid sounds list", 400
            
            # Validate all files exist
            validated_sounds = []
            for sound in sounds:
                file_name = sound.get("file")
                volume = sound.get("volume", 1.0)
                
                clean_name = sanitize_filename(file_name)
                if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                    return f"File not found: {file_name}", 404
                
                validated_sounds.append({
                    "file": clean_name,
                    "volume": max(0.1, min(1.0, volume))
                })
            
            
            raw_guild_id = req.get("guild_id")
            if not raw_guild_id:
                # Try args? Frontend usually sends in body for POST
                return "Missing guild_id", 400
            guild_id = int(raw_guild_id)

            await entrance_cog.set_entrance_multiple(str(user.id), guild_id, validated_sounds)
            return "Saved", 200
        
        @self.app.route("/api/entrance/combo", methods=["POST"])
        @requires_authorization
        async def set_entrance_combo():
            """Set combo sequence entrance (V3.4)."""
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
            
            req = await request.json
            if not req:
                return "Invalid JSON", 400
            
            sounds = req.get("sounds", [])
            if not sounds or not isinstance(sounds, list):
                return "Invalid sounds list", 400
            
            # Validate all files exist
            validated_sounds = []
            for sound in sounds:
                file_name = sound.get("file")
                volume = sound.get("volume", 1.0)
                delay = sound.get("delay", 0)
                
                clean_name = sanitize_filename(file_name)
                if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                    return f"File not found: {file_name}", 404
                
                validated_sounds.append({
                    "file": clean_name,
                    "volume": max(0.1, min(1.0, volume)),
                    "delay": max(0, min(10000, int(delay)))  # Max 10 seconds delay
                })
            
            
            raw_guild_id = req.get("guild_id")
            if not raw_guild_id: return "Missing guild_id", 400
            guild_id = int(raw_guild_id)

            await entrance_cog.set_entrance_combo(str(user.id), guild_id, validated_sounds)
            return "Saved", 200
        
        @self.app.route("/api/entrance/scheduled", methods=["POST"])
        @requires_authorization
        async def set_entrance_scheduled():
            """Set scheduled entrance sounds (V3.4)."""
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
            
            req = await request.json
            if not req:
                return "Invalid JSON", 400
            
            rules = req.get("rules", [])
            default = req.get("default", {})
            
            # Validate default
            if not default.get("file"):
                return "Default entrance required", 400
            
            default_clean = sanitize_filename(default["file"])
            if not os.path.exists(os.path.join(SOUND_FOLDER, default_clean)):
                return "Default file not found", 404
            
            validated_default = {
                "file": default_clean,
                "volume": max(0.1, min(1.0, default.get("volume", 1.0)))
            }
            
            # Validate rules
            validated_rules = []
            for rule in rules:
                file_name = rule.get("file")
                days = rule.get("days", [])
                hours = rule.get("hours", [0, 23])
                
                clean_name = sanitize_filename(file_name)
                if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                    return f"File not found: {file_name}", 404
                
                validated_rules.append({
                    "file": clean_name,
                    "volume": max(0.1, min(1.0, rule.get("volume", 1.0))),
                    "days": [int(d) for d in days if 0 <= int(d) <= 6],
                    "hours": [max(0, min(23, int(hours[0]))), max(0, min(23, int(hours[1])))]
                })
            
            
            config = {
                "default": validated_default,
                "rules": validated_rules
            }

            raw_guild_id = req.get("guild_id")
            if not raw_guild_id: return "Missing guild_id", 400
            guild_id = int(raw_guild_id)

            await entrance_cog.set_entrance_scheduled(str(user.id), guild_id, config)
            return "Saved", 200
        
        @self.app.route("/api/entrance/clear", methods=["DELETE"])
        @requires_authorization
        async def clear_entrance():
            """Clear entrance configuration for a specific guild (V3.7)."""
            user = await self.discord_oauth.fetch_user()
            guild_id = request.args.get("guild_id")

            if not guild_id:
                return "guild_id required", 400

            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503

            await entrance_cog.clear_entrance(str(user.id), int(guild_id))
            return "Cleared", 200
        
        @self.app.route("/api/entrance/admin-override", methods=["GET"])
        @requires_authorization
        async def check_admin_override():
            """Check if admin has overridden user's entrance (V3.4)."""
            user = await self.discord_oauth.fetch_user()
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return jsonify({"error": "Entrance system offline"}), 503
            
            override = entrance_cog.get_admin_override(str(user.id))
            return jsonify(override)


        @self.app.route("/api/upload", methods=["POST"])
        @requires_authorization
        async def upload_file():
            form = await request.form
            raw_guild_id = form.get("guild_id")
            logger.info(f"[UPLOAD DEBUG] Received raw_guild_id: {raw_guild_id!r} (type: {type(raw_guild_id).__name__})")
            guild_id = int(raw_guild_id) if raw_guild_id and raw_guild_id not in ("null", "global", "") else None
            logger.info(f"[UPLOAD DEBUG] Converted to guild_id: {guild_id!r} (type: {type(guild_id).__name__})")

            user = await self.discord_oauth.fetch_user()
            
            # Quota Check (Global limit for now, maybe per-guild later)
            # files_count = len(os.listdir(SOUND_FOLDER)) # Deprecated check logic?
            # if files_count >= 1000: ... 

            files = await request.files
            uploaded_files = files.getlist('file')
            if not uploaded_files:
                 return "No files found", 400

            saved_count = 0
            errors = []

            for file in uploaded_files:
                if file.filename == '': continue
                
                # Original name for Display Name
                original_clean_name = sanitize_filename(Path(file.filename).stem)
                ext = Path(file.filename).suffix.lower()
                
                if not allowed_file(file.filename):
                    errors.append(f"Invalid type: {file.filename}")
                    continue

                # Generate UUID
                file_uuid = str(uuid.uuid4())
                save_name = f"{file_uuid}{ext}"
                save_path = os.path.join(SOUND_FOLDER, save_name)
                
                await file.save(save_path)
                
                final_filename = save_name
                
                # Auto-Convert to Opus (if audio)
                if ext in {'.mp3', '.wav', '.m4a'}:
                    try:
                        target_name = f"{file_uuid}.opus"
                        target_path = os.path.join(SOUND_FOLDER, target_name)
                        
                        proc = await asyncio.create_subprocess_exec(
                            "ffmpeg", "-y", "-i", str(save_path),
                            "-c:a", "libopus", "-b:a", "96k",
                            "-ac", "2", "-v", "error", str(target_path),
                            stderr=asyncio.subprocess.PIPE
                        )
                        await proc.wait()
                        
                        # If successful, use opus as the entry
                        if os.path.exists(target_path):
                            final_filename = target_name
                            # Optional: Remove original? Keep simple for now.
                    except Exception as e:
                        logger.error(f"Conversion failed for {save_name}: {e}")

                # Insert into DB
                await db.add_sound(
                    file_uuid,
                    guild_id,
                    final_filename,
                    original_clean_name, # Display Name
                    user.id
                )
                saved_count += 1
                
                # Generate assets
                final_path = os.path.join(SOUND_FOLDER, final_filename)
                final_ext = Path(final_filename).suffix.lower()
                
                if final_ext in {'.png', '.jpg', '.jpeg', '.gif'}:
                     asyncio.create_task(self._generate_thumbnail(final_path))
                
                if final_ext in {'.mp3', '.wav', '.opus', '.m4a', '.ogg'}:
                     asyncio.create_task(self._generate_waveform_image(final_path))

            # Sync and Reload
            if saved_count > 0:

                
                entrance_cog = self.bot.get_cog("Entrance")
                if entrance_cog:
                    entrance_cog.reload_cache()

            if saved_count == 0 and errors:
                return f"Failed: {', '.join(errors)}", 400
            
            return f"Uploaded {saved_count} files.", 200

        def allowed_file(filename):
            return '.' in filename and \
                   filename.rsplit('.', 1)[1].lower() in {'mp3', 'wav', 'ogg', 'png', 'jpg', 'jpeg', 'gif'}

        @self.app.route("/api/sound/image", methods=["POST"])
        @requires_authorization
        async def upload_sound_image():
            # Validate form data
            files = await request.files
            form = await request.form
            
            uploaded_file = files.get('file')
            filename = form.get('filename')
            
            if not uploaded_file or not filename:
                return "Missing file or filename", 400
                
            clean_filename = sanitize_filename(filename)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_filename)):
                return "Target sound file not found", 404
                
            # Validate Image
            if not uploaded_file.filename:
                return "No selected file", 400
                
            ext = uploaded_file.filename.rsplit('.', 1)[1].lower() if '.' in uploaded_file.filename else ''
            if ext not in {'png', 'jpg', 'jpeg', 'gif'}:
                 return "Invalid image type (png, jpg, jpeg, gif only)", 400
            
            # Save Image with same stem as sound
            stem = Path(clean_filename).stem
            save_name = f"{stem}.{ext}"
            save_path = os.path.join(SOUND_FOLDER, save_name)
            
            # Remove existing images for this sound? 
            # (Optional cleanup to avoid multiple images for same sound)
            for e in {'png', 'jpg', 'jpeg', 'gif'}:
                p = os.path.join(SOUND_FOLDER, f"{stem}.{e}")
                if os.path.exists(p):
                    os.remove(p)
            
            await uploaded_file.save(save_path)
            
            # Generate Thumbnail
            asyncio.create_task(self._generate_thumbnail(save_path))
            
            return "Image uploaded", 200

        @self.app.route("/api/sound/rename", methods=["POST"])
        @requires_authorization
        async def rename_sound():
            user = await self.discord_oauth.fetch_user()

            req = await request.json
            if not req: return "Invalid JSON", 400

            filename = req.get("filename")
            new_name = req.get("new_name")
            tags = req.get("tags", [])  # Array of tags from frontend
            shortcut_key = req.get("shortcut_key", "")  # Single char

            if not filename or not new_name:
                return "Missing parameters", 400

            # DB Lookup (V3.6)
            sound = await db.get_sound_by_filename(filename)

            # Fallback checks
            if not sound:
                 clean_name = sanitize_filename(filename)
                 sound = await db.get_sound_by_filename(clean_name)

            if not sound:
                return "Sound not found in database", 404

            # Convert tags array to comma-separated string for DB
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags or "")
            shortcut = shortcut_key[:1].upper() if shortcut_key else None

            # Update (V3.7.4: now includes tags and shortcut)
            await db.update_sound(sound["id"], new_name.strip(), tags_str, shortcut)



            return "Renamed", 200

        @self.app.route("/api/sound/favorite", methods=["POST"])
        @requires_authorization
        async def toggle_favorite():
            user = await self.discord_oauth.fetch_user()
            req = await request.json
            filename = req.get("filename")

            if not filename: return "Missing filename", 400

            # V3.7.4: Use database instead of JSON
            action = await db.toggle_user_favorite(user.id, filename)

            return jsonify({"status": "success", "action": action})

        # --- Admin Routes ---
        # --- V3.5 Admin Endpoints ---

        @self.app.route("/api/admin/entrance/overview")
        @requires_authorization
        async def admin_get_entrance_overview():
            user = await self.discord_oauth.fetch_user()
            guild_id = request.args.get("guild_id")
            if not guild_id: return jsonify({"error": "Missing guild_id"}), 400
            
            guild = self.bot.get_guild(int(guild_id))
            if not guild: return jsonify({"error": "Guild not found"}), 404
            
            # Check Admin
            member = guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                return jsonify({"error": "Access Denied"}), 403
                
            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog: return jsonify({"error": "Entrance system offline"}), 503
            
            # Filter users in this guild with entrances
            from memer.helpers import db
            
            # Fetch all members to show everyone (or we could just show those with entrances)
            if not guild.chunked: await guild.chunk()
            
            # 1. Fetch all entrances for this guild in one query efficiently
            guild_entrances = await db.get_all_entrance_sounds_for_guild(int(guild_id))

            # 2. Fetch all proper sound names for this guild (plus globals) to resolve display names
            # Map filename -> display_name
            sound_list = await db.get_sounds_for_guild(int(guild_id))
            sound_map = {s['filename']: s['display_name'] for s in sound_list}
            
            results = []
            
            # iterate all members to match requirements of "All Users" filter in frontend
            for m in guild.members:
                uid_int = m.id
                
                # Check if this user has an entry
                entry = guild_entrances.get(uid_int)
                
                has_entrance = False
                file_info = "—"
                volume_info = 1.0
                ent_type = None

                if entry:
                    has_entrance = True
                    ent_type = entry.get('type', 'single')
                    
                    if ent_type == 'single':
                        fname = entry.get('filename')
                        if not fname:
                            # Fallback: Parse data if available
                            try:
                                import json
                                raw = entry.get('data')
                                if isinstance(raw, str):
                                    d = json.loads(raw)
                                    fname = d.get('file')
                                elif isinstance(raw, dict):
                                    fname = raw.get('file')
                            except:
                                pass
                        
                        if fname:
                             display_name = sound_map.get(fname, fname)
                             file_info = display_name
                             volume_info = entry.get('volume', 1.0)
                        else:
                             file_info = "(Error)"
                    
                    elif ent_type == 'multiple':
                        data = entry.get('data', [])
                        count = len(data) if isinstance(data, list) else 0
                        file_info = f"{count} files (Pool)"
                        volume_info = "Mixed"
                    
                    elif ent_type == 'combo':
                        data = entry.get('data', [])
                        count = len(data) if isinstance(data, list) else 0
                        file_info = f"{count} files (Sequence)"
                        volume_info = "Mixed"
                    
                    elif ent_type == 'scheduled':
                        file_info = "Scheduled Rules"
                        volume_info = "Variable"
                
                results.append({
                    "user_id": str(m.id),
                    "username": m.name,
                    "avatar": str(m.display_avatar.url) if m.display_avatar else None,
                    "entrance_type": ent_type if has_entrance else None,
                    "file": file_info if has_entrance else None,
                    "volume": volume_info if has_entrance else None
                })
                
            return jsonify(results)

        @self.app.route("/api/admin/entrance/preview", methods=["POST"])
        @requires_authorization
        async def admin_preview_entrance():
            user = await self.discord_oauth.fetch_user()
            req = await request.json
            if not req: return "Invalid JSON", 400
            
            file_name = req.get("file")
            volume = float(req.get("volume", 1.0))
            
            # Admin needs to be in a VC
            target_vc = None
            user_member = None
            for guild in self.bot.guilds:
                member = guild.get_member(user.id)
                if member and member.voice and member.voice.channel:
                    target_vc = member.voice.channel
                    user_member = member
                    break
            
            if not target_vc:
                return "You must be in a voice channel", 400
                
            clean_name = sanitize_filename(file_name)
            path = os.path.join(SOUND_FOLDER, clean_name)
            if not os.path.exists(path):
                return "File not found", 404
                
            await queue_audio(target_vc, user_member, path, max(0.1, min(1.0, volume)), None, play_clip)
            return "Playing", 200

        @self.app.route("/api/admin/analytics")
        @requires_authorization
        async def admin_get_analytics():
            user = await self.discord_oauth.fetch_user()
            guild_id = request.args.get("guild_id")
            days = int(request.args.get("days", 30))
            
            if not guild_id: return jsonify({"error": "Missing guild_id"}), 400
            
            guild = self.bot.get_guild(int(guild_id))
            if not guild: return jsonify({"error": "Guild not found"}), 404
            
             # Check Admin
            member = guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                return jsonify({"error": "Access Denied"}), 403

            analytics = await db.get_entrance_analytics(int(guild_id), days) or {}
            
            # Process and aggregate popular sounds (deduplicate mp3/opus)
            raw_popular = analytics.get("most_popular_sounds", [])
            meta = load_sound_meta()
            
            aggregated_stats = {}
            
            for row in raw_popular:
                filename = row["file"]
                stem = Path(filename).stem.lower() # Normalize to stem
                
                if stem not in aggregated_stats:
                    m = meta.get(filename, {})
                    display_name = m.get("name", filename)
                    
                    aggregated_stats[stem] = {
                        "file": filename, # Keep one valid filename for reference
                        "display_name": display_name,
                        "play_count": 0,
                        "unique_users": 0
                    }
                    
                aggregated_stats[stem]["play_count"] += row["play_count"]
                aggregated_stats[stem]["unique_users"] += row["unique_users"]

            # Convert to list and sort
            final_popular = sorted(
                list(aggregated_stats.values()), 
                key=lambda x: x["play_count"], 
                reverse=True
            )[:10]
            
            # V3.7: Get users with/without entrances from database
            users_with_entrance = analytics.get("users_with_entrance", set())
            total_set = len(users_with_entrance)

            # Calculate users without entrances
            users_without = []
            if not guild.chunked:
                await guild.chunk()

            for m in guild.members:
                if m.bot:
                    continue  # Skip bots
                if m.id not in users_with_entrance:
                    users_without.append({"user_id": str(m.id), "username": m.name})

            # Get entrance type distribution from database
            entrance_type_distribution = analytics.get("entrance_type_distribution", {})

            response = {
                "most_popular_sounds": final_popular,
                "users_without_entrances": users_without,
                "avg_volume": 1.0,
                "total_entrances_set": total_set,
                "entrance_type_distribution": entrance_type_distribution
            }
            return jsonify(response)
            
        @self.app.route("/api/admin/activity-log")
        @requires_authorization
        async def admin_get_activity_log():
            user = await self.discord_oauth.fetch_user()
            guild_id = request.args.get("guild_id")
            if not guild_id: return jsonify({"error": "Missing guild_id"}), 400
            
            limit = int(request.args.get("limit", 20))
            offset = int(request.args.get("offset", 0))
            action_type = request.args.get("action_type")
            if not action_type: action_type = None

            logs = await db.get_admin_activity_log(int(guild_id), limit, offset, action_type)
            return jsonify(logs)

        @self.app.route("/admin")
        @requires_authorization
        async def admin_dashboard():
            user = await self.discord_oauth.fetch_user()
            admin_guilds = []
            
            for guild in self.bot.guilds:
                member = guild.get_member(user.id)
                if member and member.guild_permissions.administrator:
                    admin_guilds.append({"id": str(guild.id), "name": guild.name})
            
            return await render_template("admin.html", guilds=admin_guilds, selected_guild=None, bot=self.bot.user)

        @self.app.route("/admin/<int:guild_id>")
        @requires_authorization
        async def admin_guild_view(guild_id):
            user = await self.discord_oauth.fetch_user()
            guild = self.bot.get_guild(guild_id)
            
            if not guild:
                return "Guild not found", 404
                
            member = guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                return "Access Denied: You are not an admin of this server.", 403
                
            # Fetch members for datalist
            if not guild.chunked:
                await guild.chunk()
            
            members = [{"id": str(m.id), "name": m.display_name} for m in guild.members]
            
            # Fetch Sounds from DB (Global + Guild)
            raw_sounds = await db.get_sounds_for_guild(guild_id)
            
            sounds = []
            for s in raw_sounds:
                sounds.append({
                    "filename": s["filename"],
                    "display_name": s["display_name"],
                    "guild_id": s["guild_id"],
                    "is_global": s["guild_id"] is None
                })
            
            # Fetch subreddits
            sfw_subs = await get_guild_subreddits(guild_id, "sfw")
            nsfw_subs = await get_guild_subreddits(guild_id, "nsfw")

            # Fetch Cache Info
            cache_stats = None
            meme_cog = self.bot.get_cog("Meme")
            if meme_cog:
                if hasattr(meme_cog, 'cache_service'):
                     cache_stats = await meme_cog.cache_service.get_cache_info()

            return await render_template(
                "admin.html", 
                guilds=[], 
                selected_guild={"id": str(guild.id), "name": guild.name}, 
                members=members,
                sounds=sounds,
                bot=self.bot.user,
                sfw_subs=sfw_subs,
                nsfw_subs=nsfw_subs,
                cache_stats=cache_stats
            )

        @self.app.route("/api/admin/entrance/<int:target_user_id>", methods=["DELETE"])
        @requires_authorization
        async def admin_delete_entrance(target_user_id):
            user = await self.discord_oauth.fetch_user()
            guild_id = int(request.args.get("guild_id") or 0)
            if not guild_id: return jsonify({"error": "Missing guild_id"}), 400
            
            guild = self.bot.get_guild(guild_id)
            if not guild: return jsonify({"error": "Guild not found"}), 404
            
            member = guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                return jsonify({"error": "Access Denied"}), 403

            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog: return jsonify({"error": "System offline"}), 503
            
            # Remove from DB (V3.6)
            from memer.helpers import db
            await db.delete_entrance_sound(target_user_id, guild_id)
                
            # Log action
            target_member = guild.get_member(target_user_id)
            target_name = target_member.name if target_member else f"User {target_user_id}"
            
            await db.log_admin_action(
                guild_id, user.id, user.username, "remove_entrance", 
                {}, target_user_id, target_name
            )
            return "Removed", 200
            
        @self.app.route("/api/admin/entrance", methods=["POST"])
        @requires_authorization
        async def admin_set_entrance():
            user = await self.discord_oauth.fetch_user()
            form = await request.form
            
            guild_id = int(form.get("guild_id"))
            target_user_id = int(form.get("user_id"))
            file_name = form.get("file")
            volume = float(form.get("volume", 1.0))

            guild = self.bot.get_guild(guild_id)
            if not guild: return "Guild not found", 404
            
            admin_member = guild.get_member(user.id)
            if not admin_member or not admin_member.guild_permissions.administrator:
                return "Access Denied", 403

            entrance_cog = self.bot.get_cog("Entrance")
            if not entrance_cog:
                return "Entrance system offline", 503

            target_member = guild.get_member(target_user_id)
            target_name = target_member.name if target_member else f"User {target_user_id}"

            if not file_name:
                # Remove
                from memer.helpers import db
                await db.delete_entrance_sound(target_user_id, guild_id)
                
                await db.log_admin_action(
                    guild_id, user.id, user.username, "remove_entrance", 
                    {}, target_user_id, target_name
                )
                return "Removed entrance", 200

            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return "File not found", 404

            # Save to DB (V3.6)
            from memer.helpers import db
            await db.set_entrance_sound(target_user_id, guild_id, clean_name, max(0.1, min(1.0, volume)))

            # Log
            await db.log_admin_action(
                guild_id, user.id, user.username, "set_entrance", 
                {"file": clean_name, "volume": volume}, target_user_id, target_name
            )
            
            return "Saved", 200

        @self.app.route("/api/admin/subreddit/add", methods=["POST"])
        @requires_authorization
        async def admin_add_subreddit():
            user = await self.discord_oauth.fetch_user()
            form = await request.form
            
            guild_id = int(form.get("guild_id"))
            subreddit_name = form.get("subreddit")
            sub_type = form.get("type") # sfw or nsfw

            if not subreddit_name or sub_type not in ["sfw", "nsfw"]:
                 return "Invalid parameters", 400

            guild = self.bot.get_guild(guild_id)
            if not guild: return "Guild not found", 404
            
            member = guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                return "Access Denied", 403

            meme_cog = self.bot.get_cog("Meme")
            if not meme_cog:
                 return "Meme system offline", 503

            # Validate Subreddit
            try:
                # Use the existing reddit instance from Meme cog
                sub = await meme_cog.reddit.subreddit(subreddit_name, fetch=True)
                
                # Check for NSFW compatibility
                if sub_type == "sfw" and sub.over18:
                     return "Cannot add NSFW subreddit to SFW list.", 400
                     
            except Exception as e:
                return f"Subreddit validation failed: {str(e)}", 400

            await add_guild_subreddit(guild_id, subreddit_name, sub_type)
            persist_cache()

            # Log action
            await db.log_admin_action(
                guild_id, user.id, user.username, "add_subreddit",
                {"subreddit": subreddit_name, "category": sub_type}
            )

            # Return JSON for dynamic update
            current_list = await get_guild_subreddits(guild_id, sub_type)
            return jsonify({
                "success": True, 
                "subreddit": subreddit_name,
                "updated_list": current_list
            })

        @self.app.route("/api/admin/subreddit/remove", methods=["POST"])
        @requires_authorization
        async def admin_remove_subreddit():
            user = await self.discord_oauth.fetch_user()
            form = await request.form
            
            guild_id = int(form.get("guild_id"))
            subreddit_name = form.get("subreddit")
            sub_type = form.get("type")

            guild = self.bot.get_guild(guild_id)
            if not guild: return "Guild not found", 404
            
            member = guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                return "Access Denied", 403

            await remove_guild_subreddit(guild_id, subreddit_name, sub_type)
            persist_cache()

            # Log action
            await db.log_admin_action(
                guild_id, user.id, user.username, "remove_subreddit",
                {"subreddit": subreddit_name, "category": sub_type}
            )

            # Return JSON
            current_list = await get_guild_subreddits(guild_id, sub_type)
            return jsonify({
                "success": True, 
                "subreddit": subreddit_name,
                "updated_list": current_list
            })
    
    async def broadcast_to_guild(self, guild_id, event_type, data):
        """Broadcasts only to users who are members of the given guild_id."""
        if not self.ws_clients: return
        
        msg = json.dumps({"type": event_type, "data": data})
        to_remove = []
        
        guild = self.bot.get_guild(guild_id)
        if not guild: return # Can't verify membership

        for ws, user_id in self.ws_clients.items():
            if not user_id: continue # Skip guests for guild events
            
            # Verify membership
            # We use get_member (cache) for performance. 
            # Ideally guild.chunk() should be called at startup or periodically.
            member = guild.get_member(user_id)
            
            if member:
                try:
                    await ws.send(msg)
                except:
                    to_remove.append(ws)

        for ws in to_remove:
            if ws in self.ws_clients:
                del self.ws_clients[ws]

    async def broadcast_public_message(self, event_type, data):
        """Broadcasts to ALL connected clients."""
        if not self.ws_clients: return
        msg = json.dumps({"type": event_type, "data": data})
        to_remove = []
        for ws in self.ws_clients:
            try:
                await ws.send(msg)
            except:
                to_remove.append(ws)
        for ws in to_remove:
            if ws in self.ws_clients:
                del self.ws_clients[ws]

    @commands.Cog.listener("on_sound_play")
    async def on_sound_play_event(self, filename, user_id=None, guild_id=None):
        # Stats Increment (V3.7.4: use database instead of JSON)
        try:
            await db.increment_sound_play_count(filename)
        except Exception as e:
            logger.error(f"Failed to update stats: {e}")

        user_name = "Unknown User"
        user_avatar = None
        guild_name = "Unknown Server"

        # V3.6.1: Get display name from database instead of JSON metadata cache
        display_name = filename
        sound_info = await db.get_sound_by_filename(filename)
        if sound_info and sound_info.get('display_name'):
            display_name = sound_info['display_name']

        if guild_id:
             if user_id:
                 guild = self.bot.get_guild(guild_id)
                 if guild:
                     guild_name = guild.name
                     member = guild.get_member(user_id)
                     if member:
                         user_name = member.display_name
                         user_avatar = str(member.display_avatar.url) if member.display_avatar else None

             # 1. Private Guild Event (for Glow/Toasts)
             await self.broadcast_to_guild(guild_id, "play_start", {
                 "filename": filename,
                 "user_id": user_id,
                 "user_name": user_name,
                 "user_avatar": user_avatar,
                 "guild_id": str(guild_id),  # Convert to string to prevent JavaScript precision loss
                 "display_name": display_name
             })
             
             # 2. Public Ticker Event (Global)
             await self.broadcast_public_message("ticker_update", {
                 "message": f"🔥 {user_name} played {display_name}",
                 "guild": guild_name,
                 "filename": filename,
                 "display_name": display_name
             })

    @commands.Cog.listener("on_sound_stop")
    async def on_sound_stop_event(self, guild_id):
        await self.broadcast_to_guild(guild_id, "play_end", {"guild_id": str(guild_id)})

    async def cog_load(self):
        # Run Hypercorn in background with HTTP/2 support
        config = Config()
        config.bind = ["0.0.0.0:3000"]
        
        # Enable HTTP/2 (h2) with HTTP/1.1 fallback
        config.alpn_protocols = ['h2', 'http/1.1']
        
        logger.info("Starting Hypercorn with HTTP/2 support on port 3000")
        self.server_task = self.bot.loop.create_task(serve(self.app, config))

    async def cog_unload(self):
        if self.server_task:
            self.server_task.cancel()

async def setup(bot: commands.Bot):
    await bot.add_cog(WebBox(bot))

