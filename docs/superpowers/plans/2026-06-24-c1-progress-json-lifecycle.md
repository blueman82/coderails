# C1 — progress.json lifecycle + presence/ownership guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the agentic-loop skill is active in a session, make a session-owned `progress.json` reliably exist at a deterministic location, mechanically enforced by a Stop hook — without affecting normal (non-loop) sessions.

**Architecture:** A shared path-helper script is the *sole* authority for the `progress.json` path (a model can never reproduce a cwd-derived key, so it must never compute the path). A new Stop hook (`loop_state_guard.sh`) detects an active loop via a structured `jq` match on a `coderails:agentic-loop` Skill `tool_use`, then blocks (exit 2) unless a session-owned file is present. The `agentic-loop` SKILL.md gains a stub-first contract so a compliant loop writes the file before its first stop, degrading the block to a backstop.

**Tech Stack:** Bash 3.2-compatible shell, `jq`, the repo's existing hook idioms (`hooks/scripts/check_verify_loop.sh` is the canonical pattern).

## Global Constraints

- **Bash hook conventions (copy `check_verify_loop.sh`):** read payload from stdin via `input=$(cat)`; parse with `jq`; numbered skip-gates that `exit 0` early (cheapest first); block via `exit 2` with a message on **stderr**; append a single-line `key=value` entry to `$CLAUDE_DISCIPLINE_LOG` (default `~/.claude/discipline.log`); retry the transcript read with backoff for the flush race.
- **The model NEVER computes the path.** Both the guard and the orchestrator obtain the path from `hooks/scripts/lib/agentic_loop_path.sh`. The block message carries the resolved absolute path so the model copies, never derives.
- **Loop-active detection is structured, never textual.** A `jq` match on a `tool_use` with `name=="Skill"` and `input.skill` ending in `agentic-loop`. A text grep for "agentic-loop" is forbidden — it would tyrannise maintainers working on the skill.
- **`install.sh` arms scripts via an EXPLICIT hardcoded list (lines 322–325), not a glob.** Both new scripts must be appended to that `for script in …` list or they ship without `+x` and the hook silently fails.
- **Bash 3.2 compatible** (macOS ships bash 3.2 as `/bin/bash`): no associative arrays, no `${var,,}` lowercasing, no `mapfile`.
- **C1 enforces presence + ownership ONLY**, never content freshness (that is C2's job).

---

## File structure

| File | Responsibility |
|---|---|
| `hooks/scripts/lib/agentic_loop_path.sh` (create) | Sole authority for the `progress.json` path. Pure function: prints the absolute path from a cwd. No side effects. |
| `hooks/scripts/loop_state_guard.sh` (create) | Stop hook. Detects an active loop, reads the file via the helper, blocks on absent / ownership-mismatch / stale-complete-after-rearm. |
| `hooks/scripts/tests/agentic_loop_path.test.sh` (create) | Asserts the helper's path derivation and env override. |
| `hooks/scripts/tests/loop_state_guard.test.sh` (create) | Behavioural assertions: feeds synthetic Stop payloads + fixture transcripts, asserts exit codes for every gate. |
| `hooks/hooks.json` (modify) | Register `loop_state_guard.sh` in the `Stop` array. |
| `install.sh` (modify) | Add both new scripts to the chmod list (lines 322–325). |
| `skills/agentic-loop/SKILL.md` (modify) | Stub-first Phase -2 contract; lifecycle / teardown / recency rules; persistence-section path + schema. |

---

## Task 1: Path helper — the sole path authority

**Files:**
- Create: `hooks/scripts/lib/agentic_loop_path.sh`
- Create: `hooks/scripts/tests/agentic_loop_path.test.sh`
- Modify: `install.sh:322-325` (chmod list)

**Interfaces:**
- Produces: `agentic_loop_path.sh [cwd]` — prints to stdout the absolute path
  `<base>/<slug>/progress.json`, where `<base>` is `${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}`
  and `<slug>` is `cwd` with every `/` replaced by `-`. Defaults `cwd` to `$PWD`.
  Called by Task 2's guard (reader) and, at runtime, by the orchestrator (writer).

- [ ] **Step 1: Write the failing test**

Create `hooks/scripts/tests/agentic_loop_path.test.sh`:

```bash
#!/bin/bash
# Unit test for agentic_loop_path.sh — path derivation + env override.
set -u
HELPER="$(cd "$(dirname "$0")/.." && pwd)/lib/agentic_loop_path.sh"
fails=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# 1. Default base is $HOME/.claude/agentic-loop; slug replaces / with -.
unset CLAUDE_AGENTIC_LOOP_DIR
check "default base + slug" \
  "$HOME/.claude/agentic-loop/-Users-foo-bar/progress.json" \
  "$(bash "$HELPER" /Users/foo/bar)"

# 2. Env override redirects the base (used by the guard's behavioural tests).
check "env override base" \
  "/tmp/al/-Users-foo-bar/progress.json" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar)"

# 3. No-arg form defaults to the caller's PWD.
check "defaults to PWD" \
  "/tmp/al/$(printf '%s' "$PWD" | sed 's#/#-#g')/progress.json" \
  "$(cd "$PWD" && CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash hooks/scripts/tests/agentic_loop_path.test.sh`
Expected: FAIL — the helper does not exist yet (`bash: .../agentic_loop_path.sh: No such file or directory`).

- [ ] **Step 3: Write the helper**

Create `hooks/scripts/lib/agentic_loop_path.sh`:

```bash
#!/bin/bash
# Sole authority for the agentic-loop progress.json path.
#
# A model cannot reproduce a cwd-derived key, so it must NEVER compute this path.
# Both the loop_state_guard Stop hook (reader) and the orchestrator (writer, via a
# Bash call) call this script so the path is computed in exactly one place.
#
# Pure: prints the path, creates nothing. The writer (orchestrator's Write tool)
# creates the parent directory.
#
# Usage: agentic_loop_path.sh [cwd]   (cwd defaults to $PWD)
# Path:  <base>/<slug>/progress.json
#   base = $CLAUDE_AGENTIC_LOOP_DIR (override for tests) or $HOME/.claude/agentic-loop
#   slug = cwd with every "/" replaced by "-" (mirrors Claude Code's own project-dir
#          convention, e.g. /Users/x/y -> -Users-x-y); deterministic, tool-free,
#          and debuggable (you can read which project a file belongs to).

cwd="${1:-$PWD}"
base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}"
slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
printf '%s/%s/progress.json\n' "$base" "$slug"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash hooks/scripts/tests/agentic_loop_path.test.sh`
Expected: three `ok` lines, then `PASS`.

- [ ] **Step 5: Syntax-check both scripts (the repo's test gate)**

Run: `bash -n hooks/scripts/lib/agentic_loop_path.sh && bash -n hooks/scripts/tests/agentic_loop_path.test.sh && echo OK`
Expected: `OK`.

- [ ] **Step 6: Add the helper to install.sh's chmod list**

Modify `install.sh` lines 322–325. The current block:

```bash
for script in scripts/push.sh scripts/merge.sh scripts/lib/git-common.sh \
              hooks/scripts/inject_context.sh hooks/scripts/discipline_catchup.sh \
              hooks/scripts/check_confidence_labels.sh hooks/scripts/check_verify_loop.sh \
              hooks/scripts/destructive_bash_gate.sh hooks/scripts/test_gate.sh; do
```

becomes (append the helper to the `lib/` line — its sibling `git-common.sh` is already listed individually, confirming `lib/` is not auto-covered):

```bash
for script in scripts/push.sh scripts/merge.sh scripts/lib/git-common.sh \
              hooks/scripts/lib/agentic_loop_path.sh \
              hooks/scripts/inject_context.sh hooks/scripts/discipline_catchup.sh \
              hooks/scripts/check_confidence_labels.sh hooks/scripts/check_verify_loop.sh \
              hooks/scripts/destructive_bash_gate.sh hooks/scripts/test_gate.sh; do
```

(The guard script is added to this same list in Task 2, Step 8.)

- [ ] **Step 7: Verify install.sh still parses**

Run: `bash -n install.sh && echo OK`
Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
chmod +x hooks/scripts/lib/agentic_loop_path.sh hooks/scripts/tests/agentic_loop_path.test.sh
git add hooks/scripts/lib/agentic_loop_path.sh hooks/scripts/tests/agentic_loop_path.test.sh install.sh
git commit -m "feat(agentic-loop): progress.json path helper (sole path authority)"
```

---

## Task 2: The guard hook + registration

**Files:**
- Create: `hooks/scripts/loop_state_guard.sh`
- Create: `hooks/scripts/tests/loop_state_guard.test.sh`
- Modify: `hooks/hooks.json` (register in the `Stop` array)
- Modify: `install.sh:322-325` (add the guard to the chmod list)

**Interfaces:**
- Consumes: `hooks/scripts/lib/agentic_loop_path.sh` (Task 1) — calls
  `bash "$(dirname "$0")/lib/agentic_loop_path.sh" "$cwd"` to resolve the path.
- Consumes (the `progress.json` schema the orchestrator writes, Task 3):
  `.status` (`initialising` | `in-progress` | `complete`), `.session_id`,
  `.completed_marker` (integer).
- Produces: a Stop hook that exits `0` (allow) or `2` (block, message on stderr).

**Gate order (first match decides):**
1. No transcript → allow.
2. `stop_hook_active == true` → allow (avoid stop-loop).
3. No `agentic-loop` Skill invocation in the transcript → allow (not a loop).
4. File `complete`, **not** re-armed (`invocations <= completed_marker`), and session-owned → allow.
5. File present, session-owned, and not complete → allow (presence + ownership satisfied).
6. BLOCK (exit 2): file **absent** / **session mismatch** / **stale-complete after re-arm**.

- [ ] **Step 1: Write the failing behavioural test**

Create `hooks/scripts/tests/loop_state_guard.test.sh`:

```bash
#!/bin/bash
# Behavioural test for loop_state_guard.sh — feeds synthetic Stop payloads with
# fixture transcripts and asserts exit codes for every gate. All state lives under
# a temp dir (CLAUDE_AGENTIC_LOOP_DIR + a transcript dir), never the repo tree.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/loop_state_guard.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
CWD="/work/project"
SLUG="-work-project"
FILE_DIR="$CLAUDE_AGENTIC_LOOP_DIR/$SLUG"
FILE="$FILE_DIR/progress.json"
fails=0

# A transcript line containing N agentic-loop Skill invocations.
mk_transcript() { # n_invocations -> path
  local n="$1" out="$TMP/t_$1_$RANDOM.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s' "$out"
}
# A transcript with a non-loop Skill call only.
mk_other_transcript() {
  local out="$TMP/other_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:prep"}}]}}' > "$out"
  printf '%s' "$out"
}
payload() { # transcript_path session_id [stop_hook_active]
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":%s}' \
    "$1" "$2" "$CWD" "${3:-false}"
}
write_file() { # status session_id completed_marker
  mkdir -p "$FILE_DIR"
  printf '{"schema_version":1,"status":"%s","session_id":"%s","completed_marker":%s}' "$1" "$2" "$3" > "$FILE"
}
run() { echo "$2" | bash "$GUARD" >/dev/null 2>&1; echo $?; }   # -> exit code
check() { # desc expected_code actual_code
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

# Gate 1 — no transcript file.
check "no transcript -> allow" 0 "$(run x "$(payload "$TMP/nope.jsonl" S1)")"

# Gate 3 — transcript with a non-loop Skill only -> allow.
reset; T=$(mk_other_transcript)
check "non-loop skill -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 6 absent — loop active, file missing -> BLOCK.
reset; T=$(mk_transcript 1)
check "loop active, file absent -> block" 2 "$(run x "$(payload "$T" S1)")"

# Gate 6 mismatch — file owned by another session -> BLOCK.
reset; T=$(mk_transcript 1); write_file in-progress S_OTHER 0
check "session mismatch -> block" 2 "$(run x "$(payload "$T" S1)")"

# Gate 5 — present, owned, in-progress -> allow.
reset; T=$(mk_transcript 1); write_file in-progress S1 0
check "present+owned+in-progress -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 4 — complete, owned, not re-armed (invocations 1 <= marker 1) -> allow.
reset; T=$(mk_transcript 1); write_file complete S1 1
check "complete, not re-armed -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 6 stale-complete — re-armed (invocations 2 > marker 1), stub skipped -> BLOCK.
reset; T=$(mk_transcript 2); write_file complete S1 1
check "complete but re-armed -> block" 2 "$(run x "$(payload "$T" S1)")"

# Gate 2 — already blocked this turn: would-block case allowed via loop-guard.
reset; T=$(mk_transcript 1)   # file absent => would block, but stop_hook_active short-circuits
check "stop_hook_active -> allow" 0 "$(run x "$(payload "$T" S1 true)")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash hooks/scripts/tests/loop_state_guard.test.sh`
Expected: FAIL — the guard does not exist yet (every `run` returns 127, so the `allow` cases fail).

- [ ] **Step 3: Write the guard hook**

Create `hooks/scripts/loop_state_guard.sh`:

```bash
#!/bin/bash
# Stop hook — when an agentic loop is active in this session, block (exit 2) unless
# a session-owned progress.json exists at the resolved path. Enforces PRESENCE +
# OWNERSHIP only; it does NOT police content freshness (that is Spec C2's job).
#
# Honest boundary (same as check_verify_loop.sh): this forces the file to exist and
# be this session's; it cannot force the content to be accurate.
#
# Gates run top to bottom; the first that matches decides. Cheapest skips first.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — file complete, not re-armed, session-owned          → allow (loop done)
#   skip  — file present, session-owned, not complete           → allow (presence ok)
#   BLOCK — file absent / session mismatch / stale-complete-after-rearm

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)

# Gate 1 — no transcript to inspect.
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  exit 0
fi

# Gate 2 — already blocked once this turn; allow to avoid a stop-loop.
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# Count agentic-loop Skill invocations across the WHOLE transcript. Recency
# (re-arm detection) needs the full history, so this does not tail. Structured
# jq match on a tool_use — never a text grep. Matches both the scoped name
# ("coderails:agentic-loop") and the bare ("agentic-loop"). Retry for the
# transcript-flush race until the count stabilises, as check_verify_loop does.
count_invocations() {
  jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | (.input.skill // "")
      | select(test("(^|:)agentic-loop$")) ]
    | length
  ' "$transcript" 2>/dev/null
}

prev=-1; attempts=0; invocations=0
while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
  invocations=$(count_invocations); [ -z "$invocations" ] && invocations=0
  if [ "$invocations" -eq "$prev" ]; then break; fi
  prev=$invocations
  attempts=$((attempts + 1))
  [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
done

# Gate 3 — not a loop: the opt-in marker is absent. No discipline in force.
if [ "$invocations" -eq 0 ]; then
  log_line "hook=loop_state_guard session=$session_id invocations=0 active=0 blocked=0"
  exit 0
fi

# Resolve the path — the hook is the sole path authority. Use the payload cwd
# (the project dir), falling back to the hook process PWD.
path=$(bash "$(dirname "$0")/lib/agentic_loop_path.sh" "$cwd" 2>/dev/null)

# Read file state (empty/0 when absent).
file_status=""; file_session=""; completed_marker=0
if [ -n "$path" ] && [ -f "$path" ]; then
  file_status=$(jq -r '.status // ""' "$path" 2>/dev/null)
  file_session=$(jq -r '.session_id // ""' "$path" 2>/dev/null)
  completed_marker=$(jq -r '.completed_marker // 0' "$path" 2>/dev/null)
  case "$completed_marker" in (''|*[!0-9]*) completed_marker=0;; esac
fi

# Re-armed = a new loop invocation occurred after the recorded completion. Because
# the skill is invoked once per loop, the transcript invocation count equals the
# loop ordinal, which the orchestrator records as completed_marker at teardown.
rearmed=0
if [ "$invocations" -gt "$completed_marker" ]; then rearmed=1; fi

# Gate 4 — genuinely complete: complete, NOT re-armed, and session-owned. (Ownership
# is required so another session's completed file never silences this session's loop.)
if [ "$file_status" = "complete" ] && [ "$rearmed" -eq 0 ] && [ "$file_session" = "$session_id" ]; then
  log_line "hook=loop_state_guard session=$session_id invocations=$invocations status=complete rearmed=0 owned=1 blocked=0"
  exit 0
fi

# Gate 5 — present, session-owned, and active (not complete).
if [ -n "$path" ] && [ -f "$path" ] && [ "$file_session" = "$session_id" ] && [ "$file_status" != "complete" ]; then
  log_line "hook=loop_state_guard session=$session_id invocations=$invocations status=$file_status owned=1 blocked=0"
  exit 0
fi

# Gate 6 — BLOCK. Distinguish the three failure shapes.
stub_schema='{ "schema_version": 1, "session_id": "<this-session-id>", "status": "initialising", "created": "<ISO8601>", "authorising_prompt_raw": "<verbatim authorising prompt>" }'
if [ ! -f "$path" ]; then
  reason="absent"
  msg="[loop-state-guard] Agentic loop active but no progress.json found.
Create it at this exact path (copy it verbatim — never compute the path yourself):
  $path
with this stub, then enrich it as the loop progresses:
  $stub_schema"
elif [ "$file_session" != "$session_id" ]; then
  reason="session_mismatch"
  msg="[loop-state-guard] progress.json at:
  $path
belongs to session '$file_session', not this session ('$session_id').
Adopt this loop (re-stamp session_id to '$session_id'), or reinitialise the stub."
else
  reason="stale_complete_rearmed"
  msg="[loop-state-guard] A new agentic loop has started, but progress.json at:
  $path
still records the previous loop as complete. Re-initialise the stub for the new
loop (status back to \"initialising\"/\"in-progress\", carry completed_marker forward)
before stopping."
fi

log_line "hook=loop_state_guard session=$session_id invocations=$invocations status=${file_status:-absent} reason=$reason blocked=1"
echo "$msg" >&2
exit 2
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash hooks/scripts/tests/loop_state_guard.test.sh`
Expected: eight `ok` lines, then `PASS`.

- [ ] **Step 5: Syntax-check both new files**

Run: `bash -n hooks/scripts/loop_state_guard.sh && bash -n hooks/scripts/tests/loop_state_guard.test.sh && echo OK`
Expected: `OK`.

- [ ] **Step 6: Register the hook in hooks.json**

Modify `hooks/hooks.json`. The current `Stop` array (lines 19–33) ends with `check_verify_loop.sh`:

```json
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/check_verify_loop.sh\"",
            "timeout": 15
          }
        ]
      }
    ],
```

Add `loop_state_guard.sh` after `check_verify_loop.sh` (insert a comma after its closing brace):

```json
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/check_verify_loop.sh\"",
            "timeout": 15
          },
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/loop_state_guard.sh\"",
            "timeout": 15
          }
        ]
      }
    ],
```

- [ ] **Step 7: Verify hooks.json is valid JSON**

Run: `jq empty hooks/hooks.json && echo OK`
Expected: `OK`.

- [ ] **Step 8: Add the guard to install.sh's chmod list**

Modify `install.sh` lines 322–325 (already amended in Task 1 to add the helper). Append the guard to the `hooks/scripts/` group:

```bash
for script in scripts/push.sh scripts/merge.sh scripts/lib/git-common.sh \
              hooks/scripts/lib/agentic_loop_path.sh \
              hooks/scripts/loop_state_guard.sh \
              hooks/scripts/inject_context.sh hooks/scripts/discipline_catchup.sh \
              hooks/scripts/check_confidence_labels.sh hooks/scripts/check_verify_loop.sh \
              hooks/scripts/destructive_bash_gate.sh hooks/scripts/test_gate.sh; do
```

- [ ] **Step 9: Verify install.sh still parses**

Run: `bash -n install.sh && echo OK`
Expected: `OK`.

- [ ] **Step 10: Commit**

```bash
chmod +x hooks/scripts/loop_state_guard.sh hooks/scripts/tests/loop_state_guard.test.sh
git add hooks/scripts/loop_state_guard.sh hooks/scripts/tests/loop_state_guard.test.sh hooks/hooks.json install.sh
git commit -m "feat(agentic-loop): progress.json presence/ownership Stop guard"
```

---

## Task 3: SKILL.md lifecycle contract

**Files:**
- Modify: `skills/agentic-loop/SKILL.md`

**Interfaces:**
- Consumes: `hooks/scripts/lib/agentic_loop_path.sh` (Task 1) — the orchestrator
  runs it to resolve the path.
- Produces: the lifecycle the guard (Task 2) enforces — the orchestrator writes a
  stub-first, enriches it, and tears it down with `status: "complete"` +
  `completed_marker`.

This task is documentation. There is no automated test; verification is reading the
edited sections back and confirming the four edits are present and internally
consistent with the schema the guard reads (`status`, `session_id`,
`completed_marker`).

- [ ] **Step 1: Add the stub-first Phase -2 section**

In `skills/agentic-loop/SKILL.md`, find the `## The phases` intro that ends:

```
The phases below are sequential. Run them in order. Inside an authorised loop, phases 4-7 repeat per PR / per work-unit.
```

Insert the following new section immediately **after** that paragraph and **before** `### Phase -1 — Sharpen the authorising prompt`:

```markdown
### Phase -2 — Stub `progress.json` first (the literal first action)

Before Phase -1 — before anything else — write a `progress.json` stub. This guarantees the loop's durable state file exists before the first stop, so the `loop_state_guard` Stop hook never trips a compliant loop; the block degrades to a backstop for a skipped stub.

**Resolve the path — never compute it yourself.** A cwd-derived key cannot be reproduced by hand. Get the absolute path by running the path helper:

> `bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.sh"`

It prints the absolute path. Write the stub there with the Write tool (it creates the parent directory). If `${CLAUDE_PLUGIN_ROOT}` is not set in your shell, do **not** guess the path — proceed without the stub; the `loop_state_guard` hook will block once on your first stop and hand you the exact path to use. Copy that path verbatim. Either way, the path comes from the helper (directly, or via the guard which also calls it) — never from your own derivation.

**The stub:**

```json
{
  "schema_version": 1,
  "session_id": "<this session's id>",
  "status": "initialising",
  "created": "<ISO8601 timestamp>",
  "authorising_prompt_raw": "<the user's authorising prompt, verbatim>",
  "completed_marker": <carry forward the prior file's completed_marker if one exists at this path, else 0>
}
```

If a `progress.json` already exists at the path from an earlier completed loop in this session, read its `completed_marker` and carry it forward into the new stub (do not reset it to 0) — this is what lets the guard tell a genuinely-finished loop from a new one that re-armed it (see the teardown rule below).
```

- [ ] **Step 2: Add lifecycle + teardown + recency rules to the persistence section**

Find the `## Context-window persistence` section. Replace this paragraph:

```markdown
**Loop state lives in a durable artifact, not in the conversation.** Maintain a single `progress.json` in the worktree as the source of truth for where the loop is. It is overwritten (not appended) on every phase boundary and holds: the authorisation envelope verbatim, the current phase, each work-unit's status (`pending`/`in-progress`/`done`/`blocked` with `blockedBy`), verified state carried between units (deployed version, test counts), the human-turn counters for Phase 13, and — for any work-unit that retires an existing code path — its `disposition` (`clean-break` | `preserve-compat`), plus, when `preserve-compat`, the `named_blocker` (the specific consumer still on the old path that justifies keeping it) and the `removal_ticket` tracking the deferred removal. A single overwritten JSON object — read the whole file in one shot to know current state. Do not use an append-log (`.jsonl`) that has to be replayed to derive position, and that can leave a torn tail line after a crash.
```

with:

```markdown
**Loop state lives in a durable artifact, not in the conversation.** Maintain a single `progress.json` at the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`) — outside the code repo, keyed to the project cwd, so it survives session restart/compaction and never pollutes the base every worker branches from. Resolve the path by running the helper (Phase -2); never compute it yourself. It is overwritten (not appended) on every phase boundary and holds: the authorisation envelope verbatim, the current phase, each work-unit's status (`pending`/`in-progress`/`done`/`blocked` with `blockedBy`), verified state carried between units (deployed version, test counts), the human-turn counters for Phase 13, and — for any work-unit that retires an existing code path — its `disposition` (`clean-break` | `preserve-compat`), plus, when `preserve-compat`, the `named_blocker` (the specific consumer still on the old path that justifies keeping it) and the `removal_ticket` tracking the deferred removal. A single overwritten JSON object — read the whole file in one shot to know current state. Do not use an append-log (`.jsonl`) that has to be replayed to derive position, and that can leave a torn tail line after a crash.

