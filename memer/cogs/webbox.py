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
from memer.config import SOUND_FOLDER, AUDIO_EXTS, SOUND_META_FILE, USER_SETTINGS_FILE, TICKER_SPEED, STATS_FILE
from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.helpers.guild_subreddits import (
    get_guild_subreddits,
    add_guild_subreddit,
    remove_guild_subreddit,
    persist_cache
)
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
        
        # Define Routes
        self.setup_routes()
        
        # Start Server
        self.server_task = None
        
        # Store clients as {websocket: user_id}
        self.ws_clients = {}
        
        # Caches
        self.meta_cache = self._load_json_sync(SOUND_META_FILE)
        self.stats_cache = self._load_json_sync(STATS_FILE)
        self.settings_cache = self._load_json_sync(USER_SETTINGS_FILE)
        
        # Run migration on meta_cache immediately
        if self._migrate_meta():
            self.save_sound_meta_internal(self.meta_cache)

    async def _generate_thumbnail(self, original_path):
        try:
            p = Path(original_path)
            # Create thumb filename: name_thumb.ext
            thumb_path = p.with_name(f"{p.stem}_thumb{p.suffix}")
            
            # Simple downscale to 200px width
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(p),
                "-vf", "scale=200:-1",
                "-v", "error", str(thumb_path),
                stderr=asyncio.subprocess.PIPE
            )
            await proc.wait()
        except Exception as e:
            logger.error(f"Thumbnail generation failed for {original_path}: {e}")

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
    
    def save_sound_meta_internal(self, data):
        # Sync save for init migration
        self._save_json_sync(SOUND_META_FILE, data)

    def _migrate_meta(self):
        migrated = False
        for k, v in self.meta_cache.items():
            if isinstance(v, str):
                self.meta_cache[k] = {"name": v, "tags": []}
                migrated = True
        return migrated

        


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

        def load_sound_meta():
            return self.meta_cache

        def save_sound_meta(data):
            self.meta_cache = data
            asyncio.create_task(self._save_json_async(SOUND_META_FILE, data))

        def load_user_settings():
            return self.settings_cache

        def save_user_settings(data):
            self.settings_cache = data
            asyncio.create_task(self._save_json_async(USER_SETTINGS_FILE, data))
            
        def load_sound_stats():
            return self.stats_cache
            
        def save_sound_stats(data):
            self.stats_cache = data
            asyncio.create_task(self._save_json_async(STATS_FILE, data))



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

            meta = load_sound_meta()
            stats = load_sound_stats()
            
            sounds = []
            files = sorted(Path(SOUND_FOLDER).iterdir(), key=lambda f: f.name.lower())
            
            # Pre-scan for images
            # Map clean name -> full filename
            images = {}
            thumbs = {}
            for f in files:
                if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif'}:
                    if "_thumb" in f.stem:
                        # Map base stem (remove _thumb) -> thumb filename
                        base = f.stem.replace("_thumb", "")
                        thumbs[base.lower()] = f.name
                    else:
                        images[f.stem.lower()] = f.name

            # Load User Favorites
            user_settings = load_user_settings()
            user_favs = []
            if user:
                 user_favs = user_settings.get(str(user.id), {}).get("favorites", [])

            # Deduplicate audio files - prefer .opus over .mp3
            audio_files = {}  # stem -> file path
            for f in files:
                if f.suffix.lower() in AUDIO_EXTS:
                    stem = f.stem.lower()
                    # If we haven't seen this stem, or current file is .opus and existing is not
                    if stem not in audio_files:
                        audio_files[stem] = f
                    elif f.suffix.lower() == '.opus' and audio_files[stem].suffix.lower() != '.opus':
                        # Prefer .opus over other formats
                        audio_files[stem] = f

            for stem, f in audio_files.items():
                # Meta Handling
                m = meta.get(f.name, {})
                display_name = m.get("name", f.name)
                tags = m.get("tags", [])
                
                # Logic: Prefer thumb if exists, else full image
                stem_lower = f.stem.lower()
                image_file = None
                
                if stem_lower in thumbs:
                    image_file = thumbs[stem_lower]
                elif stem_lower in images:
                    image_file = images[stem_lower]
                
                image_url = f"/sounds/{image_file}" if image_file else None
                
                sounds.append({
                    "filename": f.name,
                    "display_name": display_name,
                    "tags": tags,
                    "shortcut": m.get("shortcut"),
                    "is_favorite": f.name in user_favs,
                    "image_url": image_url,
                    "play_count": stats.get(f.name, 0)
                })
            
            # Sort: Favorites first, then Alphabetical
            sounds.sort(key=lambda x: (not x['is_favorite'], x['display_name'].lower()))

            sounds_json = json.dumps(sounds)

            return await render_template("index.html", user=user, sounds=sounds, sounds_json=sounds_json, user_favs=user_favs, bot=self.bot.user, ticker_speed=TICKER_SPEED)
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
            sounds = sorted([f for f in os.listdir(SOUND_FOLDER) if f.lower().endswith(('.mp3', '.wav', '.ogg'))])
            return await render_template("profile.html", user=user, sounds=sounds, bot=self.bot.user)

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
                # Update Stats
                stats = load_sound_stats()
                stats[clean_name] = stats.get(clean_name, 0) + 1
                save_sound_stats(stats)
                
                # Notify Ticker (via WebSocket) if possible
                # We need to broadcast to all connected clients
                if self.ws_clients:
                    # Load meta for display name
                    meta = load_sound_meta()
                    display_name = meta.get(clean_name, {}).get("name", clean_name)

                    msg = {
                        "type": "ticker_update",
                        "data": {
                            "filename": clean_name,
                            "play_count": stats[clean_name],
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

        @self.app.route("/api/upload", methods=["POST"])
        @requires_authorization
        async def upload_file():
            # Quota Check
            files_count = len(os.listdir(SOUND_FOLDER))
            if files_count >= 500:
                 return "Sound limit reached (500 files). Please ask an admin to clean up.", 403

            # Retrieve list of files. 'file' is the field name from the form.
            # handle multiple files if sending multiple with same key, or iterate keys?
            # Standard HTML input multiple sends multiple parts with same name "file"
            
            files = await request.files
            uploaded_files = files.getlist('file')
            if not uploaded_files:
                 return "No files found", 400

            saved_count = 0
            errors = []

            for file in uploaded_files:
                if file.filename == '':
                    continue
                
                clean_name = sanitize_filename(file.filename)
                if allowed_file(clean_name):
                    save_path = os.path.join(SOUND_FOLDER, clean_name)
                    await file.save(save_path)
                    saved_count += 1

                    # Auto-Convert to Opus (if audio)
                    ext = clean_name.rsplit('.', 1)[1].lower() if '.' in clean_name else ''
                    if ext in {'mp3', 'wav', 'm4a'}:
                        try:
                            # Run conversion in background to avoid blocking? 
                            # For now, quick subprocess is fine for small files
                            target = Path(save_path).with_suffix(".opus")
                            # We can't await subprocess easily in quart without creating a coroutine
                            # But let's try strict asyncio shell
                            proc = await asyncio.create_subprocess_exec(
                                "ffmpeg", "-y", "-i", str(save_path),
                                "-c:a", "libopus", "-b:a", "96k",
                                "-ac", "2", "-v", "error", str(target),
                                stderr=asyncio.subprocess.PIPE
                            )
                            await proc.wait()
                        except Exception as e:
                            print(f"Conversion failed for {clean_name}: {e}")

                else:
                    errors.append(f"Invalid type: {file.filename}")
                
                # Thumb Generation
                ext = clean_name.rsplit('.', 1)[1].lower() if '.' in clean_name else ''
                if ext in {'png', 'jpg', 'jpeg', 'gif'}:
                     asyncio.create_task(self._generate_thumbnail(save_path))

            # Reload Caches
            if saved_count > 0:
                beep_cog = self.bot.get_cog("Beep")
                if beep_cog:
                    beep_cog.reload()
                
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
            # Optional: Check if user is admin? For now, let's assume any logged in user or admin can rename?
            # Creating a safe-edit for now.
            
            req = await request.json
            if not req: return "Invalid JSON", 400
            
            filename = req.get("filename")
            new_name = req.get("new_name")
            
            if not filename or not new_name:
                return "Missing parameters", 400
                
            clean_name = sanitize_filename(filename)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return "File not found", 404
                
            meta = load_sound_meta()
            entry = meta.get(clean_name, {})
            
            # If migrating from string
            if isinstance(entry, str):
                entry = {"name": entry, "tags": []}
            
            if new_name:
                entry["name"] = new_name.strip()
                
            tags = req.get("tags")
            if tags is not None:
                # tags should be a list of strings
                if isinstance(tags, list):
                    entry["tags"] = [str(t).strip() for t in tags if str(t).strip()]
            
            shortcut = req.get("shortcut_key")
            if shortcut is not None:
                # Limit to 1 char, uppercase
                s = str(shortcut).strip().upper()
                entry["shortcut"] = s[:1] if s else ""

            meta[clean_name] = entry
            save_sound_meta(meta)
            
            return "Renamed", 200

        @self.app.route("/api/sound/favorite", methods=["POST"])
        @requires_authorization
        async def toggle_favorite():
            user = await self.discord_oauth.fetch_user()
            req = await request.json
            filename = req.get("filename")
            
            if not filename: return "Missing filename", 400
            
            settings = load_user_settings()
            uid = str(user.id)
            user_data = settings.get(uid, {})
            favs = user_data.get("favorites", [])
            
            if filename in favs:
                favs.remove(filename)
                action = "removed"
            else:
                favs.append(filename)
                action = "added"
            
            user_data["favorites"] = favs
            settings[uid] = user_data
            save_user_settings(settings)
            
            return jsonify({"status": "success", "action": action})

        # --- Admin Routes ---
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
            
            # Load sound metadata
            meta = load_sound_meta()
            
            sounds = []
            for f in sorted(Path(SOUND_FOLDER).iterdir(), key=lambda f: f.name.lower()):
                if f.suffix.lower() in AUDIO_EXTS:
                    m = meta.get(f.name, {})
                    display_name = m.get("name", f.name)
                    sounds.append({
                        "filename": f.name,
                        "display_name": display_name
                    })
            
            # Fetch subreddits
            sfw_subs = get_guild_subreddits(guild_id, "sfw")
            nsfw_subs = get_guild_subreddits(guild_id, "nsfw")

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

            if not file_name:
                # Remove
                if str(target_user_id) in entrance_cog.entrance_data:
                    del entrance_cog.entrance_data[str(target_user_id)]
                    entrance_cog.save_data()
                return "Removed entrance", 200

            clean_name = sanitize_filename(file_name)
            if not os.path.exists(os.path.join(SOUND_FOLDER, clean_name)):
                return "File not found", 404

            entrance_cog.entrance_data[str(target_user_id)] = {
                "file": clean_name,
                "volume": max(0.1, min(1.0, volume))
            }
            entrance_cog.save_data()
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

            add_guild_subreddit(guild_id, subreddit_name, sub_type)
            persist_cache()
            
            return "Added", 200

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

            remove_guild_subreddit(guild_id, subreddit_name, sub_type)
            persist_cache()
            
            return "Removed", 200
    
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
        # Stats Increment using cache
        try:
             self.stats_cache[filename] = self.stats_cache.get(filename, 0) + 1
             # Save asynchronously
             await asyncio.to_thread(self._save_json_sync, STATS_FILE, self.stats_cache)
        except Exception as e:
             logger.error(f"Failed to update stats: {e}")

        user_name = "Unknown User"
        user_avatar = None
        guild_name = "Unknown Server"
        
        # Get display name from metadata
        display_name = filename
        meta = self.meta_cache.get(filename, {})
        if meta and "name" in meta:
            display_name = meta["name"]
        
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
                 "guild_id": guild_id
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
        await self.broadcast_to_guild(guild_id, "play_end", {})

    async def cog_load(self):
        # Run Hypercorn in background
        config = Config()
        config.bind = ["0.0.0.0:3000"]
        self.server_task = self.bot.loop.create_task(serve(self.app, config))

    async def cog_unload(self):
        if self.server_task:
            self.server_task.cancel()

async def setup(bot: commands.Bot):
    await bot.add_cog(WebBox(bot))

