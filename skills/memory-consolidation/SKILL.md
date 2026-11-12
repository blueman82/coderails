---
name: memory-consolidation
description: Use to consolidate a project's memory directory — dedupe overlapping memories, flag stale or contradicted ones, and refresh the MEMORY.md index. Trigger on "consolidate memory", "clean up memory", "memory consolidation", or when running as a scheduled routine.
model: sonnet
---

# Memory Consolidation

Check and consolidate the project's memory directory at `~/.claude/projects/<slug>/memory/`.
Sessions usually write there as specified in `~/.claude/CLAUDE.md`.

## When to Use

- If configured, run weekly through `routines` in `~/.claude/coderails-dashboard.json`. You can run it on demand without a schedule.
- Run on demand if memory files have overlapping or contradictory content.

## Instructions

### Step 1: Locate the memory directory

The target is `~/.claude/projects/<project-slug>/memory/`.
Use this script to get the path.
It gets the resolved path of the working directory and sanitizes it to make the slug.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/memory_dir.py"
```

Read `MEMORY.md` in the directory that the script prints.
This file is the index of the memory files.

### Step 2: Read every memory file

Read each file the index points to.
Each memory has YAML frontmatter (`name`, `description`, `metadata.type`) and a body.

### Step 3: Find consolidation candidates

- **Overlapping memories.** Two or more files describe the same fact, decision, or project status. Merge into the newest or most complete file. Remove the superseded files.
- **Stale memories.** A newer memory contradicts a `project` or `feedback` memory. Or a memory refers to work that other records mark complete. Flag these files for the user. A `feedback` memory can contain instructions for future sessions. Do not remove it without the user's knowledge.
- **Contradicted memories.** Two memories give facts that cannot all be correct. Flag the two files. Do not select one silently.

### Step 4: Apply merges, update MEMORY.md

For each merge or removal from Step 3, update or remove the memory file.
Then update its index lines in `MEMORY.md`.
Do not keep an index line that points to a removed file.

If a merge changes the contents of a file you keep, first update its frontmatter `description:` to agree with the contents.
Then get the index line from the updated `description:`.
Do not use the description from before the merge.

**Apply this rule each time you edit `MEMORY.md`.**
Apply it if Step 3 has nothing to merge or if you edit only to stay below the index byte limit.
Do not cut text from the end of a line.

The hook can tell you the index is close to its read limit.
Compress the text without truncation.
Cutting a line mid-clause can remove information with no record of the loss. The system has no second copy of the words you cut.

The frontmatter `description:` is the durable source of the one-line summary.
Write it one time at memory setup, or update it as part of a merge as described above.
Do not change it in other sessions.

When you condense an index line, use `description:` as the source.
Do not use the previous index line.
Use fewer words and keep the concrete fact in the line: the incident, its effect, and the next step.
If you have more information about the fact, put it in the file body.
Keep the fact itself in the index line.

Before you finish, check each index line you changed.
It must end with a complete clause and include the concrete fact.
For example, keep the name, PR number, or problem that made it necessary to record the entry.
A full sentence without that fact is also damaged.

If you find a line cut mid-clause or stripped of its fact, rebuild it from the file's `description:` in this step.
A flag from Step 3 is optional.

For example, a file has this `description:`: "a failed git checkout leaves a plausible-looking tree at the OLD commit; nearly reported a merged, working fix as broken because foreign WIP blocked the checkout and my test ran against pre-merge code".

A short index line can say "a failed `git checkout` leaves a plausible-looking tree at the OLD commit; nearly reported a merged fix as broken".
It keeps the cause and the result: the checkout error left the tree at the previous commit, so a working fix looked broken.
The line "a failed `git checkout` leaves a" cuts off the clause and loses the fact.

### Step 5: Write the durable report artifact

Write `~/.claude/coderails-dashboard/routines/memory-consolidation/report-{date}.md`, where `{date}` is `YYYY-MM-DD`.
Write it also if Step 3 has nothing to change.
The scheduled artifact gate checks for this file.

```markdown
# Memory Consolidation Report — {date}

## Summary
<N> files checked. <N> merged. <N> flagged as stale/contradicted. <N> deleted.

## Merges
- <previous file(s)> → <surviving file>: <why the files merged>

## Flagged (not auto-resolved)
- <file>: <what is stale or contradicted, and why it was not auto-resolved>

## MEMORY.md index
Updated: yes|no
```
