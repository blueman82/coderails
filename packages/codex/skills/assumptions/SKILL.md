---
name: assumptions
description: Inventory and label assumptions about the subject supplied with an explicit $coderails-codex:assumptions mention.
---

# Assumptions

Treat the text supplied with the explicit `$coderails-codex:assumptions` mention
as the subject.

List every assumption you are currently making about the subject, including the
user's task, the codebase, the environment, and relevant state.

For each assumption:

- Mark it `(verified)` only when it was directly observed in this session through
  command or tool output, a file read, or an explicit user statement.
- Mark it `(inferred)` when it comes from context, recall, pattern matching, or
  any other assumption.

Return only a table with the columns `Assumption`, `Source`, and `Confidence`.
Put the verification label in `Confidence`. Perform no other work in the same
turn.
