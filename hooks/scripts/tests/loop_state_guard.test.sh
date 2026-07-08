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
# grep -c exits 1 on zero matches even though it correctly prints "0" — count()
# always exits 0 and prints just the count, so a zero-match assertion doesn't
# need an `|| echo 0` fallback that (on a match count of exactly 0) would print
# a spurious second "0" line and break the string-equality check in check().
count() { grep -c "$1" "$2" 2>/dev/null; true; }

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

# session_id: null must not collide onto a shared sentinel path. If a payload with
# session_id null (or the key missing) resolved session_id to the fixed literal "?",
# a progress.json stamped session_id "?" and sitting at ".../?/progress.json" would
# look "present + owned" (allow) to ANY session that ever hit this edge case —
# regardless of which session actually wrote it. Simulate that exact stray file
# (owned by the "?" sentinel itself), then run the guard with session_id: null:
# each invocation must get its own unique generated fallback, so the guard never
# resolves to "?" and must not see that stray file — it blocks "absent" instead.
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

# =====================================================================
# als_count_invocations malformed-line tolerance (one bad line must not
# collapse the whole slurp to empty/0 — a per-line tolerant pre-filter skips
# only the bad line, so a genuinely active loop still counts as active).
# =====================================================================
# Malformed transcript: 1 valid loop-Skill line + 1 truncated/invalid JSON line.
# Pre-fix, `jq -s` (slurp) aborted the WHOLE parse on the bad line, so
# als_count_invocations returned empty -> als_gate_require_active_loop treated
# an ACTIVE loop as "not a loop" and allowed the stop — the bug this fix closes.
# Post-fix, the malformed line is skipped and the valid line is still counted,
# so the gate must BLOCK (loop is active, no progress.json present yet).
mk_corrupt_transcript() {
  local out="$TMP/corrupt_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$out"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
reset; corrupt_t=$(mk_corrupt_transcript)
check "malformed transcript, valid loop line present -> still detected as active (block)" 2 "$(run x "$(payload "$corrupt_t" S1)")"

# A malformed line alongside a NON-loop skill call must still allow (the
# tolerant parse must not manufacture a false-positive loop detection either).
mk_corrupt_other_transcript() {
  local out="$TMP/corrupt_other_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:prep"}}]}}' > "$out"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
reset; corrupt_other_t=$(mk_corrupt_other_transcript)
check "malformed transcript, no loop line -> still allow (no false positive)" 0 "$(run x "$(payload "$corrupt_other_t" S1)")"

# skipped_malformed=N breadcrumb: als_stable_invocations' summary log line
# gains a skipped_malformed=N field (N>0) alongside the existing reason=/
# attempts=/outcome= fields on the SAME line — no separate log line, and the
# breadcrumb must name the count of lines the tolerant parse actually dropped.
reset; : > "$CLAUDE_DISCIPLINE_LOG"; write_file in-progress S1 0
run x "$(payload "$corrupt_t" S1)" >/dev/null
check "malformed transcript -> discipline log gains skipped_malformed=1" 1 \
  "$(count 'skipped_malformed=1' "$CLAUDE_DISCIPLINE_LOG")"
check "skipped_malformed breadcrumb rides the SAME summary line as hook=als_count_invocations" 1 \
  "$(count 'hook=als_count_invocations.*skipped_malformed=1' "$CLAUDE_DISCIPLINE_LOG")"

# als_count_invocations is now a ONE-SHOT primitive: on jq failure it signals
# the reason on STDERR (not by logging directly — see its own comment), and
# does NOT touch the discipline log itself. Source lib/loop_state_common.sh
# directly (call_fn-style isolation, mirroring unregistered_loop_guard.test.sh)
# and shadow PATH around the call to confirm this contract.
LIB="$(cd "$(dirname "$0")/../lib" && pwd)/loop_state_common.sh"
call_lib_fn() { local fn="$1"; shift; ( . "$LIB"; "$fn" "$@" ); }
: > "$CLAUDE_DISCIPLINE_LOG"
some_t=$(mk_transcript 1)
jq_missing_stderr=$(
  . "$LIB"
  export PATH="/nonexistent_empty_dir_for_jq_shadow_test"
  als_count_invocations "$some_t" 2>&1 1>/dev/null
)
check "jq not on PATH -> als_count_invocations signals jq_missing on stderr" "jq_missing" "$jq_missing_stderr"
check "jq not on PATH, called directly (one-shot) -> discipline log NOT touched" 0 \
  "$(count 'reason=jq_missing' "$CLAUDE_DISCIPLINE_LOG")"

# als_stable_invocations (the retrying wrapper) is where jq-failure logging
# actually happens now — EXACTLY ONE summary line per gate call, with
# attempts=N and outcome=recovered|exhausted, never one line per retry
# attempt. This is the PR #23 review fix: the prior per-attempt logging inside
# als_count_invocations left "recovered on retry" indistinguishable from
# "exhausted, fell back to 0" and double-logged on a sustained failure.

# Exhausted case: jq missing for the WHOLE retry window -> every attempt
# fails, final outcome is exhausted, exactly one log line. A blanket PATH
# shadow (like the one-shot test above uses) also breaks sleep/mktemp inside
# als_stable_invocations itself, since those are external binaries too — build
# a minimal PATH containing symlinks to everything als_stable_invocations/
# als_log need EXCEPT jq, so the retry loop's own machinery still runs.
no_jq_path="$TMP/no_jq_path"
mkdir -p "$no_jq_path"
for bin in sleep date cat rm mktemp grep printf dirname basename; do
  src=$(command -v "$bin" 2>/dev/null)
  [ -n "$src" ] && ln -sf "$src" "$no_jq_path/$bin"
