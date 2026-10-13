"""Antigravity transcript → canonical HookEvents.

Purpose: Antigravity hook payloads carry only metadata (conversationId,
transcriptPath, workspacePaths), never the prompt or reply text, so the
plugin reads the conversation transcript instead. This module is pure:
it tails the JSONL file safely and maps steps to HookEvents.

Usage:
    lines, offset = read_new_lines(transcript_path, saved_offset)
    events = events_from_lines(lines, conversation_id, cwd, transcript_path)

Transcript facts this relies on (verified against live transcripts):
- One JSON object per line, appended in completion order (NOT step order).
- Tool-call arg values are themselves JSON-encoded strings; long values may be
  truncated mid-string, which makes them undecodable.
- USER_INPUT content wraps the prompt in <USER_REQUEST>…</USER_REQUEST>.
"""

from __future__ import annotations

import json
import re

from stashai.plugin.event import HookEvent

TOOL_NAME_MAP = {
    "run_command": "bash",
    "view_file": "read",
    "write_to_file": "write",
    "replace_file_content": "edit",
    "multi_replace_file_content": "edit",
    "grep_search": "grep",
    "list_dir": "glob",
    "find_by_name": "glob",
    "invoke_subagent": "agent",
}

# Claude-style keys that stashai.plugin.summarize.summarize_tool_use reads,
# mapped from the Antigravity arg that carries the same value.
_ARG_ALIASES = {
    "run_command": {"command": "CommandLine"},
    "view_file": {"file_path": "AbsolutePath"},
    "write_to_file": {"file_path": "TargetFile"},
    "replace_file_content": {
        "file_path": "TargetFile",
        "old_string": "TargetContent",
        "new_string": "ReplacementContent",
    },
    "multi_replace_file_content": {"file_path": "TargetFile"},
    "grep_search": {"pattern": "Query", "path": "SearchPath"},
    "list_dir": {"pattern": "DirectoryPath"},
    "find_by_name": {"pattern": "Pattern"},
}

_UI_ONLY_ARGS = {"toolAction", "toolSummary"}
_REQUEST_RE = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.DOTALL)


def read_new_lines(path: str, offset: int) -> tuple[list[str], int]:
    """Return complete lines written after `offset`, and the new offset.

    Only consumes through the last newline so a line Antigravity is still
    writing is picked up whole on the next call. A file smaller than the
    offset (rewritten/rotated) restarts from 0. Unreadable → ([], offset).
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            if f.tell() < offset:
                offset = 0
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return [], offset
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset
    # Split the raw bytes on LF only: str.splitlines() would also break on
    # U+2028/U+0085/U+2029, which occur inside JSON string content.
    lines = [
        line.decode("utf-8", errors="replace")
        for line in chunk[: end + 1].split(b"\n")
        if line.strip()
    ]
    return lines, offset + end + 1


def _decode(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        # Truncated JSON string: keep the text, drop the dangling opening quote.
        return value[1:] if value.startswith('"') else value


def normalize_tool_input(raw_name: str, args: dict) -> dict:
    """Decode arg values, drop UI-only keys, add summarize-friendly aliases."""
    decoded = {k: _decode(v) for k, v in args.items() if k not in _UI_ONLY_ARGS}
    extra = {}
    for dst, src in _ARG_ALIASES.get(raw_name, {}).items():
        if isinstance(decoded.get(src), str):
            extra[dst] = decoded[src]
    if raw_name == "invoke_subagent" and isinstance(decoded.get("Subagents"), list):
        roles = [
            s["Role"]
            for s in decoded["Subagents"]
            if isinstance(s, dict) and isinstance(s.get("Role"), str)
        ]
        if roles:
            extra["description"] = ", ".join(roles)
    return {**decoded, **extra}


def _step_index(rec: dict) -> int | None:
    try:
        return int(rec.get("step_index"))
    except (TypeError, ValueError):
        return None


def _parse(lines: list[str]) -> list[dict]:
    recs = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            recs.append(rec)
    indexed = sorted((r for r in recs if _step_index(r) is not None), key=_step_index)
    return indexed + [r for r in recs if _step_index(r) is None]


def _prompt_text(content: str) -> str:
    match = _REQUEST_RE.search(content)
    return (match.group(1) if match else content).strip()


def _tool_calls(rec: dict) -> list[dict]:
    calls = rec.get("tool_calls")
    if isinstance(calls, str):
        try:
            calls = json.loads(calls)
        except ValueError:
            return []
    if not isinstance(calls, list):
        return []
    return [c for c in calls if isinstance(c, dict)]


def _args(call: dict) -> dict:
    args = call.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return {}
    return args if isinstance(args, dict) else {}


def events_from_lines(
    lines: list[str], session_id: str, cwd: str, transcript_path: str
) -> list[HookEvent]:
    """Map transcript lines to HookEvents in step order (see module docstring)."""
    base = {"session_id": session_id, "cwd": cwd, "transcript_path": transcript_path}
    out: list[HookEvent] = []
    for rec in _parse(lines):
        step_type = rec.get("type")
        if step_type == "USER_INPUT":
            text = _prompt_text(str(rec.get("content") or ""))
            if text:
                out.append(HookEvent(kind="prompt", prompt_text=text, **base))
        elif step_type == "PLANNER_RESPONSE":
            calls = _tool_calls(rec)
            for call in calls:
                raw = str(call.get("name") or "")
                if not raw:
                    continue
                out.append(
                    HookEvent(
                        kind="tool_use",
                        tool_name=TOOL_NAME_MAP.get(raw, raw),
                        tool_input=normalize_tool_input(raw, _args(call)),
                        **base,
                    )
                )
            content = str(rec.get("content") or "")
            if not calls and content.strip():
                out.append(HookEvent(kind="stop", last_assistant_message=content, **base))
    return out
