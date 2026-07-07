import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, readFileSync, existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { escalate, checkForeignSkillExists, writeRunNote } from "../src/escalate.ts";
import type { RoutineDef } from "@coderails/dashboard-lib";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "escalate-test-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function routine(overrides: Partial<RoutineDef> = {}): RoutineDef {
  return {
    name: "wiki-lint-nightly",
    skillCommand: "/coderails:wiki-lint",
    cadence: "0 3 * * *",
    expectedArtifact: {
      artifactPath: "{vault}/log.md",
      maxAgeSeconds: 129600,
      predicate: { kind: "exists" },
    },
    escalation: ["notification", "vault-note"],
    ...overrides,
  };
}

describe("escalate", () => {
  it("calls notifyImpl with a message naming the routine and failure class", () => {
    const notifyImpl = vi.fn();
    escalate({
      routine: routine(),
      runId: "abc123",
      failureClass: "artifact-gate-failed",
      reason: "Artifact does not exist",
      notifyImpl,
      vaultNotesDir: dir,
    });
    expect(notifyImpl).toHaveBeenCalledWith(
      expect.stringContaining("wiki-lint-nightly"),
      expect.stringContaining("artifact-gate-failed")
    );
  });

  it("writes a vault finding note appending a red run entry", () => {
    escalate({
      routine: routine(),
      runId: "abc123",
      failureClass: "artifact-gate-failed",
      reason: "Artifact does not exist",
      notifyImpl: vi.fn(),
      vaultNotesDir: dir,
    });
    const notePath = join(dir, "wiki-lint-nightly.md");
    expect(existsSync(notePath)).toBe(true);
    const content = readFileSync(notePath, "utf-8");
    expect(content).toContain("status: red");
    expect(content).toContain("abc123");
  });

  it("appends to an existing note rather than overwriting it", () => {
    const notePath = join(dir, "wiki-lint-nightly.md");
    writeFileSync(notePath, "---\ntitle: wiki-lint-nightly\ntype: routine-run\n---\n\n## [2026-07-01] run priorrun — green\n");
    escalate({
      routine: routine(),
      runId: "abc123",
      failureClass: "artifact-gate-failed",
      reason: "Artifact does not exist",
      notifyImpl: vi.fn(),
      vaultNotesDir: dir,
    });
    const content = readFileSync(notePath, "utf-8");
    expect(content).toContain("priorrun");
    expect(content).toContain("abc123");
  });

  it("uses a distinct failure class for a missing referenced skill", () => {
    const notifyImpl = vi.fn();
    escalate({
      routine: routine({ foreignSkillPath: "/nonexistent/skill/path" }),
      runId: "abc123",
      failureClass: "skill-missing",
      reason: "Referenced skill not found at /nonexistent/skill/path",
      notifyImpl,
      vaultNotesDir: dir,
    });
    expect(notifyImpl).toHaveBeenCalledWith(
      expect.any(String),
      expect.stringContaining("skill-missing")
    );
  });
});

describe("checkForeignSkillExists", () => {
  it("returns true when the path exists", () => {
    const path = join(dir, "SKILL.md");
    writeFileSync(path, "content");
    expect(checkForeignSkillExists(path)).toBe(true);
  });

  it("returns false when the path does not exist", () => {
    expect(checkForeignSkillExists(join(dir, "missing", "SKILL.md"))).toBe(false);
  });
});

describe("writeRunNote", () => {
  it("creates a note with status: green frontmatter for a green run", () => {
    writeRunNote(dir, "wiki-lint-nightly", "run1", "green", "succeeded");
    const content = readFileSync(join(dir, "wiki-lint-nightly.md"), "utf-8");
    expect(content).toContain("status: green");
    expect(content).toContain("run1");
  });

  it("appends a green section after an existing red section, preserving both", () => {
    writeRunNote(dir, "wiki-lint-nightly", "run1", "red", "artifact-gate-failed: x");
    writeRunNote(dir, "wiki-lint-nightly", "run2", "green", "succeeded");
    const content = readFileSync(join(dir, "wiki-lint-nightly.md"), "utf-8");
    expect(content).toContain("run1");
    expect(content).toContain("run2");
    expect(content).toContain("red");
    expect(content).toContain("green");
  });
});
