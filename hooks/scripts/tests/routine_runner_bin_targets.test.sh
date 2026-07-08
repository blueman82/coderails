#!/bin/bash
# Guard test (C5): every skills/dashboard/runner/bin/*.sh script invokes
# node against one or more `$SCRIPT_DIR/../...` relative script paths (the
# defect class C2 fixed: bin/sweeper.sh pointed at a dist/main.js that never
# existed, so every watch-plist fire died MODULE_NOT_FOUND with only the log
# to show for it). This test is table-driven and generic — it extracts every
# such argument from every bin/*.sh file via grep, resolves it relative to
# the script's own directory, and asserts the resolved file exists on disk.
# It must fail if any bin script is ever pointed at a nonexistent target
# again, without needing per-script hardcoding.
#
# Negative-control proof (documented, not run automatically — running it
# would require mutating the repo): pointing this test's extraction at the
# pre-C2 bin/sweeper.sh (`exec node "$SCRIPT_DIR/../dist/main.js"`) resolves
# to .../runner/dist/main.js, which does not exist (dist/ is gitignored, no
# build step produces it) — the existence check below fails exactly as
# intended. Verified manually during development by checking out the
# pre-fix blob and re-running the extraction+check logic against it.
#
# Usage: bash routine_runner_bin_targets.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BIN_DIR="$REPO_ROOT/skills/dashboard/runner/bin"

fails=0
checks=0
check() { # desc expected actual
  checks=$((checks+1))
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

if [ ! -d "$BIN_DIR" ]; then
  echo "FAIL - bin dir not found: $BIN_DIR"
  exit 1
fi

bin_scripts=$(find "$BIN_DIR" -maxdepth 1 -type f -name '*.sh' | sort)
if [ -z "$bin_scripts" ]; then
  echo "FAIL - no *.sh scripts found under $BIN_DIR — nothing for this guard to check"
  exit 1
fi

# dashboard-server.sh execs `npm run start`, not a node script by relative
# path — it has no `$SCRIPT_DIR/../...` node target for this guard to check
# (its own equivalent staleness/target risk is covered by
# dashboard_agent.test.sh instead). Exclude it rather than report a false
# "no target found" failure for a script this guard's node-target pattern
# was never meant to cover.
bin_scripts=$(echo "$bin_scripts" | grep -v '/dashboard-server\.sh$')

# Extract every `$SCRIPT_DIR/../<path>` argument passed to a node invocation
# in a bin script, resolve it against that script's own real directory, and
# check the resolved file exists. A bin script's SCRIPT_DIR always resolves
# to BIN_DIR itself (each script computes it via `cd "$(dirname "$0")" &&
# pwd`), so substituting BIN_DIR directly reproduces runtime resolution.
while IFS= read -r script; do
  rel="${script#"$REPO_ROOT"/}"

  # Matches quoted arguments of the form "$SCRIPT_DIR/../something" following
  # a node invocation on the same line (covers both the plain and `exec`
  # forms present in this directory today).
  targets=$(grep -oE '"\$SCRIPT_DIR/\.\./[^"]+"' "$script" | tr -d '"')

  if [ -z "$targets" ]; then
    printf 'FAIL - %s: no $SCRIPT_DIR/../... node target found to check (extraction found nothing — update this guard'"'"'s pattern if the script'"'"'s invocation style changed)\n' "$rel"
    fails=$((fails+1))
    continue
  fi

  while IFS= read -r target; do
    [ -z "$target" ] && continue
    resolved="${target/\$SCRIPT_DIR/$BIN_DIR}"
    # Normalise ../ segments so the printed path is readable; existence check
    # itself works fine on the unnormalised path too since the shell resolves
    # .. at the filesystem level.
    check "$rel -> $target resolves to an existing file" "yes" "$([ -f "$resolved" ] && echo yes || echo no)"
  done <<< "$targets"
done <<< "$bin_scripts"

if [ "$checks" -eq 0 ]; then
  echo "FAIL - zero targets were extracted/checked across all bin scripts — guard is vacuous"
  exit 1
fi

[ "$fails" -eq 0 ] && { echo "PASS ($checks target(s) checked)"; exit 0; } || { echo "FAILED ($fails/$checks)"; exit 1; }
