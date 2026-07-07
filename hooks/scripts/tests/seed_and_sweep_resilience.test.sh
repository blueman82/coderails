#!/bin/bash
# Guard test (C1): bin/seed-and-sweep.sh runs under `set -euo pipefail` and
# must reach its final `exec ... main.ts` sweep step even when the seed step
# (seedMain.ts, exit code 2 = "seed step itself crashed", per seedMain.ts's
# own exit-code contract) exits non-zero. Before the fix, a bare
# `node .../seedMain.ts` line with no `|| ...` aborted the whole script at
# that line — the calendar-triggered sweep silently never ran.
#
# This test fakes the two `/opt/homebrew/bin/node` invocations the real
# script makes by putting a fake `node` shim first on PATH: it inspects
# which script it was asked to run (seedMain.ts vs main.ts) and reacts
# accordingly — the seedMain.ts case exits with the code given via
# SEED_EXIT_CODE, the main.ts case just marks a sentinel file as proof the
# sweep step was reached and exits 0. bin/seed-and-sweep.sh hardcodes the
# absolute path /opt/homebrew/bin/node rather than a bare `node` (deliberate,
# per its own header comment — launchd carries no PATH), so this shim can't
# intercept it via PATH alone; instead this test symlinks the fake node over
# a scratch copy's expected absolute path by bind-mounting via a wrapper
# script copy with the path substituted. See below.
#
# Usage: bash seed_and_sweep_resilience.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
REAL_SCRIPT="$REPO_ROOT/skills/dashboard/runner/bin/seed-and-sweep.sh"

fails=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# Fake node: logs which script it was asked to run, honors SEED_EXIT_CODE
# for the seedMain.ts invocation, and touches a sentinel for the main.ts
# invocation (proof the sweep's `exec` line was reached).
FAKE_NODE="$TMP/fake-node.sh"
cat > "$FAKE_NODE" <<'EOF'
#!/bin/bash
script="$1"
case "$script" in
  */seedMain.ts)
    echo "fake-node: seedMain.ts invoked" >> "$LOG_FILE"
    exit "${SEED_EXIT_CODE:-0}"
    ;;
  */main.ts)
    echo "fake-node: main.ts invoked" >> "$LOG_FILE"
    touch "$SWEEP_SENTINEL"
    exit 0
    ;;
  *)
    echo "fake-node: unexpected script $script" >> "$LOG_FILE"
    exit 99
    ;;
esac
EOF
chmod +x "$FAKE_NODE"

# bin/seed-and-sweep.sh hardcodes /opt/homebrew/bin/node absolutely (by
# design — launchd carries no PATH). To substitute the fake node without
# editing the real script under test, copy it into a scratch bin/ dir
# alongside a relocated src/ (so its `$SCRIPT_DIR/../src/*.ts` relative
# resolution still finds real filenames, even though the fake node never
# reads their contents) and rewrite just the hardcoded interpreter path.
SCRATCH_RUNNER="$TMP/runner"
mkdir -p "$SCRATCH_RUNNER/bin" "$SCRATCH_RUNNER/src"
touch "$SCRATCH_RUNNER/src/seedMain.ts" "$SCRATCH_RUNNER/src/main.ts"
sed "s#/opt/homebrew/bin/node#$FAKE_NODE#g" "$REAL_SCRIPT" > "$SCRATCH_RUNNER/bin/seed-and-sweep.sh"
chmod +x "$SCRATCH_RUNNER/bin/seed-and-sweep.sh"

run_scenario() { # seed_exit_code
  LOG_FILE="$TMP/log-$1.txt"
  SWEEP_SENTINEL="$TMP/sentinel-$1"
  rm -f "$LOG_FILE" "$SWEEP_SENTINEL"
  SEED_EXIT_CODE="$1" LOG_FILE="$LOG_FILE" SWEEP_SENTINEL="$SWEEP_SENTINEL" \
    bash "$SCRATCH_RUNNER/bin/seed-and-sweep.sh" > "$TMP/stdout-$1.txt" 2> "$TMP/stderr-$1.txt"
  echo "$?"
}

# 1. Seed step succeeds (exit 0) — sweep must still run (baseline, not the
#    regression itself, but confirms the harness works before trusting the
#    failure-path result below).
exit_code_0="$(run_scenario 0)"
check "seed exit 0: script overall exit code" "0" "$exit_code_0"
check "seed exit 0: sweep (main.ts) was reached" "yes" "$([ -f "$TMP/sentinel-0" ] && echo yes || echo no)"

# 2. Seed step crashes with exit 2 (seedMain.ts's documented "seed step
#    itself crashed" code) — this is the reproduction: the sweep must STILL
#    run. Before the C1 fix, `set -euo pipefail` aborted the script at the
#    bare seedMain.ts line and this sentinel was never created.
exit_code_2="$(run_scenario 2)"
check "seed exit 2: sweep (main.ts) was reached despite seed failure (C1)" "yes" "$([ -f "$TMP/sentinel-2" ] && echo yes || echo no)"
check "seed exit 2: script's own exit code reflects the sweep's exit (0), not the seed's" "0" "$exit_code_2"
check "seed exit 2: a one-line failure note was logged to stderr" "yes" "$(grep -q 'seed step failed (exit 2)' "$TMP/stderr-2.txt" && echo yes || echo no)"

# 3. Arbitrary non-zero seed exit code (e.g. 1) also must not block the sweep.
exit_code_1="$(run_scenario 1)"
check "seed exit 1: sweep (main.ts) was reached despite seed failure" "yes" "$([ -f "$TMP/sentinel-1" ] && echo yes || echo no)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
