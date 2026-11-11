---
name: engineering-principles-bash
description: Bash/shell-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for shell script files.
---

# Engineering Principles Bash - Language-Specific Standards

**Version:** 1.0.0
**Purpose:** Apply shell idioms and safety patterns to `.sh` files.
The `engineering-principles` coordinator also selects this skill for scripts with shell shebangs and no `.sh` extension.
See Phase 0 of that skill for its language check.

---

Coderails-owned hooks, workflow helpers, launchers, and tests are Python.
Use these rules for shell code in other projects or integrations. Coderails Python modules use Python rules.

## Bash Idioms (MANDATORY)

### Safety Header
- **`set -euo pipefail`.** Put it at the top of each standalone script that callers run directly.
  `-e` stops on the first unhandled error.
  `-u` makes a misspelled name an error. Without it, Bash can use an empty string silently.
  `-o pipefail` propagates a pipeline error that the last command's exit status could hide.

- **Sourced library files.** A file other scripts read with `source` must not impose `set -e` or `set -u` on its caller.
  The top-level script makes that decision. This includes helper libraries and hook utilities.
  If you add `set -e` to a library, record it in a comment and make sure each caller needs it.

- **PreToolUse and hook scripts.** A hook in a shell-based Codex integration must degrade gracefully.
  It almost always uses `exit 0` for an internal error. An abort can break the harness that started the hook.
  These scripts skip `set -e`. For each risky read, use `|| true` or an explicit fallback.
  The different rules apply to the hook's context.
  Do not "fix" a hook by adding `set -euo pipefail` without checking if it changes the result from "degrade" to "abort."

### Quoting & Expansion
- **Use double quotes around each parameter expansion** unless you want word-splitting or globbing (`"$var"`, not `$var`).
  Missing quotes commonly cause errors with empty values or values that contain spaces or globs.
- **Use double quotes around command substitutions.** Use `local x="$(cmd)"`. Do not use `local x=$(cmd)` with an unquoted use of the result.
- **Use `"${arr[@]}"`** to iterate or pass an array. The `[@]` syntax keeps element boundaries. The `[*]` syntax in `${arr[*]}` gives one word.
- **Use `printf '%s\n'`** for arbitrary or untrusted content.
  Shells differ in how `echo` interprets sequences such as `echo -n` or `-e`.
  If the input starts with a token that looks like a flag, `echo` can interpret it as a flag.
  For example, `echo "$user_input"` behaves differently if the input is literally `-n`.

### `[[ ]]` over `[ ]`
- Use Bash's extended test `[[ ]]` in Bash scripts.
  It does not apply word-splitting or glob expansion to unquoted operands.
  It accepts `&&`, `||`, and `=~` directly and uses `==` and `!=` for pattern matching.

  Use `[ ]` if the script must work in POSIX `sh`. Check the shebang.
  For `#!/bin/sh`, use `[ ]`. For `#!/bin/bash` or `#!/usr/bin/env bash`, prefer `[[ ]]`.

### Avoid Footguns
- **Do not use `eval` on untrusted input.** To build a command dynamically, use an array of arguments.
  For example, set `cmd=(git commit -m "$msg")` and run `"${cmd[@]}"`.
  Other options are a `case` dispatch or a function lookup such as `"$fn_name" "$@"`. A function lookup does not use `eval`.

- **Do not use unquoted glob expansion in loops.** Without `nullglob`, `for f in *.txt` breaks if no paths match.
  It can also break on file names with spaces if the code uses an incorrect `IFS`.
  For filesystem paths, prefer `find ... -print0 | while IFS= read -r -d '' f`.
  If a glob loop is simpler, use `shopt -s nullglob` and handle the no-match condition.

- **Do not use word-splitting for loops.** `for word in $(some_command)` uses whitespace to divide words and can divide a value.
  For one iteration for each line, prefer `while IFS= read -r line; do ... done < <(some_command)`.
  If random access to the lines is necessary, use `mapfile -t lines < <(some_command)`.

- **For a temporary directory change, use `cd` in a subshell.** Use `(cd "$dir" && cmd)` for the temporary change.
  `cd "$dir"; cmd; cd -` changes the caller's directory if a command exits before the last step.
  The subshell cannot change the caller's directory.

### Fail-Fast Argument & Precondition Validation
- **Validate arguments before other work.** If validation does not succeed, stop with a clear stderr message.
  Check mandatory parameters, repository identity, and branch constraints before you change Git data.
- **A helper that can exit non-zero must give the cause.**
  Use one stderr format and keep the caller's exit-status contract.
- **Document each `|| true`.** `|| true` or `|| :` suppresses a command error.
  This can be safe for best-effort cleanup or if "not found" and "lookup failed" can each mean missing.
  In a comment, say why the command error is safe to ignore.

### Function Decomposition Over Monolithic Scripts
- **Use named functions** for argument parsing, precondition validation, work, and reporting.
  Put their sequence in a short `main` function.
