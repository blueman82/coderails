---
name: engineering-principles-bash
description: Bash/shell-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for shell script files.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__mcp-exec__*
paths: "**/*.sh"
---

# Engineering Principles Bash - Language-Specific Standards

**Version:** 1.0.0

Apply shell idioms and safety patterns to `.sh` files.
Phase 0 of `engineering-principles` also selects this skill for shell shebangs without a `.sh` extension.

---

Coderails hooks, workflow helpers, launchers, and tests use Python.
Use these rules for shell code in other projects or integrations.

## Bash Idioms (MANDATORY)

### Safety Header
- Put `set -euo pipefail` at the top of each standalone script that you run. The `-e` option stops on an unhandled error. The `-u` option stops on an unset name, such as a typing error. The `-o pipefail` option reports an error from a command in the pipeline. The last command’s success cannot hide it.
- **Sourced libraries.** If a caller uses `source` on the file, let the top-level script control `set -e` and `set -u`. If you set `set -e` in a library, explain it in a comment. Check that each caller can use this setting.
- **PreToolUse and other hooks.** In a shell integration with Claude Code, a hook usually uses `exit 0` on internal errors. A hook that aborts can break the harness. These hooks leave `set -e` off and check risky reads with `|| true` or a fallback. Before you add `set -euo pipefail`, check if the hook changes from "degrade" to "abort."

### Quoting & Expansion
- **Put double quotes around each expansion.** Use `"$var"` unless you intend word splitting or globbing. Without quotes, spaces, globs, and empty values can cause errors.
- **Put double quotes around command substitutions.** Use `local x="$(cmd)"` and double quotes when you use the value. Do not use `local x=$(cmd)` and then use the value without quotes.
- **Prefer `"${arr[@]}"` to `${arr[*]}` for arrays.** With `[@]`, each element stays one word. With `[*]`, the elements become one word.
- **Use `printf '%s\n'` for arbitrary or untrusted content.** The `echo` command interprets some sequences differently in different shells. For example, a value of `-n` can be a flag in `echo "$user_input"`. The same issue applies to `echo -n` and `-e`.

### `[[ ]]` over `[ ]`
- Use `[[ ]]` in Bash scripts. It does not apply word-splitting or glob expansion to unquoted operands. It accepts `&&`, `||`, `=~`, and `==` or `!=` pattern checks. Use `[ ]` for POSIX portability. If the shebang is `#!/bin/sh`, use `[ ]`. If it is `#!/bin/bash` or `#!/usr/bin/env bash`, prefer `[[ ]]`.

### Avoid Footguns
- **Do not use `eval` on untrusted input.** Build a command with an argument array (`cmd=(git commit -m "$msg")` and `"${cmd[@]}"`). Or use `case` or a function lookup such as `"$fn_name" "$@"`.
- **Use a loop that handles empty results and spaces.** With no matches, `for f in *.txt` can get the literal glob. With an unquoted filename expansion, Bash can read the parts as different words. Prefer `find ... -print0 | while IFS= read -r -d '' f` for filesystem entries. For a simpler glob loop, use `shopt -s nullglob` and check the empty result.
- **Do not use word-splitting in a loop.** The loop `for word in $(some_command)` uses whitespace as word boundaries. For lines, use `while IFS= read -r line; do ... done < <(some_command)`. For random access, use an array with `mapfile -t lines < <(some_command)`.
- **Use `cd` in a subshell for a temporary directory change.** Prefer `(cd "$dir" && cmd)` to `cd "$dir"; cmd; cd -`. The parent directory stays the same if the command fails.

### Fail-Fast Argument & Precondition Validation
- **Check arguments before work.** Check required parameters, repo identity, and branch limits before changing Git data. If a check fails, give a clear message on stderr and a nonzero status.
- **A helper must report its error.** Give an error message and a nonzero status. Use one stderr format and keep the caller’s exit-status contract.
- **Document each `|| true` or `|| :`.** These expressions hide an error from the caller. They can be correct for best-effort cleanup. For example, "not found" and "lookup failed" can mean that data is unavailable. Write a comment that says why this error can be ignored.

### Function Decomposition Over Monolithic Scripts
- **Use named functions** for argument parsing, precondition checks, execution, and reporting. Use a short `main` to show the sequence.
- **Use a namespace if multiple callers source the same library.** For example, use `widget::create` and `widget::exists` to prevent name collisions.
- **Keep function boundaries in long scripts.** A body of 100 or more lines without functions hides control flow and points where `set -e` can stop the script. Make named functions for one-time steps too.

### Avoiding Global Mutable State
- **Use `local` for names scoped to a function.** Bash names are global by default. A function can change a loop counter or accumulator that a different function uses. For example, use `local force_with_lease=0 msg="" want_add=0` at the start of the function. Python modules use Python scoping.
- **Command substitution uses a subshell.** A name you set in `$(...)` does not stay set in the caller. Capture stdout if you only require a value. Invoke the function directly to keep the names it sets.
- **A subshell-local cache lasts only for that subshell.** Specify the cache lifetime. Do not use a command substitution helper to make a script-wide cache.

