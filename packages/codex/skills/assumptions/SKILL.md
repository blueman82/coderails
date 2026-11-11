---
name: assumptions
description: Inventory and label assumptions about the subject supplied with an explicit $coderails-codex:assumptions mention.
---

# Assumptions

Use the text that accompanies an explicit `$coderails-codex:assumptions` mention as the subject.

List all your assumptions about the subject. Include the user's task, codebase, environment, and related conditions.

- Use `(verified)` only if a check in this session shows the assumption is correct. Use a tool result, file read, or direct statement from the user.
- Use `(inferred)` if the assumption comes from context, memory, a pattern, or a different assumption.

Give only a table with the columns `Assumption`, `Source`, and `Confidence`. Put the label in `Confidence`. Do no other work in this turn.
