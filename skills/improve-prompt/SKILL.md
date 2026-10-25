---
name: improve-prompt
description: Improves a prompt before execution by surfacing ambiguities, filling gaps with reasonable assumptions, and rewriting it for clarity and precision. Use this skill whenever the user invokes /improve-prompt, says "improve this prompt", "what's missing from this prompt", or asks for help tightening a task description before running it. Also trigger when a prompt is vague, underspecified, or missing success criteria that would likely produce a poor result.
---

# Improve Prompt

Rewrite an unclear prompt so a capable colleague can act on it. Keep the
user's purpose, scope, and constraints. If the user says "just do it", carry
out the task without a prompt rewrite.

## Read available context

Check relevant memory, `CLAUDE.md`, accessible project files, and the current
conversation. Use them to resolve gaps before you ask the user. Do not add
facts that these sources do not support.

## Check seven foundations

Mark each item `clear`, `missing`, or `not applicable`. Give one short reason.

1. **Done:** What output and success checks does the user need?
2. **Context:** Which environment, audience, or prior decision matters?
3. **Constraints:** What limits apply to the work?
4. **Scope:** Is the task one coherent piece of work?
5. **Prior attempts:** For a repair, what has already failed or succeeded?
6. **Mode:** Does the user want action, a draft, or discussion?
7. **Role:** Would a role make the output more precise?

Use `not applicable` for prior attempts on a new task. Use it for the role
when the task needs no persona. Check that the final prompt makes sense to a
colleague who cannot see this conversation.

## Resolve gaps

Ask one question if an unresolved gap could materially change the work. Use
short choices for a bounded answer and a short free-text question for an
open answer. Ask about a personal preference when available context cannot
establish it.

Make a stated assumption if the context supports it and the cost of an error
is low. Continue with the task when a question would add no useful decision.

## Write the improved prompt

- State the action and expected result first.
- Include only context and constraints that affect execution.
- Name success checks that a worker can verify.
- Add a role only when it improves the task.
- Use XML tags only when they make mixed instructions, context, and input
  easier to distinguish.
- Add an example only when the output format needs one. Use the smallest
  example that shows the required form.

Present the result in this order:

1. **Diagnosis:** one short line per foundation.
2. **Context used:** sources that resolved gaps.
3. **Assumptions:** only assumptions still in the rewrite.
4. **Improved prompt:** ready to use, in a triple-backtick code fence.

When the user asks for a revision, change the affected parts and preserve
the decisions already made.
