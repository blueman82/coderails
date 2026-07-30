---
name: memory-consolidation
description: Use to consolidate a project's memory directory — dedupe overlapping memories, flag stale or contradicted ones, and refresh the MEMORY.md index. Trigger on "consolidate memory", "clean up memory", "memory consolidation", or when running as a scheduled routine.
model: sonnet
---

# Memory Consolidation

Periodically health-check and consolidate a project's persistent memory
directory (`~/.claude/projects/<slug>/memory/`), the same directory the
memory system documented in `~/.claude/CLAUDE.md` writes to during normal
sessions.

## When to Use

- Run as a scheduled routine (weekly, via the `routines` section of
  `~/.claude/coderails-dashboard.json`). The skill needs no routines setup
  to work — it runs standalone on demand too.
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

**Never shorten an index line by cutting it.** A size-pressure nudge (a
hook warning the index is approaching a read-limit) may fire while you
work — it is a prompt to compress, never an instruction to truncate.
Byte-truncating a line mid-clause silently destroys information with no
record of what was lost, and nothing else in this system holds a second
copy of it once that happens.

The file's own frontmatter `description:` field is the durable source of
truth for its one-line summary — it is written once, at memory-creation
time, and normal sessions do not touch it again. When shortening an index
line, derive it from `description:`, not from the previous index line:
condense the description's wording, but never drop a fact it states
(the incident, the concrete consequence, the specific next action). If a
compressed line still can't hold the load-bearing fact, move that detail
into the memory file's own body instead of dropping it — the index line
may then simply point there.

Before finishing this step, re-check every index line you touched: does
it end on a complete clause (not a bare article, preposition, or
conjunction), and does it still carry the specific fact — a name, a PR
number, a concrete failure mode — that made the original entry worth
recording? A line that reads as a complete sentence but lost its
concrete details has been damaged just as much as one cut mid-word.

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

This report is this skill's own durable artifact, written natively by the
skill itself — the property that lets a scheduled routine gate on the
report's existence.
