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

- Run weekly through the `routines` section of
  `~/.claude/coderails-dashboard.json`, if configured. You can also run it
  on demand without a routine.
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
(`name`, `description`, top-level `type`) and a body.

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

**Use this rule on every `MEMORY.md` edit.** Keep each index line as a
complete clause. If a size hook asks for shorter text, remove supporting
detail. Do not cut off bytes or leave a sentence unfinished.

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

For example, keep "failed checkout left a stale tree and caused a false
failure report." Do not shorten it to "failed checkout left a". The first
line retains the cause and consequence. The second loses the finding.

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

The report is the skill's durable artifact. A scheduled routine checks that
it exists.
