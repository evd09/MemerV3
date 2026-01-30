import asyncio
import sys
from types import SimpleNamespace


def test_fetch_commands_no_duplicates():
    original = {
        key: sys.modules.pop(key, None)
        for key in [
            "discord",
            "discord.ext",
            "discord.ext.commands",
            "discord.app_commands",
        ]
    }

    try:
        import discord
        from discord.ext import commands
        from memer import bot as bot_module

        bot_module.DEV_GUILD_ID = 1234
        bot_module.DISABLE_GLOBAL_COMMANDS = False

        bot = commands.Bot(command_prefix="/", intents=discord.Intents.none())

        commands_list = [
            SimpleNamespace(id=1, name="foo"),
            SimpleNamespace(id=2, name="foo"),
            SimpleNamespace(id=3, name="bar"),
        ]

        async def fetch_commands(guild=None):
            return list(commands_list)

        deleted = []

        async def delete_global_command(app_id, cmd_id):
            deleted.append(cmd_id)
            commands_list[:] = [c for c in commands_list if c.id != cmd_id]

        async def sync(guild=None):
            return []

        bot.tree.get_commands = lambda: []
        bot.tree.add_command = lambda c: None
        bot.tree.clear_commands = lambda guild=None: None
        bot.tree.copy_global_to = lambda guild=None: None
        bot.tree.sync = sync
        bot.tree.fetch_commands = fetch_commands
        bot.tree.remove_command = lambda name: None
        bot.get_guild = lambda guild_id: None
        bot.http.delete_global_command = delete_global_command

        asyncio.run(bot_module.sync_app_commands(bot))

        assert deleted == [2]
        assert len(commands_list) == len({c.name for c in commands_list})
    finally:
        sys.modules.update({k: v for k, v in original.items() if v is not None})
