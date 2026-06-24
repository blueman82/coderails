# C2 — declaration-based anti-stall guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an agentic loop is active and incomplete, block any stop whose turn does not carry a valid `LOOP-STOP: <category> — <reason>` declaration — without affecting non-loop sessions and without regressing the merged C1 guard.

**Architecture:** Extract C1's loop-detection (invocation count, path resolution, progress.json state read, the LOOP-STOP vocabulary) into a sourced shared lib so the two guards can never drift on what "an active loop" means. Refactor the C1 guard to source it (behaviour-preserving, gated by C1's existing 8/8 suite). Add a new C2 Stop hook that reuses the shared detection, then checks the last assistant message for a vocab-valid `LOOP-STOP` tag.

**Tech Stack:** Bash 3.2-compatible shell, `jq`, the repo's existing hook idioms (`hooks/scripts/check_verify_loop.sh` for last-message extraction; `hooks/scripts/loop_state_guard.sh` for the gate pattern).

## Global Constraints

- **Bash hook conventions (copy `check_verify_loop.sh` / `loop_state_guard.sh`):** read payload from stdin via `input=$(cat)`; parse with `jq`; numbered skip-gates that `exit 0` early (cheapest first); block via `exit 2` with the message on **stderr**; append a single-line `key=value` entry to `$CLAUDE_DISCIPLINE_LOG`; retry the transcript read with backoff for the flush race.
- **Single-source vocabulary:** `LOOP_STOP_VOCAB="hard-stop|approval-gate|awaiting-input|complete"` is defined ONCE in `loop_state_common.sh`. The C2 guard builds both its match regex and its block-message template from that variable — they can never disagree.
- **Loop-active detection is structured, never textual:** a `jq` match on a `tool_use` with `name=="Skill"` and `input.skill` matching `(^|:)agentic-loop$`. A text grep for "agentic-loop" is forbidden.
- **The C1 refactor MUST be behaviour-preserving:** `hooks/scripts/tests/loop_state_guard.test.sh` passes unchanged (8/8) against the refactored guard. No logic edits folded into the extraction step.
- **C2 checks presence + category only** (honest boundary): it blocks an active+incomplete loop unless a `LOOP-STOP` line with a vocab category is present. It does NOT judge whether the reason is legitimate.
- **`install.sh` arms scripts via an EXPLICIT hardcoded list (not a glob):** both new scripts (`lib/loop_state_common.sh`, `loop_stall_guard.sh`) must be appended or they ship without `+x`.
- **Bash 3.2 compatible** (macOS `/bin/bash`): no associative arrays, no `${var,,}`, no `mapfile`. `local`, `${BASH_SOURCE[0]}`, and `case` globs are fine.

---

## File structure

| File | Responsibility |
|---|---|
| `hooks/scripts/lib/loop_state_common.sh` (create) | Sourced shared detection: env defaults, `als_log`, `LOOP_STOP_VOCAB`, invocation count (+flush retry), path resolution, progress.json state read. |
| `hooks/scripts/loop_state_guard.sh` (refactor) | C1 presence/ownership guard, refactored to source the lib. Behaviour unchanged. |
| `hooks/scripts/loop_stall_guard.sh` (create) | C2 anti-stall Stop hook: shared active-window decision + last-message `LOOP-STOP` tag check. |
| `hooks/scripts/tests/loop_stall_guard.test.sh` (create) | Behavioural assertions for every C2 gate via synthetic payloads + fixture transcripts. |
| `hooks/hooks.json` (modify) | Register `loop_stall_guard.sh` in the Stop array, after `loop_state_guard.sh`. |
| `install.sh` (modify) | Add both new scripts to the chmod list. |
| `skills/agentic-loop/SKILL.md` (modify) | LOOP-STOP stop-ceremony (Phase 0.5), category mapping (Stop-conditions), Phase 13 KPI, `loop_stop_counts` schema field. |

---

## Task 1: Shared detection lib + behaviour-preserving C1 refactor

**Files:**
- Create: `hooks/scripts/lib/loop_state_common.sh`
- Modify: `hooks/scripts/loop_state_guard.sh` (replace inline detection with sourced calls)
- Modify: `install.sh` (add the lib to the chmod list)
- Regression: `hooks/scripts/tests/loop_state_guard.test.sh` (run unchanged, must stay 8/8)

