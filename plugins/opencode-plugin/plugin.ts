/**
 * Stash plugin for opencode — dual-compatible with V1 and V2.
 *
 * Thin TS shim: each opencode event handler serializes its input and pipes it
 * into `stash hook run opencode <event>` via stdin. The hook scripts ship
 * inside the stashai package and run under its Python, reused from every
 * other agent's plugin. The outbound JSON contract (consumed by
 * scripts/adapt.py) is identical on both host versions.
 *
 * Loading paths:
 * - V2 (opencode 2.x): the supervisor reads the default export `{id, setup}`
 *   and calls `setup(ctx)`. Hooks are registered on domain objects
 *   (`ctx.session.hook("prompt")`, `ctx.tool.hook("execute.after")`) and bus
 *   events arrive through `ctx.event.subscribe()`.
 * - V1 (opencode 1.x): named export `StashPlugin` (keyed-hook return shape).
 *   V1 hosts may also probe `default.setup` with a V1-shaped ctx — setup
 *   detects the missing domains and returns quietly.
 *
 * Install: V1 — reference this file from the `plugin` config key. V2 — drop
 * it into a project's `.opencode/plugins/` directory (2.0.18 ignores
 * configured local directory entries). See README.
 */

import { spawn } from "node:child_process";

// opencode never emits a clean session-end signal. After this much idle time
// inside a live opencode process, treat the session as ended and fire
// on_session_end.py. Reset on every activity event (chat, tool, session.idle).
const IDLE_END_MS = 10 * 60 * 1000;

let idleTimer: ReturnType<typeof setTimeout> | null = null;
let activeSessionId = "";
let activeCwd = "";

function scheduleIdleEnd(sessionId: string): void {
  if (idleTimer) clearTimeout(idleTimer);
  if (!sessionId) return;
  activeSessionId = sessionId;
  idleTimer = setTimeout(() => {
    runHook("on_session_end", { session_id: sessionId, cwd: activeCwd });
    activeSessionId = "";
    idleTimer = null;
  }, IDLE_END_MS);
}

function cancelIdleEnd(): void {
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = null;
  activeSessionId = "";
}

function runHook(event: string, payload: unknown, showOutput = false): void {
  // Fire-and-forget. We never want a flaky Stash backend to stall opencode.
  // detached + unref so the child belongs to its own process group and gets
  // reaped independently — otherwise zombies accumulate over long sessions.
  // `stash hook run` executes the script shipped inside the stashai package,
  // under the package's own python.
  try {
    const stdio: ["pipe", "pipe", "pipe"] | ["pipe", "ignore", "ignore"] =
      showOutput ? ["pipe", "pipe", "pipe"] : ["pipe", "ignore", "ignore"];
    const child = spawn("stash", ["hook", "run", "opencode", event], {
      stdio,
      detached: !showOutput,
    });
    child.on("error", () => { /* stash missing / crash — swallow */ });
    if (showOutput) {
      child.stdout?.on("data", (chunk) => process.stderr.write(chunk));
      child.stderr?.on("data", (chunk) => process.stderr.write(chunk));
    }
    child.stdin?.write(JSON.stringify(payload));
    child.stdin?.end();
    if (!showOutput) {
      child.unref();
    }
  } catch {
    // spawn failed synchronously — swallow
  }
}

function extractText(parts: any[] | undefined): string {
  if (!Array.isArray(parts)) return "";
  return parts
    .filter((p) => p?.type === "text")
    .map((p) => p?.text ?? "")
    .join("\n");
}

export const StashPlugin = async ({
  project,
  worktree,
}: {
  project?: { worktree?: string };
  worktree?: string;
}) => {
  const cwd = worktree ?? project?.worktree ?? "";
  activeCwd = cwd;

  return {
    // Keyed hook: fires once per user message.
    "chat.message": async (
      _input: unknown,
      output: { message: any; parts: any[] },
    ) => {
      const text = extractText(output?.parts) || output?.message?.content || "";
      const sid = output?.message?.sessionID ?? "";
      runHook("on_prompt", { session_id: sid, prompt: text, cwd });
      scheduleIdleEnd(sid);
    },

    // Keyed hook: fires once per tool call, after execution.
    // Real signature: (input, output) where
    //   input = {tool, sessionID, callID, args}
    //   output = {title, output, metadata}
    "tool.execute.after": async (
      input: { tool: string; sessionID: string; callID: string; args: any },
      output: { title: string; output: string; metadata: any },
    ) => {
      runHook("on_tool_use", {
        session_id: input?.sessionID ?? "",
        tool_name: input?.tool ?? "",
        tool_input: input?.args ?? {},
        tool_response: {
          title: output?.title,
          output: output?.output,
          metadata: output?.metadata,
        },
        cwd,
      });
      scheduleIdleEnd(input?.sessionID ?? "");
    },

    // Generic bus-event dispatcher. Every session.* / message.* / file.* event
    // lands here — we switch on event.type.
    event: async ({ event }: { event: { type: string; properties?: any } }) => {
      switch (event?.type) {
        case "session.created": {
          const info = event.properties?.info;
          const sid = info?.id ?? "";
          runHook("on_session_start", { session_id: sid, cwd }, true);
          scheduleIdleEnd(sid);
          break;
        }
        case "session.deleted": {
          const info = event.properties?.info;
          runHook("on_session_end", { session_id: info?.id ?? "", cwd });
          cancelIdleEnd();
          break;
        }
        case "session.idle": {
          // session.idle fires every turn completion — refresh the idle timer
          // so the 10-min countdown only fires after real inactivity.
          scheduleIdleEnd(activeSessionId);
          break;
        }
      }
    },
  };
};

