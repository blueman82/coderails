// Pure create-vs-modify decision for a run note, extracted from main.ts's
// createRunNote so the same-day-same-button collision fix (vault.create
// throws if the note already exists — see main.ts) is unit-testable without
// an Obsidian vault mock.

export interface NoteWriteDeps {
  exists(path: string): boolean;
  create(path: string, content: string): Promise<void>;
  modify(path: string, content: string): Promise<void>;
}

export async function writeRunNote(deps: NoteWriteDeps, path: string, content: string): Promise<void> {
  if (deps.exists(path)) {
    await deps.modify(path, content);
  } else {
    await deps.create(path, content);
  }
}
