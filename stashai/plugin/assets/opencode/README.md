# Stash Plugin for opencode

Streams opencode sessions to your Stash.

## Prerequisites

- `stash` CLI installed (on PATH) and signed in
- opencode installed — V1 or V2 (opencode transpiles TS directly, no build step needed)

Streaming is gated globally: it is on whenever you are signed in
(`stash signin`) and haven't stopped recording (`stash stop`).

## Install

The same plugin file serves both host versions.

**opencode V2** — drop `plugin.ts` into a project's `.opencode/plugins/`
directory (create it if needed). The file is self-contained with zero npm
dependencies, so a symlink into the repo works:

```bash
mkdir -p .opencode/plugins
ln -s /absolute/path/to/stash/plugins/opencode-plugin/plugin.ts .opencode/plugins/stash.ts
```

Config-entry installs (`"plugins": ["/absolute/dir"]`) are the documented
form, but opencode 2.0.18 silently ignores configured local directory
entries — only `.opencode/plugins/` discovery was verified to load. V2 also
rejects direct `.ts` file entries in config with "configured plugin path
must be a directory".

**opencode V1** — point the `plugin` key (singular) at the file:

```jsonc
{
  "plugin": ["/absolute/path/to/stash/plugins/opencode-plugin/plugin.ts"]
}
```

For project-local discovery, V1 uses `.opencode/plugin/` and V2 discovers
both `.opencode/plugin/` and `.opencode/plugins/`.

Also drop `AGENTS.md` beside your opencode config so the agent knows the
`stash` CLI is available:

```bash
cat AGENTS.md >> ~/.config/opencode/AGENTS.md
```

Restart opencode.

## How it works

`plugin.ts` default-exports `{id, setup}` for the V2 plugin supervisor and
keeps the V1 `StashPlugin` named export. Each handler pipes its payload into
`stash hook run opencode <event>`, which runs the hook scripts shipped inside
the `stashai` package under the package's own Python — identical to the
Claude/Gemini/Codex plugins.

| opencode signal | Stash event |
|---|---|
| V2 `session.hook("prompt")` / V1 `chat.message` | `user_message` |
| V2 `tool.hook("execute.after")` / V1 `tool.execute.after` | `tool_use` |
| bus event `session.created` | `session_start` (records session id + cwd) |
| bus event `session.deleted` | `session_end` (clears state) |

V2 runs one shared service for every project, so the plugin cannot take the
cwd from a per-client worktree like on V1: it resolves the working directory
per session from `session.created`'s location, falling back to the directory
the plugin loaded in.

Ignored on purpose: `session.idle` only refreshes the idle timer (it fires on
every turn completion, not session end), `message.updated` streams repeatedly.
Capturing final assistant text per turn is a future TODO.

## Commands

Everything is a plain `stash` CLI subcommand — no opencode-specific slash commands:

| Command | Description |
|---------|-------------|
| `stash signin` | Sign in + first-run setup (re-run the wizard anytime: `stash setup`) |
| `stash settings` | Interactive settings page (streaming, scope, endpoint, …) |
| `stash stop` | Pause session recording across every installed plugin (`stash start` resumes) |

## Known gaps

- No final-assistant-message capture — `session.idle` fires too often to treat as "stop."

## Retrieval

opencode agents have shell access. Point the agent at the `stash` CLI for reads mid-conversation. Use `stash vfs` for filesystem-style browsing without an OS mount:

```
stash vfs "find /me -maxdepth 3 -type f"
stash vfs "rg \"database migration\" /me"
stash vfs "cat '/me/README.md'"
stash vfs "cat '/me/sessions/_index.jsonl'"
stash search "<query>"
stash whoami --json
```
