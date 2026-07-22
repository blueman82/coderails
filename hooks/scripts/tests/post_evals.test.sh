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

# Check 9 (validate_smoke) requires every pr-scope tier>=1 scripted eval to
# carry recorded freeze-time smoke evidence. Fixtures that are EXPECTED TO
# PASS validate_structure therefore need it; fixtures that are expected to be
# refused by an earlier check do not (first failure wins, so they never reach
# check 9). This is the canonical shape: cmd observed failing for a content
# reason (the feature isn't built at freeze — see freeze-before-build), and
# the negative control observed failing likewise.
# Strict JSON: --argjson rejects jq's unquoted-key object syntax.
SMOKE_OK='{"cmd_exit": 1, "negative_control_exit": 1, "cmd_output": "1 test failed", "negative_control_output": "assertion failed"}'

# ─── Step 1: well-formed tier-1 fixture → validate_structure exit 0 ──────────
FIX_OK="$TMP/ok.json"
jq -n --arg sha "$SHA" --argjson smoke "$SMOKE_OK" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log line 1", smoke: $smoke},
    {id:"e2", priority:"P0", mode:"scripted", status:"pass", cmd:"run-b", negative_control:"run-b-broken", evidence:"log line 2", smoke: $smoke}
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
jq -n --arg sha "$SHA" --argjson smoke "$SMOKE_OK" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log", smoke: $smoke}
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
jq -n --arg sha "$SHA" --argjson smoke "$SMOKE_OK" '{
  tier: 1,
  tier_justification: "2 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"break-the-fixture-under-test", evidence:"log", smoke: $smoke}
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

# ─── check 8: freeze-before-build (frozen_sha must precede the branch) ────────
# The task-evals skill stamps frozen_sha "before implementation starts", but
# nothing verified it — an evals.json could be authored after the code and
# backdated by pointing frozen_sha at any commit. This refusal makes the rule
# mechanical: frozen_sha must be an ancestor of the branch's merge-base with
# the default branch, i.e. a commit that already existed before the branch's
# own implementation commits.
#
# Fixtures are real throwaway git repos, because the check is git ancestry —
# a stubbed git would test the stub, not the rule.

# Build a repo with: base commit (BASE), then two branch commits (IMPL).
FREEZE_REPO="$TMP/freeze_repo"
mkdir -p "$FREEZE_REPO"
(
  cd "$FREEZE_REPO" || exit 1
  git init -q -b main
  git config user.email t@t; git config user.name t
  echo base > f.txt; git add f.txt; git commit -qm base
  git checkout -qb feature
  echo impl1 >> f.txt; git commit -qam impl1
  echo impl2 >> f.txt; git commit -qam impl2
) >/dev/null 2>&1
FREEZE_BASE=$(git -C "$FREEZE_REPO" rev-parse main)
FREEZE_IMPL=$(git -C "$FREEZE_REPO" rev-parse HEAD)

# 8a: compliant — frozen at the base commit, before any implementation.
FIX_FREEZE_OK="$FREEZE_REPO/evals_ok.json"
jq -n --arg sha "$SHA" --arg fsha "$FREEZE_BASE" --argjson smoke "$SMOKE_OK" '{
  tier: 1,
  tier_justification: "1 work-unit",
  frozen_sha: $fsha,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log", smoke: $smoke}
  ]
}' > "$FIX_FREEZE_OK"
post_evals::validate_structure "$FIX_FREEZE_OK" 42 "$SHA"
check "validate_structure: frozen_sha at branch base → exit 0 (compliant)" 0 $?

# 8b: violation — frozen at one of the branch's own implementation commits,
# i.e. the evals were written after the code. This is the defect.
FIX_FREEZE_LATE="$FREEZE_REPO/evals_late.json"
jq -n --arg sha "$SHA" --arg fsha "$FREEZE_IMPL" '{
  tier: 1,
  tier_justification: "1 work-unit",
  frozen_sha: $fsha,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_FREEZE_LATE"
stderr_out=$(post_evals::validate_structure "$FIX_FREEZE_LATE" 42 "$SHA" 2>&1)
check "validate_structure: frozen_sha at a branch commit → exit 1 (froze after building)" 1 $?
[[ "$stderr_out" == *"frozen_sha"* ]]
check "validate_structure: late freeze → stderr names frozen_sha" 0 $?

