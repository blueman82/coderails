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
