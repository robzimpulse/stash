"""Behavior tests for the Antigravity on_sync / on_stop hook scripts.

Purpose: pin offset tailing (no duplicates, no half lines), per-conversation
isolation, first-sight session creation, pruning, the Stop-time transcript
upload gate, and the exactly-`{}` stdout contract Antigravity requires.
The Stash client and background spawns are faked; nothing touches the network.
Usage: uv run pytest -o addopts="" plugins/tests/test_antigravity_hooks.py -q
"""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "antigravity-plugin" / "scripts"
_MODS = ("adapt", "config", "on_sync", "on_stop")


class FakeClient:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.sessions: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def create_session(self, session_id, agent_name, cwd=None, files_touched=None):
        self.sessions.append(session_id)
        return {"id": f"row-{session_id}", "app_url": f"http://app/s/{session_id}"}

    def push_event(
        self,
        agent_name,
        event_type,
        content,
        session_id,
        tool_name=None,
        metadata=None,
        client=None,
    ):
        self.events.append((event_type, content, session_id, tool_name, client))
        return {}


@pytest.fixture
def ag(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("STASH_ANTIGRAVITY_DATA", str(tmp_path / "ag-data"))
    from stashai.plugin import hooks

    # hooks._CONFIG_FILE is bound at import time to the REAL ~/.stash/config.json,
    # whose enabled_agents may exclude antigravity; point it at an absent file.
    monkeypatch.setattr(hooks, "_CONFIG_FILE", tmp_path / "absent-config.json")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    for mod in _MODS:
        sys.modules.pop(mod, None)
    on_sync = importlib.import_module("on_sync")
    on_stop = importlib.import_module("on_stop") if (SCRIPTS / "on_stop.py").exists() else None
    client = FakeClient()
    cfg = {
        "api_endpoint": "http://stash",
        "api_key": "k",
        "agent_name": "alice",
        "stopped_streaming": False,
        "client": "antigravity",
    }
    monkeypatch.setattr(on_sync, "is_configured", lambda: True)
    monkeypatch.setattr(on_sync, "get_config", lambda: dict(cfg))
    monkeypatch.setattr(on_sync, "get_client", lambda data_dir: client)
    monkeypatch.setattr(on_sync, "spawn_skills_sync", lambda cfg: None)
    monkeypatch.setattr(on_sync, "spawn_self_upgrade", lambda: None)
    yield SimpleNamespace(
        on_sync=on_sync,
        on_stop=on_stop,
        client=client,
        tmp=tmp_path,
        root=tmp_path / "ag-data" / "conversations",
    )
    for mod in _MODS:
        sys.modules.pop(mod, None)


def rec(i, type_, **kw) -> str:
    return json.dumps({"step_index": i, "source": "MODEL", "type": type_, "status": "DONE", **kw})


def append(path: Path, *lines: str, tail: str = "") -> None:
    with open(path, "a") as f:
        f.write("".join(line + "\n" for line in lines) + tail)


def payload(cid: str, transcript: Path, **extra) -> dict:
    return {
        "conversationId": cid,
        "transcriptPath": str(transcript),
        "workspacePaths": ["/repo"],
        "modelName": "auto",
        **extra,
    }


TURN = (
    rec(0, "USER_INPUT", content="<USER_REQUEST>hi</USER_REQUEST>"),
    rec(2, "GENERIC", content="file body"),
    rec(
        1,
        "PLANNER_RESPONSE",
        tool_calls=[{"name": "view_file", "args": {"AbsolutePath": '"/repo/a.py"'}}],
    ),
    rec(3, "PLANNER_RESPONSE", content="All good."),
)


def kinds(client: FakeClient) -> list[str]:
    return [e[0] for e in client.events]


def test_first_sync_creates_session_and_streams_turn(ag) -> None:
    t = ag.tmp / "t.jsonl"
    append(t, *TURN)
    ctx = ag.on_sync.run(payload("c1", t))
    assert ctx.conversation_id == "c1" and ctx.data_dir == ag.root / "c1"
    assert ag.client.sessions == ["c1"]
    assert kinds(ag.client) == ["user_message", "tool_use", "assistant_message"]
    assert ag.client.events[1][1:4] == ("Read /repo/a.py", "c1", "read")
    assert {e[4] for e in ag.client.events} == {"antigravity"}


def test_repeat_sync_streams_only_new_lines(ag) -> None:
    t = ag.tmp / "t.jsonl"
    append(t, *TURN)
    ag.on_sync.run(payload("c1", t))
    ag.on_sync.run(payload("c1", t))
    assert len(ag.client.events) == 3 and ag.client.sessions == ["c1"]
    append(t, rec(4, "USER_INPUT", content="again"))
    ag.on_sync.run(payload("c1", t))
    assert kinds(ag.client)[-1] == "user_message" and len(ag.client.events) == 4


def test_partial_line_not_consumed_until_complete(ag) -> None:
    t = ag.tmp / "t.jsonl"
    full = rec(0, "USER_INPUT", content="hello")
    append(t, tail=full[:10])
    ag.on_sync.run(payload("c1", t))
    assert ag.client.events == []
    append(t, tail=full[10:] + "\n")
    ag.on_sync.run(payload("c1", t))
    assert kinds(ag.client) == ["user_message"]


def test_shrunk_transcript_restarts_from_zero(ag) -> None:
    t = ag.tmp / "t.jsonl"
    append(t, *TURN)
    ag.on_sync.run(payload("c1", t))
    t.write_text(rec(9, "PLANNER_RESPONSE", content="fresh") + "\n")
    ag.on_sync.run(payload("c1", t))
    assert ag.client.events[-1][1] == "fresh"


def test_missing_transcript_streams_nothing(ag) -> None:
    ctx = ag.on_sync.run(payload("c1", ag.tmp / "absent.jsonl"))
    assert ctx is not None and ag.client.events == []


def test_conversations_are_isolated(ag) -> None:
    t1, t2 = ag.tmp / "a.jsonl", ag.tmp / "b.jsonl"
    append(t1, *TURN)
    append(t2, rec(0, "USER_INPUT", content="sub"))
    ag.on_sync.run(payload("parent", t1))
    ag.on_sync.run(payload("child", t2))
    assert ag.client.sessions == ["parent", "child"]
    assert {e[2] for e in ag.client.events} == {"parent", "child"}
    assert (ag.root / "parent" / "state.json").is_file()
    assert (ag.root / "child" / "state.json").is_file()


def test_unsafe_conversation_id_ignored(ag) -> None:
    assert ag.on_sync.run(payload("../evil", ag.tmp / "t.jsonl")) is None
    assert ag.on_sync.run(payload("", ag.tmp / "t.jsonl")) is None
    assert not (ag.tmp / "ag-data").exists()


def test_not_configured_is_a_noop(ag, monkeypatch) -> None:
    monkeypatch.setattr(ag.on_sync, "is_configured", lambda: False)
    assert ag.on_sync.run(payload("c1", ag.tmp / "t.jsonl")) is None
    assert not (ag.tmp / "ag-data").exists()


def test_first_sight_prunes_stale_conversations(ag) -> None:
    old, recent = ag.root / "old", ag.root / "recent"
    old.mkdir(parents=True)
    recent.mkdir()
    stale = time.time() - 8 * 24 * 3600
    os.utime(old, (stale, stale))
    ag.on_sync.run(payload("new", ag.tmp / "t.jsonl"))
    assert not old.exists() and recent.exists() and (ag.root / "new").exists()


@pytest.mark.parametrize("script", ["on_sync"])
def test_main_prints_exactly_empty_object(ag, monkeypatch, capsys, script) -> None:
    t = ag.tmp / "t.jsonl"
    append(t, *TURN)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload("c1", t))))
    getattr(ag, script).main()
    assert capsys.readouterr().out == "{}\n"


def test_main_prints_empty_object_even_on_crash(ag, monkeypatch, capsys) -> None:
    def boom(_payload):
        raise RuntimeError("x")

    monkeypatch.setattr(ag.on_sync, "run", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    ag.on_sync.main()
    assert capsys.readouterr().out == "{}\n"
