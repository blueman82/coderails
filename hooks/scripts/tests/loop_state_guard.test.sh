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
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; : > "$CLAUDE_DISCIPLINE_LOG"; }
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
# A whole-slurp parse would abort on the bad line, making als_count_invocations
# return empty and als_gate_require_active_loop misread an ACTIVE loop as "not
# a loop", allowing the stop — this test pins per-line tolerance instead: the
# malformed line is skipped, the valid line is still counted, and the gate
# must BLOCK (loop is active, no progress.json present yet).
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
# attempt. Per-attempt logging inside als_count_invocations itself would leave
# "recovered on retry" indistinguishable from "exhausted, fell back to 0" and
# double-log on a sustained failure.

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

# Recovered case: transcript is malformed on disk initially (a single
# truncated mid-write line — every non-blank line malformed), then becomes
# valid before the retry window ends (simulates the flush-race this retry
# loop exists to ride out) -> final attempt succeeds, outcome=recovered,
# still exactly one log line (not one per failed attempt beforehand).
# A whole-slurp parse would abort on the bad line and misread an ACTIVE loop
# as "not a loop" (the pre-#91 bug) — this test pins the CURRENT, honest
# contract: since every line is malformed on the early attempts (not just
# one bad line among clean ones), als_count_invocations reports
# reason=all_lines_malformed (a real reason, gating settling) rather than the
# benign skipped_malformed breadcrumb — so the retry loop correctly keeps
# going past attempt 2 instead of settling clean at 0, until the flush lands
# and the last attempt's own count is clean.
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
check "recovered on retry -> logged reason=all_lines_malformed, outcome=recovered (honest attribution, not reason=none)" 1 \
  "$(count 'reason=all_lines_malformed attempts=[0-9]* outcome=recovered' "$CLAUDE_DISCIPLINE_LOG")"

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
# Failure-attribution regressions (post-#91): an existing-but-unreadable
# transcript, or a stage-1 jq crash on a readable one, must surface a real
# reason tag — not the confident-but-wrong "skipped_malformed" breadcrumb a
# read failure was producing.
# =====================================================================

# als_count_invocations on a chmod-000 (existing, unreadable) transcript must
# signal a reason on stderr, not silently return 0 with no breadcrumb at all.
unreadable_t="$TMP/unreadable_$RANDOM.jsonl"
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$unreadable_t"
chmod 000 "$unreadable_t"
unreadable_stdout=$(call_lib_fn als_count_invocations "$unreadable_t" 2>"$TMP/unreadable.err")
unreadable_stderr=$(cat "$TMP/unreadable.err" 2>/dev/null)
chmod 644 "$unreadable_t"
check "unreadable transcript -> stdout stays empty-or-0 (fail-open contract preserved, callers coerce)" "" "$unreadable_stdout"
check "unreadable transcript -> stderr carries a real reason, not silence" 1 \
  "$([ -n "$unreadable_stderr" ] && echo 1 || echo 0)"
check "unreadable transcript -> reason is NOT the misleading skipped_malformed breadcrumb" 0 \
  "$(printf '%s' "$unreadable_stderr" | grep -qE '^skipped_malformed=' && echo 1 || echo 0)"

# als_stable_invocations on the same unreadable fixture must log a real
# reason (not reason=none) and must NOT claim outcome=recovered.
: > "$CLAUDE_DISCIPLINE_LOG"
(
  export CLAUDE_HOOK_MAX_ATTEMPTS=2
  export CLAUDE_HOOK_SLEEP_S=0.01
  chmod 000 "$unreadable_t"
  . "$LIB"
  als_stable_invocations "$unreadable_t" >/dev/null
  chmod 644 "$unreadable_t"
)
check "T1/F1: unreadable transcript -> summary log does NOT say reason=none" 0 \
  "$(count 'hook=als_count_invocations reason=none' "$CLAUDE_DISCIPLINE_LOG")"
check "T1/F1: unreadable transcript -> summary log does NOT claim outcome=recovered" 0 \
  "$(count 'outcome=recovered' "$CLAUDE_DISCIPLINE_LOG")"

# F2: stage-1 jq crashing on a READABLE file (PATH-stubbed jq that fails only
# on the -R invocation) must also surface a real reason, never
# reason=none/outcome=recovered/skipped_malformed=1 (three lies: nothing was
# malformed, nothing recovered, jq itself is broken).
STUBJQ_DIR="$TMP/stubjq_$RANDOM"
mkdir -p "$STUBJQ_DIR"
REAL_JQ=$(command -v jq)
cat > "$STUBJQ_DIR/jq" <<EOF
#!/bin/bash
for a in "\$@"; do
  if [ "\$a" = "-R" ]; then echo "stub-jq: forced failure on -R" >&2; exit 1; fi
