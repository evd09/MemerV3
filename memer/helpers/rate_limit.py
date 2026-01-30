import asyncio
import logging

log = logging.getLogger(__name__)

_last_request = 0.0
_rate_lock = asyncio.Lock()

async def throttle():
    global _last_request
    async with _rate_lock:
        now = asyncio.get_event_loop().time()
        elapsed = now - _last_request
        wait = max(0, 2.0 - elapsed)
        if wait:
            log.debug("Throttling: sleeping %.3fs before next Reddit request", wait)
            await asyncio.sleep(wait)
        _last_request = asyncio.get_event_loop().time()