**Lifecycle, enforced by the `loop_state_guard` Stop hook (presence + ownership).** The file moves through a fixed lifecycle, and the guard blocks any stop where an active loop has no session-owned file:
- **Stub-first (Phase -2):** `status: "initialising"`, stamped with this `session_id`.
- **Enrich at Phase 0:** record the envelope verbatim; `status: "in-progress"`.
- **Update at each phase boundary:** current phase, work-unit states, Spec A's disposition fields, the Phase 13 counters, `last_updated`.
- **Teardown at Phase 13:** `status: "complete"`, and set `completed_marker` to the number of agentic-loop loops run in this session so far — i.e. the prior `completed_marker` (default 0) **plus 1**. Because this skill is invoked once per loop, that ordinal matches the guard's count of agentic-loop invocations, which is how the guard distinguishes a finished loop from a new one.

**Recency — a second loop is not masked by a stale `complete`.** This skill supports multiple loops in one long session. A prior loop's `status: "complete"` must not silence the guard for a later loop. When a new loop starts, Phase -2's stub-first overwrites the file (`status` back to `initialising`), which is the primary re-arm signal. The `completed_marker` is the backstop: if a new loop skips its stub, the guard still sees that the current invocation count exceeds the recorded `completed_marker` and blocks, forcing a re-initialisation. This is why teardown must bump `completed_marker` and stub-first must carry it forward.

