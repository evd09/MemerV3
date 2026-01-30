import os
import asyncio
from pathlib import Path
from quart import Quart, render_template, request, redirect, url_for, jsonify
from quart_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
from hypercorn.asyncio import serve
from hypercorn.config import Config
import discord
from discord.ext import commands

from memer.cogs.audio.constants import SOUND_FOLDER, AUDIO_EXTS
from memer.cogs.audio.audio_player import play_clip
from memer.cogs.audio.audio_queue import queue_audio
from memer.meme_stats import get_dashboard_stats, get_top_reacted_memes

# Define the template folder explicitly
TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__)) + "/web/templates"

class WebBox(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.app = Quart(__name__, template_folder=TEMPLATE_DIR)
        self.app.secret_key = os.getenv("SECRET_KEY", "super_secret_meme_key")
        
        # Security Config
        self.app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB Limit
        
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

    def setup_routes(self):
        # --- Helpers ---
        def sanitize_filename(filename):
            """Strict alphanumeric sanitization."""
            # Keep only alphanumeric, dashes, underscores, and dots
            clean = "".join(c for c in filename if c.isalnum() or c in "-_.")
            return clean

        @self.app.errorhandler(413)
        async def request_entity_too_large(error):
            return "File too large (Max 5MB)", 413

        # --- Views ---
        @self.app.route("/")
        async def home():
            user = None
            try:
                user = await self.discord_oauth.fetch_user()
            except Unauthorized:
                pass

            sounds = []
            # Sort files case-insensitive
            files = sorted(Path(SOUND_FOLDER).iterdir(), key=lambda f: f.name.lower())
            for f in files:
                if f.suffix.lower() in AUDIO_EXTS:
                    sounds.append(f.name)
            
            return await render_template("index.html", user=user, sounds=sounds)

        @self.app.route("/profile")
        @requires_authorization
        async def profile():
            user = await self.discord_oauth.fetch_user()
            sounds = sorted([f for f in os.listdir(SOUND_FOLDER) if f.lower().endswith(('.mp3', '.wav', '.ogg'))])
            return await render_template("profile.html", user=user, sounds=sounds)

        @self.app.route("/stats")
        async def stats_page():
            user = None
            if await self.discord_oauth.authorized:
                 try: user = await self.discord_oauth.fetch_user()
                 except: pass
                 
            # Fetch stats from DB
            stats_data = {
                "total_memes": 0, "nsfw_memes": 0, 
                "user_counts": {}, "subreddit_counts": {}, "keyword_counts": {}
            }
            reactions = []
            
            try:
                stats_data = await get_dashboard_stats()
                
                # Enrich Reaction Data
                reacted = await get_top_reacted_memes(10)
                for msg_id, url, title, guild_id, channel_id, count in reacted:
                    reactions.append({
                        "title": title or "Meme",
                        "url": url,
                        "count": count,
                        "link": f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
                    })
                    
                # Resolve User IDs to Names
                resolved_users = {}
                for uid_str, count in stats_data.get("user_counts", {}).items():
                    try:
                        uid = int(uid_str)
                        user_obj = self.bot.get_user(uid)
                        if not user_obj:
                            try: user_obj = await self.bot.fetch_user(uid)
                            except: pass
                        
                        name = user_obj.name if user_obj else f"User {uid}"
                        resolved_users[name] = count
                    except:
                        resolved_users[uid_str] = count
                stats_data["user_counts"] = resolved_users
                
            except Exception as e:
                self.bot.dispatch("error", e) # Log it
                
            return await render_template(
                "stats.html", 
                user=user, 
                stats=stats_data, 
                reactions=reactions
            )

        @self.app.route("/login")
        async def login():
            return await self.discord_oauth.create_session(scope=["identify"])

        @self.app.route("/logout")
        async def logout():
            self.discord_oauth.revoke()
            return redirect(url_for("home"))

        @self.app.route("/callback")
        async def callback():
            try:
                await self.discord_oauth.callback()
            except Exception:
                pass
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
                return "User not found in any Voice Channel", 400

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

            files = await request.files
            if 'file' not in files:
                return "No file part", 400
            
            file = files['file']
            if file.filename == '':
                return "No selected file", 400
            
            # Sanitize
            clean_name = sanitize_filename(file.filename)
            
            if file and allowed_file(clean_name):
                # Check for overwrite?
                # If we want to prevent overwrite:
                # if os.path.exists(os.path.join(SOUND_FOLDER, clean_name)): ...
                # For now, allow overwrite or simple rename? Let's just allow overwrite as "update".
                
                save_path = os.path.join(SOUND_FOLDER, clean_name)
                await file.save(save_path)
                return "Uploaded", 200
            
            return "Invalid file type", 400

        def allowed_file(filename):
            return '.' in filename and \
                   filename.rsplit('.', 1)[1].lower() in {'mp3', 'wav', 'ogg'}

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
