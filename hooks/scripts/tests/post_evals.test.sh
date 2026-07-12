#!/bin/bash
# Behavioural tests for scripts/post_evals.sh
# Tests: validate_structure structural refusals + compute_and_validate_result.
set -u
SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/post_evals.sh"
source "$SCRIPT"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_str() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

SHA="deadbeef"

# ─── Step 1: well-formed tier-1 fixture → validate_structure exit 0 ──────────
FIX_OK="$TMP/ok.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log line 1"},
    {id:"e2", priority:"P0", mode:"scripted", status:"pass", cmd:"run-b", negative_control:"run-b-broken", evidence:"log line 2"}
  ]
}' > "$FIX_OK"
post_evals::validate_structure "$FIX_OK" 42 "$SHA"
check "validate_structure: well-formed tier-1 fixture → exit 0" 0 $?

# ─── check 1: file not found / invalid JSON ──────────────────────────────────
NOFILE="$TMP/does_not_exist.json"
stderr_out=$(post_evals::validate_structure "$NOFILE" 42 "$SHA" 2>&1)
check "validate_structure: missing file → exit 1" 1 $?
[[ "$stderr_out" == *"file not found or invalid JSON"* ]]
check "validate_structure: missing file → stderr mentions reason" 0 $?

INVALID_JSON="$TMP/invalid.json"
printf 'NOT JSON {{{' > "$INVALID_JSON"
stderr_out=$(post_evals::validate_structure "$INVALID_JSON" 42 "$SHA" 2>&1)
check "validate_structure: invalid JSON → exit 1" 1 $?
[[ "$stderr_out" == *"file not found or invalid JSON"* ]]
check "validate_structure: invalid JSON → stderr mentions reason" 0 $?

# ─── check 2: tier_justification required at EVERY tier (owner directive) ────
FIX_TIER0_EMPTY="$TMP/tier0_empty.json"
jq -n --arg sha "$SHA" '{
  tier: 0,
  tier_justification: "",
  head_sha: $sha,
  evals: []
}' > "$FIX_TIER0_EMPTY"
stderr_out=$(post_evals::validate_structure "$FIX_TIER0_EMPTY" 42 "$SHA" 2>&1)
check "validate_structure: tier 0 empty tier_justification → exit 1" 1 $?
[[ "$stderr_out" == *"tier 0"*"requires"*"tier_justification"* ]]
check "validate_structure: tier 0 empty tier_justification → stderr mentions reason" 0 $?

# tier-0 exemption path: non-empty tier_justification, empty evals → exit 0
FIX_TIER0_OK="$TMP/tier0_ok.json"
jq -n --arg sha "$SHA" '{
  tier: 0,
  tier_justification: "single work-unit, covered by existing test",
  head_sha: $sha,
  evals: []
}' > "$FIX_TIER0_OK"
post_evals::validate_structure "$FIX_TIER0_OK" 42 "$SHA"
check "validate_structure: tier 0 with justification, empty evals → exit 0" 0 $?
result=$(post_evals::compute_and_validate_result "$FIX_TIER0_OK")
check_str "compute_and_validate_result: tier-0 exemption → GO (vacuous)" "GO" "$result"

# tier 1 with null tier_justification → refused (this is the new behaviour;
# previously only tier 0 was checked, so this used to pass check 2 and fall
# through to later checks).
FIX_TIER1_NULL_JUST="$TMP/tier1_null_just.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: null,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_TIER1_NULL_JUST"
stderr_out=$(post_evals::validate_structure "$FIX_TIER1_NULL_JUST" 42 "$SHA" 2>&1)
check "validate_structure: tier 1 null tier_justification → exit 1" 1 $?
[[ "$stderr_out" == *"tier 1"*"requires"*"tier_justification"* ]]
check "validate_structure: tier 1 null tier_justification → stderr names tier + reason" 0 $?

# tier 2 with empty-string tier_justification → refused.
FIX_TIER2_EMPTY_JUST="$TMP/tier2_empty_just.json"
jq -n --arg sha "$SHA" '{
  tier: 2,
  tier_justification: "",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_TIER2_EMPTY_JUST"
stderr_out=$(post_evals::validate_structure "$FIX_TIER2_EMPTY_JUST" 42 "$SHA" 2>&1)
check "validate_structure: tier 2 empty tier_justification → exit 1" 1 $?
[[ "$stderr_out" == *"tier 2"*"requires"*"tier_justification"* ]]
check "validate_structure: tier 2 empty tier_justification → stderr names tier + reason" 0 $?

