---
description: Set up the test gate for the current project — detects test runner and creates .claude/test_command
---

# Test Gate Setup

Set up the test gate hook for the current project. This makes `git commit` automatically run tests first — if they fail, the commit is denied.

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
