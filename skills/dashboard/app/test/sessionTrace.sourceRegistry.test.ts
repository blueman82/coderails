import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";
import { expect, it } from "vitest";
import { collectClaudeSessionTrace, readClaudeTracePage, type TraceCollectionDeps } from "../src/lib/collect/sessionTrace";

const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const python = process.env.CODERAILS_TEST_PYTHON ?? "python3";

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "claude-source-registry-"));
  const sourceRoot = join(root, "projects"), cacheRoot = join(root, "cache");
  const dir = join(sourceRoot, "project"), subagents = join(dir, "s1", "subagents");
  await mkdir(subagents, { recursive: true });
  const rows: unknown[] = [];
  for (const [index, name] of ["Cedar Scout", "Signal Reader"].entries()) {
    const id = `a${index + 1}`, callId = `call-${index + 1}`, team = `team-${index + 1}`;
    const prompt = `Private teammate task ${index + 1}`;
    rows.push({ type: "assistant", sessionId: "s1", uuid: `request-${index}`, message: { role: "assistant", content: [
      { type: "tool_use", id: callId, name: "Agent", input: { prompt, subagent_type: "worker" } },
    ] } });
    rows.push({ type: "user", sessionId: "s1", uuid: `result-${index}`, message: { role: "user", content: [
      { type: "tool_result", tool_use_id: callId, is_error: false, content: "done" },
    ] }, toolUseResult: { status: "teammate_spawned", name, team_name: team,
      agent_id: `${name}@${team}`, teammate_id: `${name}@${team}`, prompt, agent_type: "worker" } });
    const child = [
      { type: "user", sessionId: "s1", agentId: id, isSidechain: true, uuid: `child-${id}-1`,
        message: { role: "user", content: `<teammate-message>\n${prompt}\n</teammate-message>` } },
      { type: "assistant", sessionId: "s1", agentId: id, isSidechain: true, uuid: `child-${id}-2`, attributionAgent: "worker",
        message: { role: "assistant", id: `private-message-${id}`, usage: { input_tokens: 3 },
          content: [{ type: "text", text: "See skills/wiki-query/SKILL.md before work." }] } },
    ];
    await writeFile(join(subagents, `agent-${id}.jsonl`), child.map((row) => JSON.stringify(row)).join("\n") + "\n");
    await writeFile(join(subagents, `agent-${id}.meta.json`), JSON.stringify({ name, teamName: team }));
  }
  await writeFile(join(dir, "s1.jsonl"), rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
  const deps: TraceCollectionDeps = { sourceRoot, cacheRoot, now: () => new Date("2026-10-30T14:00:00Z"),
    fs: { readFile: (path) => readFile(path, "utf8"), writeFile, stat } };
  return { root, deps, subagents, cache: join(cacheRoot, "claude", "s1") };
}

async function enrollSources(root: string, dir = root): Promise<Array<{ source_id: string; path: string; sha256: string }>> {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...await enrollSources(root, path));
    else found.push({ source_id: relative(root, path).split("\\").join("/"), path, sha256: digest(await readFile(path)) });
  }
  return found.sort((a, b) => a.source_id.localeCompare(b.source_id));
}

async function cohort(fx: Awaited<ReturnType<typeof fixture>>) {
  const manifestPath = join(fx.cache, "manifest.json"), bytes = await readFile(manifestPath);
  const manifest = JSON.parse(bytes.toString());
  const eventsPath = join(fx.cache, manifest.eventFile);
  const sourceFiles = await enrollSources(fx.deps.sourceRoot);
  const path = join(fx.root, "cohort.json");
  await writeFile(path, JSON.stringify({ schema_version: 1, cohorts: { baseline: [{ provider: "claude",
    native_session_id: "s1", parser_version: manifest.parserVersion, manifest_path: manifestPath,
    manifest_sha256: digest(bytes), events_path: eventsPath, events_sha256: digest(await readFile(eventsPath)),
    source_files: sourceFiles, eligible: true, excluded_reason: null, retry_of: null }], comparison: [] } }));
  return { path, sourceFiles, manifest, manifestPath, eventsPath };
}

function report(path: string) {
  return spawnSync(python, [resolve(process.cwd(), "../../../scripts/observation_report.py"), path],
    { encoding: "utf8", env: process.env });
}

it("reuses identical teammate sidecars once through native collection, cache and strict report", async () => {
  const fx = await fixture();
  await collectClaudeSessionTrace("s1", fx.deps);
  const enrolled = await cohort(fx), result = report(enrolled.path);
  expect(enrolled.manifest.errors).toEqual([]);
  expect(enrolled.manifest.complete).toBe(true);
  expect({ exit: result.status, stderr: result.stderr }).toEqual({ exit: 0, stderr: "" });
  expect(enrolled.manifest.sources).toHaveLength(enrolled.sourceFiles.length);
  expect(new Set(enrolled.manifest.sources.map((source: { sourceId: string }) => source.sourceId)).size).toBe(5);
  const page = await readClaudeTracePage("s1", null, 50, fx.deps);
  expect(page.complete).toBe(true);
  for (const id of ["a1", "a2"]) {
    const worker = page.events.find((event) => event.attributes["coderails.actor.id"] === id)!;
    const callId = `call-${id.slice(1)}`;
    expect(worker.parentSpanId).toBe(page.events.find((event) =>
      event.attributes["coderails.native.call_id"] === callId && event.name === "tool_request")?.spanId);
    expect(worker.provenance.sourceId).toContain(`agent-${id}.jsonl`);
    expect(worker.provenance.sourceOrdinal).toBe(1);
  }
  const again = await collectClaudeSessionTrace("s1", fx.deps);
  expect(again.eventFile).toBe(enrolled.manifest.eventFile);
  expect(again.sources).toEqual(enrolled.manifest.sources);
  expect(result.stdout).not.toContain("Private teammate task");
});

it("refuses inconsistent rereads of one sidecar before replacing a cache generation", async () => {
  const fx = await fixture();
  await collectClaudeSessionTrace("s1", fx.deps);
  const enrolled = await cohort(fx);
  const before = await readFile(enrolled.manifestPath), events = await readFile(enrolled.eventsPath);
  const sidecar = join(fx.subagents, "agent-a1.meta.json");
  let reads = 0;
  const deps = { ...fx.deps, fs: { ...fx.deps.fs, readFile: async (path: string) => {
    if (path === sidecar && ++reads === 2) await writeFile(path, (await readFile(path, "utf8")) + " ");
    return readFile(path, "utf8");
  } } };
  await expect(readClaudeTracePage("s1", null, 50, deps)).rejects.toThrow(/Native source changed during trace collection/);
  expect(reads).toBe(2);
  expect(await readFile(enrolled.manifestPath)).toEqual(before);
  expect(await readFile(enrolled.eventsPath)).toEqual(events);
  const stale = report(enrolled.path);
  expect(stale.status).toBe(2);
  expect(stale.stderr).toContain("source hash mismatch");
});
