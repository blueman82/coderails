---
name: handoff
description: Generate a structured memory file and continuation prompt for carrying work into a new Codex session. Use this whenever work needs to continue in a fresh session — design plans, implementation work, multi-session features, research threads. Triggers on "handoff", "hand off", "continue in new session", "pick this up later", "save this for next session", "create a handoff", or any intent to preserve session context for future continuation. Use proactively when a session is getting long and the user signals they want to wrap up but continue later.
---

# Handoff

Make two artifacts that let a new Codex session continue the current work with the necessary context:

1. **A project memory file** — stays in `~/.codex/projects/<project>/memory/` and loads automatically in future sessions
2. **A continuation prompt** — the user can paste it into a new session to continue the work

## When to use

- Session ends before the work is complete
- A design has been agreed but implementation has not started
- Research or analysis is complete, and the next step starts the build
- User explicitly says "handoff", "save for later", "continue next time"

## Instructions

### Step 0: Read recorded state (Muninn authoritative)

If this session has a native loop graph, get `$STATE` (the `<session>/progress.json` path) and `$SESSION` from the SessionStart bootstrap text.
Run `python3 "$SKILL_DIR/../../scripts/lib/handoff_derive.py" "$STATE" --session "$SESSION"`.
The script reads the recorded graph without changing it and prints a JSON skeleton:
`{goal, decisions[{id, cite, text}], done, recorded_proof_results, next_steps, open_questions, lessons, degraded[]}`.
Decisions include their Muninn K-IDs and citations. Proof verdicts are recorded claims and do not count as `done`.

Use the skeleton for Goal, Decisions, Done, and Next steps. Do not reconstruct them from the conversation.
**In the handoff, list each code in `degraded[]` below a "Memory degraded" line.** Exit 3 means the array is not empty.
Include this report. Do not replace it with Markdown you wrote by hand.

The script uses `memory_adapter.py` to read Muninn records.

Run these commands from the mapped project repository.
The state-key directory and plugin checkout do not identify project scope.

The skeleton uses retained R-id/window/project bindings for local decisions. It uses current task receipts for the other entries.
Keep the revision, verbatim selected quote, full set of source records, conditions, and expiry in the handoff.
Do not infer that a condition holds. Give the causes for unknown, pending, and unsupported uses.

Current Muninn has no classifier for the `normal` or `restricted` privacy categories.
Its physical source, scope, redaction, and owner-authority checks do not give a privacy class based on meaning.

For graph fields, use the provider `graph.py summarize`, `inspect`, and `collection` commands when available.
If one graph read does not succeed, omit only its result.
Do not use the standalone legacy adapter list as a fallback.
If there is no graph, omit only the fields that come from it. Then continue with Step 1.

When you report graph work, use the `node_names` entry from `inspect` or `summarize`.
Show each node's name for its work and lane code next to its stable ID.
Keep that ID in the continuation instructions and citations for the recorded work.

### Step 1: Extract from current session

Find these categories in the conversation. Include all necessary information because the new session has no context from this one:

| Category | What to capture |
|----------|----------------|
| **Goal** | What are we building/doing and why |
| **Decisions made** | Architecture selections, selected patterns, and rejected methods, with causes |
| **Constraints** | Expert feedback, technical limits, things that will not work and why |
| **Taxonomy/Schema** | Enums, categories, data structures, and DDB schemas from this work |
| **Files** | The files to read and what to look for in each |
| **What's done** | Work completed in this session (PRs, deployments, commits) |
| **Next steps** | Numbered instructions the next session can use |
| **Open questions** | Unresolved decisions for the user |

### Step 2: Write the memory file

Write to the **project-specific** memory directory. The correct path is derived from your cwd:

```
~/.codex/projects/-<cwd-with-slashes-replaced-by-dashes>/memory/
```

For example, if cwd is `/Users/you/Documents/Github/ops-agent`, write to:
`~/.codex/projects/-Users-you-Documents-Github-ops-agent/memory/`

**Do not use the auto-memory path in your system prompt as the default.**
It can be a global fallback path that other project sessions do not read. Start with the current directory.

**Monorepos can use a shared store.** Check the store location before you make a new one.
For a subproject such as `<repo>/projects/<sub>` or `<repo>/packages/<sub>`, the store is frequently keyed to the repository root.
All sessions in that repository can share one root store.
If you derive a new directory from the subproject path alone, future sessions can miss this handoff.

1. Find the existing store. Check the path derived from the current directory and each parent.
   Replace slashes with dashes for each candidate. Also check the system prompt's auto-memory path.
   Look for a populated `MEMORY.md` and `project_*.md` files.

2. If there is only one populated store, write there. Use it if it belongs to a parent directory or repository root.
   Use the store that the session reads from.

3. Make a new directory from the current path only if the repository has no populated store.

List candidate `memory/` directories. Check which one holds existing `*.md` memories.
Do not make a competing empty directory next to a populated one.

If the selected directory has no `MEMORY.md`, first check that no parent or root path has a populated store.
Then make the index with a `# Memory Index` header.

Write the memory file with type `project`:

```markdown
---
name: <descriptive name>
description: <one line with sufficient information for related queries>
type: project
---

# <Title>

## Goal
<what and why, 2-3 sentences>

## Decisions
<bullet list of decisions with their causes>

## Constraints
<things that will not work and why — expert feedback, technical limits>

## Schema / Taxonomy
<structured designs such as tables, enums, or record formats>

## Key files
<paths + what to look for in each>

## Done so far
<what was completed this session>

## Next steps
<numbered steps with concrete instructions>

## Open questions
<decisions for the user>
```

Update `MEMORY.md` index with a one-line entry.

### Step 3: Generate the continuation prompt

Give a fenced prompt block that the user can paste into a new session.

- Name the memory file so the new session can read it
- Give the first step clearly
- Include the branch name, worktree path, or JIRA ticket if related
- Keep the prompt short. The memory file contains the full information

Format:

````
```prompt
Read memory file `project_<name>.md` for full context.

<1-2 sentence summary of where we are>

Next: <the specific first thing to do>

Branch: <if applicable>
JIRA: <if applicable>
```
````

### Step 4: Confirm with user

Show the user:
1. The memory file path
2. The continuation prompt

Before the user closes the session, check with them for missing information or necessary changes.

## What NOT to include

- Conversation tone/style (the new session has its own)
- Tool outputs or raw data (give file paths)
- Debugging dead-ends (only include if they show a constraint)
- Information the next session can get from git log or the code
