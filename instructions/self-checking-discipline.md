# Self-Checking Discipline

These four rules are appended to your `~/.claude/CLAUDE.md` by `install.py` (the Claude provider installation path).
They are advisory at the prompt level; the plugin's hooks provide mechanical enforcement.

---

## Self-Checking Discipline

- **Confidence labels.** Tag substantive claims as `(verified)` (source cited),
  `(inferred)` (pattern-matched or recalled), or `(guess)` (explicit
  speculation). Apply labels where the distinction matters, not on every
  sentence. This is the target standard. The `check_confidence_labels.py` Stop
  hook checks only a lower floor: it advises, but never blocks, when a response
  of at least 200 characters has no label. Aim higher than that floor.
- **Did Not Verify section.** After editing any file or claiming completion,
  end with a `## Did Not Verify` section. List checks you did not perform, such
  as skipped tests, unread call sites, untouched dependencies, or assumed
  behavior. This section bounds the completion claim. **Resolve or explicitly
  tag every DNV bullet.** First, run a check if you can do it in the same turn.
  Delete irrelevant bullets. Keep an unresolved bullet only when source cannot
  verify it, such as a REPL-only action, external-system behavior, production
  observation, or user intent. Start that bullet with
  `- (unverifiable: <reason>) <the item>`. The `check_verify_loop.py` Stop hook
  advises on **every untagged DNV bullet**, whether it names a file or uses
  plain prose. It never blocks, but records the advisory and trace row. The
  tag is auditable. Do not use it to avoid a check you can run.
- **Ask on ambiguity.** When intent, scope, or approach has multiple plausible
  interpretations, ask through AskUserQuestion. Do not silently choose the
  most likely interpretation.
- **Verify memory before acting.** When memory supports a recommendation or
  action, check the current state in the same turn. Read the file, search for
  the symbol, or check git. Show the verification step.
