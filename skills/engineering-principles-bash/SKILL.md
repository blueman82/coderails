---
name: engineering-principles-bash
description: Bash/shell-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for shell script files.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__mcp-exec__*
paths: "**/*.sh"
---

# Engineering Principles Bash - Language-Specific Standards

**Version:** 1.0.0
**Purpose:** Enforce shell idioms and safety patterns on `.sh` files. The
`engineering-principles` coordinator also sends shell scripts without a `.sh`
extension here when they have a shebang. See Phase 0 of that skill for the
detection rule.

---

Coderails-owned hooks, workflow helpers, launchers, and tests are Python. The rules below apply when working on shell code in another project or integration; they do not describe the implementation of Coderails Python modules.

## Bash Idioms (MANDATORY)

### Safety Header
- **Use `set -euo pipefail`** at the top of each executed standalone script. Do not impose it on a sourced file. `-e` stops on the first unhandled error. `-u` rejects an unset variable. `pipefail` reports a failed pipeline command even if the last command succeeds.
- **Sourced library files are an exception.** A sourced file must not impose `set -e` or `set -u` on its caller. The top-level script owns that choice. If you add `set -e` to a library, explain the choice in a comment and check every caller.
- **PreToolUse and hook scripts are another exception.** A hook in a shell-based Claude Code integration must usually return `exit 0` after an internal error. An abrupt exit can break the calling harness. These scripts skip `set -e` and protect risky reads with `|| true` or an explicit fallback. Check this failure contract before adding `set -euo pipefail` to a hook.

### Quoting & Expansion
- **Quote every variable expansion** unless you specifically want word-splitting or globbing (`"$var"`, not `$var`). Unquoted expansions are the single most common source of bugs when a value contains spaces, globs, or is empty.
- **Quote command substitutions too**: `local x="$(cmd)"`, not `local x=$(cmd)` used later unquoted.
- **Prefer `"${arr[@]}"` over `${arr[*]}`** when iterating or passing an array — `[@]` preserves element boundaries, `[*]` flattens to one word.
- **Use `printf '%s\n'` instead of `echo`** for arbitrary or untrusted content. Shells interpret some `echo` options differently. For example, input of `-n` can change the behavior of `echo "$user_input"`.

### `[[ ]]` over `[ ]`
- Use `[[ ]]` in Bash scripts. It avoids splitting and glob expansion of operands. It supports `&&`, `||`, `=~`, and pattern matching with `==` or `!=`.
- Use POSIX `[ ]` when the script must run under `sh`. Check the shebang: `#!/bin/sh` requires portable syntax. `#!/bin/bash` and `#!/usr/bin/env bash` allow `[[ ]]`.

### Avoid Footguns
- **Never `eval` untrusted input.** For a dynamic command, use an argument array such as `cmd=(git commit -m "$msg")` followed by `"${cmd[@]}"`. A `case` branch or a function call through `"$fn_name" "$@"` may also fit. Neither needs `eval`.
- **Avoid unquoted glob expansion in loops.** `for f in *.txt` can fail when no file matches. Set `nullglob` and handle the empty case if a glob loop is simplest. For filesystem input, prefer `find ... -print0 | while IFS= read -r -d '' f`; it handles names with spaces.
- **Do not use word splitting as a loop mechanism.** `for word in $(some_command)` splits inside values that contain spaces. For lines, use `while IFS= read -r line; do ... done < <(some_command)`. Use `mapfile -t lines < <(some_command)` when later steps need random access.
- **Use a subshell for a temporary directory change:** `(cd "$dir" && cmd)`. Do not use `cd "$dir"; cmd; cd -` for this case. The subshell keeps the caller's directory unchanged if a step fails.

### Fail-Fast Argument & Precondition Validation
- **Validate arguments before doing any work**, and fail with a clear message on stderr. Check required parameters, repository identity and branch constraints before mutating Git state.
- **A helper that can fail must say why it failed**, not just return non-zero. Centralize the stderr format while preserving the caller's exit-status contract.
- **Do not use silent `|| true` without a reason.** It suppresses a command failure. This can be correct for best-effort cleanup or an optional lookup. Add a comment that says why this failure is safe to ignore.

### Function Decomposition Over Monolithic Scripts
- **Break a script into named functions** for argument parsing, precondition validation, execution and reporting. A short `main` function should make their order visible.
- **Namespace function names when a library is sourced by multiple callers**, such as `widget::create` and `widget::exists`, to avoid silent collisions.
- **Avoid a monolithic script.** A 100-line body with no function boundaries hides its control flow and `set -e` failure points. Extract named steps even when each runs once.

