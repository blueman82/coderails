---
name: using-coderails
description: Use when starting any conversation - establishes how to find and use skills, requiring skill invocation before ANY response including clarifying questions
user-invocable: false
model: sonnet
---

# Using Coderails

If you are a subagent assigned one specific task, follow that task's
instructions. Otherwise, check for relevant skills before your first action
or response. Invoke each skill that the user requests or the task needs.
Tell the user which skill you use and why when you first apply it.

## Instruction priority

Follow the runtime instruction hierarchy:

1. System and developer instructions.
2. User instructions and applicable project instruction files.
3. Coderails skill instructions.

For example, if the user tells you not to use TDD and a skill requires TDD,
follow the user unless a higher-priority instruction requires it.

## Load the skill

Use the skill mechanism for your platform:

| Platform | Method |
|---|---|
| Claude Code | `Skill` tool |
| Codex | Native skill loading |
| Copilot CLI | `skill` tool |
| Gemini CLI | `activate_skill` tool |
| Antigravity, Pi | Read `SKILL.md` with a file-read tool if no skill tool is available |

For tool names and instructions-file mappings, see [Claude Code](references/claude-code-tools.md),
[Codex](references/codex-tools.md), [Copilot CLI](references/copilot-tools.md),
[Gemini CLI](references/gemini-tools.md), [Pi](references/pi-tools.md), and
[Antigravity](references/antigravity-tools.md). Gemini CLI also loads its
mapping through `GEMINI.md`.

## Apply the skill

1. Before a response, clarification, plan, or tool call, check whether a
   requested or relevant skill applies.
2. Load the skill. If it does not apply after inspection, say so briefly and
   continue.
3. Follow its steps. If it has a checklist, track each item.
4. If several skills apply, use process skills first, then the skills for
   implementation. Follow a skill's fixed procedure when it says that the
   procedure is mandatory.

A task instruction states the required result. It does not, by itself,
cancel a relevant skill. A higher-priority instruction can change the
workflow.
