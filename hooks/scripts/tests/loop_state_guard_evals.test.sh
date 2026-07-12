#!/bin/bash
# Behavioural test for the loop-scope evals gate: the pure-function readers in
# lib/loop_state_common.sh (als_read_work_units, als_read_loop_evals_result)
# and their wiring into loop_state_guard.sh's new gate_loop_evals_required.
# Kept as a separate file from loop_state_guard.test.sh so this gate's cases
# don't need to touch every existing case in that file; run_all.sh globs both.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/../loop_state_guard.sh"
COMMON="$HERE/../lib/loop_state_common.sh"
POST_EVALS="$HERE/../../../scripts/post_evals.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
fails=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# stamp <evals_json_path>: grades a fixture in place using the REAL
# post_evals::grade_loop, so "properly stamped" test fixtures are byte-
# identical to what the writer produces — never hand-computed here.
stamp() { ( source "$POST_EVALS" >/dev/null 2>&1; post_evals::grade_loop "$1" >/dev/null ) || { printf 'stamp: grade_loop refused %s\n' "$1" >&2; return 1; } }

# ── als_read_work_units ──────────────────────────────────────────────────────
. "$COMMON"

# work_units present with 3 keys -> count 3.
f="$TMP/progress_3units.json"
jq -n '{work_units: {wu1: {status:"done"}, wu2: {status:"done"}, wu3: {status:"in-progress"}}}' > "$f"
als_read_work_units "$f"
check "work_units with 3 keys -> count 3" 3 "$ALS_WORK_UNIT_COUNT"

# legacy progress.json with no work_units key at all -> fail-open to 0.
f="$TMP/progress_legacy.json"
printf '{"schema_version":1,"status":"complete"}' > "$f"
als_read_work_units "$f"
check "legacy file, no work_units key -> 0 (fail-open)" 0 "$ALS_WORK_UNIT_COUNT"

# nonexistent path -> fail-open to 0, no error.
als_read_work_units "$TMP/does-not-exist.json"
check "nonexistent path -> 0 (fail-open)" 0 "$ALS_WORK_UNIT_COUNT"

# ── als_read_loop_evals_result ───────────────────────────────────────────────

# scope loop, result GO, non-empty tier_justification, PROPERLY STAMPED -> GO.
# (Task 1's own UNSTAMPED demotion means a GO/TIER0 fixture must now also
# carry a valid grade-loop stamp to read back as GO/TIER0 — see the dedicated
# UNSTAMPED cases further down for the unstamped/mismatched-checksum paths.)
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:1, tier_justification:"2 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' > "$d/evals.json"
stamp "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop result=GO justified + stamped -> GO" "GO" "$ALS_LOOP_EVALS_RESULT"

# scope loop, result GO, but tier_justification blank -> UNJUSTIFIED (
# justification is required at every tier, even when result already
# computed GO — eval_artifact::compute_go never inspects tier_justification,
# so this reader must catch it independently). Distinct from NO-GO so the
# guard can name the actual defect rather than misattributing it to a failed
# eval run.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", result:"GO", tier:1, tier_justification:""}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop result=GO unjustified -> UNJUSTIFIED" "UNJUSTIFIED" "$ALS_LOOP_EVALS_RESULT"

# scope loop, result GO, whitespace-only tier_justification -> UNJUSTIFIED
# (trim must treat whitespace-only as blank, not merely check non-empty-string).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", result:"GO", tier:1, tier_justification:"   "}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop result=GO whitespace-only justification -> UNJUSTIFIED" "UNJUSTIFIED" "$ALS_LOOP_EVALS_RESULT"

# no evals.json file at all -> ABSENT.
d=$(mktemp -d "$TMP/loopdir.XXXX")
als_read_loop_evals_result "$d"
check "no evals.json -> ABSENT" "ABSENT" "$ALS_LOOP_EVALS_RESULT"

# scope pr (wrong scope) -> ABSENT, never satisfies the loop gate.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"pr", result:"GO"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=pr (stray pr-scope file) -> ABSENT" "ABSENT" "$ALS_LOOP_EVALS_RESULT"

# scope loop, result NO-GO, JUSTIFIED -> NO-GO. Justification present so the
# blank-justification branch does not short-circuit before reaching the
# reader's final `else NO-GO` — a bare-NO-GO fixture with no tier_justification
# field would be caught by the blank-justification branch and never reach this
# else, leaving it with zero coverage even though the suite stayed green.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", result:"NO-GO", tier:1, tier_justification:"2 work-units, no irreversible surface"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop result=NO-GO justified -> NO-GO (exercises final else)" "NO-GO" "$ALS_LOOP_EVALS_RESULT"

