"""opencode adapter: V2 tool names normalize into Stash's tool taxonomy.

OpenCode V2 renamed two built-ins (bash -> shell, task -> subagent). The
adapter must fold them back so Stash stats keep the canonical names.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPT_PATH = ROOT / "plugins" / "opencode-plugin" / "scripts" / "adapt.py"


def _load_adapt():
    spec = importlib.util.spec_from_file_location("opencode_adapt", ADAPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_renamed_tools_normalize_to_stash_taxonomy():
    adapt = _load_adapt()
    for raw, expected in (("shell", "bash"), ("subagent", "agent")):
        event = adapt.adapt_tool_use(
            {
                "session_id": "s",
                "cwd": "c",
                "tool_name": raw,
                "tool_input": {},
                "tool_response": None,
            }
        )
        assert event.tool_name == expected
