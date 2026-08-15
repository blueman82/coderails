---
name: engineering-principles-bash
description: Bash/shell-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for shell script files.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__mcp-exec__*
paths: "**/*.sh"
---

# Engineering Principles Bash - Language-Specific Standards

**Version:** 1.0.0
**Purpose:** Enforce shell idioms and safety patterns on `.sh` files. Shebang-identified shell scripts without a `.sh` extension are routed here by the `engineering-principles` coordinator's own dispatch table before this skill loads — see that skill's Phase 0 for the detection logic; this file doesn't need to duplicate it.

---

## Bash Idioms (MANDATORY)

### Safety Header
- **`set -euo pipefail`** at the top of every standalone script that is *executed* (not sourced) — `-e` stops on the first unhandled error, `-u` turns a typo'd variable name into a hard failure instead of a silent empty string, `-o pipefail` makes a failure anywhere in a pipeline propagate instead of being masked by the last command's exit status.
- **Sourced library files are the deliberate exception.** A file that is `source`d into other scripts (helper libraries, hook utilities) must NOT impose `set -e`/`set -u` on its caller — that decision belongs to the top-level script. `scripts/lib/config.sh` in this repo documents this explicitly: "Guard-script compatible: no `set -euo pipefail` (sourced into scripts that intentionally don't)." If you add `set -e` to a library file, say so in a comment and confirm every caller actually wants it.
- **PreToolUse/hook scripts are a second deliberate exception.** A hook invoked by the Codex harness (see `hooks/scripts/*.sh` in this repo) must degrade gracefully and almost always `exit 0` even on internal failure — a hook that aborts hard can break the calling harness rather than just failing its own check. These scripts intentionally skip `set -e` and guard every risky read with `|| true` or an explicit fallback. This is not sloppiness; it is a documented tradeoff for a different execution context. Don't "fix" a hook script by bolting on `set -euo pipefail` without checking whether that changes its failure mode from "degrade" to "abort."

### Quoting & Expansion
- **Quote every variable expansion** unless you specifically want word-splitting or globbing (`"$var"`, not `$var`). Unquoted expansions are the single most common source of bugs when a value contains spaces, globs, or is empty.
- **Quote command substitutions too**: `local x="$(cmd)"`, not `local x=$(cmd)` used later unquoted.
- **Prefer `"${arr[@]}"` over `${arr[*]}`** when iterating or passing an array — `[@]` preserves element boundaries, `[*]` flattens to one word.
- **Use `printf '%s\n'` instead of `echo`** for arbitrary/untrusted content — `echo` interprets some sequences differently across shells (`echo -n`, `-e`) and can misbehave if the string starts with a flag-like token (e.g. `echo "$user_input"` where the input is literally `-n`).

