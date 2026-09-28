/**
 * Behavioral tests for plugin.ts (dual V1/V2 opencode plugin).
 *
 * How to run: `bun test plugins/opencode-plugin/` from the repo root.
 *
 * The test replaces `stash` on PATH with a shim script that appends each
 * invocation's argv + stdin payload to $STASH_SHIM_LOG, so the assertions
 * cover the REAL spawn pipeline: hook fired -> `stash hook run opencode
 * <event>` -> JSON payload on stdin. No mocks of child_process.
 *
 * V2 side: `setup(ctx)` is driven with a stub ctx that records hook
 * registrations and exposes a pushable event stream, mirroring the shapes
 * documented for @opencode/plugin on OpenCode V2 (verified against 2.0.18:
 * prompt hook {sessionID, prompt:{text}}, tool execute.after {tool,
 * sessionID, input, status, result|error}, bus events {type, data}).
 *
 * V1 side: the named export StashPlugin is driven with the V1 keyed-hook
 * shapes, proving the dual export still serves V1 hosts.
 */

import { afterEach, beforeAll, describe, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import plugin, { StashPlugin } from "./plugin";

// One stanza per `stash` invocation: argv line, then the JSON payload line.
type Stanza = { argv: string; payload: any };

let shimLog = "";
// Read cursor: each waitForStanzas(n) returns the n stanzas emitted since
// the previous waitForStanzas call (or test start), never repeats.
let cursor = 0;

function readStanzas(): Stanza[] {
  if (!existsSync(shimLog)) return [];
  const lines = readFileSync(shimLog, "utf8").split("\n").filter((l) => l !== "");
  const out: Stanza[] = [];
  for (let i = 0; i + 1 < lines.length; i += 2) {
    out.push({ argv: lines[i], payload: JSON.parse(lines[i + 1]) });
  }
  return out;
}

// The plugin spawns fire-and-forget children; poll until n new stanzas land.
async function waitForStanzas(n: number): Promise<Stanza[]> {
  const deadline = Date.now() + 5_000;
  for (;;) {
    const all = readStanzas();
    if (all.length - cursor >= n) {
      const fresh = all.slice(cursor, cursor + n);
      cursor += n;
      return fresh;
    }
    if (Date.now() > deadline) {
      throw new Error(
        `timeout: got ${all.length - cursor}/${n} stanzas: ${JSON.stringify(all.slice(cursor))}`,
      );
    }
    await new Promise((r) => setTimeout(r, 25));
  }
}

beforeAll(() => {
  const dir = mkdtempSync(join(tmpdir(), "stash-plugin-test-"));
  shimLog = join(dir, "calls.log");
  const shim = join(dir, "stash");
  writeFileSync(
    shim,
    [
      "#!/bin/sh",
      'printf \'%s\\n\' "$*" >> "$STASH_SHIM_LOG"',
      'cat >> "$STASH_SHIM_LOG"',
      'printf \'\\n\' >> "$STASH_SHIM_LOG"',
      "",
    ].join("\n"),
  );
  chmodSync(shim, 0o755);
  process.env.STASH_SHIM_LOG = shimLog;
  process.env.PATH = `${dir}:${process.env.PATH}`;
});

// Pending 10-min idle timers would keep the bun test process alive, and the
// read cursor must not leak stanzas across tests.
afterEach(() => {
  cursor = readStanzas().length;
});

/** Pushable async event stream standing in for ctx.event.subscribe(). */
function makeEventBus() {
  const buffered: any[] = [];
  let wake: (() => void) | null = null;
  return {
    emit(ev: any) {
      buffered.push(ev);
      wake?.();
    },
    stream: {
      async *[Symbol.asyncIterator]() {
        let i = 0;
        for (;;) {
          while (i < buffered.length) yield buffered[i++];
          await new Promise<void>((resolve) => {
            wake = resolve;
          });
        }
      },
    },
  };
}

type Ctx = {
  location: { directory: string };
  session: { hook: (name: string, cb: (ev: any) => any) => Promise<any> };
  tool: { hook: (name: string, cb: (ev: any) => any) => Promise<any> };
  event: { subscribe: () => AsyncIterable<any> };
};

/** Stub V2 plugin context; hooks dict records what setup() registered. */
function makeCtx(hooks: Record<string, (ev: any) => any>): { ctx: Ctx; bus: ReturnType<typeof makeEventBus> } {
  const bus = makeEventBus();
  const ctx: Ctx = {
    location: { directory: "/v2/instance/cwd" },
    session: {
      hook: (name, cb) => {
        hooks[`session.${name}`] = cb;
        return Promise.resolve({ dispose: () => {} });
      },
    },
    tool: {
      hook: (name, cb) => {
        hooks[`tool.${name}`] = cb;
        return Promise.resolve({ dispose: () => {} });
      },
    },
    event: { subscribe: () => bus.stream },
  };
  return { ctx, bus };
}

describe("V2 setup()", () => {
  test("default export is a {id, setup} definition for the V2 supervisor", () => {
    expect(typeof plugin).toBe("object");
    expect((plugin as any).id).toBe("stash");
    expect(typeof (plugin as any).setup).toBe("function");
  });

  test("returns quietly when a V1 host calls setup with a V1-shaped ctx", async () => {
    await (plugin as any).setup({});
  });

  test("prompt hook streams on_prompt with text and instance cwd", async () => {
    const hooks: Record<string, (ev: any) => any> = {};
    const { ctx } = makeCtx(hooks);
    const cleanup = await (plugin as any).setup(ctx);

    hooks["session.prompt"]({ sessionID: "s1", prompt: { text: "hello world" } });

    const [stanza] = await waitForStanzas(1);
    expect(stanza.argv).toBe("hook run opencode on_prompt");
    expect(stanza.payload).toEqual({ session_id: "s1", prompt: "hello world", cwd: "/v2/instance/cwd" });
    cleanup();
  });

  test("session.created streams on_session_start with the session's own directory", async () => {
    const hooks: Record<string, (ev: any) => any> = {};
    const { ctx, bus } = makeCtx(hooks);
    const cleanup = await (plugin as any).setup(ctx);

    bus.emit({ type: "session.created", data: { sessionID: "s2", location: { directory: "/proj/real/cwd" } } });

    const [stanza] = await waitForStanzas(1);
    expect(stanza.argv).toBe("hook run opencode on_session_start");
    expect(stanza.payload).toEqual({ session_id: "s2", cwd: "/proj/real/cwd" });
    cleanup();
  });

  test("prompt after session.created resolves cwd from the session, not the instance", async () => {
    const hooks: Record<string, (ev: any) => any> = {};
    const { ctx, bus } = makeCtx(hooks);
    const cleanup = await (plugin as any).setup(ctx);

    bus.emit({ type: "session.created", data: { sessionID: "s2", location: { directory: "/proj/real/cwd" } } });
    await waitForStanzas(1);
    hooks["session.prompt"]({ sessionID: "s2", prompt: { text: "again" } });

    const [promptStanza] = await waitForStanzas(1);
    expect(promptStanza.payload).toEqual({ session_id: "s2", prompt: "again", cwd: "/proj/real/cwd" });
    cleanup();
  });

  test("tool execute.after (completed) streams on_tool_use with the result", async () => {
    const hooks: Record<string, (ev: any) => any> = {};
    const { ctx, bus } = makeCtx(hooks);
    const cleanup = await (plugin as any).setup(ctx);
    bus.emit({ type: "session.created", data: { sessionID: "s2", location: { directory: "/proj/real/cwd" } } });
    await waitForStanzas(1);

    hooks["tool.execute.after"]({
      tool: "read",
      sessionID: "s2",
      input: { path: "x.ts" },
      status: "completed",
      result: { output: "file body", metadata: { lines: 3 } },
    });

    const [stanza] = await waitForStanzas(1);
    expect(stanza.argv).toBe("hook run opencode on_tool_use");
    expect(stanza.payload).toEqual({
      session_id: "s2",
      tool_name: "read",
      tool_input: { path: "x.ts" },
      tool_response: { output: "file body", metadata: { lines: 3 } },
      cwd: "/proj/real/cwd",
    });
    cleanup();
  });

  test("tool execute.after (error) records the error as the response", async () => {
    const hooks: Record<string, (ev: any) => any> = {};
    const { ctx } = makeCtx(hooks);
    const cleanup = await (plugin as any).setup(ctx);

    hooks["tool.execute.after"]({
      tool: "edit",
      sessionID: "s1",
      input: { path: "y.ts" },
      status: "error",
      error: { message: "boom" },
    });

    const [stanza] = await waitForStanzas(1);
    expect(stanza.payload.tool_response).toEqual({ error: { message: "boom" } });
    cleanup();
  });

  test("session.deleted streams on_session_end", async () => {
    const hooks: Record<string, (ev: any) => any> = {};
    const { ctx, bus } = makeCtx(hooks);
    const cleanup = await (plugin as any).setup(ctx);

    bus.emit({ type: "session.deleted", data: { sessionID: "s9" } });

    const [stanza] = await waitForStanzas(1);
    expect(stanza.argv).toBe("hook run opencode on_session_end");
    expect(stanza.payload.session_id).toBe("s9");
    cleanup();
  });
});

describe("V1 named export (dual compatibility)", () => {
  test("chat.message still streams on_prompt with the V1 worktree cwd", async () => {
    const hooks = await StashPlugin({ worktree: "/v1/wt" });
    hooks["chat.message"](undefined, {
      message: { sessionID: "v1" },
      parts: [{ type: "text", text: "hi from v1" }],
    });

    const [stanza] = await waitForStanzas(1);
    expect(stanza.argv).toBe("hook run opencode on_prompt");
    expect(stanza.payload).toEqual({ session_id: "v1", prompt: "hi from v1", cwd: "/v1/wt" });

    // Cancel the 10-min idle timer the handler scheduled (and cover the V1
    // deleted path while we are here).
    await hooks.event({ event: { type: "session.deleted", properties: { info: { id: "v1" } } } });
  });
});