**Interfaces:**
- Produces (sourced API, consumed by Task 2):
  - `LOOP_STOP_VOCAB` — string `"hard-stop|approval-gate|awaiting-input|complete"`.
  - `als_log "<key=value line>"` — append to `$CLAUDE_DISCIPLINE_LOG`.
  - `als_stable_invocations "<transcript_path>"` — prints the agentic-loop Skill invocation count (with flush-race retry).
  - `als_resolve_path "<cwd>"` — prints the progress.json absolute path (delegates to `agentic_loop_path.sh`).
  - `als_read_file_state "<path>"` — sets globals `ALS_STATUS`, `ALS_SESSION`, `ALS_MARKER` (marker sanitised to an integer; empty/0 when the file is absent).

- [ ] **Step 1: Create the shared lib**

Create `hooks/scripts/lib/loop_state_common.sh`:

```bash
#!/bin/bash
# loop_state_common.sh — shared detection for the agentic-loop Stop guards.
# SOURCED (not executed) by loop_state_guard.sh (C1, presence/ownership) and
# loop_stall_guard.sh (C2, anti-stall). Single source for: env defaults, the
# discipline-log helper, the LOOP-STOP vocabulary, and the active-loop /
# progress.json state resolution — so the two guards can never drift on what
# "an active loop" means.

# Single source of truth for the LOOP-STOP category vocabulary (C2). The C2 guard
# builds BOTH its match regex and its block message from this, so they can't disagree.
LOOP_STOP_VOCAB="hard-stop|approval-gate|awaiting-input|complete"

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

# Append a single key=value line to the discipline log (best-effort).
als_log() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

# Count agentic-loop Skill invocations across the WHOLE transcript (one-shot).
# Structured jq match on a tool_use — never a text grep. Matches the scoped
# ("coderails:agentic-loop") and bare ("agentic-loop") skill names.
als_count_invocations() {
  jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | (.input.skill // "")
      | select(test("(^|:)agentic-loop$")) ]
    | length
  ' "$1" 2>/dev/null
}

# Stable invocation count: retry for the transcript-flush race until it settles.
als_stable_invocations() {
  local transcript="$1" prev=-1 attempts=0 n=0
  while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
    n=$(als_count_invocations "$transcript"); [ -z "$n" ] && n=0
    if [ "$n" -eq "$prev" ]; then break; fi
    prev=$n
    attempts=$((attempts + 1))
    [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
  done
  printf '%s' "$n"
}

# Resolve the progress.json path via the sole path authority (sibling script).
als_resolve_path() { bash "$(dirname "${BASH_SOURCE[0]}")/agentic_loop_path.sh" "$1" 2>/dev/null; }

# Read progress.json state into globals ALS_STATUS / ALS_SESSION / ALS_MARKER.
# ALS_MARKER is sanitised to a non-negative integer (empty/non-numeric -> 0).
als_read_file_state() {
  ALS_STATUS=""; ALS_SESSION=""; ALS_MARKER=0
  if [ -n "$1" ] && [ -f "$1" ]; then
    ALS_STATUS=$(jq -r '.status // ""' "$1" 2>/dev/null)
    ALS_SESSION=$(jq -r '.session_id // ""' "$1" 2>/dev/null)
    ALS_MARKER=$(jq -r '.completed_marker // 0' "$1" 2>/dev/null)
    case "$ALS_MARKER" in (''|*[!0-9]*) ALS_MARKER=0;; esac
  fi
}
```

- [ ] **Step 2: Syntax-check the lib**

Run: `bash -n hooks/scripts/lib/loop_state_common.sh && echo OK`
Expected: `OK`.

- [ ] **Step 3: Refactor the C1 guard to source the lib**

