import { mkdtemp, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { TraceCollectionDeps } from "../src/lib/collect/sessionTrace";

export async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "codex-trace-"));
  const sourceRoot = join(root, "sessions");
  const cacheRoot = join(root, "telemetry");
  await mkdir(join(sourceRoot, "2026", "09", "28"), { recursive: true });
  const parent = join(sourceRoot, "2026", "09", "28", "rollout-parent.jsonl");
  const child = join(sourceRoot, "2026", "09", "28", "rollout-child-one.jsonl");
  const native = JSON.parse(await readFile(fileURLToPath(new URL("./fixtures/session-trace/codex/native-shape.json", import.meta.url)), "utf8"));
  const rows = native.parent as Record<string, unknown>[];
  const children = native.child as Record<string, unknown>[];
  const save = (path: string, value: Record<string, unknown>[]) => writeFile(path, value.map((row) => JSON.stringify(row)).join("\n") + "\n");
  await save(parent, rows); await save(child, children);
  const deps: TraceCollectionDeps = { sourceRoot, cacheRoot, now: () => new Date("2026-09-28T13:00:00Z"), fs: { readFile: (p) => readFile(p, "utf8"), writeFile, stat } };
  return { deps, parent, child, rows, children, save };
}