# 8c: disclosed late freeze passes. PR #54 set the precedent — evals authored
# after implementation, disclosed in prose rather than backdated. The gate
# enforces honesty, not the impossible. The disclosure must be explicit text,
# not a bare boolean anyone could flip silently.
FIX_FREEZE_DISCLOSED="$FREEZE_REPO/evals_disclosed.json"
jq -n --arg sha "$SHA" --arg fsha "$FREEZE_IMPL" --argjson smoke "$SMOKE_OK" '{
  tier: 1,
  tier_justification: "1 work-unit. Disclosed process gap: this evals.json was authored after implementation, not before (violates freeze-before-build). Authored at the real timestamp, not backdated.",
  frozen_sha: $fsha,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log", smoke: $smoke}
  ]
}' > "$FIX_FREEZE_DISCLOSED"
post_evals::validate_structure "$FIX_FREEZE_DISCLOSED" 42 "$SHA"
check "validate_structure: disclosed late freeze → exit 0 (escape hatch)" 0 $?

# 8d: the disclosure must actually say something about freezing. A generic
# justification mentioning neither must not open the hatch.
FIX_FREEZE_FAKE_DISCLOSURE="$FREEZE_REPO/evals_fake.json"
jq -n --arg sha "$SHA" --arg fsha "$FREEZE_IMPL" '{
  tier: 1,
  tier_justification: "1 work-unit, no irreversible surface",
  frozen_sha: $fsha,
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_FREEZE_FAKE_DISCLOSURE"
post_evals::validate_structure "$FIX_FREEZE_FAKE_DISCLOSURE" 42 "$SHA" 2>/dev/null
check "validate_structure: late freeze without disclosure wording → exit 1" 1 $?

# 8e: an unresolvable frozen_sha fails closed — it must not fall through to a
# pass just because git cannot answer.
FIX_FREEZE_BOGUS="$FREEZE_REPO/evals_bogus.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit",
  frozen_sha: "0000000000000000000000000000000000000000",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_FREEZE_BOGUS"
stderr_out=$(post_evals::validate_structure "$FIX_FREEZE_BOGUS" 42 "$SHA" 2>&1)
check "validate_structure: unresolvable frozen_sha → exit 1 (fail closed)" 1 $?

# 8f: back-compat — an evals.json with no frozen_sha at all is unchanged by
# this check. Every fixture above this block omits the field, and the loop
# scope never carries one, so a hard failure here would break existing callers.
post_evals::validate_structure "$FIX_OK" 42 "$SHA"
check "validate_structure: absent frozen_sha → unaffected (back-compat)" 0 $?

# 8f-bis: a violating file must not pass merely because jq is unavailable.
# Without this, the check fails OPEN: `jq` returning nothing looks exactly like
# "no frozen_sha field", which is the skip path. A gate that silently passes
# when its own tooling is missing is the vacuous check this whole layer exists
# to prevent.
# PATH is narrowed to an empty dir inside a subshell — jq lives in /usr/bin on
# most hosts, so trimming to system paths would not actually remove it. A
# var-assignment prefix would not apply to a shell function either, hence the
# explicit subshell.
EMPTY_BIN="$TMP/empty_bin"
mkdir -p "$EMPTY_BIN"
stderr_out=$(PATH="$EMPTY_BIN"; post_evals::validate_freeze "$FIX_FREEZE_LATE" 2>&1)
check "validate_freeze: jq unavailable → exit 1 (must not fail open)" 1 $?
[[ "$stderr_out" == *"jq"* ]]
check "validate_freeze: jq unavailable → stderr names jq" 0 $?

# 8g: loop scope is out of enforcement scope for this check — loop-scope
# artifacts live outside any repo and have no branch to compare against.
FIX_FREEZE_LOOP="$FREEZE_REPO/evals_loop.json"
jq -n --arg fsha "$FREEZE_IMPL" '{
  tier: 1,
  tier_justification: "1 work-unit",
  frozen_sha: $fsha,
  head_sha: "abc123",
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_FREEZE_LOOP"
post_evals::validate_structure "$FIX_FREEZE_LOOP" "" "" "loop"
check "validate_structure: loop scope skips the freeze check" 0 $?

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

# grade_loop: a failed write (target directory read-only, so jq's redirect
# fails) must be reported as a failure — exit 1, stderr naming the file — not
# silently echoed as GO/exit 0. Original file must be left untouched.
FIX_WRITE_FAIL_DIR="$TMP/readonly_dir"
mkdir -p "$FIX_WRITE_FAIL_DIR"
FIX_WRITE_FAIL="$FIX_WRITE_FAIL_DIR/loop.json"
jq -n --arg sha "$SHA" '{
  scope: "loop",
  tier: 1,
  tier_justification: "3 work-units, no irreversible surface",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log 1"}
  ]
}' > "$FIX_WRITE_FAIL"
before_content=$(cat "$FIX_WRITE_FAIL")
chmod 555 "$FIX_WRITE_FAIL_DIR"
stderr_out=$(post_evals::grade_loop "$FIX_WRITE_FAIL" 2>&1)
rc=$?
chmod 755 "$FIX_WRITE_FAIL_DIR"
check "grade_loop: write failure (read-only dir) -> exit 1, not 0" 1 $rc
[[ "$stderr_out" == *"grade-loop"* && "$stderr_out" == *"$FIX_WRITE_FAIL"* ]]
check "grade_loop: write failure -> stderr names the failure and the file" 0 $?
after_content=$(cat "$FIX_WRITE_FAIL")
check_str "grade_loop: write failure -> original file left untouched" "$before_content" "$after_content"
[[ -z "$(jq -r '.grading // empty' "$FIX_WRITE_FAIL")" ]]
check "grade_loop: write failure -> no .grading present" 0 $?