Replace the entire contents of `hooks/scripts/loop_state_guard.sh` with the following. This keeps every gate and every block message byte-for-byte; it only moves env defaults / logging / invocation count / path / file-state into the shared lib. (Log strings are unchanged, so C1's tests — which assert exit codes — stay green.)

```bash
#!/bin/bash
# Stop hook — when an agentic loop is active in this session, block (exit 2) unless
# a session-owned progress.json exists at the resolved path. Enforces PRESENCE +
# OWNERSHIP only; it does NOT police content freshness (that is Spec C2's job).
#
# Honest boundary (same as check_verify_loop.sh): this forces the file to exist and
# be this session's; it cannot force the content to be accurate.
#
# Shared loop-detection (invocation count, path, file state) lives in
# lib/loop_state_common.sh, sourced below and shared with loop_stall_guard.sh (C2).
#
# Gates run top to bottom; the first that matches decides. Cheapest skips first.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — file complete, not re-armed, session-owned          → allow (loop done)
#   skip  — file present, session-owned, not complete           → allow (presence ok)
#   BLOCK — file absent / session mismatch / stale-complete-after-rearm

. "$(dirname "$0")/lib/loop_state_common.sh"

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

invocations=$(als_stable_invocations "$transcript"); [ -z "$invocations" ] && invocations=0

# Gate 3 — not a loop: the opt-in marker is absent. No discipline in force.
if [ "$invocations" -eq 0 ]; then
  als_log "hook=loop_state_guard session=$session_id invocations=0 active=0 blocked=0"
  exit 0
fi

# Resolve the path — the hook is the sole path authority.
path=$(als_resolve_path "$cwd")

# Read file state (empty/0 when absent) into ALS_STATUS / ALS_SESSION / ALS_MARKER.
als_read_file_state "$path"
file_status="$ALS_STATUS"; file_session="$ALS_SESSION"; completed_marker="$ALS_MARKER"

# Re-armed = a new loop invocation occurred after the recorded completion.
rearmed=0
if [ "$invocations" -gt "$completed_marker" ]; then rearmed=1; fi

# Gate 4 — genuinely complete: complete, NOT re-armed, and session-owned.
if [ "$file_status" = "complete" ] && [ "$rearmed" -eq 0 ] && [ "$file_session" = "$session_id" ]; then
  als_log "hook=loop_state_guard session=$session_id invocations=$invocations status=complete rearmed=0 owned=1 blocked=0"
  exit 0
fi

# Gate 5 — present, session-owned, and active (not complete).
if [ -n "$path" ] && [ -f "$path" ] && [ "$file_session" = "$session_id" ] && [ "$file_status" != "complete" ]; then
  als_log "hook=loop_state_guard session=$session_id invocations=$invocations status=$file_status owned=1 blocked=0"
  exit 0
fi

# Gate 6 — BLOCK. Distinguish the three failure shapes.
stub_schema='{ "schema_version": 1, "session_id": "<this-session-id>", "status": "initialising", "created": "<ISO8601>", "authorising_prompt_raw": "<verbatim authorising prompt>", "completed_marker": 0 }'
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

als_log "hook=loop_state_guard session=$session_id invocations=$invocations status=${file_status:-absent} reason=$reason blocked=1"
echo "$msg" >&2
exit 2
```

- [ ] **Step 4: Syntax-check the refactored guard**

Run: `bash -n hooks/scripts/loop_state_guard.sh && echo OK`
Expected: `OK`.

- [ ] **Step 5: Run C1's existing suite UNCHANGED — the regression gate**

Run: `bash hooks/scripts/tests/loop_state_guard.test.sh`
Expected: eight `ok` lines, then `PASS`. (If any case fails, the extraction changed behaviour — fix the lib/guard, do not edit the test.)

- [ ] **Step 6: Add the lib to install.sh's chmod list**

Modify `install.sh`. The current `for script in …` block lists the helper and the C1 guard. Add the lib on the `lib/` line:

```bash
for script in scripts/push.sh scripts/merge.sh scripts/lib/git-common.sh \
              hooks/scripts/lib/agentic_loop_path.sh \
              hooks/scripts/lib/loop_state_common.sh \
              hooks/scripts/loop_state_guard.sh \
              hooks/scripts/inject_context.sh hooks/scripts/discipline_catchup.sh \
              hooks/scripts/check_confidence_labels.sh hooks/scripts/check_verify_loop.sh \
              hooks/scripts/destructive_bash_gate.sh hooks/scripts/test_gate.sh; do
```

(The C2 guard is added to this same list in Task 2.)

- [ ] **Step 7: Verify install.sh still parses**

Run: `bash -n install.sh && echo OK`
Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
chmod +x hooks/scripts/lib/loop_state_common.sh
git add hooks/scripts/lib/loop_state_common.sh hooks/scripts/loop_state_guard.sh install.sh
git commit -m "refactor(agentic-loop): extract shared loop-state detection into a sourced lib"
```

---

## Task 2: The C2 anti-stall guard + registration

**Files:**
- Create: `hooks/scripts/loop_stall_guard.sh`
- Create: `hooks/scripts/tests/loop_stall_guard.test.sh`
- Modify: `hooks/hooks.json` (register in the Stop array, after C1)
- Modify: `install.sh` (add the guard to the chmod list)

**Interfaces:**
- Consumes: `hooks/scripts/lib/loop_state_common.sh` (Task 1) — `LOOP_STOP_VOCAB`, `als_log`, `als_stable_invocations`, `als_resolve_path`, `als_read_file_state` (sets `ALS_STATUS`/`ALS_SESSION`/`ALS_MARKER`).
- Consumes (the `progress.json` schema): `.status`, `.session_id`, `.completed_marker`.
- Produces: a Stop hook that exits `0` (allow) or `2` (block, message on stderr).

**Gate order (first match decides):**
1. No transcript → allow.
2. `stop_hook_active == true` → allow.
3. No agentic-loop invocation → allow (not a loop).
4. `status == complete`, not re-armed, session-owned → allow (shared off-switch with C1).
5. Last assistant message has a valid `LOOP-STOP: <vocab>` line → allow (declared stop).
6. BLOCK (exit 2): active + incomplete + no valid declaration.

- [ ] **Step 1: Write the failing behavioural test**

Create `hooks/scripts/tests/loop_stall_guard.test.sh`:

```bash
#!/bin/bash
# Behavioural test for loop_stall_guard.sh — feeds synthetic Stop payloads with
# fixture transcripts (an agentic-loop invocation + a final assistant message) and
# asserts exit codes for every gate. State lives under a temp dir, never the repo.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/loop_stall_guard.sh"
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

# Build a transcript: N agentic-loop Skill invocations, then a final assistant
# text message with the given body ("" = no final text message).
mk_transcript() { # n_invocations final_text -> path
  local n="$1" final="$2" out="$TMP/t_${RANDOM}.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  if [ -n "$final" ]; then
    # jq builds a valid assistant text entry with arbitrary body text.
    jq -cn --arg t "$final" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$out"
  fi
  printf '%s' "$out"
}
mk_other_transcript() {
  local out="$TMP/other_${RANDOM}.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:prep"}}]}}' > "$out"
  printf '%s' "$out"
}
payload() { # transcript session_id [stop_hook_active]
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":%s}' \
    "$1" "$2" "$CWD" "${3:-false}"
}
write_file() { # status session_id completed_marker
  mkdir -p "$FILE_DIR"
  printf '{"schema_version":1,"status":"%s","session_id":"%s","completed_marker":%s}' "$1" "$2" "$3" > "$FILE"
}
run() { echo "$2" | bash "$GUARD" >/dev/null 2>&1; echo $?; }
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

