---
description: Set up the test gate for the current project — detects test runner and creates .claude/test_command
---

# Test Gate Setup

Set up the test gate hook for the current project. The hook runs tests before each `git commit`. If the tests do not succeed, the hook denies the commit.

## Steps

1. Check for `.claude/test_command` in the current working directory.
   If you find the file, read it and report its command. Get the user's decision before you change it.

2. If you do not find the file, use the script to find the project's test runner. It checks markers in sequence. It checks the npm `test` script, Cargo, pytest, Go, a Makefile `test` target, mix, and Gemfile.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_test_command.py"
   ```

   It prints JSON `{"command": ..., "candidates": [...]}`. For an unavailable directory, the script exits 2 with
   `directory_unavailable`. Resolve the project root and rerun the script before you select or write a command.

3. If `command` is set, propose it to the user. If `command` is null and `candidates` lists multiple entries, get the user's selection. If `candidates` is empty, get the test command from the user.

4. Make the `.claude` directory if necessary. Write the single-line test command to `.claude/test_command`.

5. Run the test command one time to check that it works. Report the result.

6. Tell the user: "Test gate is active. Every `git commit` in this project will run `<command>` first. Remove `.claude/test_command` to disable."

7. Tell the user that the hook keeps all stdout and stderr for each run. Each run has its own directory in `~/.coderails/test-output/`. Use `CODERAILS_TEST_OUTPUT_DIR` to change that path. One run can contain many tests.

   If tests do not succeed, use the reader command in the report. Add `--all`, `--start N --end M` (one-based, inclusive), or `--search TEXT --before N --after N` for literal search. With no flags, the reader gives metadata and guidance only. Use flags to get more output. The reader does not predict line ranges across runs.

   The hook compresses completed logs automatically and uses a 1 GiB budget for compressed logs. `CODERAILS_TEST_LOG_BUDGET_BYTES` overrides the budget. The oldest completed logs expire first. The hook keeps active and just-completed runs, which can go above the budget.

   The hook keeps compact measurement and expiry records apart from the logs. Bytes sent do not prove the model got them. If you read the log files directly, the reads bypass retrieval telemetry. See [the output documentation](../docs/REFERENCE.md#retained-test-gate-output).