# ─── grade_loop: regrade-on-amendment backstop ───────────────────────────────
# Post-verdict amendments require a fresh-grader attestation (regraded_by) on
# each new amendment; otherwise grade-loop refuses and writes nothing.

# (1) first grade stamps amendments_at_grade: 0 with no amendments.
FIX_AAG0="$TMP/aag0.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_AAG0"
post_evals::grade_loop "$FIX_AAG0" >/dev/null
check "grade_loop backstop: first grade, no amendments -> exit 0" 0 $?
check_str "grade_loop backstop: amendments_at_grade stamped 0" "0" "$(jq -r '.grading.amendments_at_grade' "$FIX_AAG0")"

# (1b) first grade with 2 pre-grade amendments stamps 2 (rule 1's escape valve, no gate).
FIX_AAG2="$TMP/aag2.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ],
  amendments: [ {eval:"e1", when:"2026-07-12T00:00:00Z", why:"pre-grade fix a"},
                {eval:"e1", when:"2026-07-12T00:01:00Z", why:"pre-grade fix b"} ]
}' > "$FIX_AAG2"
post_evals::grade_loop "$FIX_AAG2" >/dev/null
check "grade_loop backstop: first grade, 2 pre-grade amendments -> exit 0" 0 $?
check_str "grade_loop backstop: amendments_at_grade stamped 2" "2" "$(jq -r '.grading.amendments_at_grade' "$FIX_AAG2")"

# (2) re-grade with unchanged amendment count grades normally (status change
# alone is not gated — a fresh grader legitimately updates statuses).
jq '.evals[0].status = "fail"' "$FIX_AAG0" > "$FIX_AAG0.tmp" && mv "$FIX_AAG0.tmp" "$FIX_AAG0"
grade_out=$(post_evals::grade_loop "$FIX_AAG0")
check "grade_loop backstop: re-grade, amendments unchanged -> exit 0" 0 $?
check_str "grade_loop backstop: re-grade computes NO-GO from statuses" "NO-GO" "$grade_out"

# (3) NEGATIVE CONTROL for the backstop: post-verdict amendment WITHOUT
# regraded_by -> refused, exit 1, file byte-identical.
jq '.amendments = [ {eval:"e1", when:"2026-07-12T01:00:00Z", why:"post-verdict fix"} ] | .evals[0].status = "pass"' \
  "$FIX_AAG0" > "$FIX_AAG0.tmp" && mv "$FIX_AAG0.tmp" "$FIX_AAG0"
before_content=$(cat "$FIX_AAG0")
stderr_out=$(post_evals::grade_loop "$FIX_AAG0" 2>&1)
check "grade_loop backstop: post-verdict amendment w/o regraded_by -> exit 1" 1 $?
[[ "$stderr_out" == *"regraded_by"* ]]
check "grade_loop backstop: refusal stderr names regraded_by" 0 $?
check_str "grade_loop backstop: refused file left byte-identical" "$before_content" "$(cat "$FIX_AAG0")"

# (4) same amendment WITH non-blank regraded_by -> grades, restamps count.
jq '.amendments[0].regraded_by = "fresh grader: verify-l2-regrade agent"' \
  "$FIX_AAG0" > "$FIX_AAG0.tmp" && mv "$FIX_AAG0.tmp" "$FIX_AAG0"
grade_out=$(post_evals::grade_loop "$FIX_AAG0")
check "grade_loop backstop: post-verdict amendment with regraded_by -> exit 0" 0 $?
check_str "grade_loop backstop: attested re-grade echoes GO" "GO" "$grade_out"
check_str "grade_loop backstop: amendments_at_grade restamped to 1" "1" "$(jq -r '.grading.amendments_at_grade' "$FIX_AAG0")"

