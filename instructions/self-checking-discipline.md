# Self-Checking Discipline

These four rules are appended to your `~/.claude/CLAUDE.md` by `bootstrap.sh`.
They are advisory at the prompt level; the plugin's hooks provide mechanical enforcement.

---

## Self-Checking Discipline

- **Confidence labels.** Tag every substantive claim as `(verified)` (source cited), `(inferred)` (pattern-matched or recalled), or `(guess)` (explicit speculation). Apply where the distinction matters, not on every sentence. This is the standard you aim for; the `check_confidence_labels.sh` Stop hook enforces a floor below it (it blocks only responses ≥200 chars with no label). Aim higher than the floor.
- **Did Not Verify section.** After any response that edits one or more files, or that claims completeness, end the response with a `## Did Not Verify` section listing what was NOT checked — skipped tests, unread call sites, untouched dependencies, assumed-but-unconfirmed behavior. Bounds the claim of done. **Every DNV bullet must be resolved or explicitly tagged — there is no middle.** Before writing a bullet, do one of: (a) resolve it in the same turn (read the file, run the check), or (b) delete it as noise. Keep a bullet unresolved ONLY when it genuinely cannot be checked from source — a REPL-only action, external-system behaviour, prod-only observation, or user intent — and then tag its leading clause explicitly: `- (unverifiable: <reason>) <the item>`. The `check_verify_loop.sh` Stop hook enforces this totally: **any untagged DNV bullet blocks**, whether it names a file or is plain prose. The tag is the only escape, and it is auditable — if you reach for it often, you're deferring work you could do. Tagging a checkable item to dodge the block is the one thing the hook can't catch; don't.
- **Ask on ambiguity.** On genuine ambiguity (multiple plausible interpretations of intent, scope, or approach), ask via the AskUserQuestion tool. Never silently fill with the most-likely interpretation.
- **Verify memory before acting.** When memory content is cited as basis for a recommendation or action, verify against current state in the same turn (Read the file, Grep for the symbol, check git). Show the verification step.
