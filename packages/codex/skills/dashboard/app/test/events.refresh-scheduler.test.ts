import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const mocks = vi.hoisted(() => ({
  health: vi.fn<() => Promise<unknown[]>>(),
  gates: vi.fn<() => Promise<unknown[]>>(),
}));
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, watch: () => ({ on() { return this; }, close() {} }) };
});
vi.mock("../src/lib/collect/health", () => ({ collectHealth: mocks.health }));
vi.mock("../src/lib/collect/prGates", () => ({ collectPrGates: mocks.gates }));

import { createAggregator } from "../src/lib/collect";
import type { DashboardConfig } from "../src/lib/config";

const dirs: string[] = [];
function directory(): string {
  const dir = mkdtempSync(join(tmpdir(), "refresh-scheduler-"));
  dirs.push(dir);
  return dir;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function aggregator(roots: { projectsDir: string; loopsDir: string; runsDir: string; buildsDir: string }, gatesPollMs = 100) {
  const cfg: DashboardConfig = { repos: [], wikiPaths: [], buttons: [] };
  return createAggregator({ cfg, ...roots, activityReconcileMs: 100, gatesPollMs, activityDebounceMs: 10 });
}
afterEach(() => {
  vi.useRealTimers();
  mocks.health.mockReset();
  mocks.gates.mockReset();
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe("aggregator refresh scheduler", () => {
  it("coalesces repeated triggers per slice and publishes only completed follow-ups", async () => {
    vi.useFakeTimers();
    const roots = { projectsDir: directory(), loopsDir: directory(), runsDir: directory(), buildsDir: directory() };
    const firstHealth = deferred<unknown[]>(), nextHealth = deferred<unknown[]>();
    const firstGates = deferred<unknown[]>(), nextGates = deferred<unknown[]>();
    mocks.health.mockImplementationOnce(() => firstHealth.promise).mockImplementationOnce(() => nextHealth.promise);
    mocks.gates.mockImplementationOnce(() => firstGates.promise).mockImplementationOnce(() => nextGates.promise);
    const events: string[] = [];
    const subject = aggregator(roots);
    subject.subscribe((event) => { events.push(event); });
    subject.start();
    writeFileSync(join(roots.runsDir, "run.log"), "x");
    writeFileSync(join(roots.projectsDir, "session.jsonl"), "x");
    await vi.advanceTimersByTimeAsync(400);
    expect(mocks.health).toHaveBeenCalledTimes(1);
    expect(mocks.gates).toHaveBeenCalledTimes(1);
    firstHealth.resolve([]);
    firstGates.resolve([{ repo: "r", number: 1, state: "blocked" }]);
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.health).toHaveBeenCalledTimes(2);
    expect(mocks.gates).toHaveBeenCalledTimes(2);
    nextHealth.resolve([]);
    nextGates.resolve([{ repo: "r", number: 1, state: "merge-ready" }]);
    await vi.advanceTimersByTimeAsync(0);
    expect((subject.getSnapshot().gates[0] as { state: string }).state).toBe("merge-ready");
    expect(events.filter((event) => event === "gates")).toHaveLength(2);
    subject.stop();
  });

  it("uses changed local inputs for reconciliation and skips unchanged ticks", async () => {
    vi.useFakeTimers();
    const roots = { projectsDir: directory(), loopsDir: directory(), runsDir: directory(), buildsDir: directory() };
    const build = join(roots.buildsDir, "build");
    mkdirSync(build);
    writeFileSync(join(build, "state.json"), JSON.stringify({ schemaVersion: 1, hash: "build", state: "running" }));
    mocks.health.mockResolvedValue([]);
    mocks.gates.mockResolvedValue([]);
    const subject = aggregator(roots, 30_000);
    const events: string[] = [];
    subject.subscribe((event) => { events.push(event); });
    subject.start();
    await vi.advanceTimersByTimeAsync(0);
    const initialHealthCalls = mocks.health.mock.calls.length;
    const initialGateCalls = mocks.gates.mock.calls.length;
    await vi.advanceTimersByTimeAsync(400);
    expect(mocks.health).toHaveBeenCalledTimes(initialHealthCalls);
    expect(mocks.gates).toHaveBeenCalledTimes(initialGateCalls);
    writeFileSync(join(build, "phase"), "testing");
    await vi.advanceTimersByTimeAsync(120);
    expect(mocks.health).toHaveBeenCalledTimes(initialHealthCalls + 1);
    expect(subject.getSnapshot().builds[0].phase).toBe("testing");
    expect(events.filter((event) => event === "activity")).toHaveLength(2);
    expect(mocks.gates).toHaveBeenCalledTimes(initialGateCalls);
    writeFileSync(join(roots.runsDir, "runs.jsonl"), "{}\n");
    await vi.advanceTimersByTimeAsync(3_200);
    expect(mocks.gates).toHaveBeenCalledTimes(initialGateCalls + 1);
    subject.stop();
  });

  it("stop clears timers and suppresses late collector publication", async () => {
    vi.useFakeTimers();
    const roots = { projectsDir: directory(), loopsDir: directory(), runsDir: directory(), buildsDir: directory() };
    const pending = deferred<unknown[]>();
    mocks.health.mockImplementation(() => pending.promise);
    mocks.gates.mockImplementation(() => pending.promise);
    const subject = aggregator(roots);
    const events: string[] = [];
    subject.subscribe((event) => { events.push(event); });
    subject.start();
    subject.stop();
    pending.resolve([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(events).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ages cached sessions and refreshes rolling health with unchanged files, without polling gates", async () => {
    vi.useFakeTimers();
    const start = new Date("2026-09-29T12:00:00.000Z");
    vi.setSystemTime(start);
    const roots = { projectsDir: directory(), loopsDir: directory(), runsDir: directory(), buildsDir: directory() };
    const project = join(roots.projectsDir, "project");
    mkdirSync(project);
    const transcript = join(project, "session.jsonl");
    writeFileSync(transcript, "{}\n");
    utimesSync(transcript, start, start);
    mocks.health.mockImplementation(async () => [{ key: "usage5h", value: Date.now() < start.getTime() + 60_000 ? "before" : "after" }]);
    mocks.gates.mockResolvedValue([]);
    const subject = aggregator(roots, 24 * 3_600_000);
    subject.subscribe(() => {});
    subject.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(subject.getSnapshot().sessions[0].state).toBe("active");
    expect(subject.getSnapshot().health[0].value).toBe("before");
    vi.setSystemTime(start.getTime() + 5 * 60_000 - 100);
    await vi.advanceTimersByTimeAsync(100);
    expect(subject.getSnapshot().sessions[0].state).toBe("idle");
    expect(subject.getSnapshot().health[0].value).toBe("after");
    vi.setSystemTime(start.getTime() + 60 * 60_000 - 100);
    await vi.advanceTimersByTimeAsync(100);
    expect(subject.getSnapshot().sessions[0].state).toBe("stalled");
    expect(mocks.gates).toHaveBeenCalledTimes(1);
    subject.stop();
  });

  it("does not publish an old active classification after time advances during health collection", async () => {
    vi.useFakeTimers();
    const start = new Date("2026-09-29T12:00:00.000Z");
    vi.setSystemTime(start);
    const roots = { projectsDir: directory(), loopsDir: directory(), runsDir: directory(), buildsDir: directory() };
    const project = join(roots.projectsDir, "project");
    mkdirSync(project);
    const transcript = join(project, "session.jsonl");
    writeFileSync(transcript, "{}\n");
    utimesSync(transcript, start, start);
    const pending = deferred<unknown[]>();
    mocks.health.mockImplementation(() => pending.promise);
    mocks.gates.mockResolvedValue([]);
    const subject = aggregator(roots, 3_600_000);
    subject.subscribe(() => {});
    subject.start();
    await vi.advanceTimersByTimeAsync(6 * 60_000);
    pending.resolve([]);
    await vi.advanceTimersByTimeAsync(0);
    expect(subject.getSnapshot().sessions[0].state).toBe("idle");
    subject.stop();
  });
});
