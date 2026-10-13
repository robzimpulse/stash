"""Unit tests for the Antigravity transcript adapter.

Purpose: Antigravity hook payloads carry no prompt/reply text, so streaming
depends entirely on adapt.py turning transcript JSONL steps into HookEvents
and on read_new_lines never consuming a half-written line.
Usage: uv run pytest -o addopts="" plugins/tests/test_antigravity_adapt.py -q
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PLUGIN_SCRIPTS = Path(__file__).resolve().parent.parent / "antigravity-plugin" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "antigravity"


def _load_adapt():
    spec = importlib.util.spec_from_file_location("adapt_antigravity", PLUGIN_SCRIPTS / "adapt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapt = _load_adapt()


def rec(i, type_, **kw) -> str:
    return json.dumps({"step_index": i, "source": "MODEL", "type": type_, "status": "DONE", **kw})


def call(name, **args) -> dict:
    return {"name": name, "args": {k: json.dumps(v) for k, v in args.items()}}


def events(*lines):
    return adapt.events_from_lines(list(lines), "c1", "/repo", "/t.jsonl")


def test_prompt_extracted_from_user_request_block() -> None:
    content = (
        "<USER_REQUEST>\nfix the bug\n</USER_REQUEST>\n<ADDITIONAL_METADATA>t</ADDITIONAL_METADATA>"
    )
    [ev] = events(rec(0, "USER_INPUT", content=content))
    assert ev.kind == "prompt"
    assert ev.prompt_text == "fix the bug"
    assert (ev.session_id, ev.cwd, ev.transcript_path) == ("c1", "/repo", "/t.jsonl")


def test_prompt_without_tags_uses_whole_content() -> None:
    [ev] = events(rec(0, "USER_INPUT", content="  plain prompt \n"))
    assert ev.prompt_text == "plain prompt"


def test_empty_prompt_skipped() -> None:
    assert events(rec(0, "USER_INPUT", content="<USER_REQUEST>  </USER_REQUEST>")) == []


def test_tool_call_decoded_mapped_and_normalized() -> None:
    line = rec(
        1,
        "PLANNER_RESPONSE",
        tool_calls=[
            call("run_command", CommandLine="ls -la", Cwd="/repo", toolAction="x", toolSummary="y")
        ],
    )
    [ev] = events(line)
    assert ev.kind == "tool_use"
    assert ev.tool_name == "bash"
    assert ev.tool_input == {"CommandLine": "ls -la", "Cwd": "/repo", "command": "ls -la"}


def test_replace_file_content_normalized_for_edit_summary() -> None:
    line = rec(
        1,
        "PLANNER_RESPONSE",
        tool_calls=[
            call(
                "replace_file_content",
                TargetFile="/a.py",
                TargetContent="old",
                ReplacementContent="new",
            )
        ],
    )
    [ev] = events(line)
    assert ev.tool_name == "edit"
    assert ev.tool_input["file_path"] == "/a.py"
    assert ev.tool_input["old_string"] == "old"
    assert ev.tool_input["new_string"] == "new"


def test_unmapped_tool_passes_through() -> None:
    [ev] = events(rec(1, "PLANNER_RESPONSE", tool_calls=[call("browser_click", Selector="#go")]))
    assert ev.tool_name == "browser_click"
    assert ev.tool_input == {"Selector": "#go"}


def test_truncated_arg_value_kept_without_leading_quote() -> None:
    line = rec(
        1,
        "PLANNER_RESPONSE",
        tool_calls=[{"name": "view_file", "args": {"AbsolutePath": '"/Users/alice/very/lo'}}],
    )
    [ev] = events(line)
    assert ev.tool_input["file_path"] == "/Users/alice/very/lo"


def test_tool_calls_as_json_string_accepted() -> None:
    line = rec(1, "PLANNER_RESPONSE", tool_calls=json.dumps([call("view_file", AbsolutePath="/a")]))
    [ev] = events(line)
    assert (ev.tool_name, ev.tool_input["file_path"]) == ("read", "/a")


def test_subagent_roles_become_description() -> None:
    subs = [{"Role": "Researcher", "Prompt": "p"}, {"Role": "Reviewer", "Prompt": "q"}]
    [ev] = events(rec(1, "PLANNER_RESPONSE", tool_calls=[call("invoke_subagent", Subagents=subs)]))
    assert ev.tool_name == "agent"
    assert ev.tool_input["description"] == "Researcher, Reviewer"


def test_assistant_message_only_without_tool_calls() -> None:
    narration = rec(
        1,
        "PLANNER_RESPONSE",
        content="Looking...",
        tool_calls=[call("view_file", AbsolutePath="/a")],
    )
    final = rec(2, "PLANNER_RESPONSE", content="Done.")
    kinds = [(e.kind, e.last_assistant_message) for e in events(narration, final)]
    assert kinds == [("tool_use", ""), ("stop", "Done.")]


def test_generic_and_system_steps_skipped() -> None:
    assert events(rec(2, "GENERIC", content="out"), rec(3, "SYSTEM_MESSAGE", content="n")) == []


def test_sorted_by_step_index_and_bad_lines_skipped() -> None:
    lines = [
        rec(3, "PLANNER_RESPONSE", content="bye"),
        "not json",
        rec(1, "USER_INPUT", content="hi"),
    ]
    assert [e.kind for e in events(*lines)] == ["prompt", "stop"]


def test_fixture_transcript_roundtrip() -> None:
    lines = (FIXTURES / "transcript.jsonl").read_text().splitlines()
    evs = adapt.events_from_lines(lines, "ag-1", "/Users/alice/repo", "/t.jsonl")
    assert [e.kind for e in evs] == ["prompt", "tool_use", "stop"]
    assert evs[0].prompt_text == "list the repo"
    assert evs[1].tool_name == "bash"
    assert evs[1].tool_input["command"] == "ls"
    assert evs[1].tool_input["WaitMsBeforeAsync"] == 5000
    assert evs[2].last_assistant_message == "The repo has a README."


def test_read_new_lines_stops_at_last_newline(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_bytes(b'{"a":1}\n{"b":')
    assert adapt.read_new_lines(str(path), 0) == (['{"a":1}'], 8)
    path.write_bytes(b'{"a":1}\n{"b":2}\n')
    assert adapt.read_new_lines(str(path), 8) == (['{"b":2}'], 16)


def test_read_new_lines_resets_when_file_shrinks(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_bytes(b'{"x":1}\n')
    assert adapt.read_new_lines(str(path), 500) == (['{"x":1}'], 8)


def test_read_new_lines_missing_file_keeps_offset(tmp_path: Path) -> None:
    assert adapt.read_new_lines(str(tmp_path / "nope.jsonl"), 5) == ([], 5)
