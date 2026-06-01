---
name: handoff
description: Generate a structured memory file and continuation prompt for carrying work into a new Claude Code session. Use this whenever work needs to continue in a fresh session — design plans, implementation work, multi-session features, research threads. Triggers on "handoff", "hand off", "continue in new session", "pick this up later", "save this for next session", "create a handoff", or any intent to preserve session context for future continuation. Use proactively when a session is getting long and the user signals they want to wrap up but continue later.
---

# Handoff

Generate two artefacts that allow a fresh Claude Code session to continue the current work without re-deriving context:

1. **A project memory file** — persists in `~/.claude/projects/<project>/memory/` and loads automatically in future sessions
2. **A continuation prompt** — ready to paste into a new session to kick off the work immediately

## When to use

- Session is ending but work isn't done
- A design has been agreed but implementation hasn't started
- Research/analysis is complete and the next step is building
- User explicitly says "handoff", "save for later", "continue next time"

## Instructions

### Step 1: Extract from current session

Scan the conversation for these categories. Be thorough — the new session has ZERO context from this one:

| Category | What to capture |
|----------|----------------|
| **Goal** | What are we building/doing and why |
| **Decisions made** | Architecture choices, patterns selected, approaches rejected (with reasons) |
| **Constraints** | Expert feedback, technical limitations, things that won't work and why |
| **Taxonomy/Schema** | Any enums, categories, data structures, DDB schemas designed |
| **File references** | Specific files to read, with what to look for in each |
| **What's done** | Work already completed this session (PRs, deploys, commits) |
| **Next steps** | Ordered list of what to do next, specific enough to act on |
| **Open questions** | Unresolved decisions the user needs to make |

### Step 2: Write the memory file

Write to the **project-specific** memory directory. The correct path is derived from your cwd:

```
~/.claude/projects/-<cwd-with-slashes-replaced-by-dashes>/memory/
```

For example, if cwd is `/Users/you/Documents/Github/ops-agent`, write to:
`~/.claude/projects/-Users-you-Documents-Github-ops-agent/memory/`

**Do NOT use the path shown in your system prompt's auto-memory section** — that may be a global fallback (`-Users-harrison`) which other project sessions won't load. Always derive from cwd.

If `MEMORY.md` doesn't exist in the target directory, create it with a `# Memory Index` header.

Write the memory file with type `project`:

```markdown
---
name: <descriptive name>
description: <one-line — specific enough to surface on relevant queries>
type: project
---

# <Title>

## Goal
<what and why, 2-3 sentences>

## Decisions
<bullet list of choices made, each with WHY>

## Constraints
<things that won't work and why — expert feedback, technical limits>

## Schema / Taxonomy
<any structured designs — tables, enums, record formats>

## Key files
<paths + what to look for in each>

## Done so far
<what was completed this session>

## Next steps
<ordered, specific, actionable>

## Open questions
<decisions the user still needs to make>
```

Update `MEMORY.md` index with a one-line entry.

### Step 3: Generate the continuation prompt

Output a fenced prompt block that the user can paste into a new session. The prompt should:

- Reference the memory file by name (so the new session knows to read it)
- State the immediate next action clearly
- Include any branch name, worktree path, or JIRA ticket if relevant
- Be concise — the memory file has the detail, the prompt just kicks things off

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

Ask if anything is missing or needs adjusting before they close the session.

## What NOT to include

- Conversation tone/style (the new session has its own)
- Tool outputs or raw data (point to files instead)
- Debugging dead-ends (only include if they inform a constraint)
- Anything derivable from git log or reading the code