# scope loop, tier 0, non-empty tier_justification, no result field, PROPERLY
# STAMPED -> GO, not TIER0: grade-loop always writes .result (GO for a tier-0
# exemption — compute_go on empty .evals is vacuously true), and the reader's
# elif chain checks .result before .tier, so a stamped tier-0 file always has
# an explicit .result and never reaches the tier-0 branch. TIER0 as a
# TERMINAL outcome only occurs for an UNSTAMPED tier-0 file (no .result at
# all) — see the dedicated unstamped-TIER0 case further down, which is the
# one that actually exercises the tier-0 branch end-to-end.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:"no user-facing behaviour changed", head_sha:"deadbeef", evals:[]}' > "$d/evals.json"
stamp "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop tier=0 justified + stamped -> GO (stamping always sets .result)" "GO" "$ALS_LOOP_EVALS_RESULT"

# scope loop, tier 0, empty tier_justification -> UNJUSTIFIED (unjustified tier-0 claim does not pass).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:""}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop tier=0 unjustified (empty justification) -> UNJUSTIFIED" "UNJUSTIFIED" "$ALS_LOOP_EVALS_RESULT"

# scope loop, tier 0, whitespace-only tier_justification -> UNJUSTIFIED.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:"   "}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop tier=0 whitespace-only justification -> UNJUSTIFIED" "UNJUSTIFIED" "$ALS_LOOP_EVALS_RESULT"

# malformed (non-JSON) file -> ABSENT, not NO-GO (no genuine artifact to grade).
d=$(mktemp -d "$TMP/loopdir.XXXX")
printf 'not valid json{{{' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "malformed JSON -> ABSENT (not NO-GO)" "ABSENT" "$ALS_LOOP_EVALS_RESULT"

# scope loop, tier 0, justified, explicit result NO-GO -> NO-GO. An explicit
# NO-GO must win at every tier including tier 0 (owner directive 2026-07-06):
# "an exemption justifies having no evals, not overriding a recorded failure."
# Prior to this branch, tier 0 + justified short-circuited to TIER0 regardless
# of an explicit result, silently discarding a recorded failure.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:"probe", result:"NO-GO"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop tier=0 justified result=NO-GO -> NO-GO (explicit NO-GO wins)" "NO-GO" "$ALS_LOOP_EVALS_RESULT"

# regression: tier 0, justified, no explicit result, STAMPED -> GO (same
# reasoning as above: grade-loop always writes .result, so this converges
# with the "explicit GO" fixture below once stamped).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:"probe", head_sha:"deadbeef", evals:[]}' > "$d/evals.json"
stamp "$d/evals.json"
als_read_loop_evals_result "$d"
check "regression: scope=loop tier=0 justified no result + stamped -> GO" "GO" "$ALS_LOOP_EVALS_RESULT"

# regression: tier 0, justified, result GO explicitly pre-written, STAMPED
# (stamping recomputes .result over whatever was there — post_evals::grade_loop
# is the SSOT for .result — so this exercises the GO branch being checked
# before the tier-0 branch, same as the fixture above minus the pre-existing
# key; distinct in intent even though grade-loop makes both files converge).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:"probe", result:"GO", head_sha:"deadbeef", evals:[]}' > "$d/evals.json"
stamp "$d/evals.json"
als_read_loop_evals_result "$d"
check "regression: scope=loop tier=0 justified result=GO + stamped -> GO" "GO" "$ALS_LOOP_EVALS_RESULT"

# regression: tier 2 (non-zero), justified, result NO-GO -> still NO-GO (the
# pre-existing else-branch path for non-tier-0 must be unaffected).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:2, tier_justification:"probe", result:"NO-GO"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "regression: scope=loop tier=2 justified result=NO-GO -> NO-GO" "NO-GO" "$ALS_LOOP_EVALS_RESULT"

# tier!=0, justified, result key ABSENT ENTIRELY (not "NO-GO" explicitly,
# not tier 0) -> NO-GO via the reader's final `else` branch. Distinct from
# every existing fixture: the closest prior case (line ~136 above) sets
# result:"GO" explicitly and is caught by the second elif; this fixture has
# no result key at all, so it must fall through every elif to reach the
# final else, which is the one branch this file had zero coverage for
# until now (confirmed by direct execution against pre-change code: this
# exact fixture already returns NO-GO today — this test locks that in).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:2, tier_justification:"probe, no result key at all"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop tier=2 justified, result key absent -> NO-GO (final else)" "NO-GO" "$ALS_LOOP_EVALS_RESULT"