# tier 2 with whitespace-only tier_justification → still refused (must not
# just be non-empty string, must be non-blank).
FIX_TIER2_WHITESPACE_JUST="$TMP/tier2_whitespace_just.json"
jq -n --arg sha "$SHA" '{
  tier: 2,
  tier_justification: "   ",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_TIER2_WHITESPACE_JUST"
stderr_out=$(post_evals::validate_structure "$FIX_TIER2_WHITESPACE_JUST" 42 "$SHA" 2>&1)
check "validate_structure: tier 2 whitespace-only tier_justification → exit 1" 1 $?
[[ "$stderr_out" == *"tier 2"*"requires"*"tier_justification"* ]]
check "validate_structure: tier 2 whitespace-only tier_justification → stderr names tier + reason" 0 $?

# tier>=1 with tier_justification KEY ABSENT entirely (not just blank) →
# refused, same as an explicit blank (reviewer request: missing-key fixture).
FIX_TIER1_NO_KEY="$TMP/tier1_no_key.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_TIER1_NO_KEY"
stderr_out=$(post_evals::validate_structure "$FIX_TIER1_NO_KEY" 42 "$SHA" 2>&1)
check "validate_structure: tier 1, tier_justification key absent → exit 1" 1 $?
[[ "$stderr_out" == *"tier 1"*"requires"*"tier_justification"* ]]
check "validate_structure: tier 1, tier_justification key absent → stderr names tier + reason" 0 $?

# tier key ALSO absent (alongside tier_justification) → the message's tier
# interpolation must render a placeholder, not a blank "tier  requires...".
FIX_NO_TIER_NO_JUST="$TMP/no_tier_no_just.json"
jq -n --arg sha "$SHA" '{
  head_sha: $sha,
  evals: []
}' > "$FIX_NO_TIER_NO_JUST"
stderr_out=$(post_evals::validate_structure "$FIX_NO_TIER_NO_JUST" 42 "$SHA" 2>&1)
check "validate_structure: tier key absent, tier_justification key absent → exit 1" 1 $?
[[ "$stderr_out" == *"tier <unset> requires"*"tier_justification"* ]]
check "validate_structure: tier key absent → stderr renders <unset> placeholder, not blank" 0 $?

# non-string tier_justification (a number) → jq's gsub errors on a non-string
# operand ("number (42) cannot be matched, as it is not a string"), so the
# $(...) capture is empty and check 2's blank-justification branch fires →
# refused, fail-closed. Pinned here so a future trim rewrite can't silently
# start accepting non-string values (reviewer request).
FIX_NUMERIC_JUST="$TMP/numeric_just.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: 42,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_NUMERIC_JUST"
stderr_out=$(post_evals::validate_structure "$FIX_NUMERIC_JUST" 42 "$SHA" 2>&1)
check "validate_structure: numeric tier_justification (42) → exit 1 (jq type error, fail-closed)" 1 $?
[[ "$stderr_out" == *"tier 1"*"requires"*"tier_justification"* ]]
check "validate_structure: numeric tier_justification → stderr names tier + reason" 0 $?

# tier 1 with a real justification string → passes check 2 (falls through to
# later structural checks, which this fixture also satisfies, so exit 0).
FIX_TIER1_REAL_JUST="$TMP/tier1_real_just.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_TIER1_REAL_JUST"
post_evals::validate_structure "$FIX_TIER1_REAL_JUST" 42 "$SHA"
check "validate_structure: tier 1 with real justification → exit 0" 0 $?

# ─── check 3: tier>=1 scripted eval with empty negative_control ─────────────
FIX_EMPTY_NC="$TMP/empty_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"", evidence:"log"}
  ]
}' > "$FIX_EMPTY_NC"
stderr_out=$(post_evals::validate_structure "$FIX_EMPTY_NC" 42 "$SHA" 2>&1)
check "validate_structure: tier>=1 scripted eval empty negative_control → exit 1" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"empty negative_control"* ]]
check "validate_structure: empty negative_control → stderr names id + reason" 0 $?

# ─── check 4: negative_control textually identical to cmd ───────────────────
FIX_IDENTICAL_NC="$TMP/identical_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a", evidence:"log"}
  ]
}' > "$FIX_IDENTICAL_NC"
stderr_out=$(post_evals::validate_structure "$FIX_IDENTICAL_NC" 42 "$SHA" 2>&1)
check "validate_structure: negative_control identical to cmd → exit 1" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"identical to cmd"* ]]
check "validate_structure: identical negative_control → stderr names id + reason" 0 $?

