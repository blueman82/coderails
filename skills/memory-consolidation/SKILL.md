---
name: memory-consolidation
description: Use to consolidate a project's memory directory — dedupe overlapping memories, flag stale or contradicted ones, and refresh the MEMORY.md index. Trigger on "consolidate memory", "clean up memory", "memory consolidation", or when running as a scheduled routine.
model: sonnet
---

# Memory Consolidation

Check and consolidate the project's memory directory at
`~/.claude/projects/<slug>/memory/`. Normal sessions write there as
described in `~/.claude/CLAUDE.md`.

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

For each merge or deletion from Step 3, update the memory files and their
`MEMORY.md` index lines. Do not leave an index link to a deleted file.
If a merge changes a surviving file's scope, update its frontmatter
`description:` first. Then derive the index line from that description.

**Apply this rule whenever you edit `MEMORY.md`, even if Step 3 found no
merge.** Never cut an index line mid-clause. A size-pressure hook asks
you to compress the text, not truncate bytes. Truncation can erase a
fact without leaving a record of it.

The memory file's frontmatter `description:` is the source for its index
summary. Normal sessions do not change it. When shortening an index line,
start from `description:`, not the old index text. Keep the concrete fact:
the incident, consequence, or next action. Move only supporting detail
into the file body.

Before finishing, check each index line you changed. It must end on a
complete clause and retain its identifying fact, such as a name, PR
number, or failure mode. A complete sentence with no concrete fact is
still damaged. Rebuild existing damaged lines from their file's
`description:`, even if Step 3 found no other consolidation candidate.

Worked example — given a file whose `description:` reads "a failed git
checkout leaves a plausible-looking tree at the OLD commit; nearly
reported a merged, working fix as broken because foreign WIP blocked the
checkout and my test ran against pre-merge code", a correct shortened
index line keeps the load-bearing fact (failed checkout → stale tree →
false-broken report) while trimming connective wording: "a failed `git
checkout` leaves a plausible-looking tree at the OLD commit; nearly
reported a merged fix as broken". An incorrect shortening — the failure
mode this rule exists to prevent — stops mid-clause: "a failed `git
checkout` leaves a".

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
