import os
import sys
import asyncio
from types import SimpleNamespace

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.cogs.economy import Economy


class DummyStore:
    def __init__(self):
        self.update_calls = []

    async def is_gambling_enabled(self, guild_id):
        return True

    async def try_daily_bonus(self, uid, amount):
        return False

    async def update_balance(self, uid, amount, reason):
        self.update_calls.append((uid, amount, reason))


class DummyCtx:
    def __init__(self):
        self.command = SimpleNamespace(name='meme')
        self.guild = SimpleNamespace(id=123)
        self.author = SimpleNamespace(id=456)
        self.kwargs = {'keyword': 'foo'}
        self.interaction = None
        self._chosen_fallback = True
        self._no_reward = False

    async def reply(self, *args, **kwargs):
        pass


def test_keyword_bonus_skipped_on_fallback():
    bot = SimpleNamespace(
        config=SimpleNamespace(
            COIN_NAME='Coin',
            BASE_REWARD=10,
            KEYWORD_BONUS=5,
            DAILY_BONUS=0,
        )
    )

    economy = Economy.__new__(Economy)
    economy.bot = bot
    economy.store = DummyStore()

    ctx = DummyCtx()
    asyncio.run(economy.on_command_completion(ctx))

    assert economy.store.update_calls == [
        (str(ctx.author.id), bot.config.BASE_REWARD, f"Used /{ctx.command.name}")
    ]
