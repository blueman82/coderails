---
name: using-coderails
description: Use at the start of a conversation. Find relevant skills and invoke them before a response, a question, or another action.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
If a skill applies to the task, invoke it.
</EXTREMELY-IMPORTANT>

## Instruction Priority

Follow the runtime instruction hierarchy. A Coderails skill gives task
guidance within that hierarchy:

1. **System and developer instructions** — highest priority.
2. **User instructions** — direct requests and applicable project files,
   subject to higher-priority instructions.
3. **Coderails skills** — follow them unless a higher-priority instruction
   conflicts.

For example, follow an applicable `AGENTS.md` instruction to omit TDD when
a skill asks for it, unless a higher-priority instruction requires TDD.

## How to Access Skills

Load a skill through the platform's skill tool. Do not read its file as a
substitute for invocation.

**In Codex:** Skills load natively. Follow the instructions presented when a skill activates.

## Platform Adaptation

Skills describe actions such as dispatch, task tracking, and file reads.
Use [codex-tools.md](references/codex-tools.md) to find the Codex tools.

# Using Skills

## The Rule

Invoke a relevant or requested skill before a response or action. If it does
not apply after invocation, stop using it.

```dot
digraph skill_flow {
    "User message received" [shape=doublecircle];
    "About to enter plan mode?" [shape=doublecircle];
    "Already planned?" [shape=diamond];
    "Invoke the relevant planning skill" [shape=box];
    "Might any skill apply?" [shape=diamond];
    "Invoke the skill" [shape=box];
    "Announce: 'Using [skill] to [purpose]'" [shape=box];
    "Has checklist?" [shape=diamond];
    "Create a todo per item" [shape=box];
    "Follow skill exactly" [shape=box];
    "Respond (including clarifications)" [shape=doublecircle];

    "About to enter plan mode?" -> "Already planned?";
    "Already planned?" -> "Invoke the relevant planning skill" [label="no"];
    "Already planned?" -> "Might any skill apply?" [label="yes"];
    "Invoke the relevant planning skill" -> "Might any skill apply?";

    "User message received" -> "Might any skill apply?";
    "Might any skill apply?" -> "Invoke the skill" [label="yes"];
    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
    "Invoke the skill" -> "Announce: 'Using [skill] to [purpose]'";
    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
    "Has checklist?" -> "Create a todo per item" [label="yes"];
    "Has checklist?" -> "Follow skill exactly" [label="no"];
    "Create a todo per item" -> "Follow skill exactly";
}
```

## Red Flags

When these thoughts occur, check for a relevant skill:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Check for a skill before you answer. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Check for skills before you read. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | Use an applicable skill. |
| "I remember this skill" | Skills evolve. Read current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Use an applicable skill. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Check the required process first. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## Skill Priority

When multiple skills could apply, use this order:

1. **Process skills first.** Examples are `$coderails-codex:planning-sequence`,
   `$coderails-codex:task-evals`, and `$coderails-codex:cite-check`.
2. **Implementation skills second.** These guide execution.

For a build, run planning and task evals before implementation guidance.
For a factual claim, use cite-check before a domain skill.

## Skill Types

**Rigid** (task-evals, cite-check): Follow their evidence rules exactly.

**Flexible** (patterns): Adapt principles to context.

The skill itself tells you which.

## User Instructions

A task request does not cancel an applicable workflow.
