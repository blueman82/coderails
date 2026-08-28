import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { EventEmitter } from "node:events";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { startFactoryServer } from "../server.mjs";
import { createProjectRegistry } from "../lib/config.mjs";
import { createLauncher } from "../lib/launch.mjs";
import { createRunStore } from "../lib/runs.mjs";

async function startFactory() {
  const server = await startFactoryServer({ keepaliveMs: 5 });
  const address = server.address();
  assert.equal(address.address, "127.0.0.1");
  return { server, baseUrl: `http://127.0.0.1:${address.port}` };
}

test("serves the standalone Factory shell and an empty snapshot", async (t) => {
  const { server, baseUrl } = await startFactory();
  t.after(() => server.close());

  const page = await fetch(`${baseUrl}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Coderails Factory/);

  const ui = await fetch(`${baseUrl}/ui.js`);
  assert.equal(ui.status, 200);
  assert.match(await ui.text(), /cycleTheme/);

  const snapshot = await fetch(`${baseUrl}/api/snapshot`);
  assert.deepEqual(await snapshot.json(), { runs: [], selectedRunId: null });
});

test("keeps one localhost SSE stream alive", async (t) => {
  const { server, baseUrl } = await startFactory();
  t.after(() => server.close());

  const response = await fetch(`${baseUrl}/api/events`);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream; charset=utf-8");
  const reader = response.body.getReader();
  const { value } = await reader.read();
  assert.match(new TextDecoder().decode(value), /: keepalive/);
  await reader.cancel();
});

test("streams redacted Factory evidence through the one SSE endpoint", async (t) => {
  const store = createRunStore();
  store.create({ id: "run-1", projectId: "coderails", provider: "codex", prompt: "test" });
  const server = await startFactoryServer({ store, keepaliveMs: 5 });
  t.after(() => server.close());
  const { port } = server.address();

  const response = await fetch(`http://127.0.0.1:${port}/api/events`);
  const reader = response.body.getReader();
  await reader.read();
  store.appendEvidence({ runId: "run-1", order: 1, type: "provider_stdout", source: "provider", timestamp: "2026-08-27T10:00:00Z", payload: "secret" });
  const { value } = await reader.read();
  const event = new TextDecoder().decode(value);
  assert.match(event, /event: evidence/);
  assert.match(event, /\[redacted\]/);
  assert.doesNotMatch(event, /secret/);
  await reader.cancel();
});

test("returns the selected Factory record without a raw progress dump", async (t) => {
  const store = createRunStore();
  store.create({ id: "run-1", projectId: "coderails", provider: "codex", prompt: "Keep this exact" });
  const server = await startFactoryServer({ store });
  t.after(() => server.close());
  const { port } = server.address();

  const snapshot = await fetch(`http://127.0.0.1:${port}/api/snapshot?run=run-1`);
  assert.deepEqual(await snapshot.json(), {
    runs: [{ id: "run-1", projectId: "coderails", provider: "codex", status: "queued" }],
    selectedRunId: "run-1",
    selectedRun: {
      id: "run-1", projectId: "coderails", provider: "codex", prompt: "Keep this exact", status: "queued",
      graph: { state: "unavailable", message: "No progress graph available" }, evidence: [],
    },
  });
});

test("accepts only project, provider, and prompt when launching a Factory run", async (t) => {
  const store = createRunStore();
  const launcher = createLauncher({
    store,
    projects: createProjectRegistry({ coderails: { cwd: "/safe/coderails" } }),
    createId: () => "run-1",
    spawn: () => {
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      return child;
    },
  });
  const server = await startFactoryServer({ store, launcher });
  t.after(() => server.close());
  const { port } = server.address();

  const response = await fetch(`http://127.0.0.1:${port}/api/runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ projectId: "coderails", provider: "codex", prompt: "test", cwd: "/not/accepted" }),
  });
  assert.equal(response.status, 400);
  assert.deepEqual(store.snapshot(), { runs: [], selectedRunId: null });
});

test("creates only the server-owned demo graph fixture", async (t) => {
  const { server, baseUrl } = await startFactory();
  t.after(() => server.close());

  const response = await fetch(`${baseUrl}/api/demo`, { method: "POST" });
  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), { runId: "demo-factory-run" });

  const snapshot = await fetch(`${baseUrl}/api/snapshot?run=demo-factory-run`);
  const selected = (await snapshot.json()).selectedRun;
  assert.equal(selected.graph.state, "ready");
  assert.equal(selected.graph.nodes.length, 3);
  assert.ok(selected.evidence.length > 3);
});

test("Factory server does not import either dashboard tree", async () => {
  const source = await readFile(new URL("../server.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /skills\/dashboard|packages\/codex\/skills\/dashboard/);
});

test("Factory work leaves both dashboard trees untouched", () => {
  const repo = new URL("../../", import.meta.url);
  const changed = execFileSync(
    "git",
    ["diff", "--name-only", "origin/main", "--", "skills/dashboard", "packages/codex/skills/dashboard"],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(changed, "");
});
