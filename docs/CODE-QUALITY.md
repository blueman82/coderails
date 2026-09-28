# Coderails code-quality controls

The quality layer is deliberately small and uses the repository's existing
languages and test seams.

## Commands

```sh
python3 scripts/quality/check.py                 # warn-only full-tree inventory
python3 scripts/quality/check.py --strict       # strict full-tree check
python3 scripts/quality/check.py --strict --changed
python3 scripts/quality/tests/quality_test.py
git config core.hooksPath scripts/git-hooks
```

The default per-file limit is 400 lines. Python function/method size defaults to
100 lines. There are no grandfathered paths or function exceptions; previously
oversized dashboard suites are split into cohesive tests and shared fixtures.

Strict commit checks inspect changed tracked files, so existing debt is visible
without making an unrelated edit uncommittable.

## Enforcement

- Hard at an activated commit hook: source LOC, Python syntax/function size,
  structured JSON validity, whitespace, commented-out-code findings, optional
  Bash lint/format findings when those tools are installed, the native Python test
  suites.
- Warn-only during local iteration: full-tree inventory and `PostToolUse`
  feedback from `hooks/scripts/quality_feedback.py`. The edit hook always exits
  successfully and cannot block a write.
- Existing Coderails workflow, integrity, task-eval, and
  protected-file hooks remain authoritative and are not bypassed.
- YAGNI/KISS/DRY/SSOT and architectural boundaries remain review-level checks;
  static enforcement cannot safely prove intent without false positives.
- Coverage is not a strict gate yet: Coderails has Python/TypeScript
  surfaces but no single stable product-code coverage boundary or required
  coverage tool in the plugin runtime. Add a measured threshold only after a
  maintained coverage command exists for each intended product surface.

Python checks require Ruff, Black, Pyright and strict mypy; a missing required
tool fails the strict check. Each provider is checked with its own import paths.
Generated pure semantic copies must exactly match the sole maintained source.
The external system skill validator requires PyYAML in the test interpreter;
this is a validation dependency, not a plugin runtime dependency.
Owned runtime and tests use Python. Generic shell checks still support external
projects when shell inputs are explicitly supplied; no owned shell runtime remains.

## Activation and ceilings

The tracked pre-commit hook is inactive until each clone opts in with
`git config core.hooksPath scripts/git-hooks`. Per-file and per-function
grandfathered exceptions have been removed. The checker still accepts
`--max-loc` / `MAX_LOC` and `--max-function-lines` / `MAX_FUNCTION_LINES`;
the default policy remains 400/100 and the migration is validated at those
defaults without raising them. The repository's existing
workflow and server-side integrity rules remain the stronger boundaries. There
is no automatic hook installation or additional plugin runtime dependency.

The commented-code detector is intentionally conservative: it catches common
statement-shaped comments and leaves prose, documentation comments, Markdown,
generated assets, fixtures, and lockfiles alone. It is a signal, not a parser.
