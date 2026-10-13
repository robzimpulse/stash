"""Shape checks for the Antigravity native plugin manifest + hooks.json.

Purpose: Antigravity loads `~/.gemini/config/plugins/stash/` verbatim, so a
malformed hooks.json silently means no streaming. These tests pin the
contract: one named hook group, only supported events, machine-independent
`stash hook run antigravity <event>` commands, and timeouts in SECONDS.
Usage: uv run pytest -o addopts="" plugins/tests/test_antigravity_manifest.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "antigravity-plugin" / "plugin"
_FLAT_EVENTS = {"PreInvocation", "PostInvocation", "Stop"}
_GROUPED_EVENTS = {"PreToolUse", "PostToolUse"}


def _handlers(spec: dict):
    for event, entries in spec.items():
        if event == "enabled":
            continue
        assert event in _FLAT_EVENTS | _GROUPED_EVENTS, event
        for entry in entries:
            if event in _GROUPED_EVENTS:
                assert "matcher" in entry
                yield from ((event, h) for h in entry["hooks"])
            else:
                yield event, entry


def test_plugin_json_names_the_plugin() -> None:
    data = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    assert data["name"] == "stash"


def test_hooks_json_wires_sync_and_stop() -> None:
    data = json.loads((PLUGIN_DIR / "hooks.json").read_text())
    assert set(data) == {"stash"}
    wired = {(event, h["command"]) for event, h in _handlers(data["stash"])}
    assert wired == {
        ("PreInvocation", "stash hook run antigravity on_sync"),
        ("PostToolUse", "stash hook run antigravity on_sync"),
        ("Stop", "stash hook run antigravity on_stop"),
    }


def test_hooks_json_timeouts_are_seconds() -> None:
    data = json.loads((PLUGIN_DIR / "hooks.json").read_text())
    for _, handler in _handlers(data["stash"]):
        assert handler.get("type", "command") == "command"
        assert isinstance(handler["timeout"], int) and 1 <= handler["timeout"] <= 10
