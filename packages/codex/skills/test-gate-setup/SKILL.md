---
name: test-gate-setup
description: Configure the native Coderails Codex commit test gate for the current project by detecting and verifying its test command.
---

# Test Gate Setup

Configure the current project's opt-in commit test gate. The Coderails Codex `PreToolUse` hook reads one command from the current worktree's trusted Git metadata and denies `git commit` when that command fails. A repository file cannot configure this gate.

Work from the project's root directory.

1. Resolve the configuration path with `git rev-parse --git-path coderails/test_command`. If that file exists, read and report its current command. Use `request_user_input` to ask whether to keep or replace it. Stop without changing the file if the user keeps it.
2. Otherwise, detect available test commands:
   - `package.json` with a `test` script: `npm test`
   - `Cargo.toml`: `cargo test`
   - `pyproject.toml`, `setup.py`, or `setup.cfg`: `pytest -x`
   - `go.mod`: `go test ./...`
   - `Makefile` with a `test` target: `make test`
   - `mix.exs`: `mix test`
   - `Gemfile`: `bundle exec rspec`
3. If exactly one command is detected, propose it. If several are detected, use `request_user_input` to select one. If none are detected, ask for a test command.
4. Run the selected command once from the project root. If it fails, report the failure and do not activate the gate unless the user explicitly chooses to keep that failing command.
5. Create the resolved path's parent directory if needed and write the selected command as its single line.
6. Confirm the configured command and explain that deleting the resolved Git-internal file disables the gate.
7. Explain retained output: every hook execution of the configured command is
   one run (possibly many tests), with complete stdout/stderr under
   `~/.coderails/test-output/` or the `CODERAILS_TEST_OUTPUT_DIR` override. Failure
   notices provide measurements, the full log path and a quoted command for
   this provider's `hooks/scripts/test_output.py` reader. Add `--all`,
   `--start N --end M` (one-based, inclusive), or literal
   `--search TEXT --before N --after N`. With no flags, reads always return
   metadata and guidance. Expand requests explicitly as needed; there is no
   cross-run line-range prediction. Completed logs compress automatically
   under a 1 GiB compressed-log budget (`CODERAILS_TEST_LOG_BUDGET_BYTES`
   overrides it). Oldest completed logs expire first; active and just-completed
   runs are protected and may exceed the budget. Compact measurement and expiry
   records persist separately. Reader records measure emitted bytes, not confirmed
   model delivery; direct file reads are unobserved. Only attach actual
   downstream feedback using `observe <request-file> --delivered-bytes N
   --truncated yes|no --source TEXT`.

Do not modify global Codex configuration or Claude-specific files.
