#!/bin/bash
# Unit test for graph_readiness.sh — pure read-only readiness query over
# progress.json's durable execution graph. Each case is paired with an
# explicit negative control: a fixture built the same way, with only the
# one deciding field flipped, so each assertion is proven to actually
# discriminate rather than pass by construction.
set -u

HELPER="$(cd "$(dirname "$0")/.." && pwd)/lib/graph_readiness.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
run_check() { # desc, fixture, node, expected_stdout, expected_exit
  local desc="$1" fixture="$2" node="$3" want_out="$4" want_exit="$5"
  local out rc
  out=$(bash "$HELPER" "$fixture" "$node"); rc=$?
  if [ "$out" = "$want_out" ] && [ "$rc" = "$want_exit" ]; then
    printf 'ok   - %s\n' "$desc"
  else
    printf 'FAIL - %s\n      expected: out=%s exit=%s\n      actual:   out=%s exit=%s\n' \
      "$desc" "$want_out" "$want_exit" "$out" "$rc"
    fails=$((fails+1))
  fi
}

# Single predecessor A -> B (no join).
build_single_pred() { # outfile pred_outcome
  jq -n --arg po "$2" '
    {
      graph: {
        nodes: {
          A: {status:$po, outcome:$po, retry:{attempts:0,max:5}},
          B: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
        },
        edges: [{from:"A",to:"B"}],
        joins: {}
      }
    }
  ' > "$1"
}

# Two-input mode:"all" join J, inputs [X,Y].
build_join() { # outfile x_outcome y_outcome
  jq -n --arg xo "$2" --arg yo "$3" '
    {
      graph: {
        nodes: {
          X: {status:$xo, outcome:$xo, retry:{attempts:0,max:5}},
          Y: {status:$yo, outcome:$yo, retry:{attempts:0,max:5}},
          J: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
        },
        edges: [{from:"X",to:"J"},{from:"Y",to:"J"}],
        joins: {J:{id:"J",mode:"all",inputs:["X","Y"]}}
      }
    }
  ' > "$1"
}

build_single_pred "$TMP/single_running.json" "running"
build_single_pred "$TMP/single_done.json" "done"
build_single_pred "$TMP/single_failed.json" "failed"
build_single_pred "$TMP/single_skipped.json" "skipped"
build_join "$TMP/join_mixed.json" "done" "running"
build_join "$TMP/join_both_done.json" "done" "done"
build_join "$TMP/join_stale.json" "done" "stale"

# (a) single predecessor not-done -> blocked.
run_check "(a) single predecessor running (not done) -> blocked" \
  "$TMP/single_running.json" B blocked 1

# (b) single predecessor done -> ready. Negative control of (a): identical
# fixture shape, only the predecessor's outcome flipped.
run_check "(b) single predecessor done -> ready (negative control of a)" \
  "$TMP/single_done.json" B ready 0

# (c) two-input join, one done one running -> blocked.
run_check "(c) two-input join: one done, one running -> blocked" \
  "$TMP/join_mixed.json" J blocked 1

# (d) two-input join, both done -> ready. Negative control of (c): same
# join shape, the running input flipped to done.
run_check "(d) two-input join: both done -> ready (negative control of c)" \
  "$TMP/join_both_done.json" J ready 0

# (e) a failed predecessor -> blocked (failed is NOT terminal-success).
run_check "(e) failed predecessor -> blocked (failed is not terminal-success)" \
  "$TMP/single_failed.json" B blocked 1
run_check "(e-control) done predecessor -> ready (negative control of e)" \
  "$TMP/single_done.json" B ready 0

# (f) a skipped predecessor -> ready (skipped IS terminal-success).
run_check "(f) skipped predecessor -> ready (skipped is terminal-success)" \
  "$TMP/single_skipped.json" B ready 0
run_check "(f-control) failed predecessor -> blocked (negative control of f)" \
  "$TMP/single_failed.json" B blocked 1

# New `stale` enum value: a dispatched-but-idle node. Must NOT be treated as
# terminal-success — same non-terminal bucket as running/blocked/failed,
# distinct from done/skipped. Exercised inside a join (harder case: one
# input real-done, one input stale).
run_check "(stale) join with one stale input -> blocked (stale is not terminal-success)" \
  "$TMP/join_stale.json" J blocked 1
run_check "(stale-control) join both done -> ready (negative control of stale)" \
  "$TMP/join_both_done.json" J ready 0

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
