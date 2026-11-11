---
name: memory-consolidation
description: Use on demand to consolidate a project's memory directory — dedupe overlapping memories, flag stale or contradicted ones, and refresh the MEMORY.md index. Trigger on "consolidate memory", "clean up memory", or "memory consolidation".
---

# Memory Consolidation

When the user tells you to consolidate memory, check the project's memory directory `~/.codex/projects/<slug>/memory/`.
The memory system in `~/.codex/AGENTS.md` writes there during usual sessions.

## When to Use

- Run on demand when memory files have visibly accumulated overlapping or
  contradictory content.
- A user-owned external scheduler may invoke the same procedure in the future,
  but the native Codex plugin includes and configures no scheduler.

## Instructions

### Step 1: Locate the memory directory

The target is `~/.codex/projects/<project-slug>/memory/`. Get it with `scripts/memory_dir.py --provider codex`.
Find the script at `../../scripts/memory_dir.py` relative to this `SKILL.md`.
The script gets `<project-slug>` from the sanitized project working directory path where you invoke this skill.
First read `MEMORY.md` in that directory. It is the index of memory files.

### Step 2: Read every memory file

Read each file the index points to. Each memory has YAML frontmatter
(`name`, `description`, `metadata.type`) and a body.

### Step 3: Find consolidation candidates

- **Overlapping memories:** Two or more files describe the same fact, decision, or project status.
  Merge them into the most recent or complete file. Remove the superseded files.

- **Stale memories:** A newer memory contradicts a `project` or `feedback` record, or a different record marks its work complete.
  Flag it for the user. Do not remove it silently. A `feedback` record can contain a standing instruction.

- **Contradicted memories:** Two records give facts that cannot all be correct. Flag the two records.
  Do not silently select one.

### Step 4: Apply merges, update MEMORY.md

For each merge or removal from Step 3, update or remove the corresponding files. Then update their index lines in `MEMORY.md`.
Remove links to files that no longer exist.
If a merge changes a file's scope, first make its frontmatter `description:` accurate for the current content.
Then use the updated description for the index line. Do not use a description that the merge made stale.

**Apply this rule each time you edit `MEMORY.md`.** It also applies if Step 3 found nothing to merge or a hook warns that the index is near its read limit.
Condense index lines. Do not cut them at a byte limit.
A cut can remove part of a clause without a record of the removed text. This system has no other copy of that line.

The file's frontmatter `description:` is the authoritative source for its one-line summary.
Write the description when you make the memory file. Update it only as part of a deliberate merge as above.
Use `description:` to condense an index line. Do not use the previous index line.

Keep the concrete fact in the index line, such as the incident, its effect, and the next step.
If the description has more related information, move that information to the memory file's body.
Keep the concrete fact on the index line itself.

Check each changed line before you finish. Make sure it ends with a complete clause.
The last word must not be a word such as "the", "of", or "and".
Make sure it includes the fact that made the initial entry useful, such as a name, PR number, or cause of an error.

An index line with a complete sentence and no concrete fact has the same problem as a line cut in the middle.
Write such lines again from the file's `description:` in this step. Do this if you find a damaged line that Step 3 did not flag.

Worked example. The file's `description:` reads:

"a failed git checkout leaves a plausible-looking tree at the OLD commit; nearly reported a merged, working fix as broken because foreign WIP blocked the checkout and my test ran against pre-merge code"

A concise index line keeps the connection between the checkout error, the stale tree, and the incorrect report:

"a failed `git checkout` leaves a plausible-looking tree at the OLD commit; nearly reported a merged fix as broken".

An incorrect index line stops in the middle of the clause:

"a failed `git checkout` leaves a".

### Step 5: Write the durable report artifact

Write `~/.codex/coderails-dashboard/routines/memory-consolidation/report-{date}.md` with `{date}` in `YYYY-MM-DD` format.
Write the file if Step 3 found nothing to change, too. An external caller can check for that file.
Use this content:

```markdown
# Memory Consolidation Report — {date}

## Summary
<N> files examined. <N> merged. <N> flagged as stale/contradicted. <N> removed.

## Merges
- <superseded files> → <surviving file>: <one-line cause>

## Flagged (not auto-resolved)
- <file>: <what's stale or contradicted, and why it was not auto-resolved>

## MEMORY.md index
Updated: yes|no
```

The skill writes this durable report itself. An external caller can gate on
its existence.