# ─── check 4 (hardened): whitespace-normalised comparison ────────────────────
# Trailing-space variant: negative_control differs from cmd only by trailing
# whitespace — still the same command, must be rejected.
FIX_TRAILING_SPACE="$TMP/trailing_space_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a  ", evidence:"log"}
  ]
}' > "$FIX_TRAILING_SPACE"
stderr_out=$(post_evals::validate_structure "$FIX_TRAILING_SPACE" 42 "$SHA" 2>&1)
check "validate_structure: negative_control differs from cmd only by trailing space → exit 1" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"identical to cmd"* ]]
check "validate_structure: trailing-space variant → stderr names id + reason" 0 $?

# ─── check 4 (hardened): "true; cmd" wrapper rejected ────────────────────────
FIX_TRUE_WRAP="$TMP/true_wrap_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"true; run-a", evidence:"log"}
  ]
}' > "$FIX_TRUE_WRAP"
stderr_out=$(post_evals::validate_structure "$FIX_TRUE_WRAP" 42 "$SHA" 2>&1)
check "validate_structure: negative_control='true; cmd' wrapper → exit 1 (vacuous control)" 1 $?
[[ "$stderr_out" == *"e1"* ]]
check "validate_structure: 'true; cmd' wrapper → stderr names id" 0 $?

# ─── check 4 (hardened): echo-wrap rejected ──────────────────────────────────
FIX_ECHO_WRAP="$TMP/echo_wrap_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"echo x && run-a", evidence:"log"}
  ]
}' > "$FIX_ECHO_WRAP"
stderr_out=$(post_evals::validate_structure "$FIX_ECHO_WRAP" 42 "$SHA" 2>&1)
check "validate_structure: negative_control='echo x && cmd' wrapper → exit 1 (vacuous control)" 1 $?
[[ "$stderr_out" == *"e1"* ]]
check "validate_structure: echo-wrap wrapper → stderr names id" 0 $?

# ─── check 4 (hardened): legitimately different control still accepted ──────
FIX_LEGIT_DIFFERENT="$TMP/legit_different_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"break-the-fixture-under-test", evidence:"log"}
  ]
}' > "$FIX_LEGIT_DIFFERENT"
post_evals::validate_structure "$FIX_LEGIT_DIFFERENT" 42 "$SHA"
check "validate_structure: legitimately different negative_control (different command) → exit 0" 0 $?

# ─── check 5: P0 eval with empty evidence ────────────────────────────────────
FIX_EMPTY_EVIDENCE="$TMP/empty_evidence.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:""}
  ]
}' > "$FIX_EMPTY_EVIDENCE"
stderr_out=$(post_evals::validate_structure "$FIX_EMPTY_EVIDENCE" 42 "$SHA" 2>&1)
check "validate_structure: P0 eval empty evidence → exit 1" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"empty evidence"* ]]
check "validate_structure: P0 empty evidence → stderr names id + reason" 0 $?

# ─── check 6: head_sha mismatch ──────────────────────────────────────────────
stderr_out=$(post_evals::validate_structure "$FIX_OK" 42 "newsha" 2>&1)
check "validate_structure: head_sha mismatch → exit 1" 1 $?
[[ "$stderr_out" == *"$SHA"* && "$stderr_out" == *"newsha"* ]]
check "validate_structure: head_sha mismatch → stderr mentions both shas" 0 $?

# ─── check 7: tier >= 1 requires at least one P0 eval (closes vacuous-GO gap) ──
# A tier-1+ artifact with an empty .evals array or only P1 evals currently
# computes GO past every other refusal (compute_go's P0-only gate is vacuously
# satisfied when there are no P0 evals at all). This refusal closes that gap
# at the WRITER layer; eval_artifact::compute_go's pure-function semantics are
# unchanged.
FIX_TIER1_EMPTY_EVALS="$TMP/tier1_empty_evals.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: []
}' > "$FIX_TIER1_EMPTY_EVALS"
stderr_out=$(post_evals::validate_structure "$FIX_TIER1_EMPTY_EVALS" 42 "$SHA" 2>&1)
check "validate_structure: tier 1 + empty evals → exit 1 (refused)" 1 $?
[[ "$stderr_out" == *"P0"* ]]
check "validate_structure: tier 1 + empty evals → stderr names the P0 reason" 0 $?

