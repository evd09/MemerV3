"""OAuth authentication routes"""
import os
from quart import Blueprint, redirect, url_for, session

# Module dependencies (injected by webbox)
_discord_oauth = None

def init_auth(discord_oauth):
    """Initialize module dependencies"""
    global _discord_oauth
    _discord_oauth = discord_oauth

def create_auth_blueprint() -> Blueprint:
    """Create and return auth blueprint"""
    bp = Blueprint('auth', __name__)

    @bp.route("/login")
    async def login():
        """Initiate Discord OAuth flow"""
        # Enable insecure transport for local testing if not using HTTPS
        from quart import current_app
        redirect_uri = current_app.config.get("DISCORD_REDIRECT_URI", "")
        if "https" not in redirect_uri:
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

        session.permanent = True
        return await _discord_oauth.create_session(scope=["identify"])

    @bp.route("/logout")
    async def logout():
        """Revoke OAuth session and clear session"""
        _discord_oauth.revoke()
        session.clear()
        return redirect(url_for("views.home"))

    @bp.route("/callback")
    async def callback():
        """OAuth callback handler"""
        try:
            await _discord_oauth.callback()

            # Check if user is blocked after successful OAuth
            from memer.helpers import db
            user = await _discord_oauth.fetch_user()

            is_blocked = await db.is_user_blocked(user.id)
            if is_blocked:
                from memer.utils.logger_setup import setup_logger
                logger = setup_logger("web.auth", "web.log")
                logger.warning(f"🚫 Blocked user {user.id} ({user.username}) attempted to login - denying access")
                # Clear session and deny access
                _discord_oauth.revoke()
                session.clear()
                return """
                <html>
                <head><title>Access Denied</title></head>
                <body style="background: #18181b; color: #fff; font-family: system-ui; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
                    <div style="text-align: center; max-width: 500px; padding: 2rem;">
                        <h1 style="color: #ef4444; font-size: 3rem; margin: 0;">🚫 Access Denied</h1>
                        <p style="color: #a1a1aa; margin: 1rem 0;">Your account has been blocked from accessing this service.</p>
                        <p style="color: #71717a; font-size: 0.875rem;">If you believe this is an error, please contact the bot owner.</p>
                    </div>
                </body>
                </html>
                """, 403

        except Exception as e:
            # Dispatch error to bot error handler
            from quart import current_app
            if hasattr(current_app, 'bot'):
                current_app.bot.dispatch("error", e)
            return f"Callback Error: {e}", 500
        return redirect(url_for("views.home"))

    return bp
