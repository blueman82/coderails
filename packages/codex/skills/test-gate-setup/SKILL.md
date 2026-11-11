---
name: test-gate-setup
description: Configure the native Coderails Codex commit test gate for the current project by detecting and verifying its test command.
---

# Test Gate Setup

Configure the current project's opt-in commit test gate.
The Coderails Codex `PreToolUse` hook reads one command from the current worktree's trusted Git metadata and denies `git commit` when that command fails.
A repository file cannot configure this gate.

Work from the project's root directory.

1. Resolve the configuration path with `git rev-parse --git-path coderails/test_command`.
   If that file exists, read and report its current command.
   Use `request_user_input` to let the user select one option: keep it or replace it.
   Stop without changing the file if the user keeps it.

2. If there is no file, find available test commands with `scripts/detect_test_command.py`.
   Use `../../scripts/detect_test_command.py` relative to this `SKILL.md`. Run it from the project root.
   The script defines the marker list sequence. It prints JSON `{"command": ..., "candidates": [...]}`.
   If the directory is unavailable, the script exits 2 with `directory_unavailable`.
   Find the project root and run it again before you select or write a command.

3. If the script sets `command`, propose it.
   If `command` is null and `candidates` has multiple entries, use `request_user_input` to select one.
   If `candidates` is empty, ask for a test command.

4. Run the selected command one time from the project root.
   If the command exits with an error, report the error. Activate the gate only if the user explicitly selects that command.
5. Make the resolved path's parent directory if needed and write the selected command as its single line.
6. Give the configured command. Tell the user that removal of the resolved Git-internal file disables the gate.
7. Tell the user about test output.

   Each time the hook uses the configured command, it records one run. One run can have multiple tests.
   It records full stdout and stderr in `~/.coderails/test-output/` or the `CODERAILS_TEST_OUTPUT_DIR` override.
   Error notices give measurements, the full log path, and a quoted command for this provider's `hooks/scripts/test_output.py` reader.

   Add `--all`, `--start N --end M` (one-based, inclusive), or literal `--search TEXT --before N --after N`.
   With no flags, reads give metadata and guidance. Explicitly select more output as necessary.
   The reader does not predict line ranges across runs.

   The tool compresses completed logs automatically. It uses a 1 GiB budget unless `CODERAILS_TEST_LOG_BUDGET_BYTES` overrides it.
   The oldest completed logs expire first. The tool keeps active runs and newly completed runs.
   These runs can use more than the budget. Compact measurement and expiry records stay independently.

   Reader records measure the bytes it sends. They do not show that the model received them.
   The reader has no record of direct file reads.
   Use `observe <request-file> --delivered-bytes N --truncated yes|no --source TEXT` only to attach actual downstream feedback.

Do not change global Codex configuration or Claude-specific files.