# ── UNSTAMPED: the new grade-loop stamp check ────────────────────────────────

# (f reader-level) tier-0, justified, no .result, no .grading at all (never
# stamped) -> UNSTAMPED. This is the terminal TIER0-would-be case: only an
# unstamped tier-0 file ever reaches the tier-0 branch (a stamped one always
# has .result and resolves via the GO branch instead — see above).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:0, tier_justification:"docs-only, never stamped"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop tier=0 justified, no .grading -> UNSTAMPED" "UNSTAMPED" "$ALS_LOOP_EVALS_RESULT"

# (f reader-level) hand-written result:"GO", no .grading at all -> UNSTAMPED.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", result:"GO", tier:1, tier_justification:"hand-written, never graded"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop result=GO, no .grading -> UNSTAMPED" "UNSTAMPED" "$ALS_LOOP_EVALS_RESULT"

# (g reader-level) stamped GO, then a status is edited post-stamp (checksum
# mismatch, .grading.by/checksum still present but stale) -> UNSTAMPED.
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", tier:1, tier_justification:"2 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' > "$d/evals.json"
stamp "$d/evals.json"
als_read_loop_evals_result "$d"
check "sanity: stamped fixture reads GO before tamper" "GO" "$ALS_LOOP_EVALS_RESULT"
tmp_tamper="$d/evals.json.tamper"
jq '.evals[0].status = "fail" | .result = "GO"' "$d/evals.json" > "$tmp_tamper" && mv "$tmp_tamper" "$d/evals.json"
als_read_loop_evals_result "$d"
check "stamped GO, status tampered post-stamp (checksum mismatch) -> UNSTAMPED" "UNSTAMPED" "$ALS_LOOP_EVALS_RESULT"

# ── gate_loop_evals_required (end-to-end guard invocations) ─────────────────
# Helpers copied verbatim (in spirit) from loop_state_guard.test.sh, per the
# plan's instruction that bash test files in this repo are self-contained.
CWD="/work/project"
SLUG="-work-project"
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }   # session_id -> dir
file_path() { printf '%s/progress.json' "$(file_dir "$1")"; }              # session_id -> file

mk_transcript() { # n_invocations -> path
  local n="$1" out="$TMP/t_$1_$RANDOM.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s' "$out"
}
payload() { # transcript_path session_id [stop_hook_active]
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":%s}' \
    "$1" "$2" "$CWD" "${3:-false}"
}
# write_file: status session_id completed_marker [path_session_id] [work_units_json]
# The 5th arg, if given, is spliced in verbatim as the .work_units value.
write_file() {
  local path_session="${4:-$2}"
  local dir; dir=$(file_dir "$path_session")
  mkdir -p "$dir"
  if [ -n "${5:-}" ]; then
    jq -n --arg status "$1" --arg session "$2" --argjson marker "$3" --argjson wu "$5" \
      '{schema_version:1, status:$status, session_id:$session, completed_marker:$marker, work_units:$wu}' \
      > "$dir/progress.json"
  else
    printf '{"schema_version":1,"status":"%s","session_id":"%s","completed_marker":%s}' "$1" "$2" "$3" > "$dir/progress.json"
  fi
}
run() { echo "$2" | bash "$GUARD" >/dev/null 2>&1; echo $?; }   # -> exit code
run_err() { echo "$2" | bash "$GUARD" 2>&1 >/dev/null; }        # -> stderr
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

WU3='{"wu1":{"status":"done"},"wu2":{"status":"done"},"wu3":{"status":"done"}}'
WU2='{"wu1":{"status":"done"},"wu2":{"status":"done"}}'
WU5='{"wu1":{"status":"done"},"wu2":{"status":"done"},"wu3":{"status":"done"},"wu4":{"status":"done"},"wu5":{"status":"done"}}'

# Core behaviour test: complete, owned, 3 work_units, no sibling evals.json.
# Negative control: als_gate_loop_complete alone (presence/ownership only) would
# pass this at exit 0, proving a loop-scope-evals gap that this guard closes —
# so this test asserts the evals-aware blocking behaviour directly.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
err=$(run_err x "$(payload "$T" S1)")
code=$(run x "$(payload "$T" S1)")
check "complete+owned+3 work_units+no evals.json -> block (exit 2)" 2 "$code"
case "$err" in
  *"loop-scope evals"*"$(file_dir S1)/evals.json"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - stderr missing expected evals path/text: %s\n' "$err" ;;
esac