FIX_TIER1_ONLY_P1="$TMP/tier1_only_p1.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P1", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_TIER1_ONLY_P1"
stderr_out=$(post_evals::validate_structure "$FIX_TIER1_ONLY_P1" 42 "$SHA" 2>&1)
check "validate_structure: tier 1 + only-P1 evals → exit 1 (refused)" 1 $?
[[ "$stderr_out" == *"P0"* ]]
check "validate_structure: tier 1 + only-P1 evals → stderr names the P0 reason" 0 $?

# tier 0 + empty evals is the exemption path — must still pass (already
# covered by FIX_TIER0_OK above; re-assert here to pin it against check 7).
post_evals::validate_structure "$FIX_TIER0_OK" 42 "$SHA"
check "validate_structure: tier 0 + empty evals → exit 0 (exemption unaffected by check 7)" 0 $?

# ─── ordering: check 2 fires before check 3 (tier 0 has no scripted evals to fail check 3) ──
# (implicitly proven by FIX_TIER0_OK passing above; explicit ordering test below)
FIX_ORDER="$TMP/order.json"
jq -n --arg sha "$SHA" '{
  tier: 0,
  tier_justification: "",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"", evidence:""}
  ]
}' > "$FIX_ORDER"
stderr_out=$(post_evals::validate_structure "$FIX_ORDER" 42 "$SHA" 2>&1)
check "validate_structure: tier-0 check fires before negative_control/evidence checks" 1 $?
[[ "$stderr_out" == *"tier 0 requires"* ]]
check "validate_structure: order proof — stderr is the tier-0 message, not later checks" 0 $?

# ─── compute_and_validate_result ─────────────────────────────────────────────
result=$(post_evals::compute_and_validate_result "$FIX_OK")
check_str "compute_and_validate_result: all-pass fixture → GO" "GO" "$result"

FIX_FAIL="$TMP/fail.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"fail", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_FAIL"
result=$(post_evals::compute_and_validate_result "$FIX_FAIL")
check_str "compute_and_validate_result: P0 fail → NO-GO" "NO-GO" "$result"

# ─── grade-loop: neutral loop-scope grading + stamp ──────────────────────────
# Loop-scope fixtures carry no PR number; grade-loop's structural validation
# is the loop variant (no pr arg, check 6 becomes "head_sha non-blank").

# (a) all-P0-pass loop fixture -> result=GO, graded_at set, grading.checksum
# matches eval_artifact::grading_checksum recomputed independently.
FIX_LOOP_GO="$TMP/loop_go.json"
jq -n --arg sha "$SHA" '{
  scope: "loop",
  tier: 1,
  tier_justification: "3 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log 1"},
    {id:"e2", priority:"P0", mode:"scripted", status:"pass", cmd:"run-b", negative_control:"run-b-broken", evidence:"log 2"}
  ]
}' > "$FIX_LOOP_GO"
grade_out=$(post_evals::grade_loop "$FIX_LOOP_GO")
check "grade_loop: all-P0-pass -> exit 0" 0 $?
check_str "grade_loop: all-P0-pass -> echoes GO" "GO" "$grade_out"
check_str "grade_loop: all-P0-pass -> writes .result=GO" "GO" "$(jq -r '.result' "$FIX_LOOP_GO")"
[[ -n "$(jq -r '.graded_at // ""' "$FIX_LOOP_GO")" ]]
check "grade_loop: all-P0-pass -> .graded_at is set" 0 $?
check_str "grade_loop: all-P0-pass -> .grading.by is post_evals.sh grade-loop" "post_evals.sh grade-loop" "$(jq -r '.grading.by // ""' "$FIX_LOOP_GO")"
written_checksum=$(jq -r '.grading.checksum // ""' "$FIX_LOOP_GO")
[[ -n "$written_checksum" ]]
check "grade_loop: all-P0-pass -> .grading.checksum is non-empty" 0 $?
expected_checksum=$(eval_artifact::grading_checksum "$FIX_LOOP_GO" "GO")
check_str "grade_loop: written checksum matches independent recomputation" "$expected_checksum" "$written_checksum"

# (b) P0-fail loop fixture -> NO-GO, still stamped.
FIX_LOOP_NOGO="$TMP/loop_nogo.json"
jq -n --arg sha "$SHA" '{
  scope: "loop",
  tier: 1,
  tier_justification: "3 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"fail", cmd:"run-a", negative_control:"run-a-broken", evidence:"log 1"}
  ]
}' > "$FIX_LOOP_NOGO"
grade_out=$(post_evals::grade_loop "$FIX_LOOP_NOGO")
check "grade_loop: P0-fail -> exit 0 (successful grade, even NO-GO)" 0 $?
check_str "grade_loop: P0-fail -> echoes NO-GO" "NO-GO" "$grade_out"
check_str "grade_loop: P0-fail -> writes .result=NO-GO" "NO-GO" "$(jq -r '.result' "$FIX_LOOP_NOGO")"
check_str "grade_loop: P0-fail -> .grading.by still stamped" "post_evals.sh grade-loop" "$(jq -r '.grading.by // ""' "$FIX_LOOP_NOGO")"

