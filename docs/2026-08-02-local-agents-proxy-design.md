# Local `/agents` chat via a local LLM proxy — design

Date: 2026-08-02
Status: Approved (brainstorming, Approach 1)

## Goal

On a **local-only** Docker self-host of Stash, the `/agents` UI chat should run
against a local LLM proxy (the Docker Desktop LLM proxy at
`http://172.17.0.1:20128`) instead of failing with "The agent turn failed.
Try again."

Background (verified):
- `/agents` chat → `POST /api/v1/me/agent-chat` → `sprite_agent_service.stream_chat`
  → `_turn_events` → `sprite_service.exec_stream(argv=["claude", "-p", …], env=…)`.
- `AGENT_EXEC_MODE` defaults to `"local"`, which runs the `claude` CLI as a
  subprocess **inside the backend container**.
- The backend image does **not** ship `claude` (no Node either), so the spawn
  dies with `FileNotFoundError`, swallowed by the generic `Exception` catch and
  surfaced as the generic turn-failed message.
- The Ask-the-Stash path (`/api/v1/me/ask`) uses the in-process `AsyncAnthropic`
  and already works against the proxy; this design is only for the `/agents` UI.

## Changes

### 1. Backend image — install native `claude`

In `backend/Dockerfile`, install the Claude Code native binary onto `PATH`
(matching how cloud sprites ship it). So `exec_stream` can spawn `claude`.

### 2. Local-mode env — carry proxy config into the child

`agent_auth.resolve` returns `RunAuth(harness=CLAUDE)` with empty env in local
mode. Change it so, when `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` are set in
the container env, they are included in `auth.env`.

`_local_exec_stream` builds the child env as `env={**inherited, **auth.env}`,
where `inherited` is the backend `os.environ` minus `ANTHROPIC_API_KEY`. The
explicit `auth.env` therefore restores `ANTHROPIC_API_KEY` (and adds
`ANTHROPIC_BASE_URL`) for the child `claude`.

Verified: the `claude` CLI sends the API key the same way the SDK does and works
against the proxy with just `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` (probe
returned `PONG`).

## Data flow

`/agents` chat → `POST /api/v1/me/agent-chat` → `stream_chat` → `_turn_events` →
`exec_stream(["claude","-p",prompt,…], env={**inherited, **auth.env})` → child
`claude` reads `ANTHROPIC_BASE_URL` → proxy at `172.17.0.1:20128`.

## Error handling / non-regression

- If `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY` are unset locally, local mode
  keeps working via the host's own claude login (existing behavior — no
  regression). The proxy-config passthrough is additive.
- Keep the child env construction (`env={**inherited, **auth.env}`) unchanged so
  the `ANTHROPIC_API_KEY` strip + explicit override still holds for the cloud/
  managed paths.

## Testing

1. Rebuild the backend image; restart the local stack.
2. `/agents` chat → returns a streamed reply proxied to the local model.
3. Ask-the-Stash (`POST /api/v1/me/ask`) still streams (regression).
4. Clean up any test API keys minted during verification.
