# Stash Plugin for Antigravity

Streams Antigravity conversations to your Stash: prompts, tool calls, final
replies, and a transcript snapshot when the agent goes idle.

## Prerequisites

- `stash` CLI installed and signed in (`uv tool install stashai && stash signin`)
- Antigravity with native plugin support (`~/.gemini/config/plugins/`)

## Install

`stash setup` detects Antigravity (`agy` on PATH or `~/.gemini/antigravity/`)
and copies `plugin/` to `~/.gemini/config/plugins/stash/`. It also upserts the
Stash context block into `~/.gemini/GEMINI.md` (shared with Gemini CLI — one
block total). Start a **new** Antigravity conversation to load the hooks.

Antigravity does not run hooks from `~/.gemini/settings.json`, so this plugin
and the Gemini CLI plugin never double-stream.

## How it works

Antigravity hook payloads carry no prompt or reply text, so every hook tails
the conversation's `transcriptPath` from a saved byte offset:

| Antigravity hook | Script | Does |
|---|---|---|
| `PreInvocation` | `on_sync` | first sight → create session; stream new transcript steps |
| `PostToolUse` (`*`) | `on_sync` | stream new transcript steps |
| `Stop` | `on_stop` | stream new steps; when `fullyIdle`, upload transcript (60 s cooldown) |

| Transcript step | Stash event |
|---|---|
| `USER_INPUT` | `user_message` (text inside `<USER_REQUEST>`) |
| `PLANNER_RESPONSE` with `tool_calls` | one `tool_use` per call |
| `PLANNER_RESPONSE` without `tool_calls` | `assistant_message` |

State is per conversation under `~/.stash/plugins/antigravity/conversations/`
(subagents and parallel chats each get their own session); directories idle
for 7+ days are pruned.

## Known gaps

- Planner narration that accompanies tool calls is not streamed.
- Tool results are not attached to `tool_use` events.
- Upload failures are not shown on the Desktop upload-health card.
