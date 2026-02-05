"""WebSocket connection management and broadcasting."""
import asyncio
import json
from quart import websocket, session
import discord
from memer.utils.logger_setup import setup_logger

logger = setup_logger("web.websocket", "web.log")

# Module state (initialized by webbox.py)
_bot: discord.Client = None
_ws_clients: dict = {}  # {websocket: user_id}


def init_websocket(bot: discord.Client, ws_clients: dict):
    """Initialize module with shared dependencies.

    Args:
        bot: Discord bot instance
        ws_clients: Shared WebSocket clients dict (reference)
    """
    global _bot, _ws_clients
    _bot = bot
    _ws_clients = ws_clients


async def ws_handler():
    """WebSocket /ws route handler.

    Handles WebSocket connections, authenticates users via session,
    and maintains connection until client disconnects.
    """
    # Authenticate via Session
    user_id = None
    try:
        # Read directly from session to avoid "Session modified during websocket" error
        # caused by fetch_user() potentially refreshing tokens.
        user_id = session.get("DISCORD_USER_ID")
    except:
        pass  # Guest or unauth

    # Check if user is blocked
    if user_id:
        from memer.helpers import db
        if await db.is_user_blocked(user_id):
            logger.warning(f"Blocked user {user_id} attempted WebSocket connection")
            await websocket.close(1008, "Access denied: Account blocked")
            return

    ws = websocket._get_current_object()
    _ws_clients[ws] = user_id
    logger.info(f"WebSocket connected: user_id={user_id}")

    try:
        while True:
            # Keep connection alive (receive messages but don't process)
            await websocket.receive()
    except asyncio.CancelledError:
        pass
    finally:
        if ws in _ws_clients:
            del _ws_clients[ws]
            logger.info(f"WebSocket disconnected: user_id={user_id}")


async def broadcast_to_guild(guild_id: int, event_type: str, data: dict):
    """Broadcast message to all clients who are members of the guild.

    Args:
        guild_id: Discord guild ID
        event_type: Event type string (e.g., 'play_start', 'tts_start')
        data: Event data dictionary

    Example:
        await broadcast_to_guild(123456789, "play_start", {
            "filename": "test.mp3",
            "user_name": "Alice"
        })
    """
    if not _ws_clients:
        return

    msg = json.dumps({"type": event_type, "data": data})
    to_remove = []

    guild = _bot.get_guild(guild_id)
    if not guild:
        return  # Can't verify membership

    for ws, user_id in _ws_clients.items():
        if not user_id:
            continue  # Skip guests for guild events

        # Verify membership
        # We use get_member (cache) for performance.
        # Ideally guild.chunk() should be called at startup or periodically.
        member = guild.get_member(user_id)

        if member:
            try:
                await ws.send(msg)
            except Exception as e:
                logger.error(f"Broadcast error to user {user_id}: {e}")
                to_remove.append(ws)

    # Clean up dead connections
    for ws in to_remove:
        if ws in _ws_clients:
            del _ws_clients[ws]


async def broadcast_public_message(event_type: str, data: dict):
    """Broadcast message to ALL connected clients.

    Args:
        event_type: Event type string (e.g., 'ticker_update')
        data: Event data dictionary

    Example:
        await broadcast_public_message("ticker_update", {
            "message": "Server restarted"
        })
    """
    if not _ws_clients:
        return

    msg = json.dumps({"type": event_type, "data": data})
    to_remove = []

    for ws in _ws_clients:
        try:
            await ws.send(msg)
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
            to_remove.append(ws)

    # Clean up dead connections
    for ws in to_remove:
        if ws in _ws_clients:
            del _ws_clients[ws]


def create_websocket_route(app):
    """Register WebSocket route with Quart app.

    Args:
        app: Quart application instance
    """
    app.websocket("/ws")(ws_handler)
    logger.info("WebSocket route /ws registered")
