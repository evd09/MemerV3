#!/usr/bin/env python3
"""Print Discord application command names.

This script uses Discord's HTTP API to list both global and guild-specific
commands for the application defined by ``APPLICATION_ID``.  A guild to query
can be specified via the ``GUILD_ID`` environment variable.  Authentication is
performed with ``DISCORD_TOKEN``.

The output is intended to help verify that command registrations (or removals)
have propagated correctly.
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


def _print_commands(label: str, commands: Iterable[Dict[str, Any]]) -> None:
    print(f"{label}:")
    commands = list(commands)
    if not commands:
        print("  (none)")
        return

    for cmd in commands:
        print(f"- {cmd['name']}")
        for opt in cmd.get("options", []):
            # type 1: subcommand, type 2: subcommand group
            if opt.get("type") in (1, 2):
                print(f"  - {opt['name']}")
                if opt.get("type") == 2:
                    for sub in opt.get("options", []):
                        if sub.get("type") == 1:
                            print(f"    - {sub['name']}")
    print()


def main() -> None:
    token = _get_env("DISCORD_TOKEN")
    app_id = _get_env("APPLICATION_ID")
    guild_id = os.getenv("GUILD_ID")

    global_url = f"{API_BASE}/applications/{app_id}/commands"
    global_cmds = _fetch(global_url, token)
    _print_commands("Global commands", global_cmds)

    if guild_id:
        guild_url = f"{API_BASE}/applications/{app_id}/guilds/{guild_id}/commands"
        guild_cmds = _fetch(guild_url, token)
        _print_commands(f"Guild commands for {guild_id}", guild_cmds)
    else:
        print("No GUILD_ID provided; skipping guild command fetch.")


if __name__ == "__main__":
    main()
