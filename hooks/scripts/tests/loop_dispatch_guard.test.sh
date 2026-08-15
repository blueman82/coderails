#!/bin/bash
# Behavioural test for loop_dispatch_guard.sh — the PreToolUse:Agent gate that
# mirrors loop_state_guard.sh's work-unit-count + loop-scope-evals check, but
# fires at DISPATCH time (before a coderails:loop-worker Agent call) instead
# of at loop completion. Helper conventions copied verbatim (in spirit) from
# loop_state_guard_evals.test.sh, per this repo's "bash test files are
# self-contained" pattern.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/../loop_dispatch_guard.sh"
POST_EVALS="$HERE/../../../scripts/post_evals.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1
fails=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

stamp() { ( source "$POST_EVALS" >/dev/null 2>&1; post_evals::grade_loop "$1" >/dev/null ) || { printf 'stamp: grade_loop refused %s\n' "$1" >&2; return 1; } }

CWD="/work/project"
SLUG="-work-project"
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }
file_path() { printf '%s/progress.json' "$(file_dir "$1")"; }

# write_file: session_id completed_marker [work_units_json]
write_file() {
  local session="$1" marker="$2" wu="${3:-{\}}"
  local dir; dir=$(file_dir "$session")
  mkdir -p "$dir"
  jq -n --arg session "$session" --argjson marker "$marker" --argjson wu "$wu" \
    '{schema_version:1, status:"in-progress", session_id:$session, completed_marker:$marker, work_units:$wu}' \
    > "$dir/progress.json"
}

# payload: session_id subagent_type
payload() {
  printf '{"tool_name":"Agent","tool_input":{"subagent_type":"%s"},"session_id":"%s","cwd":"%s"}' \
    "$2" "$1" "$CWD"
}

run() { echo "$1" | bash "$GUARD"; }   # -> stdout (JSON block, or empty on allow)
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

is_denied() { # stdout_json -> 0 if permissionDecision=deny, 1 otherwise
  printf '%s' "$1" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}

WU2='{"wu1":{"status":"done"},"wu2":{"status":"done"}}'
WU3='{"wu1":{"status":"done"},"wu2":{"status":"done"},"wu3":{"status":"done"}}'

# ── Non-Agent tool call -> always allow, no matter the state ────────────────
reset; write_file S1 0 "$WU3"
out=$(echo '{"tool_name":"Bash","tool_input":{"command":"ls"},"session_id":"S1","cwd":"'"$CWD"'"}' | bash "$GUARD")
check "non-Agent tool call -> allow (empty stdout)" "" "$out"

# ── No progress.json at all -> allow (nothing registered yet) ───────────────
reset
out=$(run "$(payload S1 coderails:loop-worker)")
check "no progress.json -> allow" "" "$out"

# ── Non-implementation-unit subagent_type -> always allow, regardless of count
reset; write_file S1 0 "$WU3"
out=$(run "$(payload S1 coderails:preflight-scout)")
check "non-implementation-unit subagent_type, 3 prior units, no evals.json -> allow" "" "$out"
[ -z "$out" ]
check "non-implementation-unit subagent_type is not denied" 0 $?

# ── Below threshold: 1 prior unit -> next dispatch is ordinal #2 -> allow ───
reset; write_file S1 0 '{"wu1":{"status":"done"}}'
out=$(run "$(payload S1 coderails:loop-worker)")
check "1 prior work_unit (dispatch ordinal #2), no evals.json -> allow (below threshold)" "" "$out"

# ── At/above threshold: 2 prior units -> this dispatch is #3 -> no evals.json -> BLOCK
reset; write_file S1 0 "$WU2"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "2 prior work_units (dispatch ordinal #3), no evals.json -> BLOCK" 0 $?
case "$out" in
  *"evals.json"*"Phase 2.7c"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - deny reason missing evals.json/Phase 2.7c mention: %s\n' "$out" ;;
esac

# ── At threshold, evals.json present, GO, justified, STAMPED -> allow ───────
reset; write_file S1 0 "$WU2"
jq -n '{scope:"loop", verification_level:1, verification_justification:"2 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "2 prior units, GO evals justified+stamped -> allow" "" "$out"

# ── At threshold, evals.json present, VERIFICATION_LEVEL0, justified, STAMPED -> allow
reset; write_file S1 0 "$WU2"
jq -n '{scope:"loop", verification_level:0, verification_justification:"docs-only loop, no runtime behaviour", head_sha:"deadbeef", evals:[]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "2 prior units, VERIFICATION_LEVEL0 justified+stamped -> allow" "" "$out"

# ── At threshold, evals.json NO-GO -> BLOCK ─────────────────────────────────
reset; write_file S1 0 "$WU2"
jq -n '{scope:"loop", result:"NO-GO", verification_level:1, verification_justification:"2 work-units, no irreversible surface"}' > "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "2 prior units, NO-GO evals -> BLOCK" 0 $?

# ── At threshold, evals.json GO but UNJUSTIFIED -> BLOCK ────────────────────
reset; write_file S1 0 "$WU2"
jq -n '{scope:"loop", result:"GO", verification_level:1, verification_justification:""}' > "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "2 prior units, GO but unjustified evals -> BLOCK" 0 $?

# ── At threshold, evals.json hand-written GO, never stamped -> BLOCK (UNSTAMPED)
reset; write_file S1 0 "$WU2"
jq -n '{scope:"loop", result:"GO", verification_level:1, verification_justification:"hand-written, never graded"}' > "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "2 prior units, hand-written GO never stamped -> BLOCK (UNSTAMPED)" 0 $?

# ── Well above threshold: 5 prior units, no evals.json -> BLOCK ─────────────
reset; write_file S1 0 '{"wu1":{"status":"done"},"wu2":{"status":"done"},"wu3":{"status":"done"},"wu4":{"status":"done"},"wu5":{"status":"done"}}'
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "5 prior work_units, no evals.json -> BLOCK" 0 $?

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
