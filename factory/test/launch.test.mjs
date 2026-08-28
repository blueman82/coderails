import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { test } from "node:test";
import { createProjectRegistry } from "../lib/config.mjs";
import { createLauncher } from "../lib/launch.mjs";
import { createRunStore } from "../lib/runs.mjs";

function controlledChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  return child;
}

function launcher({ spawn } = {}) {
  return createLauncher({
    store: createRunStore(),
    projects: createProjectRegistry({ coderails: { cwd: "/safe/coderails" } }),
    createId: () => "run-1",
    now: () => "2026-08-27T10:00:00.000Z",
    spawn,
  });
}

test("rejects project and provider values outside the Factory allowlists", () => {
  const run = launcher({ spawn: () => { throw new Error("must not spawn"); } });

  assert.throws(() => run.launch({ projectId: "../../tmp", provider: "codex", prompt: "test" }), /unknown project/);
  assert.throws(() => run.launch({ projectId: "coderails", provider: "sh -c", prompt: "test" }), /unknown provider/);
});

test("launches each provider with fixed argv and never a shell", () => {
  const calls = [];
  const run = launcher({ spawn: (...args) => { calls.push(args); return controlledChild(); } });

  run.launch({ projectId: "coderails", provider: "codex", prompt: "a ; rm -rf /" });
  assert.deepEqual(calls[0], ["codex", ["exec", "--json", "--skip-git-repo-check", "a ; rm -rf /"], { cwd: "/safe/coderails", shell: false, stdio: ["ignore", "pipe", "pipe"] }]);

  const claude = launcher({ spawn: (...args) => { calls.push(args); return controlledChild(); } });
  claude.launch({ projectId: "coderails", provider: "claude", prompt: "use a literal prompt" });
  assert.deepEqual(calls[1], ["claude", ["-p", "--output-format", "stream-json", "use a literal prompt"], { cwd: "/safe/coderails", shell: false, stdio: ["ignore", "pipe", "pipe"] }]);
});

test("binds the Factory run before spawning the provider", () => {
  let snapshot;
  let run;
  run = launcher({ spawn: () => {
    snapshot = run.store.snapshot();
    return controlledChild();
  } });

  run.launch({ projectId: "coderails", provider: "codex", prompt: "test" });
  assert.equal(snapshot.selectedRun.id, "run-1");
  assert.equal(snapshot.selectedRun.status, "queued");
});

test("normalises provider stdout and stderr into ordered redacted evidence", () => {
  const child = controlledChild();
  const run = launcher({ spawn: () => child });

  run.launch({ projectId: "coderails", provider: "codex", prompt: "test" });
  child.stdout.emit("data", "token=secret\n");
  child.stderr.emit("data", "failure details\n");
  child.emit("close", 0);

  const evidence = run.store.snapshot().selectedRun.evidence;
  assert.deepEqual(evidence.map(({ order, type, source, redacted, payload }) => ({ order, type, source, redacted, payload })), [
    { order: 1, type: "provider_stdout", source: "provider", redacted: true, payload: "[redacted]" },
    { order: 2, type: "provider_stderr", source: "provider", redacted: true, payload: "[redacted]" },
  ]);
  assert.equal(run.store.snapshot().selectedRun.status, "completed");
});

test("keeps a provider run failed when its process errors before close", () => {
  const child = controlledChild();
  const run = launcher({ spawn: () => child });

  run.launch({ projectId: "coderails", provider: "claude", prompt: "test" });
  child.emit("error", new Error("missing provider"));
  child.emit("close", 0);

  assert.equal(run.store.snapshot().selectedRun.status, "failed");
});