done
exec "$REAL_JQ" "\$@"
EOF
chmod +x "$STUBJQ_DIR/jq"
readable_t=$(mk_transcript 1)
: > "$CLAUDE_DISCIPLINE_LOG"
(
  export CLAUDE_HOOK_MAX_ATTEMPTS=1
  export PATH="$STUBJQ_DIR:$PATH"
  . "$LIB"
  als_stable_invocations "$readable_t" >/dev/null
)
check "F2: stage-1 jq crash on readable file -> NOT reason=none" 0 \
  "$(count 'hook=als_count_invocations reason=none' "$CLAUDE_DISCIPLINE_LOG")"
check "F2: stage-1 jq crash on readable file -> NOT outcome=recovered" 0 \
  "$(count 'outcome=recovered' "$CLAUDE_DISCIPLINE_LOG")"

# T3: the stage-2 jq_parse_error fallback branch is still independently
# reachable after the F1/F2 rc-capture — a jq that only fails on the FINAL
# filter program (not on -R/-s length) must still surface jq_parse_error, not
# be silently absorbed by the earlier read_error/all_lines_malformed checks.
STUBJQ2_DIR="$TMP/stubjq2_$RANDOM"
mkdir -p "$STUBJQ2_DIR"
cat > "$STUBJQ2_DIR/jq" <<EOF
#!/bin/bash
for a in "\$@"; do
  case "\$a" in *loop_name*) echo "stub-jq: forced failure on final filter" >&2; exit 1;; esac
done
exec "$REAL_JQ" "\$@"
EOF
chmod +x "$STUBJQ2_DIR/jq"
t3_readable=$(mk_transcript 1)
t3_stderr=$(
  . "$LIB"
  export PATH="$STUBJQ2_DIR:$PATH"
  als_count_invocations "$t3_readable" 2>&1 1>/dev/null
)
check "T3: stage-2 filter jq failure -> jq_parse_error still reachable" "jq_parse_error" "$t3_stderr"

# F3/T1: a transcript whose EVERY non-blank line is malformed (parsed=0,
# total>0) must be distinguishable from "one bad line among many, otherwise
# clean" — the guard must still ALLOW (fail-open, unchanged stdout contract)
# but the log must not claim outcome=recovered.
all_malformed_t="$TMP/all_malformed_$RANDOM.jsonl"
printf '%s\n' '{"type":"assistant", BROKEN LINE ONE' > "$all_malformed_t"
printf '%s\n' '{"type":"assistant", BROKEN LINE TWO' >> "$all_malformed_t"
reset
check "T1: permanently-malformed-only transcript -> gate still allows" 0 \
  "$(run x "$(payload "$all_malformed_t" S1)")"
: > "$CLAUDE_DISCIPLINE_LOG"
(
  export CLAUDE_HOOK_MAX_ATTEMPTS=2
  export CLAUDE_HOOK_SLEEP_S=0.01
  . "$LIB"
  als_stable_invocations "$all_malformed_t" >/dev/null
)
check "F3: all-lines-malformed -> summary log does NOT claim outcome=recovered" 0 \
  "$(count 'outcome=recovered' "$CLAUDE_DISCIPLINE_LOG")"
# F4 pin: all_lines_malformed is a REAL reason tag (unlike the benign
# skipped_malformed breadcrumb), so it must gate settling on EVERY attempt
# for a fixture that never becomes valid — burning the full retry budget
# (attempts=MAX_ATTEMPTS, outcome=exhausted), not settling early at count=0.
# A regression that let all_lines_malformed stop gating settling would still
# satisfy the "not outcome=recovered" check above by accident (e.g. logging
# nothing at all, or logging outcome=exhausted with the wrong attempts=N) —
# this pins the exact honest line, closing that gap.
check "F4: all-lines-malformed exhausts the FULL retry budget (attempts=2), not an early settle" 1 \
  "$(count 'reason=all_lines_malformed attempts=2 outcome=exhausted' "$CLAUDE_DISCIPLINE_LOG")"

# T4: N>1 skipped_malformed count — 2 malformed lines + 1 valid line ->
# skipped_malformed=2 (not double-counted, not truncated to 1).
mixed_malformed_t="$TMP/mixed_malformed_$RANDOM.jsonl"
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$mixed_malformed_t"
printf '%s\n' '{"type":"assistant", BROKEN LINE ONE' >> "$mixed_malformed_t"
printf '%s\n' '{"type":"assistant", BROKEN LINE TWO' >> "$mixed_malformed_t"
mixed_stderr=$(call_lib_fn als_count_invocations "$mixed_malformed_t" 2>&1 1>/dev/null)
check "T4: 2 malformed + 1 valid line -> skipped_malformed=2" "skipped_malformed=2" "$mixed_stderr"

