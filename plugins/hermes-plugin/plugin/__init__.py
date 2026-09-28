"""Stash native Hermes plugin — hybrid wiring.

Registers the five session hooks and, when each fires, rebuilds the exact
shell-hook stdin envelope (`{hook_event_name, tool_name, tool_input,
session_id, cwd, extra}` — the shape Hermes' `agent/shell_hooks.py::
_payload_fields` produces) and hands it to `stash hook run hermes <event>`.
The scripts, adapt layer, and streaming behavior stay byte-identical between
shell-hook and native users; there is no second event format.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_HOOK_TIMEOUT_SECONDS = 15

# kwargs promoted to top-level envelope keys; everything else lands under extra.
# Mirrors _TOP_LEVEL_PAYLOAD_KEYS in Hermes' agent/shell_hooks.py.
_TOP_LEVEL_KEYS = {"tool_name", "args", "session_id", "parent_session_id"}


def build_envelope(event: str, **kwargs) -> dict:
    """Native hook kwargs -> shell-hook stdin envelope."""
    try:
        cwd = str(Path.cwd())
    except OSError:
        cwd = ""
    return {
        "hook_event_name": event,
        "tool_name": kwargs.get("tool_name"),
        "tool_input": kwargs.get("args") if isinstance(kwargs.get("args"), dict) else None,
        "session_id": kwargs.get("session_id") or kwargs.get("parent_session_id") or "",
        "cwd": cwd,
        "extra": {k: v for k, v in kwargs.items() if k not in _TOP_LEVEL_KEYS},
    }


def dispatch(event: str, **kwargs) -> None:
    """Forward one hook event to the stash CLI.

    Never raises: streaming must not break the Hermes turn loop — a dead
    stash binary or network failure degrades to no streaming, not an error.
    """
    payload = json.dumps(build_envelope(event, **kwargs), default=str)
    try:
        subprocess.run(
            ["stash", "hook", "run", "hermes", event],
            input=payload,
            text=True,
            capture_output=True,
            timeout=_HOOK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return


def register(ctx) -> None:
    here = Path(__file__).parent

    # The skill replaces the old "copy HERMES.md into your project" step:
    # the agent learns the stash CLI through skill_view("stash:stash").
    ctx.register_skill("stash", here / "skills" / "stash" / "SKILL.md")

    for event in (
        "on_session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
        "on_session_end",
    ):

        def make_handler(_event):
            def handler(**kwargs):
                dispatch(_event, **kwargs)
                return None  # observer-only: never inject context or directives

            return handler

        ctx.register_hook(event, make_handler(event))
