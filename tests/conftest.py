import sys
import os
import types
from types import SimpleNamespace

# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Stub asyncpraw with minimal Reddit and Submission
asyncpraw = types.ModuleType("asyncpraw")
asyncpraw.models = types.ModuleType("asyncpraw.models")

class Submission:
    pass

class Reddit:
    pass

class Subreddit:
    pass

asyncpraw.models.Submission = Submission
asyncpraw.models.Subreddit = Subreddit
asyncpraw.Reddit = Reddit

sys.modules.setdefault("asyncpraw", asyncpraw)
sys.modules.setdefault("asyncpraw.models", asyncpraw.models)

# Stub discord with Embed and errors.NotFound and ext.commands.Context
discord_stub = types.ModuleType("discord")

class Embed:
    def __init__(self, **kwargs):
        self.title = kwargs.get("title")
        self.url = kwargs.get("url")
        self.description = kwargs.get("description")
        self.image = SimpleNamespace(url=None)
        self.footer = SimpleNamespace(text=None)

    def set_image(self, *, url):
        self.image.url = url

    def set_footer(self, *, text):
        self.footer.text = text

class NotFound(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)

discord_stub.Embed = Embed
discord_stub.errors = SimpleNamespace(NotFound=NotFound)
discord_stub.Interaction = object
def ui_button(*args, **kwargs):
    def decorator(func):
        return func
    return decorator

discord_stub.ButtonStyle = SimpleNamespace(primary=1, secondary=2)
discord_stub.ui = SimpleNamespace(View=object, button=ui_button, Button=object)

ext_module = types.ModuleType("discord.ext")
commands_module = types.ModuleType("discord.ext.commands")
tasks_module = types.ModuleType("discord.ext.tasks")

class Cog:
    @classmethod
    def listener(cls, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

commands_module.Context = object
commands_module.Cog = Cog
commands_module.Bot = object

def hybrid_command(*args, **kwargs):
    def decorator(func):
        def wrapper(*a, **k):
            return func(*a, **k)
        wrapper.error = lambda f: f
        return wrapper
    return decorator

commands_module.hybrid_command = hybrid_command

def check(predicate):
    return predicate

commands_module.check = check

def loop(*args, **kwargs):
    def decorator(func):
        return func
    return decorator

tasks_module.loop = loop

ext_module.commands = commands_module
ext_module.tasks = tasks_module

discord_stub.ext = ext_module
discord_stub.app_commands = types.ModuleType("discord.app_commands")

sys.modules.setdefault("discord", discord_stub)
sys.modules.setdefault("discord.ext", ext_module)
sys.modules.setdefault("discord.ext.commands", commands_module)
sys.modules.setdefault("discord.ext.tasks", tasks_module)
sys.modules.setdefault("discord.app_commands", discord_stub.app_commands)

# Ensure global caches are clean for each test
import pytest
from memer import reddit_meme as meme_mod


@pytest.fixture(autouse=True)
def _clear_caches():
    meme_mod.ID_CACHE.clear()
    meme_mod.HASH_CACHE.clear()
    meme_mod.WARM_CACHE.clear()
