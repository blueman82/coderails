# Coderails code-quality controls

The quality checks use the repository's existing languages and test seams.

## Commands

```sh
python3 scripts/quality/check.py                 # warn-only full-tree inventory
python3 scripts/quality/check.py --strict       # strict full-tree check
python3 scripts/quality/check.py --strict --changed
python3 scripts/quality/tests/quality_test.py
git config core.hooksPath scripts/git-hooks
```

The default file limit is 400 lines. The Python function and method limit is
100 lines. No path or function has a grandfathered exception. Oversized
dashboard suites were split into smaller tests and shared fixtures.

Strict commit checks inspect changed files in these source roots:
`.claude-plugin/`, `agents/`, `commands/`, `hooks/`, `instructions/`,
`packages/`, `scripts/`, and `skills/`. They also inspect root
`install.py` and `uninstall.py`. See `SOURCE_ROOTS` in
`scripts/quality/check.py` for the maintained list.

The default scan excludes root `AGENTS.md` and `docs/`. Use `--paths` to
check one of those files directly. Existing debt in scanned files remains
visible. It does not block an unrelated edit.

## Enforcement

- **Commit hook:** checks source length, Python syntax and function length,
  JSON validity, whitespace, and commented-out code. It checks Bash lint
  and format when those tools are installed. It runs the native Python
  test suites.
- **Local warnings:** the full-tree inventory and `PostToolUse` feedback
  from `hooks/scripts/quality_feedback.py`. The edit hook always exits
  successfully. It cannot block a write.
- Existing Coderails workflow, integrity, task-eval, and
  protected-file hooks remain authoritative and are not bypassed.
- YAGNI, KISS, DRY, SSOT, and architecture remain review checks. Static
  checks cannot reliably infer intent without false positives.
- Coverage is not a strict gate yet: Coderails has Python/TypeScript
  surfaces but no single stable product-code coverage boundary or required
  coverage tool in the plugin runtime. Add a measured threshold only after a
  maintained coverage command exists for each intended product surface.

Python checks require Ruff, Black, Pyright, and strict mypy. A missing
required tool fails the strict check. Each provider uses its own import
paths. Generated pure semantic copies must match the maintained source
exactly. The external system skill validator needs PyYAML in its test
interpreter. PyYAML is a validation dependency, not a plugin runtime
dependency.
Owned runtime and tests use Python. Generic shell checks still support external
projects when shell inputs are explicitly supplied; no owned shell runtime remains.

## Activation and ceilings

The tracked pre-commit hook is inactive until each clone runs
`git config core.hooksPath scripts/git-hooks`. There are no grandfathered
file or function exceptions. The checker still accepts `--max-loc` /
`MAX_LOC` and `--max-function-lines` / `MAX_FUNCTION_LINES`. The default
limits remain 400/100. The migration was validated at those limits.
Workflow and server integrity rules remain the stronger boundaries.
The hook does not install automatically. It adds no plugin runtime
dependency.

The commented-code detector is intentionally conservative: it catches common
statement-shaped comments and leaves prose, documentation comments, Markdown,
generated assets, fixtures, and lockfiles alone. It is a signal, not a parser.