# =====================================================================
# als_extract_last_text: non-object JSON line in the tail window must not
# blind the whole extraction (companion to als_count_invocations' malformed-
# line tolerance above, but a DIFFERENT failure shape: `fromjson? // empty`
# happily emits any valid JSON value, not only objects, so a bare scalar or
# array line passes stage 1 clean; stage 2's `select(.type == "assistant")`
# then errors on that non-object value, and with 2>/dev/null the whole
# `jq -s` pipeline yields empty — even though a real assistant-text line sits
# right next to it in the same tail window.
# =====================================================================
mk_nonobject_line_transcript() {
  local out="$TMP/nonobject_$RANDOM.jsonl"
  printf '%s\n' '123' > "$out"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"final answer text"}]}}' >> "$out"
  printf '%s' "$out"
}
nonobject_t=$(mk_nonobject_line_transcript)
extracted=$(call_lib_fn als_extract_last_text "$nonobject_t" 10)
check "bare scalar JSON line alongside valid assistant text -> text still extracted" "final answer text" "$extracted"

mk_nonobject_array_transcript() {
  local out="$TMP/nonobject_array_$RANDOM.jsonl"
  printf '%s\n' '[1,2,3]' > "$out"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"final answer text"}]}}' >> "$out"
  printf '%s' "$out"
}
nonobject_array_t=$(mk_nonobject_array_transcript)
extracted_array=$(call_lib_fn als_extract_last_text "$nonobject_array_t" 10)
check "bare JSON array line alongside valid assistant text -> text still extracted" "final answer text" "$extracted_array"

# Reversed ordering: the poison line comes AFTER the assistant-text line, not
# before. `last // ""` means this exercises a materially different path than
# the two tests above — and it's the shape a live transcript actually takes,
# since the assistant message is rarely the final line in the tail window (a
# trailing tool_result, hook record, etc. commonly follows it). Without this
# ordering the poison-before-text tests above could pass by coincidence if
# the guard only skipped LEADING junk rather than filtering every element.
mk_trailing_nonobject_transcript() {
  local out="$TMP/trailing_nonobject_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"final answer text"}]}}' > "$out"
  printf '%s\n' '123' >> "$out"
  printf '%s' "$out"
}
trailing_nonobject_t=$(mk_trailing_nonobject_transcript)
extracted_trailing=$(call_lib_fn als_extract_last_text "$trailing_nonobject_t" 10)
check "bare scalar JSON line AFTER valid assistant text -> text still extracted" "final answer text" "$extracted_trailing"

mk_trailing_nonobject_array_transcript() {
  local out="$TMP/trailing_nonobject_array_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"final answer text"}]}}' > "$out"
  printf '%s\n' '[1,2,3]' >> "$out"
  printf '%s' "$out"
}
trailing_nonobject_array_t=$(mk_trailing_nonobject_array_transcript)
extracted_trailing_array=$(call_lib_fn als_extract_last_text "$trailing_nonobject_array_t" 10)
check "bare JSON array line AFTER valid assistant text -> text still extracted" "final answer text" "$extracted_trailing_array"

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

# =====================================================================
# als_gate_unstubbed_grace — nag-once grace for an invoked-but-never-stubbed
# session. Fires ONLY on absence; a session's own prior absent-block log line
# releases the SAME (session, invocation-count) pairing exactly once — a NEW
# invocation count re-arms. Grace must never release when progress.json
# actually exists (that's the mismatch/stale-complete paths, unaffected).
# =====================================================================

# (1) Grace release: first run on absent file -> block (as before). Then
# pre-seed the exact absent-block log line and re-run the SAME payload ->
# exit 0, with unstubbed_grace=released recorded in the log.
reset; T=$(mk_transcript 1)
check "grace: first run, file absent -> block (unchanged)" 2 "$(run x "$(payload "$T" S1)")"
check "grace: first run wrote the absent-block log line" 1 \
  "$(count 'hook=loop_state_guard session=S1 invocations=1 status=absent reason=absent blocked=1' "$CLAUDE_DISCIPLINE_LOG")"
check "grace: second run, same payload, log carries the prior absent-block -> allow" 0 "$(run x "$(payload "$T" S1)")"
check "grace: release recorded in log as unstubbed_grace=released" 1 \
  "$(count 'hook=loop_state_guard session=S1 invocations=1 unstubbed_grace=released blocked=0' "$CLAUDE_DISCIPLINE_LOG")"

