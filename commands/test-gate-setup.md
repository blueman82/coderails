---
description: Set up the test gate for the current project — detects test runner and creates .claude/test_command
---

# Test Gate Setup

Set up the test gate hook for this project. It runs tests before each `git commit` and denies the commit if they fail.

## Steps

1. Check if `.claude/test_command` already exists in the current working directory. If it does, read it and report what's configured. Ask if the user wants to change it.

2. If it doesn't exist, detect the project's test runner by checking for these files (in order):
   - `package.json` → check for a `test` script → use `npm test`
   - `Cargo.toml` → use `cargo test`
   - `pyproject.toml` or `setup.py` or `setup.cfg` → use `pytest -x`
   - `go.mod` → use `go test ./...`
   - `Makefile` → check for a `test` target → use `make test`
   - `mix.exs` → use `mix test`
   - `Gemfile` → use `bundle exec rspec`

3. If a test runner is detected, propose it to the user. If multiple are detected, ask which one to use. If none are detected, ask the user to provide the command.

4. Create the `.claude` directory if it doesn't exist, then write the single-line test command to `.claude/test_command`.

5. Run the test command once to verify it works. Report the result.

6. Confirm: "Test gate is active. Every `git commit` in this project will run `<command>` first. Remove `.claude/test_command` to disable."

7. Explain how to read test output. Each hook run keeps complete stdout and
   stderr under `~/.coderails/test-output/`. Set `CODERAILS_TEST_OUTPUT_DIR` to
   use another directory. A run can contain many tests. On failure, use the
   reader command in the report. Add `--all`, `--start N --end M` (one-based,
   inclusive), or `--search TEXT --before N --after N` for a literal search.
   A read without flags returns metadata and guidance. Expand each request as
   needed; line ranges from one run do not predict ranges in another run.

   Completed logs compress automatically. The compressed-log budget is 1 GiB;
   `CODERAILS_TEST_LOG_BUDGET_BYTES` can change it. The oldest completed logs
   expire first. Active and just-completed runs are protected and can exceed
   the budget. Compact measurement and expiry records persist separately.
   Emitted bytes do not prove model delivery. Ordinary log-file reads bypass
   retrieval telemetry. See [the output reference](../docs/REFERENCE.md#retained-test-gate-output).
