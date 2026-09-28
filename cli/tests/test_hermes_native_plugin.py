"""Tests for the stash native Hermes plugin (hybrid wiring).

The native plugin's ONLY job is to rebuild the shell-hook stdin envelope
(`{hook_event_name, tool_name, tool_input, session_id, cwd, extra}` — the
exact shape `agent/shell_hooks.py::_payload_fields` produces in Hermes) from
native hook kwargs, and hand it to `stash hook run hermes <event>` unchanged.
A native user must get byte-identical behavior to a shell-hook user: same
scripts, same adapt layer, no second event format.
"""

from __future__ import annotations

import json
import subprocess  # noqa: F401  (asserted by signature below)
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = REPO_ROOT / "stashai" / "plugin" / "assets" / "hermes" / "plugin"


def _load_plugin_module():
    sys.path.insert(0, str(PLUGIN_DIR))
    import importlib

    import __init__ as stash_hermes_plugin  # the plugin dir's __init__.py

    return importlib.reload(stash_hermes_plugin)


# --- envelope builder: the one piece of real logic in the plugin ---


def test_envelope_matches_shell_hook_wire_format() -> None:
    mod = _load_plugin_module()
    envelope = mod.build_envelope(
        "post_tool_call",
        tool_name="terminal",
        args={"command": "ls"},
        result={"output": "ok"},
        session_id="sess-1",
        duration_ms=12,
        status="ok",
    )

    assert envelope["hook_event_name"] == "post_tool_call"
    assert envelope["tool_name"] == "terminal"
    assert envelope["tool_input"] == {"command": "ls"}
    assert envelope["session_id"] == "sess-1"
    assert envelope["cwd"]  # always present, resolved at fire time
    # everything non-top-level lands under extra, like _payload_fields
    assert envelope["extra"]["duration_ms"] == 12
    assert envelope["extra"]["status"] == "ok"
    assert "tool_name" not in envelope["extra"]
    assert "args" not in envelope["extra"]


def test_envelope_non_tool_event_has_null_tool_fields() -> None:
    mod = _load_plugin_module()
    envelope = mod.build_envelope("on_session_start", session_id="s", model="m", platform="cli")

    assert envelope["tool_name"] is None
    assert envelope["tool_input"] is None
    # model/platform ride in extra exactly as the shell-hook envelope does
    assert envelope["extra"]["model"] == "m"
    assert envelope["extra"]["platform"] == "cli"


def test_envelope_json_serializable_roundtrip() -> None:
    mod = _load_plugin_module()
    envelope = mod.build_envelope(
        "pre_llm_call",
        session_id="s",
        user_message="hello",
        is_first_turn=True,
        conversation_history=[{"role": "user", "content": "hello"}],
        model="m",
        platform="telegram",
    )
    payload = json.dumps(envelope)

    # adapt.py parses this exact payload shape; the roundtrip must keep it
    sys.path.insert(0, str(REPO_ROOT / "plugins" / "hermes-plugin" / "scripts"))
    for m in ("adapt", "config"):
        sys.modules.pop(m, None)
    import adapt  # noqa: F401

    event = adapt.adapt_prompt(json.loads(payload))
    assert event.session_id == "s"
    assert event.prompt_text == "hello"


def test_envelope_must_be_json_default_serializable() -> None:
    """Hermes hook kwargs can carry non-JSON objects (e.g. exception instances);
    the shell-hook path serializes with default=str — the plugin must too, or a
    single odd kwarg kills every subsequent stream event."""
    mod = _load_plugin_module()
    envelope = mod.build_envelope(
        "post_tool_call",
        tool_name="terminal",
        args={"command": "ls"},
        result=RuntimeError("boom"),  # not JSON serializable
        session_id="s",
    )
    payload = json.dumps(envelope, default=str)
    assert "boom" in payload


# --- dispatch: the plugin subprocesses to stash hook run ---


def test_dispatch_invokes_stash_hook_run(monkeypatch) -> None:
    mod = _load_plugin_module()
    calls: list[tuple[list[str], str]] = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("input")))
        return subprocess.CompletedProcess(cmd, 0, b"{}", b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod.dispatch("on_session_start", session_id="s")

    cmd, payload = calls[0]
    assert cmd[:4] == ["stash", "hook", "run", "hermes"]
    assert cmd[4] == "on_session_start"
    assert json.loads(payload)["hook_event_name"] == "on_session_start"


def test_dispatch_never_raises_on_subprocess_failure(monkeypatch) -> None:
    """Streaming must never break the Hermes session: a dead stash binary or
    network failure degrades to no streaming, not an error in the turn loop."""
    mod = _load_plugin_module()

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no stash binary")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.dispatch("on_session_start", session_id="s") is None


def test_dispatch_has_timeout(monkeypatch) -> None:
    """In-process hooks block the turn loop; the subprocess call must be
    bounded so a hung stash can't hang Hermes."""
    mod = _load_plugin_module()
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess("stash", 0, b"{}", b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod.dispatch("on_session_end", session_id="s")

    assert seen["timeout"] is not None
    assert seen["timeout"] > 0


# --- registration: what register(ctx) wires ---


def test_register_wires_all_five_hooks_and_skill(monkeypatch) -> None:
    mod = _load_plugin_module()
    registered_hooks: dict[str, object] = {}
    registered_skills: dict[str, Path] = {}

    class Ctx:
        def register_hook(self, hook_name, callback):
            registered_hooks[hook_name] = callback

        def register_skill(self, name, path, **kwargs):
            registered_skills[name] = Path(path)

    mod.register(Ctx())

    assert set(registered_hooks) == {
        "on_session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
        "on_session_end",
    }
    assert (
        registered_hooks["pre_llm_call"](session_id="s", user_message="hi", is_first_turn=True)
        is None
    )
    assert (
        registered_hooks["post_llm_call"](
            session_id="s", assistant_response="ok", is_first_turn=False
        )
        is None
    )
    assert "stash" in registered_skills
    assert registered_skills["stash"].name == "SKILL.md"
    assert registered_skills["stash"].exists()


def test_plugin_yaml_declares_hooks_and_metadata() -> None:
    import yaml

    manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text())
    assert manifest["name"] == "stash"
    assert set(manifest["provides_hooks"]) == {
        "on_session_start",
        "pre_llm_call",
        "post_tool_call",
        "post_llm_call",
        "on_session_end",
    }