- **Use a namespace for function names in a shared library.**
  For example, use `widget::create` and `widget::exists` to prevent silent collisions if multiple callers use the library.
- **Divide long scripts into functions.** A body of 100 or more inline lines with no function boundaries violates this rule.
  Move steps into functions if the script invokes each only one time too.
  This makes control flow and error points with `set -e` clear.

### Avoiding Global Mutable State
- **Prefer `local` for names a function owns.** Bash names have global scope by default.
  Without `local`, one function can change a value that a different function uses.
  Declare local names at the start of the function body, for example `local force_with_lease=0 msg="" want_add=0`.
  Python modules use Python scoping.

- **Command substitution runs in a subshell.** An assignment in `$(...)` does not change values in the caller.
  Capture stdout if only the result is necessary. If the caller needs the assignments, invoke the function directly.
- **A subshell-local cache lasts only for that invocation.** Make the lifetime explicit.
  Do not use values from a helper run in command substitution as a script-wide cache.

### `shellcheck`-Clean Patterns
- If `shellcheck` is available (`command -v shellcheck`), run it on each new or changed script.
  Correct these results immediately:
  - **SC2086** (unquoted shell expansion) — quote it.
  - **SC2046** (unquoted command substitution) — quote it, or if word-splitting is intentional, mark it with a `# shellcheck disable=SC2046` comment explaining why.
  - **SC2164** (`cd` without `||` or `set -e` covering it) — `cd "$dir" || exit 1` or rely on an active `set -e`, explicitly.
  - **SC2155** (`local x=$(cmd)` hides the command's exit status) — declare and assign on different lines: `local x; x=$(cmd)`.
  - **SC2181** — test the command directly with `if cmd; then`. Do not test `$?` with `cmd; if [[ $? -eq 0 ]]; then`.
- A `# shellcheck disable=SCxxxx` marks a pattern the tool can ignore if you document it.
  Put a comment next to it that says why the pattern is necessary.

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Exit if a precondition does not hold | `if [[ cond ]]; then ... rest of function ... fi` | `[[ ! cond ]] && return 1` / `[[ ! cond ]] && { err "..."; }`, then continue without indenting |
| Declare-then-assign | `local x=$(cmd)` | `local x; x=$(cmd)` (preserves `cmd`'s exit status) |
| Array in a loop | `for w in $(cmd)` | `mapfile -t words < <(cmd)` then `for w in "${words[@]}"` |
| Test the command | `cmd; if [[ $? -eq 0 ]]; then` | `if cmd; then` |
| No useless cat | `cat file \| grep pattern` | `grep pattern file` |
| No backticks | `` `cmd` `` | `$(cmd)` |
| Explicit cause of an error | An error fallback with no comment | A fallback with a comment, as shown below |
| Bash extended test | `[ "$x" = "y" ]` | `[[ "$x" == "y" ]]` |

```bash
cmd || true
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
# AFTER: Use `set -e` at script top, quoted expansions, and `[[ ]]`.
# Use an array without `eval`. Use `local` and test the command directly.
# Use the positional argument before array capture, so `shift` has an effect.
# No `|| true` is necessary because `rm -f` exits 0 for missing files.
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

  # Check preconditions before other work.
  git rev-parse --verify "$branch" >/dev/null 2>&1 \
    || { printf 'Unknown branch: %s\n' "$branch" >&2; exit 1; }

  # ... actual work, e.g. skip an interactive confirmation when --force was given ...
  [[ "$force" -eq 1 ]] || : # placeholder: the work reads $force here
}

main "$@"
```

---

## Function Namespacing Template

```bash
#!/usr/bin/env bash
# Multiple callers use `source` on `lib/widget.sh`. This file does not use `set -e` or `set -u`.
# The top-level script makes that decision.

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

- [ ] `set -euo pipefail` at the top of each script that runs directly. See Safety Header for libraries and harness hooks
- [ ] Use double quotes around shell expansions (`"$var"`, `"${arr[@]}"`, `"$(cmd)"`)
- [ ] `[[ ]]` unless the shebang needs POSIX `sh`
- [ ] `eval` only for project-owned config that an attacker cannot control. A comment gives the cause
- [ ] No unquoted glob loops (`for f in *.txt`) without `nullglob` or a `find -print0` alternative
- [ ] No word-splitting used as a loop mechanism (`for w in $(cmd)`) — use `mapfile`/`while read`
- [ ] `local` for each name a function owns
- [ ] No `local x=$(cmd)`. Declare and assign on different lines to keep `cmd`'s exit status
- [ ] No `cmd; if [[ $? -eq 0 ]]` — test the command directly
- [ ] A comment for each `|| true` or `|| :` says why the error is safe to ignore
- [ ] Function namespace (`namespace::function`) in files that multiple callers use with `source`
- [ ] Check preconditions and exit before deep nesting
- [ ] A function for each step you can isolate. Do not use a monolithic body of 100 or more lines
- [ ] Run `shellcheck` if available. Correct results or document why you disable a check