# (4b) restamp checksum integrity: the written .grading.checksum equals an
# independent recomputation via eval_artifact::grading_checksum.
written_checksum_aag0=$(jq -r '.grading.checksum // ""' "$FIX_AAG0")
expected_checksum_aag0=$(eval_artifact::grading_checksum "$FIX_AAG0" "GO")
check_str "grade_loop backstop: restamp checksum matches independent recomputation" "$expected_checksum_aag0" "$written_checksum_aag0"

# (5) blank regraded_by is not an attestation.
jq '.amendments += [ {eval:"e1", when:"2026-07-12T02:00:00Z", why:"another post-verdict fix", regraded_by: "   "} ]' \
  "$FIX_AAG0" > "$FIX_AAG0.tmp" && mv "$FIX_AAG0.tmp" "$FIX_AAG0"
post_evals::grade_loop "$FIX_AAG0" 2>/dev/null
check "grade_loop backstop: blank regraded_by -> exit 1 (refused)" 1 $?

# (6) prior grading object WITHOUT amendments_at_grade (old writer) reads as 0.
FIX_OLD="$TMP/old_writer.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_OLD"
post_evals::grade_loop "$FIX_OLD" >/dev/null
jq 'del(.grading.amendments_at_grade) | .amendments = [ {eval:"e1", when:"2026-07-12T03:00:00Z", why:"post-verdict, old stamp"} ]' \
  "$FIX_OLD" > "$FIX_OLD.tmp" && mv "$FIX_OLD.tmp" "$FIX_OLD"
post_evals::grade_loop "$FIX_OLD" 2>/dev/null
check "grade_loop backstop: old stamp w/o amendments_at_grade treated as 0 -> refused" 1 $?

# (7) malformed amendments fail CLOSED: a non-object amendment entry (the
# shorthand a negligent orchestrator writes) refuses instead of grading.
FIX_MALF="$TMP/malformed_amend.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_MALF"
post_evals::grade_loop "$FIX_MALF" >/dev/null
jq '.amendments = ["fixed e1 config path"]' "$FIX_MALF" > "$FIX_MALF.tmp" && mv "$FIX_MALF.tmp" "$FIX_MALF"
post_evals::grade_loop "$FIX_MALF" 2>/dev/null
check "grade_loop backstop: non-object amendment entry -> exit 1 (fail closed)" 1 $?

# (8) disarm-by-regeneration: del(.grading) alone does not re-arm the
# first-grade path — grade residue (.graded_at/.result) still trips the gate.
FIX_REGEN="$TMP/regen.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_REGEN"
post_evals::grade_loop "$FIX_REGEN" >/dev/null
jq 'del(.grading) | .amendments = [ {eval:"e1", when:"2026-07-12T04:00:00Z", why:"post-verdict, stamp shed"} ]' \
  "$FIX_REGEN" > "$FIX_REGEN.tmp" && mv "$FIX_REGEN.tmp" "$FIX_REGEN"
post_evals::grade_loop "$FIX_REGEN" 2>/dev/null
check "grade_loop backstop: del(.grading) with grade residue -> still refused" 1 $?

# (9) scalar-number amendments (not an array) fail-open under jq's fractional
# `length` semantics unless explicitly guarded — refuse instead of grading.
FIX_SCALAR="$TMP/scalar_amend.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_SCALAR"
post_evals::grade_loop "$FIX_SCALAR" >/dev/null
jq '.amendments = 2.5' "$FIX_SCALAR" > "$FIX_SCALAR.tmp" && mv "$FIX_SCALAR.tmp" "$FIX_SCALAR"
post_evals::grade_loop "$FIX_SCALAR" 2>/dev/null
check "grade_loop backstop: scalar-number amendments -> exit 1 (refused)" 1 $?

# (10) mixed batch smuggling: one attested + one unattested amendment in the
# SAME post-verdict write must still refuse (an ALL-unattested predicate
# mutation would let this slip through since not every entry is unattested).
FIX_MIXED="$TMP/mixed_batch.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_MIXED"
post_evals::grade_loop "$FIX_MIXED" >/dev/null
jq '.amendments = [
      {eval:"e1", when:"2026-07-12T05:00:00Z", why:"post-verdict fix a", regraded_by:"fresh grader run"},
      {eval:"e1", when:"2026-07-12T05:01:00Z", why:"post-verdict fix b"}
    ]' "$FIX_MIXED" > "$FIX_MIXED.tmp" && mv "$FIX_MIXED.tmp" "$FIX_MIXED"
before_content_mixed=$(cat "$FIX_MIXED")
post_evals::grade_loop "$FIX_MIXED" 2>/dev/null
check "grade_loop backstop: mixed attested/unattested batch -> exit 1 (refused)" 1 $?
check_str "grade_loop backstop: mixed batch refused file left byte-identical" "$before_content_mixed" "$(cat "$FIX_MIXED")"