### Avoiding Global Mutable State
- **Use `local` for function-scoped variables.** Bash variables are global by default. An unmarked counter can change another function's state. Declare local values near the start of the function, for example `local force_with_lease=0 msg="" want_add=0`. Python modules use Python scoping.
- **Command substitution runs in a subshell.** A variable assigned inside `$(...)` does not survive in the caller. Capture stdout when only a value is needed; invoke the function directly when its variable assignments must remain visible.
- **A subshell-local cache does not persist across calls.** Make the lifetime explicit. Do not describe a variable set by a command-substituted helper as a script-wide cache.

### `shellcheck`-Clean Patterns
- Run `shellcheck` on every new or modified script when it's available (`command -v shellcheck`). Common findings worth fixing on sight:
  - **SC2086** (unquoted variable) — quote it.
  - **SC2046** (unquoted command substitution) — quote it, or if word-splitting is intentional, mark it with a `# shellcheck disable=SC2046` comment explaining why.
  - **SC2164** (`cd` without `||` or `set -e` covering it) — `cd "$dir" || exit 1` or rely on an active `set -e`, explicitly.
  - **SC2155** (`local x=$(cmd)` masks the command's exit status with `local`'s own) — declare and assign separately: `local x; x=$(cmd)`.
  - **SC2181** (checking `$?` instead of the command directly) — `if cmd; then` not `cmd; if [[ $? -eq 0 ]]; then`.
- A `# shellcheck disable=SCxxxx` is a documented exception, not a way to silence the tool — it should sit next to a comment explaining why the flagged pattern is intentional here.

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Guard clause | `if [[ cond ]]; then ... rest of function ... fi` | `[[ ! cond ]] && return 1` / `[[ ! cond ]] && { err "..."; }`, then continue unindented |
| Declare-then-assign | `local x=$(cmd)` | `local x; x=$(cmd)` (preserves `cmd`'s exit status) |
| Array over word-splitting | `for w in $(cmd)` | `mapfile -t words < <(cmd)` then `for w in "${words[@]}"` |
| Direct test | `cmd; if [[ $? -eq 0 ]]; then` | `if cmd; then` |
| No useless cat | `cat file \| grep pattern` | `grep pattern file` |
| No backticks | `` `cmd` `` | `$(cmd)` |
| Explicit failure reason | `cmd \|\| true` (no comment) | `cmd \|\| true  # best-effort: cleanup step, ok if nothing to remove` |
| `[[ ]]` over `[ ]` | `[ "$x" = "y" ]` | `[[ "$x" == "y" ]]` |

---

## Example: Before/After

```bash
# BEFORE (violations: no set -e, unquoted expansions, [ ] with no quoting,
# eval on a dynamic string, no local, $? check, silent || true)
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
# AFTER (set -e at script top; quoted expansions; [[ ]]; no eval — direct
# invocation with an array; local; direct test; positionals consumed before
# the array capture, so `shift` isn't dead code; no unnecessary || true —
# `rm -f` already exits 0 on missing files)
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

  # Fail fast on preconditions before doing any real work.
  git rev-parse --verify "$branch" >/dev/null 2>&1 \
    || { printf 'Unknown branch: %s\n' "$branch" >&2; exit 1; }

  # ... actual work, e.g. skip an interactive confirmation when --force was given ...
  [[ "$force" -eq 1 ]] || : # placeholder: real work reads $force here
}

main "$@"
```

---

## Function Namespacing Template

```bash
#!/usr/bin/env bash
# lib/widget.sh — sourced by multiple callers; deliberately no set -e/-u here
# (that decision belongs to the top-level script that sources this file).

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

- [ ] `set -euo pipefail` at the top of every standalone executed script (not sourced libraries, not harness hooks — see Safety Header exceptions)
- [ ] Every variable expansion quoted (`"$var"`, `"${arr[@]}"`, `"$(cmd)"`)
- [ ] `[[ ]]` used instead of `[ ]` (unless the shebang requires POSIX `sh`)
- [ ] No `eval` on anything that isn't project-owned, non-attacker-controlled config — and even then, commented as to why
- [ ] No unquoted glob loops (`for f in *.txt`) without `nullglob` or a `find -print0` alternative
- [ ] No word-splitting used as a loop mechanism (`for w in $(cmd)`) — use `mapfile`/`while read`
- [ ] Every function-scoped variable declared `local`
- [ ] No `local x=$(cmd)` — declare and assign on separate lines so `cmd`'s exit status isn't masked
- [ ] No `cmd; if [[ $? -eq 0 ]]` — test the command directly
- [ ] Every `|| true` / `|| :` has a comment explaining why the failure is safe to ignore
- [ ] Functions namespaced (`namespace::function`) in any file sourced by more than one caller
- [ ] Guard clauses / early returns over deep nesting
- [ ] Script decomposed into functions once it does more than one clearly separable thing — no 100+ line monolithic body
- [ ] `shellcheck` run and clean (or disables are commented with a reason) when `shellcheck` is available
