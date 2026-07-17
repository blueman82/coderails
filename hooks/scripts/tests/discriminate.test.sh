#!/bin/bash
# Behavioural tests for scripts/post_evals.sh validate-discriminating.
# Freeze-time gate: proves a scripted eval's fixtures.formula can both pass
# and fail before the check is ever trusted at completion. See
# skills/task-evals/SKILL.md for the fixtures schema and honest boundary.
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

# ─── case 1: THE REAL BUG (regression lock) ──────────────────────────────────
# loop 8b69e779's actual broken awk formula: exits 1 on BOTH the good and bad
# fixture (39/39 splits into 7 fields under -F'[ /]', so $(NF-2) lands on the
# literal string "suites", never the numerator/denominator) — non-discriminating.
FIX_REAL_BUG="$TMP/real_bug.json"
BROKEN_FORMULA='awk -F'"'"'[ /]'"'"' '"'"'/suites passed/ {found=1; ok=($(NF-3) == $(NF-2))} END {exit (found && ok) ? 0 : 1}'"'"''
jq -n --arg sha "$SHA" --arg formula "$BROKEN_FORMULA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: ("bash run_all.sh 2>&1 | " + $formula),
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "--- run_all: 39/39 suites passed ---",
        bad: "--- run_all: 18/40 suites passed ---",
        formula: $formula
      }
    }
  ]
}' > "$FIX_REAL_BUG"
stderr_out=$(post_evals::validate_discriminating "$FIX_REAL_BUG" 2>&1)
check "validate_discriminating: loop 8b69e779 broken awk -> exit 1 (non-discriminating)" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"non-discriminating"* ]]
check "validate_discriminating: broken awk -> stderr names id + non-discriminating" 0 $?
[[ "$stderr_out" == *"1"* ]]
check "validate_discriminating: broken awk -> stderr mentions the shared exit code" 0 $?

# ─── case 2: repaired formula is ACCEPTED ────────────────────────────────────
FIX_REPAIRED="$TMP/repaired.json"
REPAIRED_FORMULA='awk '"'"'/suites passed/ {found=1; split($3,a,"/"); ok=(a[1]==a[2] && a[1]>0)} END {exit (found && ok) ? 0 : 1}'"'"''
jq -n --arg sha "$SHA" --arg formula "$REPAIRED_FORMULA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: ("bash run_all.sh 2>&1 | " + $formula),
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "--- run_all: 39/39 suites passed ---",
        bad: "--- run_all: 18/40 suites passed ---",
        formula: $formula
      }
    }
  ]
}' > "$FIX_REPAIRED"
post_evals::validate_discriminating "$FIX_REPAIRED"
check "validate_discriminating: repaired awk formula -> exit 0 (accepted)" 0 $?

# ─── case 3: vacuous-pass rejection (formula exits 0 on both fixtures) ──────
FIX_VACUOUS="$TMP/vacuous.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | cat",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "anything",
        bad: "anything else",
        formula: "cat"
      }
    }
  ]
}' > "$FIX_VACUOUS"
stderr_out=$(post_evals::validate_discriminating "$FIX_VACUOUS" 2>&1)
check "validate_discriminating: cat (exits 0 on both) -> exit 1 (non-discriminating)" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"non-discriminating"* ]]
check "validate_discriminating: vacuous-pass -> stderr names id + non-discriminating" 0 $?
[[ "$stderr_out" == *"0"* ]]
check "validate_discriminating: vacuous-pass -> stderr mentions the shared exit code (0)" 0 $?

# ─── case 4: grandfathering — no fixtures field validates as today ─────────
FIX_NO_FIXTURES="$TMP/no_fixtures.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {id: "e1", priority: "P0", mode: "scripted", status: "pass", cmd: "run-a", negative_control: "run-a-broken", evidence: "log"}
  ]
}' > "$FIX_NO_FIXTURES"
post_evals::validate_discriminating "$FIX_NO_FIXTURES"
check "validate_discriminating: no fixtures field -> exit 0 (grandfathered)" 0 $?

# ─── case 5: formula-not-derivable — no pipe in cmd, no explicit fixtures.formula ─
FIX_NO_FORMULA="$TMP/no_formula.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "run-a-no-pipe",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: { good: "g", bad: "b" }
    }
  ]
}' > "$FIX_NO_FORMULA"
stderr_out=$(post_evals::validate_discriminating "$FIX_NO_FORMULA" 2>&1)
check "validate_discriminating: cmd has no pipe, no fixtures.formula -> exit 1 (fail-closed)" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"fixtures.formula"* ]]
check "validate_discriminating: formula-not-derivable -> stderr tells author to supply fixtures.formula" 0 $?

