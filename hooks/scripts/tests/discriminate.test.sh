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
[[ "$stderr_out" == *"both exit 1"* ]]
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
[[ "$stderr_out" == *"both exit 0"* ]]
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

# ─── case 11: fixtures present but bad omitted -> reject (unsafe-accept fix) ─
# Author supplies good + formula but omits bad; bad defaults to "" and the
# gate could otherwise ACCEPT — proof against an empty string the author
# never wrote. This formula makes the danger concrete: grep on the omitted
# empty string exits 1 (no match), which LOOKS like a legitimate "bad fails"
# — good_rc=0, bad_rc=1 — the exact unsafe-accept shape, without ever
# checking a real bad fixture.
FIX_BAD_OMITTED="$TMP/bad_omitted.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | grep -q '\''39/39'\''",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: { good: "39/39 suites passed", formula: "grep -q '\''39/39'\''" }
    }
  ]
}' > "$FIX_BAD_OMITTED"
stderr_out=$(post_evals::validate_discriminating "$FIX_BAD_OMITTED" 2>&1)
check "validate_discriminating: fixtures.bad omitted -> exit 1 (reject, not accept)" 1 $?
[[ "$stderr_out" == *"e1"* ]]
check "validate_discriminating: bad omitted -> stderr names the eval id" 0 $?

# ─── case 12: fixtures present but good omitted -> reject (same unsafe direction) ─
# Same unsafe-accept shape as case 11, mirrored: this formula makes empty
# input (the omitted good's default) exit 0 trivially, while the real bad
# fixture correctly exits non-zero — good_rc=0, bad_rc=1 — without ever
# checking a real good fixture the author wrote.
FIX_GOOD_OMITTED="$TMP/good_omitted.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | ! grep -q FAIL",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: { bad: "18/40 suites passed - FAIL", formula: "! grep -q FAIL" }
    }
  ]
}' > "$FIX_GOOD_OMITTED"
stderr_out=$(post_evals::validate_discriminating "$FIX_GOOD_OMITTED" 2>&1)
check "validate_discriminating: fixtures.good omitted -> exit 1 (reject)" 1 $?
[[ "$stderr_out" == *"e1"* ]]
check "validate_discriminating: good omitted -> stderr names the eval id" 0 $?

# ─── case 13: env-guard broadened — 126 (permission denied) on bad leg -> reject ─
# Without the fix, good_rc=0 && bad_rc=126 falls into the accept path (an
# environmental crash read as a legitimate discrimination fail).
NOPERM="$TMP/noperm_e13.sh"
printf '#!/bin/bash\necho hi\n' > "$NOPERM"
chmod -x "$NOPERM"
FIX_ENV_126="$TMP/env_126.json"
jq -n --arg sha "$SHA" --arg noperm "$NOPERM" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: ("bash run_all.sh 2>&1 | if grep -q g; then exit 0; else " + $noperm + "; fi"),
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "g", bad: "b",
        formula: ("if grep -q g; then exit 0; else " + $noperm + "; fi")
      }
    }
  ]
}' > "$FIX_ENV_126"
stderr_out=$(post_evals::validate_discriminating "$FIX_ENV_126" 2>&1)
check "validate_discriminating: bad leg exits 126 -> exit 1 (env-suspect, not accept)" 1 $?
[[ "$stderr_out" != *"non-discriminating"* ]]
check "validate_discriminating: exit 126 -> stderr does NOT claim non-discriminating" 0 $?

# ─── case 14: env-guard broadened — 137 (SIGKILL) on bad leg -> reject ──────
# A formula that CRASHES on bad input is environmental-suspect, not a valid
# content fail — a crash is not a discrimination signal.
FIX_ENV_137="$TMP/env_137.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | if grep -q g; then exit 0; else kill -9 $$; fi",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: {
        good: "g", bad: "b",
        formula: "if grep -q g; then exit 0; else kill -9 $$; fi"
      }
    }
  ]
}' > "$FIX_ENV_137"
stderr_out=$(post_evals::validate_discriminating "$FIX_ENV_137" 2>&1)
check "validate_discriminating: bad leg exits 137 (SIGKILL) -> exit 1 (env-suspect)" 1 $?
[[ "$stderr_out" != *"non-discriminating"* ]]
check "validate_discriminating: exit 137 -> stderr does NOT claim non-discriminating" 0 $?

# ─── case 15: 142 timeout message still distinct after the >=128 broadening ─
# CRITICAL ORDERING: the 142 (128+SIGALRM) check must still fire with its own
# message, not get swallowed by the new >=128 environmental-suspect check.
FIX_TIMEOUT="$TMP/timeout.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | sleep 15",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: { good: "g", bad: "b", formula: "sleep 15" }
    }
  ]
}' > "$FIX_TIMEOUT"
stderr_out=$(post_evals::validate_discriminating "$FIX_TIMEOUT" 2>&1)
check "validate_discriminating: timeout still exit 1" 1 $?
[[ "$stderr_out" == *"timed out"* ]]
check "validate_discriminating: timeout message still distinct (not swallowed by >=128 check)" 0 $?

# ─── case 16: malformed fixtures (not an object) -> reject with distinct message ─
FIX_MALFORMED="$TMP/malformed.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "bash run_all.sh 2>&1 | cat",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: "not-an-object"
    }
  ]
}' > "$FIX_MALFORMED"
stderr_out=$(post_evals::validate_discriminating "$FIX_MALFORMED" 2>&1)
check "validate_discriminating: fixtures is a string, not object -> exit 1" 1 $?
[[ "$stderr_out" == *"e1"* && "$stderr_out" == *"object"* ]]
check "validate_discriminating: malformed fixtures -> stderr names id + says 'object'" 0 $?

# ─── case 17: pipe-derivation happy path — no fixtures.formula, derivation succeeds ─
# Every other fixtures block in this suite supplies fixtures.formula explicitly,
# so the "${cmd##*|}" derivation-from-cmd branch (case 5 above only exercises
# its FAIL-CLOSED half — no pipe, no formula) was never exercised on the path
# where it actually derives a formula and that formula genuinely discriminates.
# cmd's last-pipe segment ("grep -q x") is the derived formula: good="x" makes
# it exit 0, bad="y" makes it exit 1 — accepted via derivation, not override.
FIX_DERIVED="$TMP/derived.json"
jq -n --arg sha "$SHA" '{
  tier: 1,
  tier_justification: "1 work-unit, scripted change",
  head_sha: $sha,
  evals: [
    {
      id: "e1", priority: "P0", mode: "scripted", status: "pass",
      cmd: "echo x | grep -q x",
      negative_control: "run-a-broken", evidence: "log",
      fixtures: { good: "x", bad: "y" }
    }
  ]
}' > "$FIX_DERIVED"
post_evals::validate_discriminating "$FIX_DERIVED"
check "validate_discriminating: derived formula (no fixtures.formula) discriminates -> exit 0 (accepted)" 0 $?

# ─── CLI dispatch: validate-discriminating wired into the subcommand case ────
usage_out=$(bash "$SCRIPT" 2>&1)
[[ "$usage_out" == *"validate-discriminating"* ]]
check "usage text mentions validate-discriminating" 0 $?

cli_out=$(bash "$SCRIPT" validate-discriminating "$FIX_REPAIRED" 2>&1)
rc=$?
check "CLI dispatch: validate-discriminating on repaired fixture -> exit 0" 0 $rc

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
