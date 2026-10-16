---
description: Set up the test gate for the current project — detects test runner and creates .claude/test_command
---

# Test Gate Setup

Set up the test gate hook for the current project. This makes `git commit` automatically run tests first — if they fail, the commit is denied.

## Steps

1. Check if `.claude/test_command` already exists in the current working directory. If it does, read it and report what's configured. Ask if the user wants to change it.

2. If it doesn't exist, detect the project's test runner with the script (it owns the ordered marker list: npm `test` script, Cargo, pytest, Go, a Makefile `test` target, mix, Gemfile):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_test_command.py"
   ```

   It prints JSON `{"command": ..., "candidates": [...]}`. A missing directory exits 2 with
   `directory_unavailable`; resolve the project root and rerun before selecting or writing a command.

3. If `command` is set, propose it to the user. If `command` is null and `candidates` has several entries, ask which one to use. If `candidates` is empty, ask the user to provide the command.

4. Create the `.claude` directory if it doesn't exist, then write the single-line test command to `.claude/test_command`.

5. Run the test command once to verify it works. Report the result.

6. Confirm: "Test gate is active. Every `git commit` in this project will run `<command>` first. Remove `.claude/test_command` to disable."

7. Explain that every hook execution of the configured command retains complete
   stdout/stderr in a unique run under `~/.coderails/test-output/` (override with
   `CODERAILS_TEST_OUTPUT_DIR`). A run may contain many tests. On failure, follow
   the reported reader command: add `--all`, `--start N --end M` (one-based,
   inclusive), or `--search TEXT --before N --after N` for literal search.
   Without flags, reads always return metadata and guidance. Expand requests
   explicitly as needed; there is no cross-run line-range prediction.
   Completed logs compress automatically under a 1 GiB compressed-log budget
   (`CODERAILS_TEST_LOG_BUDGET_BYTES` overrides it). Oldest completed logs expire
   first; active and just-completed runs are protected and may exceed the budget.
   Compact measurement and expiry records persist separately. Emitted bytes are
   not proof of model delivery;
   ordinary log-file reads bypass retrieval telemetry. See
   [the output reference](../docs/REFERENCE.md#retained-test-gate-output).
