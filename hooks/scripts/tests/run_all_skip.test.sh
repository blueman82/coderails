#!/bin/bash
# Behavioural test for run_all.sh's rc==3 (SKIP) handling. run_all.sh globs
# *.test.sh in its own directory, so each case copies the real run_all.sh
# into a scratch dir alongside synthetic fake suites (bare `exit N` scripts)
# and runs it there — proving the real aggregation logic, not a re-implementation.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_ALL="$SCRIPT_DIR/run_all.sh"

fails=0
checks=0
check() { # desc expected actual
  checks=$((checks+1))
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

fake_suite() { # dir name exit_code
  printf '#!/bin/bash\nexit %s\n' "$3" > "$1/$2"
  chmod +x "$1/$2"
}

new_scratch() {
  local dir
  dir="$(mktemp -d)"
  cp "$RUN_ALL" "$dir/run_all.sh"
  printf '%s' "$dir"
}

# --- case 1: pass + fail + skip -> names the skip AND exits 1 (the fail wins) ---
TMP1="$(new_scratch)"
fake_suite "$TMP1" a_pass.test.sh 0
fake_suite "$TMP1" b_fail.test.sh 1
fake_suite "$TMP1" c_skip.test.sh 3
out1="$(bash "$TMP1/run_all.sh" 2>&1)"; rc1=$?
check "case1: pass+fail+skip -> exit 1 (a real failure is present)" "1" "$rc1"
check "case1: skip suite is named as SKIPPED, not FAILED" "yes" "$(printf '%s' "$out1" | grep -q 'SKIPPED (prerequisite): c_skip.test.sh' && echo yes || echo no)"
check "case1: summary reports 1 skipped" "yes" "$(printf '%s' "$out1" | grep -qE '1 skipped' && echo yes || echo no)"
rm -rf "$TMP1"

# --- case 2: remove the failing suite (pass + skip only) -> exits 0, skip still printed ---
TMP2="$(new_scratch)"
fake_suite "$TMP2" a_pass.test.sh 0
fake_suite "$TMP2" c_skip.test.sh 3
out2="$(bash "$TMP2/run_all.sh" 2>&1)"; rc2=$?
check "case2: pass+skip, no fail -> exit 0" "0" "$rc2"
check "case2: skip suite still named" "yes" "$(printf '%s' "$out2" | grep -q 'SKIPPED (prerequisite): c_skip.test.sh' && echo yes || echo no)"
check "case2: summary shows 1 skipped" "yes" "$(printf '%s' "$out2" | grep -qE '1 skipped' && echo yes || echo no)"
rm -rf "$TMP2"

# --- case 3: ALL suites skip -> the F6 all-skipped floor: non-zero exit + WARNING ---
TMP3="$(new_scratch)"
fake_suite "$TMP3" a_skip.test.sh 3
fake_suite "$TMP3" b_skip.test.sh 3
out3="$(bash "$TMP3/run_all.sh" 2>&1)"; rc3=$?
check "case3: all suites skipped -> non-zero exit (not a vacuous green)" "yes" "$([ "$rc3" -ne 0 ] && echo yes || echo no)"
check "case3: all-skipped WARNING is printed" "yes" "$(printf '%s' "$out3" | grep -q 'WARNING: all .* suites skipped' && echo yes || echo no)"
rm -rf "$TMP3"

# --- case 4: NEGATIVE CONTROL — a real assertion failure (exit 1) with deps
# present must still exit 1, never be absorbed as a skip (exit 3 is never
# produced by run_all.sh itself; it only ever passes rc==3 through from a suite) ---
TMP4="$(new_scratch)"
fake_suite "$TMP4" a_fail.test.sh 1
out4="$(bash "$TMP4/run_all.sh" 2>&1)"; rc4=$?
check "case4 negative control: a real failure -> exit 1 (never absorbed)" "1" "$rc4"
check "case4 negative control: failing suite reported FAILED, not SKIPPED" "yes" "$(printf '%s' "$out4" | grep -q 'FAILED (exit 1)' && echo yes || echo no)"
check "case4 negative control: no SKIPPED line for an exit-1 suite" "yes" "$(printf '%s' "$out4" | grep -q 'SKIPPED' && echo no || echo yes)"
rm -rf "$TMP4"

if [ "$checks" -eq 0 ]; then
  echo "FAIL - zero checks ran — guard is vacuous"
  exit 1
fi

[ "$fails" -eq 0 ] && { echo "PASS ($checks checks)"; exit 0; } || { echo "FAILED ($fails/$checks)"; exit 1; }