# (2) Re-invocation re-arms: after release at invocations=1, a transcript
# with invocations=2 (still no file) -> block again (new count, no matching
# log line for count=2 yet).
T2=$(mk_transcript 2)
check "grace: re-invocation (count=2) after release at count=1 -> block again (re-armed)" 2 "$(run x "$(payload "$T2" S1)")"

# (3) Grace is absent-only: with progress.json PRESENT (owned by a different
# session, i.e. mismatch), and an absent-nag line for THIS session already in
# the log -> still block (grace must not release when the file exists).
reset; T=$(mk_transcript 1)
run x "$(payload "$T" S1)" >/dev/null   # seeds the absent-block line for (S1, invocations=1)
write_file in-progress S_OTHER 0 S1     # now the file EXISTS (session mismatch)
check "grace: file present (session mismatch) despite a seeded absent-nag line -> still block" 2 \
  "$(run x "$(payload "$T" S1)")"

# (4) Session isolation + BRE escape: S1's nag line must not leak to a
# DIFFERENT session (S2.with.dots) hitting the identical transcript with no
# file. Session id deliberately contains "." to exercise the grep pattern's
# regex-escaping of the session_id.
reset; T=$(mk_transcript 1)
run x "$(payload "$T" S1)" >/dev/null   # seeds S1's absent-block line
S2_DOTTED="S2.with.dots"
check "grace: S1's nag line does not leak to a different session (S2.with.dots) -> still block" 2 \
  "$(run x "$(payload "$T" "$S2_DOTTED")")"

# (4b) Adversarial positive-match: seed an absent-block line for a session
# whose NAME is regex-metachar-free ("S2xwithydots" — literal x/y where
# S2.with.dots has dots), then run the guard as "S2.with.dots" with no
# progress.json. An UNescaped pattern "session=S2.with.dots " would treat
# each "." as a wildcard and WOULD match the seeded "session=S2xwithydots "
# line, falsely releasing (exit 0). With correct BRE-escaping the literal
# dots in the pattern must NOT match the seeded x/y line -> the guard must
# still BLOCK (exit 2).
reset; T=$(mk_transcript 1)
run x "$(payload "$T" "S2xwithydots")" >/dev/null   # seeds S2xwithydots' absent-block line
check "grace: unescaped-dot pattern must not false-match a metachar-free sibling line -> still block" 2 \
  "$(run x "$(payload "$T" "$S2_DOTTED")")"

# (4c) Dotted self-release: seed the absent-block line for the literal
# dotted session S2.with.dots itself, then rerun as S2.with.dots -> the
# escaped pattern must still match its OWN literal line -> RELEASE (exit 0).
# Proves the escaping doesn't break legitimate literal matches.
reset; T=$(mk_transcript 1)
run x "$(payload "$T" "$S2_DOTTED")" >/dev/null   # seeds S2.with.dots' own absent-block line
check "grace: dotted session's own seeded line still releases itself (escaping doesn't break literal matches)" 0 \
  "$(run x "$(payload "$T" "$S2_DOTTED")")"

# (5) Unwritable-log fail-safe: point CLAUDE_DISCIPLINE_LOG at an unwritable
# path (a directory, so any open-for-append fails) -> two consecutive runs
# BOTH exit 2 (grace can never release; degrade to today, never silent disarm).
reset; T=$(mk_transcript 1)
UNWRITABLE_DIR="$TMP/unwritable-log-dir-$RANDOM"
mkdir -p "$UNWRITABLE_DIR"
# CLAUDE_DISCIPLINE_LOG points at a directory (not a file): als_log's own
# printf-redirect open fails every time, so the absent-block line never
# lands, no matter how many times the guard runs.
rc1=$(CLAUDE_DISCIPLINE_LOG="$UNWRITABLE_DIR" run x "$(payload "$T" S1)")
rc2=$(CLAUDE_DISCIPLINE_LOG="$UNWRITABLE_DIR" run x "$(payload "$T" S1)")
check "grace: unwritable log, first run -> block" 2 "$rc1"
check "grace: unwritable log, second run -> STILL block (no silent disarm)" 2 "$rc2"

# (6) Compliant sequence: nag once, then write a session-owned in-progress
# stub -> allow via the normal present-and-owned path (arming intact after
# grace exists; grace itself is a no-op once the file exists).
reset; T=$(mk_transcript 1)
check "grace: compliant sequence, first run (no stub yet) -> block" 2 "$(run x "$(payload "$T" S1)")"
write_file in-progress S1 0
check "grace: compliant sequence, stub now written -> allow via present+owned (arming intact)" 0 "$(run x "$(payload "$T" S1)")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