**Honest boundary.** The guard guarantees the file *exists* and is *this session's* — not that its content is faithfully maintained (the same limit `check_verify_loop.sh` documents). Keeping the file current is still your job; the guard only catches its absence.
```

- [ ] **Step 3: Verify the edits read consistently**

Run: `grep -n "Phase -2\|completed_marker\|loop_state_guard\|agentic_loop_path" skills/agentic-loop/SKILL.md`
Expected: matches in the new Phase -2 section and the persistence section — confirming the stub-first contract, the path helper reference, and the `completed_marker` lifecycle/recency rules are all present and refer to the same field names the guard reads (`status`, `session_id`, `completed_marker`).

- [ ] **Step 4: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "docs(agentic-loop): stub-first progress.json lifecycle + recency contract"
```

---

## Self-review

**Spec coverage** (against `docs/superpowers/specs/2026-06-24-c1-progress-json-lifecycle-design.md`):

| Spec element | Task |
|---|---|
| Path authority — model never computes path; shared helper; resolved path in block message | Task 1 (helper); Task 2 (guard calls helper, block message carries path); Task 3 (orchestrator runs helper, fallback to block message) |
| Loop-active detection — structured `jq` on Skill `tool_use`, never textual | Task 2, Step 3 (`count_invocations`) |
| Stub-first contract (couples to SKILL.md) | Task 3, Step 1 (Phase -2) |
| Enrich at Phase 0 / update at boundaries / teardown at Phase 13 | Task 3, Step 2 (lifecycle bullets) |
| Recency re-arming via `completed_marker` | Task 2 (`rearmed` logic); Task 3, Step 2 (teardown bump + carry-forward) |
| Guard gates 1–6 | Task 2, Step 3 |
| Registration in hooks.json, timeout 15 | Task 2, Step 6 |
| Schema additions (`schema_version`, `session_id`, `status`, `created`, `last_updated`, `completed_marker`) | Task 3, Steps 1–2 (stub + lifecycle) |
| install.sh explicit chmod list — both scripts appended | Task 1, Step 6 + Task 2, Step 8 |
| Honest-boundary documentation | Task 2 (guard header); Task 3, Step 2 |
| Testing — `bash -n` + synthetic-payload behavioural assertions | Task 1, Step 5; Task 2, Steps 1–5 |

