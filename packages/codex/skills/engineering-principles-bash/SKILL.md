---
name: engineering-principles-bash
description: Bash/shell-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for shell script files.
---

# Engineering Principles Bash - Language-Specific Standards

**Version:** 1.0.0
**Purpose:** Enforce shell idioms and safety patterns on `.sh` files. Shebang-identified shell scripts without a `.sh` extension are routed here by the `engineering-principles` coordinator's own dispatch table before this skill loads — see that skill's Phase 0 for the detection logic; this file doesn't need to duplicate it.

---

Coderails-owned hooks, workflow helpers, launchers, and tests are Python. The rules below apply when working on shell code in another project or integration; they do not describe the implementation of Coderails Python modules.

## Bash Idioms (MANDATORY)

### Safety Header
- **`set -euo pipefail`** at the top of every standalone script that is *executed* (not sourced) — `-e` stops on the first unhandled error, `-u` turns a typo'd variable name into a hard failure instead of a silent empty string, `-o pipefail` makes a failure anywhere in a pipeline propagate instead of being masked by the last command's exit status.
- **Sourced library files are the deliberate exception.** A file that is `source`d into other scripts (helper libraries, hook utilities) must NOT impose `set -e`/`set -u` on its caller — that decision belongs to the top-level script. If you add `set -e` to a library file, say so in a comment and confirm every caller actually wants it.
- **PreToolUse/hook scripts are a second deliberate exception.** A hook invoked by the Codex harness in a shell-based integration must degrade gracefully and almost always `exit 0` even on internal failure — a hook that aborts hard can break the calling harness rather than just failing its own check. These scripts intentionally skip `set -e` and guard every risky read with `|| true` or an explicit fallback. This is not sloppiness; it is a documented tradeoff for a different execution context. Don't "fix" a hook script by bolting on `set -euo pipefail` without checking whether that changes its failure mode from "degrade" to "abort."

### Quoting & Expansion
- **Quote every variable expansion** unless you specifically want word-splitting or globbing (`"$var"`, not `$var`). Unquoted expansions are the single most common source of bugs when a value contains spaces, globs, or is empty.
- **Quote command substitutions too**: `local x="$(cmd)"`, not `local x=$(cmd)` used later unquoted.
- **Prefer `"${arr[@]}"` over `${arr[*]}`** when iterating or passing an array — `[@]` preserves element boundaries, `[*]` flattens to one word.
- **Use `printf '%s\n'` instead of `echo`** for arbitrary/untrusted content — `echo` interprets some sequences differently across shells (`echo -n`, `-e`) and can misbehave if the string starts with a flag-like token (e.g. `echo "$user_input"` where the input is literally `-n`).

### `[[ ]]` over `[ ]`
- Use `[[ ]]` (bash's extended test) instead of POSIX `[ ]` in bash scripts: no word-splitting/glob-expansion of unquoted operands, supports `&&`/`||`/`=~` directly, and `==`/`!=` pattern matching. `[ ]` is only appropriate when a script must stay POSIX-`sh`-portable (rare in this repo — check the shebang: `#!/bin/sh` means stay in `[ ]`, `#!/bin/bash` or `#!/usr/bin/env bash` means `[[ ]]` is available and preferred).

### Avoid Footguns
- **Never `eval` untrusted input.** If you find yourself reaching for `eval` to build a command dynamically, there is almost always a safer construct: an array of arguments (`cmd=(git commit -m "$msg")`; `"${cmd[@]}"`), a `case` dispatch, or a function-name lookup (`"$fn_name" "$@"` — calling a function by variable name doesn't need `eval`).
- **Avoid unquoted glob expansion in loops** (`for f in *.txt` breaks when there are zero matches, unless `nullglob` is set, and breaks on filenames with spaces if `IFS` isn't handled). Prefer `find ... -print0 | while IFS= read -r -d '' f` for anything touching a real filesystem, or `shopt -s nullglob` when a plain glob loop is genuinely simpler and the empty-match case is handled.
- **Don't rely on word-splitting as your loop mechanism.** `for word in $(some_command)` splits on whitespace unconditionally, including inside values that shouldn't be split. Prefer `while IFS= read -r line; do ... done < <(some_command)` when lines (not words) are the unit, or an array (`mapfile -t lines < <(some_command)`) when you need random access afterward.
- **`cd` inside a subshell, not the caller's shell**, when you only need a temporary directory change: `(cd "$dir" && cmd)` instead of `cd "$dir"; cmd; cd -` — the subshell can't leak a directory change back to the rest of the script even if an earlier step fails partway through.

### Fail-Fast Argument & Precondition Validation
- **Validate arguments before doing any work**, and fail with a clear message on stderr. Check required parameters, repository identity and branch constraints before mutating Git state.
- **A helper that can fail must say why it failed**, not just return non-zero. Centralize the stderr format while preserving the caller's exit-status contract.
- **No silent `|| true` without a reason.** `|| true` (or `|| :`) suppresses a command's failure — sometimes correct (a best-effort cleanup step, a check where "not found" and "lookup failed" are both fine to treat as absent), but it hides a real bug just as often. When you use it, say in a comment *why* this particular failure is safe to ignore.

### Function Decomposition Over Monolithic Scripts
- **Break a script into named functions** for argument parsing, precondition validation, execution and reporting. A short `main` function should make their order visible.
- **Namespace function names when a library is sourced by multiple callers**, such as `widget::create` and `widget::exists`, to avoid silent collisions.
- **No monolithic "do everything inline" scripts** — if a script's body reads top-to-bottom as 100+ lines with no function boundaries, that's a KISS/decomposition violation, not a style preference. Extract steps into functions even if each is called exactly once; it makes the control flow (and the `set -e` failure points) legible.

### Avoiding Global Mutable State
- **Prefer `local` for every function-scoped variable.** A bash function's variables are global by default; forgetting `local` on a loop counter or accumulator is a classic source of one function silently corrupting another's state. Declare function-scoped shell variables explicitly, for example `local force_with_lease=0 msg="" want_add=0`, at the top of the function body. Python modules use Python scoping instead.
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
