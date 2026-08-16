# Coderails code-quality controls

The quality layer is deliberately small and uses the repository's existing
languages and test seams.

## Commands

```sh
scripts/quality/check.sh                 # warn-only full-tree inventory
scripts/quality/check.sh --strict       # strict full-tree check
scripts/quality/check.sh --strict --changed
bash scripts/quality/tests/quality.test.sh
git config core.hooksPath scripts/git-hooks
```

The default per-file limit is 400 lines (`MAX_LOC` overrides it). Python
function/method size defaults to 100 lines (`MAX_FUNCTION_LINES` overrides it).
Strict commit checks inspect changed tracked files, so existing debt is visible
without making an unrelated edit uncommittable. A deliberate threshold override
must be explicit in the command or environment.

## Enforcement

- Hard at an activated commit hook: source LOC, Python syntax/function size,
  structured JSON validity, whitespace, commented-out-code findings, optional
  Bash lint/format findings when those tools are installed, the shell test
  suites, and the Codex Python self-check.
- Warn-only during local iteration: full-tree inventory and `PostToolUse`
  feedback from `hooks/scripts/quality_feedback.sh`. The edit hook always exits
  successfully and cannot block a write.
- Existing Coderails workflow, integrity, task-eval, provider-separation, and
  protected-file hooks remain authoritative and are not bypassed.
- YAGNI/KISS/DRY/SSOT and architectural boundaries remain review-level checks;
  static enforcement cannot safely prove intent without false positives.
- Coverage is not a strict gate yet: Coderails has shell/Python/TypeScript
  surfaces but no single stable product-code coverage boundary or required
  coverage tool in the plugin runtime. Add a measured threshold only after a
  maintained coverage command exists for each intended product surface.

`shellcheck` and `shfmt` are optional. Their absence is reported explicitly;
they are never represented as having passed. If installed, findings fail the
strict command and are reported by the warn-only command.

## Activation and ceilings

The tracked pre-commit hook is inactive until each clone opts in with
`git config core.hooksPath scripts/git-hooks`. Git's `--no-verify` remains an
agent/user-controlled bypass inside the existing local trust domain; the
repository's existing workflow and server-side integrity rules are the stronger
boundaries. There is no automatic hook installation and no new dependency.

The commented-code detector is intentionally conservative: it catches common
statement-shaped comments and leaves prose, documentation comments, Markdown,
generated assets, fixtures, and lockfiles alone. It is a signal, not a parser.