# (c) tier-0 exemption fixture (empty evals + justification) -> stamps.
FIX_LOOP_TIER0="$TMP/loop_tier0.json"
jq -n --arg sha "$SHA" '{
  scope: "loop",
  tier: 0,
  tier_justification: "docs-only loop, no runtime behaviour",
  head_sha: $sha,
  evals: []
}' > "$FIX_LOOP_TIER0"
grade_out=$(post_evals::grade_loop "$FIX_LOOP_TIER0")
check "grade_loop: tier-0 exemption -> exit 0" 0 $?
check_str "grade_loop: tier-0 exemption -> echoes GO (vacuous)" "GO" "$grade_out"
check_str "grade_loop: tier-0 exemption -> .grading.by stamped" "post_evals.sh grade-loop" "$(jq -r '.grading.by // ""' "$FIX_LOOP_TIER0")"

# (d) grade-loop refuses a fixture with blank tier_justification (reuses check 2).
FIX_LOOP_BLANK_JUST="$TMP/loop_blank_just.json"
jq -n --arg sha "$SHA" '{
  scope: "loop",
  tier: 1,
  tier_justification: "",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log 1"}
  ]
}' > "$FIX_LOOP_BLANK_JUST"
stderr_out=$(post_evals::grade_loop "$FIX_LOOP_BLANK_JUST" 2>&1)
check "grade_loop: blank tier_justification -> exit 1 (refused)" 1 $?
[[ "$stderr_out" == *"tier_justification"* ]]
check "grade_loop: blank tier_justification -> stderr mentions tier_justification" 0 $?
[[ -z "$(jq -r '.result // ""' "$FIX_LOOP_BLANK_JUST")" ]]
check "grade_loop: refused fixture -> no .result written" 0 $?

# grade-loop also refuses a fixture with a blank head_sha (loop-variant check 6).
FIX_LOOP_BLANK_SHA="$TMP/loop_blank_sha.json"
jq -n '{
  scope: "loop",
  tier: 1,
  tier_justification: "3 work-units, no irreversible surface",
  head_sha: "",
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log 1"}
  ]
}' > "$FIX_LOOP_BLANK_SHA"
stderr_out=$(post_evals::grade_loop "$FIX_LOOP_BLANK_SHA" 2>&1)
check "grade_loop: blank head_sha -> exit 1 (refused, loop variant check 6)" 1 $?
[[ "$stderr_out" == *"head_sha"* ]]
check "grade_loop: blank head_sha -> stderr mentions head_sha" 0 $?

# (e) checksum function is deterministic and changes when any status or the
# result changes.
checksum_1=$(eval_artifact::grading_checksum "$FIX_LOOP_GO" "GO")
checksum_2=$(eval_artifact::grading_checksum "$FIX_LOOP_GO" "GO")
check_str "grading_checksum: deterministic across repeated calls" "$checksum_1" "$checksum_2"

checksum_diff_result=$(eval_artifact::grading_checksum "$FIX_LOOP_GO" "NO-GO")
[[ "$checksum_1" != "$checksum_diff_result" ]]
check "grading_checksum: differs when result string changes" 0 $?

# Same evals content, but a status flipped -> checksum differs (uses FIX_LOOP_GO
# vs FIX_LOOP_NOGO, both graded above so both carry .grading/.result, but the
# checksum function only extracts {id,priority,status} from .evals, so this
# still isolates status-sensitivity from the extra fields).
checksum_go_fixture=$(eval_artifact::grading_checksum "$FIX_LOOP_GO" "GO")
checksum_nogo_fixture=$(eval_artifact::grading_checksum "$FIX_LOOP_NOGO" "GO")
[[ "$checksum_go_fixture" != "$checksum_nogo_fixture" ]]
check "grading_checksum: differs when eval statuses differ" 0 $?

# ─── CLI dispatch: bare invocation prints usage, exits 1 ─────────────────────
usage_out=$(bash "$SCRIPT" 2>&1)
rc=$?
check "bare invocation: exits 1" 1 $rc
[[ "$usage_out" == *"Usage"* ]]
check "bare invocation: prints usage" 0 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
