---
name: memory-consolidation
description: Consolidate a project's memory directory on request. Merge overlapping records, flag stale or conflicting records, and update the MEMORY.md index. Use for "consolidate memory", "clean up memory", or "memory consolidation".
---

# Memory Consolidation

On request, check and consolidate the project's persistent memory directory:
`~/.codex/projects/<slug>/memory/`. The memory system in
`~/.codex/AGENTS.md` writes there during normal sessions.

## When to Use

- Run on demand when memory files have visibly accumulated overlapping or
  contradictory content.
- A user-owned external scheduler may invoke this same routine in the future,
  but the native Codex plugin includes and configures no scheduler.

## Instructions

### Step 1: Locate the memory directory

The target is `~/.codex/projects/<project-slug>/memory/`.
`<project-slug>` is the sanitized path of the working directory where this
skill runs. Read `MEMORY.md` first. It indexes the memory files.

### Step 2: Read every memory file

Read each file the index points to. Each memory has YAML frontmatter
(`name`, `description`, `metadata.type`) and a body.

### Step 3: Find consolidation candidates

- **Overlapping memories:** Two or more files describe the same fact,
  decision, or project state. Merge them into the most recent or complete
  file. Delete the superseded files.
- **Stale memories:** A newer memory contradicts a `project` or `feedback`
  record, or another record marks its work complete. Flag it for the user.
  Do not delete it silently. A `feedback` record can contain a standing
  instruction.
- **Contradicted memories:** Two records assert incompatible facts. Flag
  both. Do not silently choose a winner.

### Step 4: Apply merges, update MEMORY.md

For each merge or deletion, update the affected memory files. Then update
their `MEMORY.md` entries. Remove links to deleted files. If a merge changes
a surviving file's scope, update its frontmatter `description:` first.
Build the new index line from that description.

Use these rules whenever you edit `MEMORY.md`. They also apply when there
is no merge. A size-pressure warning asks you to shorten entries; it does
not permit truncation. Never cut an index line in the middle of a clause.

The file's `description:` is the source for its index summary. Normal
sessions do not change it after memory creation. Shorten its wording, but
keep the concrete incident, consequence, or next action in the index line.
Move only extra detail to the memory body. Do not build the new line from
the old index line.

Check every line you touch. It must end with a complete clause. It must
keep its specific fact, such as a name, PR number, or failure mode. Repair
an existing damaged line in this step, even if Step 3 found no other merge.
Build the repair from the memory file's `description:`.

Example: Foreign work blocked `git checkout`, leaving a plausible tree at
the old commit. A test of that tree made a merged fix look broken. The short
index line must retain that cause and consequence. A line ending with
"a failed `git checkout` leaves a" loses the fact.

### Step 5: Write the durable report artifact

Always write
`~/.codex/coderails-dashboard/routines/memory-consolidation/report-{date}.md`.
Use `YYYY-MM-DD` for `{date}`. Write it even when Step 3 finds no change.
An external caller checks for this file.

```markdown
# Memory Consolidation Report — {date}

## Summary
<N> files reviewed. <N> merged. <N> flagged as stale/contradicted. <N> deleted.

## Merges
- <old file(s)> → <surviving file>: <one-line reason>

## Flagged (not auto-resolved)
- <file>: <what's stale or contradicted, and why it wasn't auto-resolved>

## MEMORY.md index
Updated: yes|no
```

This report is the skill's durable artifact. An external caller can gate on
its existence.
