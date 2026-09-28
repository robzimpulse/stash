# Stash Plugin for Hermes Agent

Streams Hermes Agent (NousResearch `hermes-agent`) sessions to your Stash.

## Prerequisites

- `stash` CLI installed and signed in (`uv tool install stashai && stash signin`)
- New Hermes builds: nothing else — the installer drops a native plugin.
- Old Hermes builds (no `plugins` subcommand): Hermes ≥ the version that
  shipped shell hooks in `config.yaml`
  (see hermes-agent.nousresearch.com/docs/user-guide/features/hooks)

## Install

`stash signin` detects Hermes (the `hermes` binary or `~/.hermes/`) and wires
this plugin automatically (re-running it refreshes the install; `stash settings`
can toggle agents later).

**New Hermes builds (native plugin):** the installer copies `plugin/` to
`~/.hermes/plugins/stash/` and enables it through Hermes' own
`plugins.enabled` allow-list (`hermes plugins enable stash`). The five session
hooks are registered in-process; each one forwards the event to
`stash hook run hermes <event>` — the same scripts, same streaming behavior as
before. Restart Hermes (or run `hermes gateway restart`) to load it. No
config.yaml hook entries, no per-hook approval prompts.

You can also install straight from this repo without `stash signin`:

```
hermes plugins install https://github.com/robzimpulse/stash#plugins/hermes-plugin/plugin
```

(The `#subdir` fragment matters: the repo root is the whole app; the plugin
lives at that subdirectory. The `stash` CLI must still be installed and signed
in — the plugin shells out to it.)

Upgrading from a shell-hook install is automatic: the installer removes the old
`# stash-plugin:begin/end` marker block from `config.yaml` in the same run, so
events never stream twice.

**Old Hermes builds (shell hooks):** the installer writes the `hooks` entries
from `config.snippet.yaml` into `~/.hermes/config.yaml` inside a
`# stash-plugin:begin` / `# stash-plugin:end` marker block, preserving
everything else in the file. If your config already has its own top-level
`hooks:` block the installer refuses (duplicate YAML keys would silently drop
one of the blocks) — add the snippet entries to your existing block by hand
instead.

### Approve the hooks (shell-hook installs only)

Hermes asks for one-time approval per `(event, command)` pair the first time a
hook fires; approvals persist in `~/.hermes/shell-hooks-allowlist.json`.

- Interactive sessions: approve the five stash hooks when prompted, or run
  `hermes hooks list` to review them first.
- Non-interactive / gateway sessions: pre-approve with `HERMES_ACCEPT_HOOKS=1`,
  `hermes --accept-hooks chat`, or `hooks_auto_accept: true` in config.yaml.
- `hermes hooks doctor` diagnoses hooks that silently stopped firing.

## What streams

| Hermes event | Stash event |
|---|---|
| `on_session_start` | — (creates the session record) |
| `pre_llm_call` | `user_message` (fires once per user turn) |
| `post_tool_call` | `tool_use` |
| `post_llm_call` | `assistant_message` (once per turn, after the tool loop) |
| `on_session_end` | `session_end` + transcript finalize |

Hermes exposes no transcript path, so the session page is materialized from
the streamed events. Hook stdout must be valid JSON for Hermes, so the scripts
always answer `{}` and send any warnings to stderr (Hermes logs).

## Agent context

New installs ship a native skill: `skill_view("stash:stash")` (or
`skills_list` → category `plugin`) teaches the agent the `stash` CLI — no
manual copy step. Old Hermes builds: copy the block in `HERMES.md` into your
project's `HERMES.md` or `AGENTS.md`.

## Commands

Everything is a plain `stash` CLI subcommand — no Hermes-specific commands:

| Command | Description |
|---------|-------------|
| `stash signin` | Interactive setup (auth + install) |
| `stash settings` | Interactive settings page (streaming, endpoint, …) |
| `stash stop` | Pause session recording across every installed plugin (`stash start` resumes) |

## Retrieval

Hermes has terminal access. For reads mid-conversation, let the agent shell
out to the `stash` CLI — all commands support `--json`:

```
stash vfs "cat '/me/sessions/_index.jsonl'"
stash search "<query>"
stash whoami --json
```
