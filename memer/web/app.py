"""Quart application factory"""
import os
import datetime
from quart import Quart, send_from_directory, redirect, url_for
from quart_discord import DiscordOAuth2Session, Unauthorized

from memer.config import SOUND_FOLDER

def create_app(bot, ws_clients: dict, logger, template_folder: str, static_folder: str):
    """Create and configure Quart application.

    Args:
        bot: Discord bot instance
        ws_clients: Shared WebSocket clients dict
        logger: Logger instance
        template_folder: Path to templates directory
        static_folder: Path to static files directory

    Returns:
        Configured Quart app
    """
    app = Quart(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
        static_url_path='/static'
    )

    # ==================== Configuration ====================
    app.secret_key = os.getenv("SECRET_KEY", "super_secret_meme_key")

    # Enable debug mode to disable template caching
    app.config["DEBUG"] = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Security Config
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB Limit
    app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)

    # Configure Discord OAuth
    app.config["DISCORD_CLIENT_ID"] = os.getenv("DISCORD_CLIENT_ID", "")
    app.config["DISCORD_CLIENT_SECRET"] = os.getenv("DISCORD_CLIENT_SECRET", "")
    app.config["DISCORD_REDIRECT_URI"] = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:3000/callback")
    app.config["DISCORD_BOT_TOKEN"] = os.getenv("DISCORD_TOKEN", "")

    discord_oauth = DiscordOAuth2Session(app)

    # ==================== Middleware ====================
    _setup_middleware(app)

    # ==================== Initialize Modules ====================
    from memer.web import websocket, auth, views
    from memer.web.api import sounds, entrance, admin, tts

    # Initialize all modules with dependencies
    websocket.init_websocket(bot, ws_clients)
    auth.init_auth(discord_oauth)
    views.init_views(bot, discord_oauth)
    sounds.init_sounds_api(bot, discord_oauth, ws_clients, logger)
    entrance.init_entrance_api(bot, discord_oauth, logger)
    admin.init_admin_api(bot, discord_oauth, logger, template_folder)
    tts.init_tts_api(bot, discord_oauth, logger)

    # ==================== Register Routes ====================
    _setup_routes(app)

    # Register WebSocket route
    websocket.create_websocket_route(app)

    # Register auth and view blueprints
    app.register_blueprint(auth.create_auth_blueprint())
    app.register_blueprint(views.create_views_blueprint())

    # Register API blueprints
    app.register_blueprint(sounds.create_sounds_blueprint())
    app.register_blueprint(entrance.create_entrance_blueprint())
    app.register_blueprint(admin.create_admin_blueprint())
    app.register_blueprint(admin.create_admin_views_blueprint())
    app.register_blueprint(tts.create_tts_blueprint())

    # ==================== Error Handlers ====================
    @app.errorhandler(413)
    async def request_entity_too_large(error):
        return "File too large (Max 5MB)", 413

    @app.errorhandler(Unauthorized)
    async def redirect_unauthorized(e):
        return redirect(url_for("auth.login"))

    return app


def _setup_middleware(app):
    """Setup cache control middleware"""

    @app.after_request
    async def add_cache_headers(response):
        """Add strategic cache headers for different resource types"""
        from quart import request
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


def _setup_routes(app):
    """Setup misc application routes"""

    @app.route("/manifest.json")
    async def manifest():
        """PWA manifest file"""
        from quart import current_app
        import os
        template_dir = current_app.template_folder
        return await send_from_directory(os.path.join(template_dir, "../static"), "manifest.json")

    @app.route("/sw.js")
    async def service_worker():
        """Service worker for PWA"""
        from quart import current_app
        import os
        template_dir = current_app.template_folder
        return await send_from_directory(os.path.join(template_dir, "../static"), "sw.js")

    @app.route("/sounds/<path:filename>")
    async def sound_static(filename):
        """Static route for sound files"""
        return await send_from_directory(SOUND_FOLDER, filename)