# evals.json present, scope loop, result GO, justified, STAMPED -> allow (exit 0).
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:1, tier_justification:"2 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
check "GO evals justified + stamped -> allow" 0 "$(run x "$(payload "$T" S1)")"

# evals.json present, scope loop, result GO, but tier_justification blank ->
# block (exit 2) — owner directive closes the gap where GO alone bypassed
# the justification requirement. Reviewer finding FH: the guard now emits a
# dedicated UNJUSTIFIED message naming tier_justification explicitly, distinct
# from the "no passing loop-scope evals.json found" NO-GO/ABSENT message.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", result:"GO", tier:1, tier_justification:""}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "GO evals unjustified -> block (exit 2)" 2 "$code"
case "$err" in
  *"tier_justification"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - UNJUSTIFIED stderr missing tier_justification mention: %s\n' "$err" ;;
esac

# tier-0 exemption: scope loop, tier 0, non-empty tier_justification, no
# result, STAMPED -> allow.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:0, tier_justification:"docs-only loop, no runtime behaviour", head_sha:"deadbeef", evals:[]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
check "TIER0 exemption evals + stamped -> allow" 0 "$(run x "$(payload "$T" S1)")"

# evals.json present but NO-GO, JUSTIFIED -> block, stderr mentions the loop
# dir path. Justification present so this exercises the reader's final `else
# NO-GO` branch at the e2e level too — a fixture with no tier_justification
# field would be caught by the blank-justification branch first and never
# reach this else.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", result:"NO-GO", tier:1, tier_justification:"2 work-units, no irreversible surface"}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "NO-GO evals (justified) -> block (exit 2)" 2 "$code"
case "$err" in
  *"$(file_dir S1)/evals.json"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - stderr missing loop dir path: %s\n' "$err" ;;
esac

# Only 2 work_units, no evals.json at all -> allow (tier trigger not met, <3 skips read).
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU2"
check "2 work_units, no evals.json -> allow (below threshold)" 0 "$(run x "$(payload "$T" S1)")"

# work_units absent entirely (legacy loop) -> fail-open, allow.
reset; T=$(mk_transcript 1); write_file complete S1 1
check "work_units absent (legacy loop) -> allow (fail-open)" 0 "$(run x "$(payload "$T" S1)")"

# Re-armed path: complete but re-armed (invocations 2 > marker 1), 5 work_units,
# no evals.json -> the EXISTING als_gate_loop_complete does not allow (re-armed
# breaks its condition); the NEW gate also does not fire (ALS_REARMED != 0);
# control falls through to the PRE-EXISTING stale-complete-rearmed block.
# Assert the pre-existing message fires, NOT the new evals message — proving
# the new gate doesn't shadow or duplicate the rearm-detection block.
reset; T=$(mk_transcript 2); write_file complete S1 1 S1 "$WU5"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "re-armed, 5 work_units, no evals.json -> block via PRE-EXISTING rearm gate" 2 "$code"
case "$err" in
  *"still records the previous loop as complete"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - stderr missing pre-existing rearm message: %s\n' "$err" ;;
esac
case "$err" in
  *"loop-scope evals"*) fails=$((fails+1)); printf 'FAIL - new gate message wrongly fired on re-armed path: %s\n' "$err" ;;
  *) : ;;
esac

# Session-mismatch path: 3 work_units, no evals.json, but progress.json's
# session_id doesn't match this session -> block via the PRE-EXISTING
# session_mismatch message, NOT the new "loop-scope evals" message. The new
# gate's guard condition requires ALS_SESSION = session_id, so a mismatch
# should never let it fire.
reset; T=$(mk_transcript 1); write_file complete OTHER 1 S1 "$WU3"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "session-mismatch, 3 work_units, no evals.json -> block via PRE-EXISTING session_mismatch gate" 2 "$code"
case "$err" in
  *"session_id 'OTHER' recorded inside it, but this session is 'S1'"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - stderr missing pre-existing session_mismatch message: %s\n' "$err" ;;
esac
case "$err" in
  *"loop-scope evals"*) fails=$((fails+1)); printf 'FAIL - new gate message wrongly fired on session-mismatch path: %s\n' "$err" ;;
  *) : ;;
esac

# evals.json with bare {"scope":"loop"} — no result, no tier, no
# tier_justification key at all -> UNJUSTIFIED (missing key trims to "", same
# as an explicit blank) -> block.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop"}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
check "bare {scope:loop} (no result, no tier, no tier_justification key) -> UNJUSTIFIED -> block (exit 2)" 2 "$code"