### `shellcheck`-Clean Patterns
- If `command -v shellcheck` succeeds, run `shellcheck` on each new or changed script. Check these diagnostics first.
  - **SC2086**. Put double quotes around the expansion.
  - **SC2046**. Put double quotes around the command substitution. To use word-splitting intentionally, add `# shellcheck disable=SC2046` and a comment that says why.
  - **SC2164**. Use `cd "$dir" || exit 1` or explicitly rely on active `set -e`.
  - **SC2155**. The `local` in `local x=$(cmd)` hides the command’s exit status. Use two statements: `local x; x=$(cmd)`.
  - **SC2181**. Check the command directly with `if cmd; then`. Do not use `cmd; if [[ $? -eq 0 ]]; then`.
- Put a comment with each `# shellcheck disable=SCxxxx` that says why the pattern is intentional.

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Check before the function body | `if [[ cond ]]; then ... rest of function ... fi` | `[[ ! cond ]] && return 1` / `[[ ! cond ]] && { err "..."; }`, then continue unindented |
| Declare-then-assign | `local x=$(cmd)` | `local x; x=$(cmd)` (keeps the exit status from `cmd`) |
| Array for loop values | `for w in $(cmd)` | `mapfile -t words < <(cmd)` then `for w in "${words[@]}"` |
| Check the command directly | `cmd; if [[ $? -eq 0 ]]; then` | `if cmd; then` |
| No useless cat | `cat file \| grep pattern` | `grep pattern file` |
| No backticks | `` `cmd` `` | `$(cmd)` |
| Comment on ignored errors | An ignored error without a comment | A comment that says why the error is safe to ignore |
| Bash conditional test | `[ "$x" = "y" ]` | `[[ "$x" == "y" ]]` |

For best-effort cleanup, add a comment to `cmd || true`:

```bash
cmd || true  # best-effort: cleanup step, ok if nothing to remove
```

---

## Example: Before/After

```bash
# BEFORE (violations: no set -e, unquoted expansions, [ ] with no quoting,
# eval on a dynamic string, no local, $? check, silent `|| true`)
process() {
  files=$1
  for f in $files
  do
    if [ -f $f ]
    then
      eval "grep $2 $f"
      result=$?
      if [ $result -eq 0 ]
      then
        echo Found match in $f
      fi
    fi
  done
  rm -f /tmp/scratch* || true
}
```

```bash
# AFTER: set -e at the top, quoted expansions, and [[ ]].
# Use an argument array, local names, and a direct command test.
# Read the first positional value and use `shift` before you build the array.
# `rm -f` exits 0 for missing files, so no `|| true` is necessary.
set -euo pipefail

process() {
  local pattern="$1"; shift
  local files=("$@")
  local f
  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    if grep -q "$pattern" "$f"; then
      printf 'Found match in %s\n' "$f"
    fi
  done
  rm -f /tmp/scratch*
}
```

---

## Argument Validation Template

```bash
#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s <branch> [--force]\n' "$(basename "$0")" >&2
}

main() {
  local branch="${1:-}" force=0
  [[ -z "$branch" ]] && { usage; exit 1; }
  [[ "${2:-}" == "--force" ]] && force=1

  # Check preconditions before starting the work.
  git rev-parse --verify "$branch" >/dev/null 2>&1 \
    || { printf 'Unknown branch: %s\n' "$branch" >&2; exit 1; }

  # Do the work. For example, skip interactive confirmation if the caller gives `--force`.
  [[ "$force" -eq 1 ]] || : # The work reads $force here.
}

main "$@"
```

---

## Function Namespacing Template

```bash
#!/usr/bin/env bash
# Callers source lib/widget.sh. The top-level script controls set -e and set -u.

widget::create() {
  local name="${1:-}"
  [[ -n "$name" ]] || { printf 'widget::create: name required\n' >&2; return 1; }
  printf 'created %s\n' "$name"
}

widget::exists() {
  local name="${1:-}"
  [[ -f "$name.widget" ]]
}
```

---

## Checklist

Before completing bash/shell code changes:

- [ ] `set -euo pipefail` at the top of each standalone script you run. Follow the Safety Header rules for libraries and hooks.
- [ ] Put double quotes around each expansion (`"$var"`, `"${arr[@]}"`, `"$(cmd)"`)
- [ ] Use `[[ ]]` unless the shebang specifies POSIX `sh`.
- [ ] Use `eval` only with project-owned config that an attacker cannot control. Write a comment that says why you use it.
- [ ] No unquoted glob loops (`for f in *.txt`) without `nullglob` or a `find -print0` alternative
- [ ] No word-splitting used as a loop mechanism (`for w in $(cmd)`) — use `mapfile`/`while read`
- [ ] Use `local` for each name scoped to a function.
- [ ] Use one statement for `local` and one to set the value. Keep the command’s exit status.
- [ ] No `cmd; if [[ $? -eq 0 ]]` — test the command directly
- [ ] Each `|| true` or `|| :` has a comment that says why you can ignore a nonzero exit.
- [ ] Use `namespace::function` if more than one caller sources the file.
- [ ] Check conditions and exit the function to prevent deep nesting.
- [ ] Use a function for each step that can run independently. Keep function boundaries in scripts of 100 or more lines.
- [ ] If available, run `shellcheck`. Correct the problems it reports or document why you disable a check.