// ---------------------------------------------------------------------------
// V2 (opencode 2.x) plugin definition.
// ---------------------------------------------------------------------------

type V2Event = { type: string; data?: any };

// Structural subset of the V2 plugin context (@opencode/plugin). Inline on
// purpose: the plugin ships with zero npm dependencies, like every other
// agent shim in this repo.
type V2Ctx = {
  location?: { directory?: string };
  session?: { hook?: (name: string, cb: (event: any) => any) => Promise<unknown> };
  tool?: { hook?: (name: string, cb: (event: any) => any) => Promise<unknown> };
  event?: { subscribe?: (options?: { signal?: AbortSignal }) => AsyncIterable<V2Event> };
};

async function setup(ctx: V2Ctx): Promise<() => void> {
  // V1 hosts (~1.18.x) also invoke default.setup with a V1-shaped ctx that
  // lacks the V2 domain methods — V1 is served by the named export instead.
  const session = ctx?.session;
  const tool = ctx?.tool;
  const events = ctx?.event;
  if (
    typeof session?.hook !== "function" ||
    typeof tool?.hook !== "function" ||
    typeof events?.subscribe !== "function"
  ) {
    return () => {};
  }

  // V2 runs one shared service for every project, so this instance's own
  // location is only the fallback cwd; session.created reports each
  // session's real directory. The service is long-lived, so bound the map by
  // dropping the oldest quarter when it fills (Map iterates insertion order).
  const instanceCwd = ctx.location?.directory ?? "";
  const sessionDirs = new Map<string, string>();
  const cwdFor = (sid: string): string => sessionDirs.get(sid) ?? instanceCwd;

  // V2 equivalent of chat.message: fires once per admitted user prompt,
  // before it enters the session inbox.
  await session.hook!("prompt", (event: any) => {
    const sid = event?.sessionID ?? "";
    activeCwd = cwdFor(sid);
    runHook("on_prompt", { session_id: sid, prompt: event?.prompt?.text ?? "", cwd: activeCwd });
    scheduleIdleEnd(sid);
  });

  // V2 equivalent of tool.execute.after: one mutable event carries the call
  // input plus either the completed result or the error.
  await tool.hook!("execute.after", (event: any) => {
    const sid = event?.sessionID ?? "";
    activeCwd = cwdFor(sid);
    const toolResponse =
      event?.status === "completed" ? event?.result ?? {} : { error: event?.error };
    runHook("on_tool_use", {
      session_id: sid,
      tool_name: event?.tool ?? "",
      tool_input: event?.input ?? {},
      tool_response: toolResponse,
      cwd: activeCwd,
    });
    scheduleIdleEnd(sid);
  });

  // Bus events, V2 shape: {type, data: {sessionID, ...}}.
  const controller = new AbortController();
  void (async () => {
    for await (const ev of events.subscribe!({ signal: controller.signal })) {
      const sid = ev?.data?.sessionID ?? "";
      switch (ev?.type) {
        case "session.created": {
          const dir = ev?.data?.location?.directory ?? "";
          if (sid && dir) {
            if (sessionDirs.size >= 512) {
              let drop = 128;
              for (const key of sessionDirs.keys()) {
                if (drop-- <= 0) break;
                sessionDirs.delete(key);
              }
            }
            sessionDirs.set(sid, dir);
          }
          activeCwd = dir || instanceCwd;
          runHook("on_session_start", { session_id: sid, cwd: activeCwd }, true);
          scheduleIdleEnd(sid);
          break;
        }
        case "session.deleted": {
          const cwd = cwdFor(sid);
          sessionDirs.delete(sid);
          runHook("on_session_end", { session_id: sid, cwd });
          cancelIdleEnd();
          break;
        }
        case "session.idle": {
          // session.idle fires every turn completion — refresh the idle timer
          // so the 10-min countdown only fires after real inactivity.
          scheduleIdleEnd(activeSessionId);
          break;
        }
      }
    }
  })();

  return () => {
    controller.abort();
    cancelIdleEnd();
  };
}

/**
 * Default export: V2 reads {id, setup}; V1 (1.18.29+) reads server(), and
 * older V1 hosts discover the StashPlugin named export.
 */
export default { id: "stash", server: StashPlugin, setup };