# Gate 1 — no transcript file.
check "no transcript -> allow" 0 "$(run x "$(payload "$TMP/nope.jsonl" S1)")"

# Gate 3 — non-loop skill only -> allow.
reset; T=$(mk_other_transcript)
check "non-loop skill -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 4 — complete, not re-armed, owned -> allow (no tag needed).
reset; T=$(mk_transcript 1 ""); write_file complete S1 1
check "complete off-switch -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 5 — active, incomplete, last message carries a valid LOOP-STOP tag -> allow.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: awaiting-input — waiting on the user's plan confirmation"); write_file in-progress S1 0
check "valid LOOP-STOP tag -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 5 — complete category tag is also accepted.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
check "complete tag -> allow" 0 "$(run x "$(payload "$T" S1)")"

# Gate 6 — active, incomplete, NO tag -> block.
reset; T=$(mk_transcript 1 "Here is a status update with no declaration."); write_file in-progress S1 0
check "no declaration -> block" 2 "$(run x "$(payload "$T" S1)")"

# Gate 6 — tag present but category OUTSIDE the vocab -> block.
reset; T=$(mk_transcript 1 "LOOP-STOP: paused — taking a break"); write_file in-progress S1 0
check "out-of-vocab category -> block" 2 "$(run x "$(payload "$T" S1)")"

# Gate 2 — already blocked this turn: would-block case allowed via loop-guard.
reset; T=$(mk_transcript 1 "no declaration here"); write_file in-progress S1 0
check "stop_hook_active -> allow" 0 "$(run x "$(payload "$T" S1 true)")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash hooks/scripts/tests/loop_stall_guard.test.sh`
Expected: FAIL — the guard does not exist yet (`run` returns 127, so the allow cases fail).

- [ ] **Step 3: Write the C2 guard**

Create `hooks/scripts/loop_stall_guard.sh`:

```bash
#!/bin/bash
# Stop hook — anti-stall (C2). When an agentic loop is active and incomplete, block
# (exit 2) unless the stopping turn carries a valid LOOP-STOP declaration:
#   LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>
# Checks PRESENCE + a vocab CATEGORY only (honest boundary, same as check_verify_loop):
# it forces a categorised declaration, it cannot force the reason to be truthful.
#
# Shared loop-detection lives in lib/loop_state_common.sh (also used by C1's
# loop_state_guard.sh); the active-window decision is identical to C1's.
#
# Gates run top to bottom; the first that matches decides.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — loop complete, not re-armed, session-owned          → allow (loop done)
#   skip  — last message carries a valid LOOP-STOP declaration  → allow (declared)
#   BLOCK — active + incomplete + no valid declaration

. "$(dirname "$0")/lib/loop_state_common.sh"

TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"

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

invocations=$(als_stable_invocations "$transcript"); [ -z "$invocations" ] && invocations=0

# Gate 3 — not a loop: the opt-in marker is absent. No discipline in force.
if [ "$invocations" -eq 0 ]; then
  als_log "hook=loop_stall_guard session=$session_id invocations=0 active=0 blocked=0"
  exit 0
fi

# Resolve path + file state (shared with C1).
path=$(als_resolve_path "$cwd")
als_read_file_state "$path"
rearmed=0
if [ "$invocations" -gt "$ALS_MARKER" ]; then rearmed=1; fi

# Gate 4 — loop done (shared off-switch with C1): complete, not re-armed, owned.
if [ "$ALS_STATUS" = "complete" ] && [ "$rearmed" -eq 0 ] && [ "$ALS_SESSION" = "$session_id" ]; then
  als_log "hook=loop_stall_guard session=$session_id invocations=$invocations status=complete blocked=0"
  exit 0
fi

# Extract the last assistant text, retrying for the transcript-flush race
# (same approach as check_verify_loop.sh).
extract_last_text() {
  tail -n "$TAIL_LINES" "$transcript" 2>/dev/null | jq -s -r '
    [.[]?
     | select(.type == "assistant")
     | (.message.content
        | if type == "array" then [ .[]? | select(.type == "text") | .text ] | join(" ")
          elif type == "string" then .
          else "" end)
     | select(type == "string" and length > 0)]
    | last // ""
  ' 2>/dev/null
}
prev_len=-1; attempts=0; text=""
while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
  text=$(extract_last_text); cur_len=${#text}
  if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then break; fi
  prev_len=$cur_len
  attempts=$((attempts + 1))
  [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
done

# Gate 5 — a valid LOOP-STOP declaration is present in the last message. The regex
# is built from the single-source vocab; the category must be followed by a
# non-alphanumeric char or end-of-line so "completed" does not match "complete".
if printf '%s\n' "$text" | grep -qiE "^[[:space:]]*LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})([^[:alnum:]]|$)"; then
  als_log "hook=loop_stall_guard session=$session_id invocations=$invocations declared=1 blocked=0"
  exit 0
fi

# Gate 6 — BLOCK. Hand back the exact tag template, built from the single-source vocab.
als_log "hook=loop_stall_guard session=$session_id invocations=$invocations declared=0 blocked=1"
echo "[loop-stall-guard] Active agentic loop, no LOOP-STOP declaration in your last message.
Continue the loop, OR declare your stop by ending your message with a line:
  LOOP-STOP: <${LOOP_STOP_VOCAB}> — <reason>
Declaring \`complete\` means the loop is done: also set progress.json status to
\"complete\" and run the Phase 13 self-audit." >&2
exit 2
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash hooks/scripts/tests/loop_stall_guard.test.sh`
Expected: eight `ok` lines, then `PASS`.

- [ ] **Step 5: Syntax-check both new files**

Run: `bash -n hooks/scripts/loop_stall_guard.sh && bash -n hooks/scripts/tests/loop_stall_guard.test.sh && echo OK`
Expected: `OK`.

- [ ] **Step 6: Register the hook in hooks.json**

Modify `hooks/hooks.json`. The Stop array currently ends with `loop_state_guard.sh`:

```json
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/loop_state_guard.sh\"",
            "timeout": 15
          }
        ]
      }
    ],
```

