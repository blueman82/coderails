import { describe, it, expect, vi } from "vitest";
import { writeRunNote } from "../src/notes";
import type { NoteWriteDeps } from "../src/notes";

function makeDeps(overrides: Partial<NoteWriteDeps> = {}): NoteWriteDeps {
  return {
    exists: vi.fn(() => false),
    create: vi.fn(async () => {}),
    modify: vi.fn(async () => {}),
    ...overrides,
  };
}

describe("writeRunNote — fresh note", () => {
  it("creates the note when no file exists at the path", async () => {
    const deps = makeDeps({ exists: vi.fn(() => false) });

    await writeRunNote(deps, "dashboard-runs/2026-07-06-wiki-lint.md", "content-a");

    expect(deps.create).toHaveBeenCalledWith("dashboard-runs/2026-07-06-wiki-lint.md", "content-a");
    expect(deps.modify).not.toHaveBeenCalled();
  });
});

describe("writeRunNote — same-day same-button re-run", () => {
  it("modifies the existing note in place instead of colliding on create", async () => {
    const deps = makeDeps({ exists: vi.fn(() => true) });

    await writeRunNote(deps, "dashboard-runs/2026-07-06-wiki-lint.md", "content-b");

    expect(deps.modify).toHaveBeenCalledWith("dashboard-runs/2026-07-06-wiki-lint.md", "content-b");
    expect(deps.create).not.toHaveBeenCalled();
  });

  it("replaces the full content on modify rather than appending", async () => {
    const deps = makeDeps({ exists: vi.fn(() => true) });

    await writeRunNote(deps, "dashboard-runs/2026-07-06-wiki-lint.md", "status: done\nfull replacement");

    expect(deps.modify).toHaveBeenCalledWith(
      "dashboard-runs/2026-07-06-wiki-lint.md",
      "status: done\nfull replacement"
    );
  });
});
