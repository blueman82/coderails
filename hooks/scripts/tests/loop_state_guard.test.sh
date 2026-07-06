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
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }   # session_id -> dir
file_path() { printf '%s/progress.json' "$(file_dir "$1")"; }              # session_id -> file
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
write_file() { # status session_id completed_marker [path_session_id]
  # path_session_id defaults to session_id — the file lives at the path this
  # session_id resolves to, unless a test wants to write it at a DIFFERENT
  # session's path (to simulate a copied/corrupted file — see session_mismatch).
  local path_session="${4:-$2}"
  local dir; dir=$(file_dir "$path_session")
  mkdir -p "$dir"
  printf '{"schema_version":1,"status":"%s","session_id":"%s","completed_marker":%s}' "$1" "$2" "$3" > "$dir/progress.json"
}
run() { echo "$2" | bash "$GUARD" >/dev/null 2>&1; echo $?; }   # -> exit code
check() { # desc expected_code actual_code
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

# als_gate_no_transcript — no transcript file.
check "no transcript -> allow" 0 "$(run x "$(payload "$TMP/nope.jsonl" S1)")"

# als_gate_require_active_loop — transcript with a non-loop Skill only -> allow.
reset; T=$(mk_other_transcript)
check "non-loop skill -> allow" 0 "$(run x "$(payload "$T" S1)")"

# block_state_failure (absent) — loop active, file missing -> BLOCK.
reset; T=$(mk_transcript 1)
check "loop active, file absent -> block" 2 "$(run x "$(payload "$T" S1)")"

# block_state_failure (mismatch) — a file sitting at S1's own path but stamped
# with a different session_id inside (copied/corrupted content) -> BLOCK.
reset; T=$(mk_transcript 1); write_file in-progress S_OTHER 0 S1
check "session mismatch (corrupted content at own path) -> block" 2 "$(run x "$(payload "$T" S1)")"

# NOTE: this verifies the GUARD's behaviour given an already-session-scoped
# absent file — it does NOT discriminate the path-computation fix itself,
# because file_dir()/write_file() above independently reconstruct the
# session-scoped path rather than calling agentic_loop_path.sh. It would pass
# unchanged even against the old cwd-only path helper. The real discriminating
# test for session-isolation is agentic_loop_path.test.sh's own
# "distinct sessions -> distinct paths" check, which calls the real helper.
# What this test DOES prove: S2's in-progress file at S2's own path is
# invisible to S1's guard run, which sees no file at ITS path and blocks
# "absent", not "mismatch".
reset; T=$(mk_transcript 1); write_file in-progress S2 0
check "distinct session in same cwd -> own path, not visible to S1 (absent)" 2 "$(run x "$(payload "$T" S1)")"

# gate_present_and_owned — present, owned, in-progress -> allow.
reset; T=$(mk_transcript 1); write_file in-progress S1 0
check "present+owned+in-progress -> allow" 0 "$(run x "$(payload "$T" S1)")"

# null_payload builds a raw Stop payload whose session_id key is JSON null (the
# real-world trigger: jq's `.session_id // "?"` maps null AND missing keys to
# the literal "?" — but leaves an empty STRING "" alone, since only null/false/
# missing are falsy in jq). payload() above can only emit a quoted string, so
# this needs its own raw-JSON builder to reach the actual null case.
null_payload() { # transcript_path -> payload with session_id: null
  jq -cn --arg t "$1" --arg c "$CWD" '{transcript_path:$t,session_id:null,cwd:$c,stop_hook_active:false}'
}

# Fix 1 regression test — session_id: null must not collide onto a shared
# sentinel path. Before the fix, EVERY payload with session_id null (or the key
# missing) resolved session_id to the fixed literal "?", so a progress.json
# stamped session_id "?" and sitting at ".../?/progress.json" would look
# "present + owned" (allow) to ANY session that ever hit this edge case —
# regardless of which session actually wrote it. Simulate that exact stray
# file (owned by the "?" sentinel itself, matching what the OLD code would
# have written for a prior malformed-payload session), then run the guard with
# session_id: null. Pre-fix this must ALLOW (it is genuinely "present+owned" at
# the shared sentinel path); post-fix each invocation gets its own unique
# generated fallback, so the guard never resolves to "?" and must not see that
# stray file — it blocks "absent" instead.
reset; T=$(mk_transcript 1); write_file in-progress '?' 0 '?'
check "null session_id -> unique fallback, not old '?' sentinel (absent, not allow)" 2 "$(run x "$(null_payload "$T")")"

# And two SEPARATE guard runs with session_id: null must not collide with EACH
# OTHER either: the first run's block message names its own resolved path;
# write a file there, then confirm a second independent invocation (fresh
# unique fallback) still does not see it as present+owned.
reset; T=$(mk_transcript 1)
first_msg=$(echo "$(null_payload "$T")" | bash "$GUARD" 2>&1 >/dev/null)
first_path=$(printf '%s\n' "$first_msg" | grep -o "$CLAUDE_AGENTIC_LOOP_DIR/[^ ]*progress.json" | head -1)
if [ -n "$first_path" ]; then
  mkdir -p "$(dirname "$first_path")"
  printf '{"schema_version":1,"status":"in-progress","session_id":"?","completed_marker":0}' > "$first_path"
fi
check "two null-session_id runs -> second still blocks (own unique path, not first's)" 2 "$(run x "$(null_payload "$T")")"

# als_gate_loop_complete — complete, owned, not re-armed (invocations 1 <= marker 1) -> allow.
reset; T=$(mk_transcript 1); write_file complete S1 1
check "complete, not re-armed -> allow" 0 "$(run x "$(payload "$T" S1)")"

# block_state_failure (stale-complete) — re-armed (invocations 2 > marker 1) -> BLOCK.
reset; T=$(mk_transcript 2); write_file complete S1 1
check "complete but re-armed -> block" 2 "$(run x "$(payload "$T" S1)")"

# als_gate_stop_loop — already blocked this turn: would-block case allowed via loop-guard.
reset; T=$(mk_transcript 1)   # file absent => would block, but stop_hook_active short-circuits
check "stop_hook_active -> allow" 0 "$(run x "$(payload "$T" S1 true)")"

# als_sanitise_session_id — malformed raw ids are REPLACED (not fresh-fallback)
# so a malformed id can't silently orphan its own real session. Source the lib
# directly in a subshell and call the function under test, same isolation
# pattern as unregistered_loop_guard.test.sh's call_fn-style checks.
COMMON_LIB="$(cd "$(dirname "$0")/../lib" && pwd)/loop_state_common.sh"
sanitised() { ( . "$COMMON_LIB"; als_sanitise_session_id "$1" ); }
check "sanitise: '/' replaced with '_'" "foo_bar" "$(sanitised "foo/bar")"
# Transform order is "/" -> "_" first, then ".." collapsed: "../../etc" becomes
# ".._.._etc" after the "/" replacement, then sed removes both ".." pairs,
# leaving "__etc". Documented exact expected value per this deterministic order.
check "sanitise: '..' collapsed/removed" "__etc" "$(sanitised "../../etc")"
check "sanitise: normal id passes through unchanged" "normal-id-123" "$(sanitised "normal-id-123")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