# (11) slice-boundary escape valve: FIX_AAG2 already carries amendments_at_grade
# stamped 2 with two pre-grade (exempt) unattested amendments — reused as-is,
# not re-created. Appending ONE attested amendment brings the count to 3 > 2;
# grade-loop must succeed because the slice starts at the stamped index 2, so
# the two old unattested entries are exempt from the attestation check.
jq '.amendments += [ {eval:"e1", when:"2026-07-12T06:00:00Z", why:"post-verdict fix", regraded_by:"fresh grader run three"} ]' \
  "$FIX_AAG2" > "$FIX_AAG2.tmp" && mv "$FIX_AAG2.tmp" "$FIX_AAG2"
grade_out=$(post_evals::grade_loop "$FIX_AAG2")
check "grade_loop backstop: slice-boundary escape valve -> exit 0" 0 $?
check_str "grade_loop backstop: amendments_at_grade restamped to 3" "3" "$(jq -r '.grading.amendments_at_grade' "$FIX_AAG2")"

# (12) non-string regraded_by (e.g. a number) does not count as attestation —
# jq's `and` short-circuits so a non-string never reaches `test`.
FIX_NONSTR="$TMP/nonstring_regraded_by.json"
jq -n --arg sha "$SHA" '{
  scope: "loop", tier: 1, tier_justification: "1 work-unit, scripted change", head_sha: $sha,
  evals: [ {id:"e1", priority:"P0", mode:"scripted", status:"pass", cmd:"run-a", negative_control:"run-a-broken", evidence:"log"} ]
}' > "$FIX_NONSTR"
post_evals::grade_loop "$FIX_NONSTR" >/dev/null
jq '.amendments = [ {eval:"e1", when:"2026-07-12T07:00:00Z", why:"post-verdict fix", regraded_by: 123} ]' \
  "$FIX_NONSTR" > "$FIX_NONSTR.tmp" && mv "$FIX_NONSTR.tmp" "$FIX_NONSTR"
post_evals::grade_loop "$FIX_NONSTR" 2>/dev/null
check "grade_loop backstop: non-string regraded_by (number) -> exit 1 (refused)" 1 $?

# ─── CLI dispatch: bare invocation prints usage, exits 1 ─────────────────────
usage_out=$(bash "$SCRIPT" 2>&1)
rc=$?
check "bare invocation: exits 1" 1 $rc
[[ "$usage_out" == *"Usage"* ]]
check "bare invocation: prints usage" 0 $?

# ─── validate_embed: posted-body embedded-artifact contract ─────────────────
# Task 2's daemon extracts the embedded evals.json from the posted PR comment
# to judge it; this validator guarantees the comment body actually carries
# exactly one parseable fenced JSON block that agrees with the artifact.
# tier is read from the BODY'S OWN marker line (what the daemon triages on),
# never from an argument — a body whose marker says tier=0 but whose block
# disagrees is exactly the incoherence this check exists to catch.

FIX_EMBED_SRC="$TMP/embed_src.json"
jq -n --arg sha "$SHA" '{
  schema_version: 1,
  scope: "pr",
  task_ref: "192",
  tier: 0,
  tier_justification: "single work-unit, covered by existing test",
  head_sha: $sha,
  evals: []
}' > "$FIX_EMBED_SRC"

mk_body() { # marker_tier json_block_or_empty num_blocks
  local marker_tier="$1" block="$2" num_blocks="${3:-1}"
  local out="$TMP/body_$$_$RANDOM.md"
  {
    printf '<!-- coderails-eval-summary v1 pr=192 head_sha=%s result=GO tier=%s -->\n' "$SHA" "$marker_tier"
    printf '## Eval summary\n\nAll P0 evals pass.\n'
    local i
    for ((i=0; i<num_blocks; i++)); do
      printf '\n```json\n%s\n```\n' "$block"
    done
  } > "$out"
  printf '%s' "$out"
}

