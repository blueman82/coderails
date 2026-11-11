---
name: handoff
description: Generate a structured memory file and continuation prompt for carrying work into a new Claude Code session. Use this whenever work needs to continue in a fresh session — design plans, implementation work, multi-session features, research threads. Triggers on "handoff", "hand off", "continue in new session", "pick this up later", "save this for next session", "create a handoff", or any intent to preserve session context for future continuation. Use proactively when a session is getting long and the user signals they want to wrap up but continue later.
model: sonnet
---

# Handoff

Write two artifacts that let a new Claude Code session continue this work without rebuilding context.

1. **A project memory file** — persists in `~/.claude/projects/<project>/memory/` and loads automatically in future sessions
2. **A continuation prompt** — paste into a new session to start the work immediately

## When to use

- The session will end before the work is done
- A design has been agreed but implementation has not started
- Research or analysis is complete and the next step is implementation
- User explicitly says "handoff", "save for later", "continue next time"

## Instructions

### Step 0: Read recorded state (Muninn authoritative)

If the session has a native loop graph, first run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/handoff_derive.py" <state> --session <session_id>`. The script reads the loop data without changes. It prints a JSON skeleton `{goal, decisions[{id, cite, text}], done, recorded_proof_results, next_steps, open_questions, lessons, degraded[]}`. The decisions include Muninn K-ids and cites. Proof verdicts are recorded claims and do not go in `done`.

Use the skeleton for Goal, Decisions, Done, and Next steps. Do not reconstruct those sections from the conversation. **In the handoff, list each code in `degraded[]` below a "Memory degraded" line.** Exit 3 means the list is nonempty. Do not skip that output or replace it with hand-written Markdown.

The script uses `memory_adapter.py` to read Muninn records.

Run the commands from the mapped project repository. The state-key directory and plugin checkout do not tell you the project scope.

The skeleton uses R-id, window, and project bindings from local decisions. It uses only receipts that match the current task for other decisions. Keep the revision, complete `supports`, conditions, and expiry in the handoff. Copy the selected quote verbatim. Check a condition before you say it is satisfied. Show unknown and pending status and the codes for unsupported use.

Muninn does not classify content by sensitivity. Its physical source, scope, redaction, and owner-authority checks do not tell you the sensitivity of the content.

For graph fields, use the provider’s `graph.py summarize`, `inspect`, and applicable `collection` commands. If one graph read fails, omit only its result. Do not use the standalone legacy adapter list as a fallback. If there is no graph, omit only fields from the graph. Then continue with Step 1.

For graph work, read `node_names` from `inspect` or `summarize`. Give each node’s one-word task name and lane code next to its stable ID. Include the stable ID when you cite records or give continuation instructions.

### Step 1: Extract from current session

Examine the conversation for these categories. Include all information related to these categories. The new session has no context from this one.

| Category | What to capture |
|----------|----------------|
| **Goal** | What are we building/doing and why |
| **Decisions made** | Architecture selections, patterns selected, approaches rejected (and why) |
| **Constraints** | Expert feedback, technical limits, things that will not work and why |
| **Taxonomy/Schema** | Enums, categories, data structures, and DDB schemas from this session |
| **Files** | Which files to read and what to look for in each |
| **What's done** | Work completed in this session (PRs, deploys, commits) |
| **Next steps** | List the steps in sequence, with instructions to do each one |
| **Open questions** | Unresolved decisions the user needs to make |

### Step 2: Write the memory file

Write to the **project-specific** memory directory. The correct path is derived from your cwd:

```
~/.claude/projects/-<cwd-with-slashes-replaced-by-dashes>/memory/
```

For example, if cwd is `/Users/you/Documents/Github/ops-agent`, write to:
`~/.claude/projects/-Users-you-Documents-Github-ops-agent/memory/`

**Do not rely on the auto-memory path in the system prompt.** It can be a global fallback that other sessions do not read. Always derive the path from cwd.

**In a monorepo, check the store location before you derive a new path.** If cwd is in a subproject such as `<repo>/projects/<sub>` or `<repo>/packages/<sub>`, the store frequently uses the **repo root**. All the repo sessions can share that store. A new `memory/` directory for the subproject can hold a handoff that future sessions cannot find.

1. Find the existing store. Check the path for cwd and for each parent directory. Replace slashes with dashes. Also check the auto-memory path from the system prompt. Select the store that contains a populated `MEMORY.md` and `project_*.md` files.
2. If you find only one populated store, write there. This applies when the store uses a parent directory or the repo root. Use the store the session reads.
3. Only create a new cwd-derived directory if NO populated store exists for this repo (genuinely first memory for the project).

A short check: list candidate `memory/` dirs and see which holds existing `*.md` memories. Do not make a competing empty folder next to a populated one.

Check for a populated store at a parent path or the root. If there is none and the selected directory has no `MEMORY.md`, make it with a `# Memory Index` header.

Write the memory file with type `project`:

```markdown
---
name: <descriptive name>
description: <one line that helps find this memory for related queries>
type: project
---

# <Title>

## Goal
<what and why, 2-3 sentences>

## Decisions
<bullet list of selections made, each with WHY>

## Constraints
<things that will not work and why — expert feedback, technical limits>

## Schema / Taxonomy
<structured designs — tables, enums, record formats>

## Key files
<paths + what to look for in each>

## Done so far
<what was completed this session>

## Next steps
<instructions in sequence>

## Open questions
<decisions for the user>
```

Update `MEMORY.md` index with a one-line entry.

### Step 3: Generate the continuation prompt

Output a fenced prompt block that the user can paste into a new session. The prompt should:

- Give the name of the memory file (so the new session knows to read it)
- Give the urgent next step
- Include the branch name, worktree path, or JIRA ticket if applicable
- Keep the prompt short. Use the memory file for the full instructions.

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

Before the user closes the session, invite them to identify missing information or changes.

## What NOT to include

- Conversation tone/style (the new session has its own)
- Tool outputs or raw data (point to files)
- Debugging dead-ends (include only if they show a constraint)
- Information the next session can get from git log or the code