Add `loop_stall_guard.sh` after it (insert a comma after the `loop_state_guard.sh` block's closing brace):

```json
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/loop_state_guard.sh\"",
            "timeout": 15
          },
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/loop_stall_guard.sh\"",
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

Modify `install.sh` — append the C2 guard to the `hooks/scripts/` group (the lib was added in Task 1):

```bash
for script in scripts/push.sh scripts/merge.sh scripts/lib/git-common.sh \
              hooks/scripts/lib/agentic_loop_path.sh \
              hooks/scripts/lib/loop_state_common.sh \
              hooks/scripts/loop_state_guard.sh \
              hooks/scripts/loop_stall_guard.sh \
              hooks/scripts/inject_context.sh hooks/scripts/discipline_catchup.sh \
              hooks/scripts/check_confidence_labels.sh hooks/scripts/check_verify_loop.sh \
              hooks/scripts/destructive_bash_gate.sh hooks/scripts/test_gate.sh; do
```

- [ ] **Step 9: Verify install.sh still parses**

Run: `bash -n install.sh && echo OK`
Expected: `OK`.

- [ ] **Step 10: Commit**

```bash
chmod +x hooks/scripts/loop_stall_guard.sh hooks/scripts/tests/loop_stall_guard.test.sh
git add hooks/scripts/loop_stall_guard.sh hooks/scripts/tests/loop_stall_guard.test.sh hooks/hooks.json install.sh
git commit -m "feat(agentic-loop): declaration-based anti-stall Stop guard (C2)"
```

---

## Task 3: SKILL.md — LOOP-STOP contract, category mapping, Phase 13 KPI

**Files:**
- Modify: `skills/agentic-loop/SKILL.md`

**Interfaces:**
- Consumes: the C2 guard's contract (Task 2) — the `LOOP-STOP: <category> — <reason>` line with category ∈ {hard-stop, approval-gate, awaiting-input, complete}, and the `complete`⇒teardown coupling.
- Produces: the orchestrator-facing rules the C2 guard enforces.

Documentation only; no automated test. Verification is reading the edited sections back and confirming the four edits use the same vocabulary and field names the guard reads.

- [ ] **Step 1: Add the LOOP-STOP bullet to Phase 0.5 (the stop-ceremony)**

In `skills/agentic-loop/SKILL.md`, find the Phase 0.5 bullet list. The third bullet is:

```markdown
- Never narrate a claim about an artifact (PR merged, deploy live) without having run the check this turn (Phase 12).
```

Insert a new bullet immediately **after** it:

```markdown
- End any stopping turn inside an active loop with a LOOP-STOP declaration line — `LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>` — emitted in the SAME turn as the confidence-label and Did-Not-Verify requirements above (the `loop_stall_guard` hook blocks a stop that lacks one; bundling all three keeps you from clearing one stop hook only to trip another). Declaring `complete` means the loop is done: also set `progress.json` `status: "complete"` and run the Phase 13 teardown.
```

- [ ] **Step 2: Add the LOOP-STOP category mapping to the Stop-conditions section**

Find the end of the Stop-conditions section:

```markdown
**Loop complete:**
5. All authorised work done and all gates passed — run Phase 13, then stop.
```

Insert immediately **after** those two lines:

```markdown

**Declaring the stop (the LOOP-STOP contract).** Whichever class applies, a stop inside an active loop must be declared, or the `loop_stall_guard` Stop hook blocks it. End the stopping turn with:

> `LOOP-STOP: <category> — <reason>`

where `<category>` is exactly one of:
- `hard-stop` — one of the four hard-stop conditions above.
- `approval-gate` — a named risk boundary awaiting sign-off (pause-then-proceed).
- `awaiting-input` — a planned interaction point inside the loop (the Phase -1 improve-prompt ask, the Phase 1 plan confirmation). Use this sparingly: Phase 13 counts `awaiting-input` declarations as avoidable stalls.
- `complete` — all authorised work done. Declaring `complete` is the teardown: also set `progress.json` `status: "complete"` and run Phase 13 in the same turn, or the guards keep treating the loop as active.

The hook checks the declaration is present with a valid category; it cannot check the reason is honest (same boundary as the verify-loop hook). The Phase 13 category counts are the audit on that.
```

- [ ] **Step 3: Add the LOOP-STOP KPI bullet to Phase 13**

Find the Phase 13 "Disposition violations" bullet (it ends with "…so deferred removals cannot silently rot."). Insert a new bullet immediately **after** it:

```markdown
- **LOOP-STOP declarations by category** — the per-category counts of this loop's `LOOP-STOP` declarations (`progress.json` `loop_stop_counts`). Report the breakdown; a high `awaiting-input` count is a primary avoidable-stall signal — each one is a yield the factory should ideally have absorbed. This is the audit that keeps the anti-stall guard's honest boundary (a model can rubber-stamp `awaiting-input`) from hiding stalls behind a valid-looking tag.
```

- [ ] **Step 4: Add the `loop_stop_counts` field to the persistence schema**

Find this fragment in the "Loop state lives in a durable artifact" paragraph:

```markdown
the human-turn counters for Phase 13, and — for any work-unit that retires an existing code path —
```

Replace it with:

```markdown
the human-turn counters and per-category `loop_stop_counts` (`{hard-stop, approval-gate, awaiting-input, complete}`) for Phase 13, and — for any work-unit that retires an existing code path —
```

- [ ] **Step 5: Verify the edits read consistently**

Run: `grep -n "LOOP-STOP\|loop_stop_counts\|loop_stall_guard\|awaiting-input" skills/agentic-loop/SKILL.md`
Expected: matches in Phase 0.5, the Stop-conditions section, Phase 13, and the persistence schema — all using the same vocabulary (`hard-stop|approval-gate|awaiting-input|complete`) and field name (`loop_stop_counts`) the C2 guard reads.

- [ ] **Step 6: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "docs(agentic-loop): LOOP-STOP declaration contract + Phase 13 stall KPI"
```

---

## Self-review

**Spec coverage** (against `docs/superpowers/specs/2026-06-24-c2-anti-stall-guard-design.md`):

| Spec element | Task |
|---|---|
| Block (exit 2), continue-or-declare | Task 2 (gate 6) |
| Fire on loop-active, no envelope-class gate | Task 2 (gates 3–6 use only invocation count + status) |
| Declaration = structured text tag in last message | Task 2 (gate 5, `extract_last_text` + regex) |
| Presence + category-from-vocab check | Task 2 (gate 5 regex from `LOOP_STOP_VOCAB`) |
| Active window = C1's off-switch (complete + not rearmed) | Task 2 (gate 4) |
| Single-source vocabulary | Task 1 (`LOOP_STOP_VOCAB` in lib); Task 2 (regex + message built from it) |
| Copy-paste tag template in block message | Task 2 (gate 6 message built from `LOOP_STOP_VOCAB`) |
| `complete`⇒teardown coupling | Task 2 (block message) + Task 3 (Phase 0.5 bullet, Stop-conditions, schema) |
| DRY shared lib + behaviour-preserving C1 refactor | Task 1 (lib + refactor + Step 5 regression gate) |
| C1 8/8 regression gate | Task 1, Step 5 |
| Phase 13 category KPI | Task 3, Step 3 |
| `loop_stop_counts` schema | Task 3, Step 4 |
| Registration after C1, timeout 15 | Task 2, Step 6 |
| install.sh — both new scripts in explicit list | Task 1, Step 6 (lib) + Task 2, Step 8 (guard) |
| Testing — bash -n + synthetic-payload behavioural assertions | Task 1 Steps 2/4/5; Task 2 Steps 1–5 |

**Placeholder scan:** no `TBD`/`TODO`/"add error handling"/"similar to" — every code and markdown block is complete and literal.

**Type/field consistency:** the C2 guard reads `.status`/`.session_id`/`.completed_marker` (same as C1, via the shared `als_read_file_state`). `LOOP_STOP_VOCAB` is defined once and consumed by the guard regex, the block message, and mirrored verbatim in the three SKILL.md edits. The lib's `als_*` function names match between the lib definition (Task 1) and both guards' calls (Tasks 1 and 2). `loop_stop_counts` is the field name in both Phase 13 (Step 3) and the schema (Step 4).

**`AskUserQuestion`/Stop interaction (open verification, from the spec):** whether `AskUserQuestion` fires the Stop hook is a runtime behaviour not checkable from source. If it does not fire, the Phase -1/Phase 1 asks never reach C2 (zero friction). If it does, they are declared `awaiting-input`. The design and this plan hold either way; no task depends on the answer.

## Sequencing

A (clean-migration discipline) — DONE, merged #12.
→ C1 (progress.json lifecycle + presence/ownership guard) — DONE, merged #13.
→ **C2** (this plan) — declaration-based anti-stall guard.
→ B — slim the skill.
→ D — superpowers construction-discipline seam (sonnet-only).