**Placeholder scan:** no `TBD`/`TODO`/"add error handling"/"similar to" — every code and markdown block is complete and literal.

**Type/field consistency:** the guard reads `.status`, `.session_id`, `.completed_marker`; the stub (Task 3, Step 1) and lifecycle (Task 3, Step 2) write exactly those names. `completed_marker` is an integer in both. `status` values (`initialising`/`in-progress`/`complete`) match between the guard's gates and the SKILL.md lifecycle. The helper's path output is consumed identically by the guard (`bash …/lib/agentic_loop_path.sh "$cwd"`) and the orchestrator (`bash …/lib/agentic_loop_path.sh`).

**Design decision surfaced for the executor (not in the spec verbatim):** the spec says `completed_marker` is "the transcript position / count of agentic-loop invocations at completion time" but does not say how the *model* obtains that count (it cannot reliably count its own tool-uses). This plan resolves it: since the skill is invoked once per loop, the loop ordinal equals the invocation count, so the model writes `completed_marker = prior + 1` (a file read + arithmetic, persisted across compaction). Primary re-arm signal remains stub-first; the marker is the backstop. Known limitation: if the skill is invoked more than once for a single loop, the count inflates and the guard may spuriously block once → the model re-inits → safe degradation.

## Sequencing

A (clean-migration discipline) — DONE, merged `#12`.
→ **C1** (this plan) — make progress.json reliable.
→ C2 — thin declaration-based anti-stall hook reading C1's reliable file.
→ B — slim the skill.
→ D — superpowers construction-discipline seam (sonnet-only).
