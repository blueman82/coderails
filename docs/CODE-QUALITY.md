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
100 lines. The limits apply to all paths and functions. The dashboard uses smaller tests and shared fixtures.

Strict commit checks examine tracked files with changes. The full-tree inventory shows problems elsewhere without blocking the commit.

## Enforcement

- **Activated commit hook (blocking):** checks source length, Python syntax and function length, JSON syntax, whitespace, and commented-out code.
  It checks Bash lint and format if the tools are installed. It runs the native Python test suites.
- **Local warnings:** The full-tree inventory and `PostToolUse` feedback from `hooks/scripts/quality_feedback.py` are advisory. The edit hook always exits without blocking a write.
- The Coderails workflow, integrity, task-eval, and protected-file hooks continue to apply.
- YAGNI, KISS, DRY, SSOT, and architecture remain inspection checks. Static checks cannot reliably infer intent without incorrect positive results.
- The strict gate does not check coverage. Coderails has Python and TypeScript code.
  The plugin runtime has no shared coverage boundary for that code and specifies no coverage tool.
  Add a measured threshold only after each part of the runtime in scope has a coverage command that maintainers keep current.

Python checks use Ruff, Black, Pyright, and strict mypy. The strict check fails if a tool does not run. Each provider uses its own import paths.

The pure semantics copies must have the same bytes as their source. The external system skill validator uses PyYAML in its test interpreter. PyYAML is a dependency for validation only.
Owned runtime and tests use Python. Generic shell checks can test external projects if the caller supplies shell inputs.

## Activation and ceilings

Run `git config core.hooksPath scripts/git-hooks` in each clone to activate the tracked pre-commit hook. The same limits apply to all files and functions.

The checker accepts `--max-loc` / `MAX_LOC` and `--max-function-lines` / `MAX_FUNCTION_LINES`. The default limits are 400 and 100 lines. The migration tests use these defaults.

The repository's workflow and server-side integrity rules are stronger controls. Hook installation is manual. The plugin runtime has no new dependency.

The detector flags comments that look like code statements. It skips prose, documentation comments, Markdown, machine-made assets, fixtures, and lockfiles. It uses patterns to flag possible problems.