# als_read_loop_evals_result directly on the bare fixture -> UNJUSTIFIED
# (missing-key fixture, reader level, per reviewer request).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop"}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop, tier_justification key absent -> UNJUSTIFIED" "UNJUSTIFIED" "$ALS_LOOP_EVALS_RESULT"

# als_read_loop_evals_result on a GO result with tier_justification key absent
# entirely (not just blank) -> UNJUSTIFIED (per reviewer request).
d=$(mktemp -d "$TMP/loopdir.XXXX")
jq -n '{scope:"loop", result:"GO", tier:1}' > "$d/evals.json"
als_read_loop_evals_result "$d"
check "scope=loop result=GO, tier_justification key absent -> UNJUSTIFIED" "UNJUSTIFIED" "$ALS_LOOP_EVALS_RESULT"

# e2e: UNJUSTIFIED path via the guard's dedicated case branch (distinct from
# NO-GO/ABSENT). Message must name tier_justification.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:1, tier_justification:""}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "UNJUSTIFIED (tier 1, blank justification, no result) -> block (exit 2)" 2 "$code"
case "$err" in
  *"tier_justification"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - UNJUSTIFIED e2e stderr missing tier_justification mention: %s\n' "$err" ;;
esac

# e2e: tier!=0, justified, result key absent entirely -> block via the
# reader's NO-GO final-else path, same as the reader-level case above but
# through the full guard invocation.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:2, tier_justification:"probe, no result key at all"}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "e2e: tier=2 justified, result key absent -> block (exit 2, final else NO-GO)" 2 "$code"
case "$err" in
  *"$(file_dir S1)/evals.json"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - e2e final-else stderr missing loop dir path: %s\n' "$err" ;;
esac

# ── UNSTAMPED e2e (Task 1's own guard arm) ───────────────────────────────────

# (f) hand-written result:"GO", no .grading at all -> guard BLOCKS, stderr
# mentions grade-loop (the remediation the message points to).
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", result:"GO", tier:1, tier_justification:"hand-written, never graded"}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "e2e: hand-written GO, no .grading -> block (exit 2)" 2 "$code"
case "$err" in
  *"grade-loop"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - UNSTAMPED e2e stderr missing grade-loop mention: %s\n' "$err" ;;
esac
case "$err" in
  *"treat .grading as provenance, not proof against forgery"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - UNSTAMPED e2e stderr missing honesty clause: %s\n' "$err" ;;
esac

# (g) stamped GO, but a status is edited afterwards (checksum mismatch) -> blocks.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:1, tier_justification:"2 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
check "sanity: e2e stamped GO allows before tamper" 0 "$(run x "$(payload "$T" S1)")"
tmp_tamper="$(file_dir S1)/evals.json.tamper"
jq '.evals[0].status = "fail" | .result = "GO"' "$(file_dir S1)/evals.json" > "$tmp_tamper" && mv "$tmp_tamper" "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
check "e2e: stamped GO, status tampered post-stamp -> block (exit 2)" 2 "$code"

# (h) properly graded GO -> allows (same fixture pre-tamper above, re-asserted
# standalone so this case is independently pinned).
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:1, tier_justification:"2 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
check "e2e: properly graded GO -> allow" 0 "$(run x "$(payload "$T" S1)")"

# (i) stamped TIER0 -> allow; unstamped TIER0 -> block.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:0, tier_justification:"docs-only loop, no runtime behaviour", head_sha:"deadbeef", evals:[]}' > "$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
check "e2e: stamped tier-0 exemption -> allow" 0 "$(run x "$(payload "$T" S1)")"

reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", tier:0, tier_justification:"docs-only loop, never stamped"}' > "$(file_dir S1)/evals.json"
code=$(run x "$(payload "$T" S1)")
err=$(run_err x "$(payload "$T" S1)")
check "e2e: unstamped tier-0 exemption -> block (exit 2)" 2 "$code"
case "$err" in
  *"grade-loop"*) : ;;
  *) fails=$((fails+1)); printf 'FAIL - unstamped TIER0 e2e stderr missing grade-loop mention: %s\n' "$err" ;;
esac

# stop_hook_active:true short-circuit still wins over UNSTAMPED — the
# short-circuit gate (als_gate_stop_loop) runs before progress.json is even
# loaded, so it must allow regardless of what evals.json says.
reset; T=$(mk_transcript 1); write_file complete S1 1 S1 "$WU3"
jq -n '{scope:"loop", result:"GO", tier:1, tier_justification:"hand-written, never graded"}' > "$(file_dir S1)/evals.json"
check "stop_hook_active:true short-circuits UNSTAMPED -> allow" 0 "$(run x "$(payload "$T" S1 true)")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