### `[[ ]]` over `[ ]`
- Use `[[ ]]` (bash's extended test) instead of POSIX `[ ]` in bash scripts: no word-splitting/glob-expansion of unquoted operands, supports `&&`/`||`/`=~` directly, and `==`/`!=` pattern matching. `[ ]` is only appropriate when a script must stay POSIX-`sh`-portable (rare in this repo — check the shebang: `#!/bin/sh` means stay in `[ ]`, `#!/bin/bash` or `#!/usr/bin/env bash` means `[[ ]]` is available and preferred).
- This repo's own hook scripts mix both: some (`test_gate.sh`, `no_edit_on_main.sh`) use `[ ]` throughout even under a `#!/bin/bash` shebang. That's a real inconsistency to flag, not a pattern to copy into new code — new scripts should use `[[ ]]`.

### Avoid Footguns
- **Never `eval` untrusted input.** If you find yourself reaching for `eval` to build a command dynamically, there is almost always a safer construct: an array of arguments (`cmd=(git commit -m "$msg")`; `"${cmd[@]}"`), a `case` dispatch, or a function-name lookup (`"$fn_name" "$@"` — calling a function by variable name doesn't need `eval`). This repo's `hooks/scripts/test_gate.sh` uses `eval "$test_cmd"` deliberately because the test command is project-owned config, not attacker input — but that tradeoff should be a one-line comment, not silent.
- **Avoid unquoted glob expansion in loops** (`for f in *.txt` breaks when there are zero matches, unless `nullglob` is set, and breaks on filenames with spaces if `IFS` isn't handled). Prefer `find ... -print0 | while IFS= read -r -d '' f` for anything touching a real filesystem, or `shopt -s nullglob` when a plain glob loop is genuinely simpler and the empty-match case is handled.
- **Don't rely on word-splitting as your loop mechanism.** `for word in $(some_command)` splits on whitespace unconditionally, including inside values that shouldn't be split. Prefer `while IFS= read -r line; do ... done < <(some_command)` when lines (not words) are the unit, or an array (`mapfile -t lines < <(some_command)`) when you need random access afterward.
- **`cd` inside a subshell, not the caller's shell**, when you only need a temporary directory change: `(cd "$dir" && cmd)` instead of `cd "$dir"; cmd; cd -` — the subshell can't leak a directory change back to the rest of the script even if an earlier step fails partway through.

### Fail-Fast Argument & Precondition Validation
- **Validate arguments before doing any work**, and fail with a clear message on stderr, not a silent default. `scripts/push.sh` calls `require::feature` / `require::repo` (from `scripts/lib/git-common.sh`) as guard clauses right after arg parsing, before any git state is mutated; `scripts/merge.sh` calls `require::repo` the same way. `require::clean` is also defined in `git-common.sh` but is not currently called by either script — it's only stubbed out in test files today, so treat it as defined-but-unused rather than an active guard clause.
- **A helper that can fail must say why it failed**, not just return non-zero. `git-common.sh`'s `err()` helper (`printf ... >&2; exit 1`) centralizes this so every guard clause reports consistently instead of each call site inventing its own message.
- **No silent `|| true` without a reason.** `|| true` (or `|| :`) suppresses a command's failure — sometimes correct (a best-effort cleanup step, a check where "not found" and "lookup failed" are both fine to treat as absent), but it hides a real bug just as often. When you use it, say in a comment *why* this particular failure is safe to ignore. `hooks/scripts/test_gate.sh`'s `IFS= read -r -d '' -t 5 input || true` is safe because a `read` timeout on stdin still leaves `$input` usable; that's worth a one-line note, and ideally the script should have one.

### Function Decomposition Over Monolithic Scripts
- **Break a script into named functions** once it does more than one clearly separable thing — parse args, validate preconditions, do the work, report the result are natural seams. `scripts/push.sh` wraps its entire body in `push::main()` and calls it once at the bottom (`push::main "$@"`); `scripts/lib/git-common.sh` exposes small single-purpose functions (`dirty`, `clean`, `ahead`, `pr::exists`) instead of one large script with inline logic.
- **Namespace function names when a library is sourced by multiple callers** — this repo's convention is `namespace::function` (`pr::num`, `pr::head_sha`, `coderails::config_path`, `sync::main_branch`). This avoids silent collisions when two sourced libraries happen to define a function with the same short name.
- **No monolithic "do everything inline" scripts** — if a script's body reads top-to-bottom as 100+ lines with no function boundaries, that's a KISS/decomposition violation, not a style preference. Extract steps into functions even if each is called exactly once; it makes the control flow (and the `set -e` failure points) legible.

### Avoiding Global Mutable State
- **Prefer `local` for every function-scoped variable.** A bash function's variables are global by default; forgetting `local` on a loop counter or accumulator is a classic source of one function silently corrupting another's state. Every function in `scripts/lib/git-common.sh` and `scripts/push.sh` declares its variables with `local` (`local force_with_lease=0 msg="" want_add=0`) at the top of the function body.
- **Command substitution runs in a subshell — a variable assigned inside `$(...)` never survives back to the caller.** This repo's `git-common.sh` deliberately exploits both sides of that fact, and the two patterns are opposites, not the same rule applied three times:
  - `pr::_trusted_login` and `pr::_trusted_permission` only need to hand a value back via stdout, so they *are* called via command substitution (`trusted=$(pr::_trusted_login)`, `permission=$(pr::_trusted_permission)`, both inside `pr::_trusted_comment_bodies`). Each has an internal `_PR_TRUSTED_LOGIN`/`_PR_TRUSTED_PERMISSION` variable, but per their own header comments this is explicitly **not** a cache that survives across calls — every `$(...)` invocation starts a fresh subshell, so the variable never makes it back to the caller. It only guards against a redundant fetch if the function happened to be called more than once inside the same subshell's lifetime.
  - `pr::_trusted_comment_bodies_or_fail`, by contrast, genuinely needs its assignments (`PR_TRUST_FETCH_FAIL_REASON`, `_PR_TRUSTED_COMMENT_BODIES`) to escape into the caller's shell, so it is called as a plain statement (`pr::_trusted_comment_bodies_or_fail "$num"`) and the caller reads the resulting globals afterward — never as `foo=$(pr::_trusted_comment_bodies_or_fail "$num")`, which would silently discard the escape.

  When you only need a function's stdout, `$(...)` is exactly right and the subshell's transience is a feature; when you need its side-effect variables to persist into the caller's shell, don't wrap the call in `$(...)`.
- **A `$(...)`-wrapped "cache" variable only survives within that one subshell's lifetime — never across the whole script run.** `_PR_TRUSTED_LOGIN` and `_PR_TRUSTED_PERMISSION` in this repo explicitly disclaim caching across processes/subshells despite the variable name suggesting persistence. Treat any state you actually need to survive as either a return value the caller captures explicitly (`$(...)`), or a global set by a function called as a plain statement (never `$(...)`-wrapped), as `pr::_trusted_comment_bodies_or_fail` does.

### `shellcheck`-Clean Patterns
- Run `shellcheck` on every new or modified script when it's available (`command -v shellcheck`). Common findings worth fixing on sight:
  - **SC2086** (unquoted variable) — quote it.
  - **SC2046** (unquoted command substitution) — quote it, or if word-splitting is intentional, mark it with a `# shellcheck disable=SC2046` comment explaining why.
  - **SC2164** (`cd` without `||` or `set -e` covering it) — `cd "$dir" || exit 1` or rely on an active `set -e`, explicitly.
  - **SC2155** (`local x=$(cmd)` masks `cmd`'s exit status with `local`'s own) — declare and assign on separate lines: `local x; x=$(cmd)`. `scripts/push.sh` calls this out directly for its own `push_output`/`push_rc` capture: "`local push_output=$(...)` would mask git's exit status with `local`'s own (always-zero) status." Note this fix is applied in that one spot only — the same file still has uncited `local br=$(branch)`, `local num=$(pr::num)`, and `local url=$(gh pr create ...)` elsewhere, so don't treat `push.sh` as universally SC2155-clean; treat the cited line as the example, not the whole file.
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
