#!/usr/bin/env python3
"""Antigravity PreInvocation + PostToolUse hook: stream new transcript steps.

Purpose: Antigravity payloads carry no prompt/reply text, so each call tails
the conversation transcript from a saved byte offset and streams the new
steps (user_message / tool_use / assistant_message). The first call for a
conversationId also creates the Stash session row and runs the usual
session-start chores (skills sync, self-upgrade, stale-state pruning).

Usage: wired by plugin/hooks.json as `stash hook run antigravity on_sync`
(payload JSON on stdin). `run(payload)` is also imported by on_stop.
Contract: stdout is always exactly `{}` — Antigravity requires a JSON object.
"""

from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path
from typing import NamedTuple

from adapt import events_from_lines, read_new_lines
from config import (
    conversation_dir,
    get_client,
    get_config,
    get_stdin_data,
    is_configured,
    state_root,
)

from stashai.plugin.event import HookEvent
from stashai.plugin.hooks import (
    create_session_record,
    reset_session_record_state,
    stream_assistant_message,
    stream_tool_use,
    stream_user_message,
    uploads_enabled,
)
from stashai.plugin.session_upload import spawn_self_upgrade, spawn_skills_sync
from stashai.plugin.state import load_state, reset_stats, save_state

PRUNE_AFTER_SECONDS = 7 * 24 * 3600
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class SyncContext(NamedTuple):
    conversation_id: str
    transcript_path: str
    cwd: str
    data_dir: Path
    cfg: dict


def emit_ok() -> None:
    sys.stdout.write("{}\n")
    sys.stdout.flush()


def prune_stale(root: Path, keep: str, now: float | None = None) -> None:
    """Remove conversation dirs untouched for PRUNE_AFTER_SECONDS (except `keep`)."""
    now = time.time() if now is None else now
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name == keep or not entry.is_dir():
            continue
        try:
            if now - entry.stat().st_mtime > PRUNE_AFTER_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _stream(client, cfg: dict, state: dict, data_dir: Path, event: HookEvent) -> None:
    if event.kind == "prompt":
        stream_user_message(client, cfg, state, event.prompt_text, event)
    elif event.kind == "tool_use":
        stream_tool_use(client, cfg, state, event, data_dir)
    elif event.kind == "stop":
        stream_assistant_message(client, cfg, state, event)


def run(payload: dict) -> SyncContext | None:
    """Sync one conversation; returns its context, or None when skipped."""
    if not is_configured():
        return None
    cid = str(payload.get("conversationId") or "")
    if not _SAFE_ID.fullmatch(cid):
        return None
    transcript = str(payload.get("transcriptPath") or "")
    paths = payload.get("workspacePaths")
    cwd = str(paths[0]) if isinstance(paths, list) and paths else ""
    data_dir = conversation_dir(cid)
    cfg = get_config()

    state = load_state(data_dir)
    first_sight = state.get("session_id") != cid
    if first_sight:
        reset_session_record_state(state)
        state["session_id"] = cid
        state["offset"] = 0
        save_state(data_dir, state)
        reset_stats(data_dir)
        state = load_state(data_dir)

    offset = int(state.get("offset") or 0)
    lines, new_offset = read_new_lines(transcript, offset) if transcript else ([], offset)
    # Persist before streaming: at-most-once delivery, never duplicates.
    state["offset"] = new_offset
    save_state(data_dir, state)

    events = events_from_lines(lines, cid, cwd, transcript)
    enabled = uploads_enabled(cfg)
    try:
        with get_client(data_dir) as client:
            if first_sight and enabled:
                start = HookEvent(
                    kind="session_start", session_id=cid, cwd=cwd, transcript_path=transcript
                )
                create_session_record(client, cfg, state, start, data_dir)
            for event in events:
                _stream(client, cfg, state, data_dir, event)
    except Exception:
        pass

    if first_sight and enabled:
        spawn_skills_sync(cfg)
        spawn_self_upgrade()
        prune_stale(state_root() / "conversations", keep=cid)
    return SyncContext(cid, transcript, cwd, data_dir, cfg)


def main() -> None:
    try:
        run(get_stdin_data())
    except Exception:
        pass
    finally:
        emit_ok()


if __name__ == "__main__":
    main()