# (1) tier-0 body WITHOUT any fenced block → rc 1, named message.
BODY_NO_BLOCK=$(mk_body "0" "" 0)
stderr_out=$(post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_NO_BLOCK" 2>&1)
check "validate_embed: tier-0 body without fenced block → exit 1" 1 $?
[[ "$stderr_out" == *"fenced json block"* || "$stderr_out" == *"json block"* ]]
check "validate_embed: no block → stderr names the missing-block reason" 0 $?

# (2) tier-0 body with exactly one MATCHING block → rc 0.
MATCHING_BLOCK=$(jq -c . "$FIX_EMBED_SRC")
BODY_MATCH=$(mk_body "0" "$MATCHING_BLOCK" 1)
post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_MATCH"
check "validate_embed: tier-0 body with matching block → exit 0" 0 $?

# (3) tier-1 body WITHOUT a block → rc 0 (not required at tier 1/2).
BODY_TIER1_NO_BLOCK=$(mk_body "1" "" 0)
post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_TIER1_NO_BLOCK"
check "validate_embed: tier-1 body without block → exit 0 (not required)" 0 $?

# (4) SO-33 control: two fenced json blocks → rc 1, named (proves the
# validator actually counts blocks rather than vacuously finding "a" block).
BODY_TWO_BLOCKS=$(mk_body "0" "$MATCHING_BLOCK" 2)
stderr_out=$(post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_TWO_BLOCKS" 2>&1)
check "validate_embed: two fenced json blocks → exit 1" 1 $?
[[ "$stderr_out" == *"exactly one"* ]]
check "validate_embed: two blocks → stderr names the exactly-one reason" 0 $?

# (5) SO-33 control: one block present but it does NOT parse as JSON → rc 1,
# named (proves the validator actually jq-parses the block, not just counts
# fences).
BODY_MALFORMED=$(mk_body "0" "NOT JSON {{{" 1)
stderr_out=$(post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_MALFORMED" 2>&1)
check "validate_embed: malformed (non-parsing) block → exit 1" 1 $?
[[ "$stderr_out" == *"parse"* ]]
check "validate_embed: malformed block → stderr names the parse failure" 0 $?

# (6) SO-33 control: block parses but its .tier disagrees with the marker's
# tier → rc 1, named (proves the validator compares tier, not just presence).
WRONG_TIER_BLOCK=$(jq -c '.tier = 2' "$FIX_EMBED_SRC")
BODY_WRONG_TIER=$(mk_body "0" "$WRONG_TIER_BLOCK" 1)
stderr_out=$(post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_WRONG_TIER" 2>&1)
check "validate_embed: block .tier disagrees with marker tier → exit 1" 1 $?
[[ "$stderr_out" == *"tier"* ]]
check "validate_embed: wrong tier → stderr names the tier mismatch" 0 $?

# (7) SO-33 control: block parses, tier matches, but .task_ref disagrees with
# the source evals.json's .task_ref → rc 1, named.
WRONG_REF_BLOCK=$(jq -c '.task_ref = "999"' "$FIX_EMBED_SRC")
BODY_WRONG_REF=$(mk_body "0" "$WRONG_REF_BLOCK" 1)
stderr_out=$(post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_WRONG_REF" 2>&1)
check "validate_embed: block .task_ref disagrees with source file → exit 1" 1 $?
[[ "$stderr_out" == *"task_ref"* ]]
check "validate_embed: wrong task_ref → stderr names the task_ref mismatch" 0 $?

# (8) fail-closed: marker line unparseable (malformed/missing marker) → rc 1,
# named — proves the tier check isn't vacuously satisfied with no marker to
# compare against.
BODY_NO_MARKER="$TMP/body_no_marker.md"
{
  printf 'not a marker line at all\n'
  printf '\n```json\n%s\n```\n' "$MATCHING_BLOCK"
} > "$BODY_NO_MARKER"
stderr_out=$(post_evals::validate_embed "$FIX_EMBED_SRC" "$BODY_NO_MARKER" 2>&1)
check "validate_embed: unparseable marker line → exit 1 (fail-closed)" 1 $?
[[ "$stderr_out" == *"marker"* ]]
check "validate_embed: unparseable marker → stderr names the marker reason" 0 $?

# ═══ validate_smoke: recorded freeze-time smoke evidence ════════════════════
# Closes the gap where a frozen eval could name a command that never existed,
# or pair with a negative control that passed vacuously. Both defects survived
# the skill's prose-mandated smoke-run, because nothing recorded its result.
#
# The load-bearing constraint: check 8 (freeze-before-build) means `cmd` is
# EXPECTED to fail at freeze — the feature isn't built yet. So this gate must
# NOT require cmd to exit 0. What separates a broken cmd from a legitimately
# not-yet-passing one is the SHAPE of the outcome, not its polarity: a
# nonexistent script exits 127 (command/file not found), whereas a real
# assertion failure exits 1. The negative_control is different — it is defined
# to fail regardless of build state, so its polarity IS checkable.

SMOKE_BASE='{
  tier: 1,
  tier_justification: "1 work-unit",
  head_sha: $sha
}'

mk_smoke() { # <outfile> <cmd_rc> <nc_rc>  → tier-1 file with one smoke-carrying eval
  jq -n --arg sha "$SHA" --argjson crc "$2" --argjson nrc "$3" '{
    tier: 1,
    tier_justification: "1 work-unit",
    head_sha: $sha,
    evals: [
      {id:"e1", priority:"P0", mode:"scripted", status:"pending",
       cmd:"run-a", negative_control:"run-a-broken", evidence:"log",
       smoke: {cmd_exit: $crc, negative_control_exit: $nrc,
               cmd_output: "1 test failed", negative_control_output: "assertion failed"}}
    ]
  }' > "$1"
}

# (S1) INSTANCE 1 — a cmd naming a script that never existed. Exit 127 is
# command-not-found: the check never reached the artifact it claims to test.
# This must be refused even though 127 is non-zero and a not-yet-built feature
# also exits non-zero. Polarity cannot separate them; shape can.
FIX_SMOKE_ENOENT="$TMP/smoke_enoent.json"
mk_smoke "$FIX_SMOKE_ENOENT" 127 1
stderr_out=$(post_evals::validate_smoke "$FIX_SMOKE_ENOENT" 2>&1)
check "validate_smoke: cmd exit 127 (nonexistent script) → exit 1 [instance 1]" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"not found"* ]]
check "validate_smoke: cmd 127 → stderr names the eval and the reason" 0 $?

# (S1-bis) The same file with a REAL assertion failure (exit 1) must pass.
# This is the freeze-before-build case: feature not built, check runs fine,
# reports a genuine failure. If this fails, the gate contradicts check 8.
FIX_SMOKE_HONEST_FAIL="$TMP/smoke_honest_fail.json"
mk_smoke "$FIX_SMOKE_HONEST_FAIL" 1 1
post_evals::validate_smoke "$FIX_SMOKE_HONEST_FAIL"
check "validate_smoke: cmd exit 1 (not yet built) → exit 0 (freeze-before-build compatible)" 0 $?

# (S1-ter) A cmd that already passes at freeze is also fine — a check can
# legitimately be green if it guards an existing property.
FIX_SMOKE_PASSING="$TMP/smoke_passing.json"
mk_smoke "$FIX_SMOKE_PASSING" 0 1
post_evals::validate_smoke "$FIX_SMOKE_PASSING"
check "validate_smoke: cmd exit 0 at freeze → exit 0 (permitted)" 0 $?

# (S2) INSTANCES 2 & 3 — the negative control exited 0. Instance 2: the control
# wrote outside git, so validate_freeze SKIPPED and returned 0, which read as
# compliance. Instance 3: the "removed" jq was still on PATH, so the control
# passed for the wrong reason. Both look identical to a genuine pass and both
# are caught by requiring OBSERVED non-zero on the control.
FIX_SMOKE_NC_ZERO="$TMP/smoke_nc_zero.json"
mk_smoke "$FIX_SMOKE_NC_ZERO" 1 0
stderr_out=$(post_evals::validate_smoke "$FIX_SMOKE_NC_ZERO" 2>&1)
check "validate_smoke: negative_control exit 0 → exit 1 (vacuous) [instances 2,3]" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"negative_control"* ]]
check "validate_smoke: vacuous control → stderr names eval and negative_control" 0 $?

