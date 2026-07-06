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
  tier_justification: "",
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

# ─── check 2: tier 0 with empty tier_justification ───────────────────────────
FIX_TIER0_EMPTY="$TMP/tier0_empty.json"
jq -n --arg sha "$SHA" '{
  tier: 0,
  tier_justification: "",
  head_sha: $sha,
  evals: []
}' > "$FIX_TIER0_EMPTY"
stderr_out=$(post_evals::validate_structure "$FIX_TIER0_EMPTY" 42 "$SHA" 2>&1)
check "validate_structure: tier 0 empty tier_justification → exit 1" 1 $?
[[ "$stderr_out" == *"tier 0 requires"* ]]
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

# ─── check 3: tier>=1 scripted eval with empty negative_control ─────────────
FIX_EMPTY_NC="$TMP/empty_nc.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
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
  tier_justification: "",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"fail", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_FAIL"
result=$(post_evals::compute_and_validate_result "$FIX_FAIL")
check_str "compute_and_validate_result: P0 fail → NO-GO" "NO-GO" "$result"

# ─── CLI dispatch: bare invocation prints usage, exits 1 ─────────────────────
usage_out=$(bash "$SCRIPT" 2>&1)
rc=$?
check "bare invocation: exits 1" 1 $rc
[[ "$usage_out" == *"Usage"* ]]
check "bare invocation: prints usage" 0 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