# ─── case 6: environmental failure is distinct from non-discriminating ──────
FIX_ENV_FAIL="$TMP/env_fail.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | this_binary_does_not_exist_xyz_123",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "anything",
        bad: "anything else",
        formula: "this_binary_does_not_exist_xyz_123"
      }
    }
  ]
}' > "$FIX_ENV_FAIL"
stderr_out=$(post_evals::validate_discriminating "$FIX_ENV_FAIL" 2>&1)
check "validate_discriminating: nonexistent binary -> exit 1 (refused)" 1 $?
[[ "$stderr_out" != *"non-discriminating"* ]]
check "validate_discriminating: nonexistent binary -> stderr does NOT claim non-discriminating" 0 $?
[[ "$stderr_out" == *"e1"* ]]
check "validate_discriminating: nonexistent binary -> stderr names the eval id" 0 $?

# ─── case 7: existing structure checks still fire when fixtures are present ─
FIX_STRUCTURE_STILL_FIRES="$TMP/structure_still_fires.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | cat",
      negative_control: "",
      evidence: "log",
      fixtures: {
        good: "g",
        bad: "b",
        formula: "cat"
      }
    }
  ]
}' > "$FIX_STRUCTURE_STILL_FIRES"
stderr_out=$(post_evals::validate_structure "$FIX_STRUCTURE_STILL_FIRES" 42 "$SHA" 2>&1)
check "validate_structure: tier>=1 scripted eval with empty negative_control (fixtures present) -> exit 1" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"empty negative_control"* ]]
check "validate_structure: empty negative_control still fires with fixtures present" 0 $?

# ─── case 8 (additional): good fails / bad passes → distinct message from case 4 ─
# Formula genuinely inverted: it greps for the BAD fixture's own text, so the
# good fixture (which lacks it) exits non-zero and the bad fixture exits 0 —
# opposite exit codes, but the WRONG way round, which is a different defect
# class from "same exit code both ways" (case 1/3) and must get its own
# message, not be conflated with non-discriminating.
FIX_INVERTED="$TMP/inverted.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | grep -q '"'"'18/40'"'"'",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "--- run_all: 39/39 suites passed ---",
        bad: "--- run_all: 18/40 suites passed ---",
        formula: "grep -q '"'"'18/40'"'"'"
      }
    }
  ]
}' > "$FIX_INVERTED"
stderr_out=$(post_evals::validate_discriminating "$FIX_INVERTED" 2>&1)
check "validate_discriminating: good fails / bad passes (inverted) -> exit 1" 1 $?
[[ "$stderr_out" == *"e1"* ]]
check "validate_discriminating: inverted case -> stderr names id" 0 $?
[[ "$stderr_out" != *"non-discriminating"* ]]
check "validate_discriminating: inverted case -> stderr is a DISTINCT message from non-discriminating" 0 $?

# ─── case 9: fixtures.formula explicit override takes precedence over cmd parsing ─
FIX_EXPLICIT_FORMULA="$TMP/explicit_formula.json"
jq -n --arg sha "$SHA" --arg formula "$REPAIRED_FORMULA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "some-wrapper-script-with-no-useful-pipe-segment",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "--- run_all: 39/39 suites passed ---",
        bad: "--- run_all: 18/40 suites passed ---",
        formula: $formula
      }
    }
  ]
}' > "$FIX_EXPLICIT_FORMULA"
post_evals::validate_discriminating "$FIX_EXPLICIT_FORMULA"
check "validate_discriminating: explicit fixtures.formula used even when cmd has no pipe -> exit 0" 0 $?

# ─── case 10: multiple evals, non-fixtures eval alongside a broken one ──────
# The gate must check EVERY eval carrying fixtures, not just the first.
FIX_MULTI="$TMP/multi.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "2 work-units, scripted change",
  head_sha: $sha,
  evals: [
    {id: "e1", priority: "P0", mode: "scripted", status: "pass", cmd: "run-a", negative_control: "run-a-broken", evidence: "log"},
    {
      id: "e2", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | cat",
      negative_control: "run-b-broken", evidence: "log",
      fixtures: { good: "g", bad: "b", formula: "cat" }
    }
  ]
}' > "$FIX_MULTI"
stderr_out=$(post_evals::validate_discriminating "$FIX_MULTI" 2>&1)
check "validate_discriminating: second eval's broken fixtures -> exit 1" 1 $?
[[ "$stderr_out" == *"e2"* ]]
check "validate_discriminating: multi-eval -> stderr names the offending id (e2, not e1)" 0 $?

# ─── CLI dispatch: validate-discriminating wired into the subcommand case ────
usage_out=$(bash "$SCRIPT" 2>&1)
[[ "$usage_out" == *"validate-discriminating"* ]]
check "usage text mentions validate-discriminating" 0 $?

cli_out=$(bash "$SCRIPT" validate-discriminating "$FIX_REPAIRED" 2>&1)
rc=$?
check "CLI dispatch: validate-discriminating on repaired fixture -> exit 0" 0 $rc

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
