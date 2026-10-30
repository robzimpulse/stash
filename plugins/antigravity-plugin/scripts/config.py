"""Antigravity plugin config. Reads ~/.stash/config.json (CLI config).

Purpose: per-agent constants for the shared `stashai.plugin.agent_config`
helpers, plus per-conversation state directories — Antigravity runs parallel
chats and subagents, each with its own conversationId, so one shared
state.json would cross-wire sessions.

Usage:
    data_dir = conversation_dir(conversation_id)
    with get_client(data_dir) as client: ...

Paths are computed at call time (not import time) so tests and long-lived
importers always see the current STASH_ANTIGRAVITY_DATA / HOME.
"""

from __future__ import annotations

from pathlib import Path

from stashai.plugin import agent_config
from stashai.plugin.agent_config import get_stdin_data
from stashai.plugin.stash_client import StashClient

_CLIENT = "antigravity"

__all__ = [
    "conversation_dir",
    "get_client",
    "get_config",
    "get_stdin_data",
    "is_configured",
    "state_root",
]


def state_root() -> Path:
    return agent_config.data_dir_from_env("STASH_ANTIGRAVITY_DATA", ".stash/plugins/antigravity")


def conversation_dir(conversation_id: str) -> Path:
    return state_root() / "conversations" / conversation_id


def get_config() -> dict:
    return agent_config.get_config(_CLIENT)


def get_client(data_dir: Path) -> StashClient:
    return agent_config.get_client(_CLIENT, data_dir)


def is_configured() -> bool:
    return agent_config.is_configured(_CLIENT)