# (S3) The trap in a naive polarity check: an env-error is ALSO non-zero. A
# control that exits 127 because its own tooling is missing tests nothing, yet
# satisfies a bare `!= 0` assertion. This is instance 2's vacuous-pass bug
# relocated one level up, so the control needs BOTH non-zero AND not-env-error.
FIX_SMOKE_NC_ENOENT="$TMP/smoke_nc_enoent.json"
mk_smoke "$FIX_SMOKE_NC_ENOENT" 1 127
stderr_out=$(post_evals::validate_smoke "$FIX_SMOKE_NC_ENOENT" 2>&1)
check "validate_smoke: negative_control exit 127 → exit 1 (non-zero but vacuous)" 1 $?

# (S3-bis) Timeout (142) and crash (>=128) on the control are equally
# environmental — same taxonomy validate_discriminating already uses.
FIX_SMOKE_NC_TIMEOUT="$TMP/smoke_nc_timeout.json"
mk_smoke "$FIX_SMOKE_NC_TIMEOUT" 1 142
post_evals::validate_smoke "$FIX_SMOKE_NC_TIMEOUT" 2>/dev/null
check "validate_smoke: negative_control timeout (142) → exit 1 (environmental)" 1 $?

FIX_SMOKE_CMD_CRASH="$TMP/smoke_cmd_crash.json"
mk_smoke "$FIX_SMOKE_CMD_CRASH" 139 1
post_evals::validate_smoke "$FIX_SMOKE_CMD_CRASH" 2>/dev/null
check "validate_smoke: cmd crash (139 SIGSEGV) → exit 1 (environmental)" 1 $?

