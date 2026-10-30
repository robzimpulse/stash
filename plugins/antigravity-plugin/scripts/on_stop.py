#!/usr/bin/env python3
"""Antigravity Stop hook: final sync, then transcript snapshot when idle.

Purpose: Stop fires when the agent loop ends a turn. We stream any steps
on_sync hasn't seen yet, and — only when Antigravity reports fullyIdle and
this conversation has a Stash session row — spawn the detached transcript
upload. Antigravity has no session-end event, so this is the Codex pattern:
a 60 s per-session cooldown; the backend keeps the latest snapshot.

Usage: wired by plugin/hooks.json as `stash hook run antigravity on_stop`.
Contract: stdout is always exactly `{}`; Stash warnings go to stderr.
"""

from __future__ import annotations

import sys

from config import get_stdin_data
from on_sync import emit_ok, run

from stashai.plugin.event import HookEvent
from stashai.plugin.hooks import color_upload_health_warning, upload_health_warning
from stashai.plugin.state import load_state
from stashai.plugin.transcript_upload import spawn_transcript_upload


def finish(payload: dict) -> None:
    ctx = run(payload)
    if ctx is None:
        return
    state = load_state(ctx.data_dir)
    if payload.get("fullyIdle") is True and state.get("session_row_id"):
        spawn_transcript_upload(
            data_dir=ctx.data_dir,
            transcript_path=ctx.transcript_path,
            session_id=ctx.conversation_id,
            agent_name=ctx.cfg["agent_name"],
            cwd=ctx.cwd,
            base_url=ctx.cfg["api_endpoint"],
            api_key=ctx.cfg["api_key"],
        )
    event = HookEvent(
        kind="stop",
        session_id=ctx.conversation_id,
        cwd=ctx.cwd,
        transcript_path=ctx.transcript_path,
    )
    warning = upload_health_warning(ctx.cfg, state, event, ctx.data_dir)
    if warning:
        print(color_upload_health_warning(warning), file=sys.stderr)


def main() -> None:
    try:
        finish(get_stdin_data())
    except Exception:
        pass
    finally:
        emit_ok()


if __name__ == "__main__":
    main()
