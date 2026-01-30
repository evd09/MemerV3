#!/usr/bin/env python3
"""Remove Discord application command names.

This script uses Discord's HTTP API to delete both global and guild-specific
slash commands for the application defined by ``APPLICATION_ID``. Command names
are provided as command-line arguments. Authentication is performed with
``DISCORD_TOKEN``. A guild to target can be specified via the ``GUILD_ID``
environment variable.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Iterable

import requests

API_BASE = "https://discord.com/api/v10"


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _fetch(url: str, token: str) -> Iterable[Dict[str, Any]]:
    headers = {"Authorization": f"Bot {token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _delete(url: str, token: str) -> None:
    headers = {"Authorization": f"Bot {token}"}
    resp = requests.delete(url, headers=headers)
    if resp.status_code not in (200, 204):
        resp.raise_for_status()


def _remove_commands(label: str, url: str, token: str, names: Iterable[str]) -> None:
    commands = _fetch(url, token)
    for cmd in commands:
        if cmd["name"] in names:
            del_url = f"{url}/{cmd['id']}"
            _delete(del_url, token)
            print(f"Deleted {label} command: {cmd['name']}")


def main() -> None:
    token = _get_env("DISCORD_TOKEN")
    app_id = _get_env("APPLICATION_ID")
    guild_id = os.getenv("GUILD_ID")
    names = sys.argv[1:]
    if not names:
        print("Usage: clear_commands.py <command-name> [command-name ...]", file=sys.stderr)
        sys.exit(1)

    global_url = f"{API_BASE}/applications/{app_id}/commands"
    _remove_commands("global", global_url, token, names)

    if guild_id:
        guild_url = f"{API_BASE}/applications/{app_id}/guilds/{guild_id}/commands"
        _remove_commands(f"guild {guild_id}", guild_url, token, names)
    else:
        print("No GUILD_ID provided; skipping guild command cleanup.")


if __name__ == "__main__":
    main()
