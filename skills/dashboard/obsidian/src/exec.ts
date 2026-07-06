// Pure orchestration logic for pressing a dashboard button from Obsidian —
// no Obsidian API calls here (same split as render.ts/main.ts from Task
// 12), so this is unit-testable with injected fakes and no Obsidian mock.
//
// buildArgv is imported directly from Task 7's source
// (skills/dashboard/app/src/lib/argv.ts) rather than re-implemented here —
// esbuild bundles it into dist/main.js at build time (see
// esbuild.config.mjs). Two independently-maintained copies of the
// profile→flag mapping is how a `standard` button could silently drift into
// a `bypass` one; importing the one true source closes that off by
// construction.
import { buildArgv } from "../../app/src/lib/argv";
import type { ButtonItem, PermissionProfile } from "./render";

export interface IntentFile {
  button: string;
  input?: string;
  requestedAt: number;
  source: "obsidian";
}

export interface UnresolvedRun {
  notePath: string;
}

export interface VaultNote {
  path: string;
  content: string;
}

type ExecFileCallback = (error: (Error & { code?: unknown }) | null, stdout: string, stderr: string) => void;

export interface ExecDeps {
  mkdirIntentDir(path: string): void;
  writeIntentFile(path: string, data: string): void;
  findUnresolvedRun(button: string): UnresolvedRun | null;
  createRunNote(path: string, content: string): Promise<void>;
  modifyRunNote(path: string, content: string): Promise<void>;
  execFile(
    command: string,
    args: readonly string[],
    options: { cwd: string },
    callback: ExecFileCallback
  ): unknown;
  now(): number;
  randomRunId(): string;
}

export type PressResult =
  | { ok: true; runId: string; notePath: string }
  | { ok: false; reason: "undeclared" | "unresolved" | "invalid-input" };

const QUEUE_DIR = "queue"; // joined onto the caller-supplied dashboard dir by writeIntentFile's path
const RUNS_FOLDER = "dashboard-runs";

function isoDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

function runNotePath(button: string, requestedAt: number): string {
  return `${RUNS_FOLDER}/${isoDate(requestedAt)}-${button}.md`;
}

function runningFrontmatter(button: string, profile: PermissionProfile, startedAt: number): string {
  return [
    "---",
    "status: running",
    `button: ${button}`,
    `profile: ${profile}`,
    `startedAt: ${new Date(startedAt).toISOString()}`,
    "---",
    "",
    `Running \`${button}\`...`,
    "",
  ].join("\n");
}

function finalFrontmatter(
  button: string,
  profile: PermissionProfile,
  startedAt: number,
  endedAt: number,
  exitCode: number,
  output: string
): string {
  const status = exitCode === 0 ? "done" : "failed";
  return [
    "---",
    `status: ${status}`,
    `button: ${button}`,
    `profile: ${profile}`,
    `startedAt: ${new Date(startedAt).toISOString()}`,
    `endedAt: ${new Date(endedAt).toISOString()}`,
    `exitCode: ${exitCode}`,
    `duration: ${endedAt - startedAt}ms`,
    "---",
    "",
    "```",
    output,
    "```",
    "",
  ].join("\n");
}

export async function pressButton(
  deps: ExecDeps,
  buttons: ButtonItem[],
  name: string,
  input?: string
): Promise<PressResult> {
  const button = buttons.find((b) => b.name === name);
  if (!button) {
    return { ok: false, reason: "undeclared" };
  }

  if (input !== undefined && input.startsWith("-")) {
    // buildArgv would throw on this anyway (flag-smuggling guard) — checked
    // here too so a press never reaches fs/spawn for invalid input.
    return { ok: false, reason: "invalid-input" };
  }

  if (deps.findUnresolvedRun(button.name)) {
    return { ok: false, reason: "unresolved" };
  }

  const argv = buildArgv(button, input);

  const runId = deps.randomRunId();
  const requestedAt = deps.now();

  const intent: IntentFile = {
    button: button.name,
    ...(input !== undefined ? { input } : {}),
    requestedAt,
    source: "obsidian",
  };

  deps.mkdirIntentDir(QUEUE_DIR);
  deps.writeIntentFile(`${QUEUE_DIR}/${runId}.json`, JSON.stringify(intent));

  const notePath = runNotePath(button.name, requestedAt);
  await deps.createRunNote(notePath, runningFrontmatter(button.name, button.profile, requestedAt));

  await new Promise<void>((resolve) => {
    deps.execFile("claude", argv, { cwd: button.cwd }, (error, stdout, stderr) => {
      const endedAt = deps.now();
      const errorCode = error?.code;
      const exitCode = !error ? 0 : typeof errorCode === "number" ? errorCode : 1;
      void deps
        .modifyRunNote(
          notePath,
          finalFrontmatter(button.name, button.profile, requestedAt, endedAt, exitCode, stdout + stderr)
        )
        .finally(resolve);
    });
  });

  return { ok: true, runId, notePath };
}
