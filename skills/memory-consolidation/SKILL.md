---
name: memory-consolidation
description: Use to consolidate a project's memory directory — dedupe overlapping memories, flag stale or contradicted ones, and refresh the MEMORY.md index. Trigger on "consolidate memory", "clean up memory", "memory consolidation", or when running as a scheduled routine.
---

# Memory Consolidation

Periodically health-check and consolidate a project's persistent memory
directory (`~/.claude/projects/<slug>/memory/`), the same directory the
memory system documented in `~/.claude/CLAUDE.md` writes to during normal
sessions.

## When to Use

- Run as a scheduled routine (weekly, per the `routines` config section
  documented in `skills/dashboard/lib/README.md`).
- Run on demand when memory files have visibly accumulated overlapping or
  contradictory content.

## Instructions

### Step 1: Locate the memory directory

The target is `~/.claude/projects/<project-slug>/memory/`, where
`<project-slug>` is the sanitized form of the project's working directory
path (matching the directory this skill itself is invoked from). Read
`MEMORY.md` in that directory first — it is the index of every memory file.

### Step 2: Read every memory file

Read each file the index points to. Each memory has YAML frontmatter
(`name`, `description`, `metadata.type`) and a body.

### Step 3: Find consolidation candidates

- **Overlapping memories**: two or more files describing the same fact,
  decision, or ongoing project state. Merge into the most recent/complete
  one; delete the superseded file(s).
- **Stale memories**: a `project` or `feedback` memory whose content is
  contradicted by a newer memory, or that references work explicitly
  marked complete elsewhere. Flag for the user rather than silently
  deleting — memory of type `feedback` in particular represents a
  standing instruction and must not be dropped without the user's
  awareness.
- **Contradicted memories**: two memories asserting incompatible facts.
  Flag both; do not silently pick a winner.

### Step 4: Apply merges, update MEMORY.md

For each merge or deletion decided in Step 3: update or remove the
affected memory file(s), then update `MEMORY.md`'s index line(s) to match.
Never leave `MEMORY.md` pointing at a file that no longer exists.

### Step 5: Write the durable report artifact

Write `~/.claude/coderails-dashboard/routines/memory-consolidation/report-{date}.md`
(where `{date}` is `YYYY-MM-DD`), unconditionally, even if Step 3 found
nothing to change — this file's existence is what the routine's
artifact-gate checks. Its content:

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

This report is this skill's own durable artifact — it is written natively
by this skill (unlike `sync-docs`, which needs an external
`--append-system-prompt` wrapper to produce a file at all; see
`skills/dashboard/lib/README.md` and the routine config's
`expectedArtifact` for `memory-consolidation`).
