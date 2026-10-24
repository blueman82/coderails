---
description: Set up the test gate for the current project — detects test runner and creates .claude/test_command
---

# Test Gate Setup

Set up the test gate hook for this project. It runs tests before each
`git commit`. It denies the commit if the tests fail.

## Steps

1. Check for `.claude/test_command` in the current working directory.
   If it exists, read and report its command. Ask whether to change it.

2. If the file does not exist, check these project files in order:
   - `package.json` → check for a `test` script → use `npm test`
   - `Cargo.toml` → use `cargo test`
   - `pyproject.toml` or `setup.py` or `setup.cfg` → use `pytest -x`
   - `go.mod` → use `go test ./...`
   - `Makefile` → check for a `test` target → use `make test`
   - `mix.exs` → use `mix test`
   - `Gemfile` → use `bundle exec rspec`

3. Propose a detected test runner. If several are available, ask the user
   which to use. If none is available, ask for a test command.

4. Create `.claude` if needed. Write one line with the test command to
   `.claude/test_command`.

5. Run the test command once. Report the result.

6. Confirm: "Test gate is active. Every `git commit` in this project will run `<command>` first. Remove `.claude/test_command` to disable."

7. Explain how to read test output. Each hook run keeps complete stdout and
   stderr under `~/.coderails/test-output/`. Set `CODERAILS_TEST_OUTPUT_DIR`
   to use another directory. One run can contain many tests. On failure,
   use the reader command in the report. Use `--all` for the full log.
   Use `--start N --end M` for an inclusive, one-based range. Use
   `--search TEXT --before N --after N` for a literal search. A read with
   no flags returns metadata and guidance. Expand a request as needed.
   Line numbers from one run do not predict numbers in another run.

   Completed logs compress automatically. The compressed-log budget is
   1 GiB. `CODERAILS_TEST_LOG_BUDGET_BYTES` changes that limit. The oldest
   completed logs expire first. Active and recent runs are protected, so
   they can exceed the budget. Compact measurements and expiry records
   persist separately. Emitted bytes do not prove model delivery.
   Ordinary log-file reads bypass retrieval telemetry. See
   [the output reference](../docs/REFERENCE.md#retained-test-gate-output).