done
: > "$CLAUDE_DISCIPLINE_LOG"
(
  # MAX_ATTEMPTS/SLEEP_S are computed ONCE at source time from the env vars
  # (loop_state_common.sh:14-15) — export the overrides BEFORE sourcing, not
  # after, or the outer test file's own CLAUDE_HOOK_MAX_ATTEMPTS=1 (line 11,
  # set for the exit-code tests above) wins and this retry window never opens.
  export CLAUDE_HOOK_MAX_ATTEMPTS=3
  export CLAUDE_HOOK_SLEEP_S=0.01
  export PATH="$no_jq_path"
  . "$LIB"
  als_stable_invocations "$some_t" >/dev/null
)
check "jq missing for whole retry window -> exactly ONE summary log line" 1 \
  "$(count 'hook=als_count_invocations' "$CLAUDE_DISCIPLINE_LOG")"
check "sustained jq failure -> logged outcome=exhausted" 1 \
  "$(count 'reason=jq_missing attempts=[0-9]* outcome=exhausted' "$CLAUDE_DISCIPLINE_LOG")"

# Recovered case: transcript is malformed on disk initially, then becomes
# valid before the retry window ends (simulates the flush-race this retry
# loop exists to ride out) -> final attempt succeeds, outcome=recovered,
# still exactly one log line (not one per failed attempt beforehand).
# Post-fix: a single wholly-malformed line is tolerantly SKIPPED (not a jq
# parse failure of the whole slurp any more, since stage 1 drops just that
# line) — the first attempt sees count=0 skipped_malformed=1, so reason stays
# "none" and the skip is what triggers the summary line; outcome=recovered
# because the settling (last) attempt's own count is clean.
: > "$CLAUDE_DISCIPLINE_LOG"
flush_t="$TMP/flush_$RANDOM.jsonl"
printf '%s\n' '{"type":"assistant", TRUNCATED-MID-WRITE' > "$flush_t"
(
  # Same export-before-source ordering as the exhausted-case block above.
  export CLAUDE_HOOK_MAX_ATTEMPTS=5
  export CLAUDE_HOOK_SLEEP_S=0.05
  . "$LIB"
  # Overwrite the transcript with valid content shortly after the loop starts,
  # so the first attempt(s) see the malformed version and a later attempt
  # sees the recovered one.
  ( sleep 0.06; printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$flush_t" ) &
  bg_pid=$!
  als_stable_invocations "$flush_t" >/dev/null
  wait "$bg_pid" 2>/dev/null
)
check "recovered on retry -> exactly ONE summary log line (not one per attempt)" 1 \
  "$(count 'hook=als_count_invocations' "$CLAUDE_DISCIPLINE_LOG")"
check "recovered on retry -> logged outcome=recovered, skipped_malformed breadcrumb from the earlier skip survives" 1 \
  "$(count 'reason=none attempts=[0-9]* outcome=recovered skipped_malformed=1' "$CLAUDE_DISCIPLINE_LOG")"

# Clean case: no jq failure at any attempt -> zero log lines from this path.
: > "$CLAUDE_DISCIPLINE_LOG"
clean_t=$(mk_transcript 1)
(
  export CLAUDE_HOOK_MAX_ATTEMPTS=1
  . "$LIB"
  als_stable_invocations "$clean_t" >/dev/null
)
check "clean transcript, no jq failure -> zero als_count_invocations log lines" 0 \
  "$(count 'hook=als_count_invocations' "$CLAUDE_DISCIPLINE_LOG")"

# =====================================================================
# als_log brace-group redirection (no stderr leak, no dir auto-create)
# =====================================================================
missing_parent_log="$TMP/does-not-exist-$RANDOM/discipline.log"
stderr_out=$(
  CLAUDE_DISCIPLINE_LOG="$missing_parent_log" bash -c '. "'"$LIB"'"; als_log "test-message"' 2>&1 >/dev/null
)
check "als_log with missing parent dir -> stderr empty" "" "$stderr_out"
# Exit code contract: als_log's exit status when the redirect itself fails is
# the shell's own failed-redirect status (1), unmasked by a trailing-only
# 2>/dev/null. Only the stray stderr LINE is suppressed, not this exit code,
# so this asserts "unchanged", not "0".
CLAUDE_DISCIPLINE_LOG="$missing_parent_log" bash -c '. "'"$LIB"'"; als_log "test-message"' 2>/dev/null
check "als_log with missing parent dir -> exit code unchanged (1, same as pre-fix)" 1 "$?"
[ ! -d "$(dirname "$missing_parent_log")" ]
check "als_log does not auto-create the missing parent dir" 0 "$?"

# =====================================================================
# loop_state_guard.sh cwd fallback to $PWD when payload .cwd absent
# =====================================================================
payload_no_cwd() { # transcript_path session_id [stop_hook_active] -- same shape as payload() but no "cwd" key
  printf '{"transcript_path":"%s","session_id":"%s","stop_hook_active":%s}' \
    "$1" "$2" "${3:-false}"
}
reset
T=$(mk_transcript 1)
# Write the progress.json at the path agentic_loop_path.sh resolves for $PWD
# (not the fixture's $CWD="/work/project"), since with .cwd absent the guard
# must fall back to $PWD, not the test's synthetic CWD constant.
PWD_PATH=$(bash "$(cd "$(dirname "$0")/../lib" && pwd)/agentic_loop_path.sh" "$PWD" S1)
mkdir -p "$(dirname "$PWD_PATH")"
printf '{"schema_version":1,"status":"in-progress","session_id":"S1","completed_marker":0}' > "$PWD_PATH"
check "payload with .cwd absent -> resolves via \$PWD fallback (present+owned, allow)" 0 \
  "$(run x "$(payload_no_cwd "$T" S1)")"
rm -rf "$(dirname "$PWD_PATH")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
