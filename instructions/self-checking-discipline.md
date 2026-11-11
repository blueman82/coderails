# Self-Checking Discipline

For the Claude provider, `install.py` adds these four rules to `~/.claude/CLAUDE.md`. The prompt rules give guidance. The plugin hooks apply the mechanical checks.

---

## Self-Checking Discipline

- **Confidence labels.** Mark substantive claims with `(verified)`, `(inferred)`, or `(guess)`.
  Use `(verified)` when you cite the source.
  Use `(inferred)` when a pattern or memory is the basis.
  Use `(guess)` for speculation you make explicit.
  Apply labels if the difference is important.

  The `check_confidence_labels.py` Stop hook gives an advisory if a reply has 200 or more characters and no label.
  The hook does not block. Follow the full rule.

- **`Did Not Verify` section.** After an edit or a claim that the work is complete, end with a `## Did Not Verify` section.
  List the checks you did not do. Examples are tests you skipped, call sites you did not read, dependencies you did not check, or an assumption about behavior.
  The list limits the claim that the work is complete.

  Do the check in this turn if you can. Remove items that do not apply.
  Keep an item only if the source cannot verify it. Examples are a REPL-only step, external-system behavior, a production observation, or user intent.

  Start that bullet with `- (unverifiable: <reason>) <the item>`.
  The `check_verify_loop.py` Stop hook gives an advisory for each DNV bullet without the tag, with or without a file name.
  It records the advisory and a telemetry row. It does not block.
  The tag lets readers audit the claim. Do not use the tag to skip a check you can do.

- **Ambiguity.** If intent, scope, or approach can have more than one meaning, use `AskUserQuestion`.
  Do not select an interpretation without a question.

- **Check memory before use.** If memory is the basis for a recommendation or step, check the current conditions in the same turn.
  Read the file, find the symbol, or check Git. Show the check.
