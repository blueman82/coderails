#!/bin/bash
# Regression: two concurrent progress.json writers must not lose each
# other's updates (AC-8). Ports post_review.test.sh's slow-jq-shim race
# widener verbatim (lines 181-206) rather than inventing a new one: one
# writer is graph_executor_apply_wave (Unit 2), the other an unrelated
# als_atomic_progress_update mutation on the same file.
set -u
LIB="$(cd "$(dirname "$0")/../lib" && pwd)/graph_executor.sh"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_val() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

PROG="$TMP/progress.json"
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [],
    loop_stop_counts: {} }
' > "$PROG"

JQ_BIN=$(command -v jq)
SLOW_BIN="$TMP/slow-bin"
mkdir -p "$SLOW_BIN"
printf '#!/bin/bash\nsleep 0.1\nexec %s "$@"\n' "$JQ_BIN" > "$SLOW_BIN/jq"
chmod +x "$SLOW_BIN/jq"

PATH="$SLOW_BIN:$PATH" CLAUDE_HOOK_MAX_ATTEMPTS=100 CLAUDE_HOOK_SLEEP_S=0.01 \
  bash -c 'source "$1"; graph_executor_apply_wave "$2" "{\"A\":{\"status\":\"done\",\"outcome\":\"done\"}}"' \
  bash "$LIB" "$PROG" & writer_wave=$!
PATH="$SLOW_BIN:$PATH" CLAUDE_HOOK_MAX_ATTEMPTS=100 CLAUDE_HOOK_SLEEP_S=0.01 \
  bash -c 'source "$1"; als_atomic_progress_update "$2" --arg cat complete ".loop_stop_counts[\$cat] = ((.loop_stop_counts[\$cat] // 0) + 1)"' \
  bash "$LIB" "$PROG" & writer_counter=$!
wait "$writer_wave"; wave_rc=$?
wait "$writer_counter"; counter_rc=$?

check "concurrent progress writers: wave update succeeds" 0 "$wave_rc"
check "concurrent progress writers: counter update succeeds" 0 "$counter_rc"
check_val "concurrent progress writers: wave update survives" "done" "$(jq -r '.graph.nodes.A.outcome' "$PROG")"
check_val "concurrent progress writers: counter update survives" "1" "$(jq -r '.loop_stop_counts.complete' "$PROG")"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