# (S4) The teeth. A scripted eval with NO smoke object at all must be refused
# at tier>=1 — otherwise the whole gate is opt-in and an agent skips it by
# omission, exactly as `fixtures` is skipped today.
FIX_SMOKE_MISSING="$TMP/smoke_missing.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pending",
     cmd:"run-a", negative_control:"run-a-broken", evidence:"log"}
  ]
}' > "$FIX_SMOKE_MISSING"
stderr_out=$(post_evals::validate_smoke "$FIX_SMOKE_MISSING" 2>&1)
check "validate_smoke: scripted eval with no smoke object → exit 1 (not opt-in)" 1 $?
[[ "$stderr_out" == *"smoke"* ]]
check "validate_smoke: missing smoke → stderr names smoke" 0 $?

# (S5) A malformed smoke object (exit codes absent or non-numeric) must fail
# closed, not fall through `// ""` into a misleading pass — the same defect
# class validate_discriminating guards with its fixtures-type check.
FIX_SMOKE_MALFORMED="$TMP/smoke_malformed.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pending",
     cmd:"run-a", negative_control:"run-a-broken", evidence:"log",
     smoke: "ran it, looked fine"}
  ]
}' > "$FIX_SMOKE_MALFORMED"
stderr_out=$(post_evals::validate_smoke "$FIX_SMOKE_MALFORMED" 2>&1)
check "validate_smoke: smoke not an object → exit 1 (fail closed)" 1 $?

FIX_SMOKE_NONNUM="$TMP/smoke_nonnum.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"scripted", status:"pending",
     cmd:"run-a", negative_control:"run-a-broken", evidence:"log",
     smoke: {cmd_exit: "zero", negative_control_exit: 1}}
  ]
}' > "$FIX_SMOKE_NONNUM"
stderr_out=$(post_evals::validate_smoke "$FIX_SMOKE_NONNUM" 2>&1)
check "validate_smoke: non-numeric exit code → exit 1 (fail closed)" 1 $?

# (S6) Scope limits. agent-run evals carry no cmd, so they carry no smoke —
# requiring one would block every judgement eval.
FIX_SMOKE_AGENTRUN="$TMP/smoke_agentrun.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit",
  head_sha: $sha,
  evals: [
    {id:"e1", priority:"P0", mode:"agent-run", status:"pending",
     assert:"the UI renders", evidence:"verifier report"}
  ]
}' > "$FIX_SMOKE_AGENTRUN"
post_evals::validate_smoke "$FIX_SMOKE_AGENTRUN"
check "validate_smoke: agent-run eval needs no smoke → exit 0" 0 $?

# Tier 0 is the exemption path: no evals to smoke.
FIX_SMOKE_TIER0="$TMP/smoke_tier0.json"
jq -n --arg sha "$SHA" '{
  tier: 0, tier_justification: "single work-unit, covered by existing test",
  head_sha: $sha, evals: []
}' > "$FIX_SMOKE_TIER0"
post_evals::validate_smoke "$FIX_SMOKE_TIER0"
check "validate_smoke: tier 0 exemption → exit 0" 0 $?

# (S7) Same fail-open lesson PR #261 paid for: without an explicit guard, a
# missing jq makes every read empty and a violating file looks exactly like a
# compliant one. PATH is narrowed to an EMPTY dir, not to /usr/bin:/bin —
# instance 3 is precisely the bug of narrowing to a path that still holds jq.
stderr_out=$(PATH="$EMPTY_BIN"; post_evals::validate_smoke "$FIX_SMOKE_NC_ZERO" 2>&1)
check "validate_smoke: jq unavailable → exit 1 (must not fail open)" 1 $?
[[ "$stderr_out" == *"jq"* ]]
check "validate_smoke: jq unavailable → stderr names jq" 0 $?

# (S8) Wired into validate_structure, not merely available as a function —
# an unwired gate is documentation. A file failing only the smoke check must
# be refused by the top-level validator every caller actually invokes.
stderr_out=$(post_evals::validate_structure "$FIX_SMOKE_NC_ZERO" 42 "$SHA" 2>&1)
check "validate_structure: vacuous negative control → exit 1 (smoke gate wired in)" 1 $?

# Back-compat: tier-1 files predating this gate carry no smoke object. They
# are refused by S4 above, which is intentional — but the tier-0 and agent-run
# paths must stay open, and every pre-existing passing fixture that carries
# scripted evals now needs smoke. Assert the well-formed fixture still passes
# once smoke is present, so the gate is additive and not a blanket break.
FIX_SMOKE_FULL="$TMP/smoke_full.json"
mk_smoke "$FIX_SMOKE_FULL" 1 1
post_evals::validate_structure "$FIX_SMOKE_FULL" 42 "$SHA"
check "validate_structure: well-formed file with smoke evidence → exit 0" 0 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
