#!/bin/bash
# Integration test: A || B -> C fan-out/join shape, proven end-to-end via
# actual graph_readiness.sh invocations (not hand-asserted join logic) — the
# acceptance shape for U3_graph_executor's fan-out/join contract.
#
# Shape: P (predecessor) -> A, P -> B (fan-out); A -> C, B -> C, joined by a
# mode:"all" join C with inputs [A,B] (fan-in). Each wave below is a
# SEPARATE literal fixture file (jq -n, same convention as
# graph_contract.test.sh) — this test never mutates graph.nodes on an
# existing file; only the orchestrator's als_atomic_progress_update does
# that, once per real wave (see loop_state_common.sh).
# shellcheck disable=SC2015 # Final assertion chain is the suite's established tally idiom.
set -u

HELPER="$(cd "$(dirname "$0")/.." && pwd)/lib/graph_readiness.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
run_check() { # desc, fixture, node, expected_stdout, expected_exit
    local desc="$1" fixture="$2" node="$3" want_out="$4" want_exit="$5"
    local out rc
    out=$(bash "$HELPER" "$fixture" "$node")
    rc=$?
    if [ "$out" = "$want_out" ] && [ "$rc" = "$want_exit" ]; then
        printf 'ok   - %s\n' "$desc"
    else
        printf 'FAIL - %s\n      expected: out=%s exit=%s\n      actual:   out=%s exit=%s\n' \
            "$desc" "$want_out" "$want_exit" "$out" "$rc"
        fails=$((fails + 1))
    fi
}

build_fixture() { # outfile a_outcome b_outcome
    jq -n --arg ao "$2" --arg bo "$3" '
    {
      session_id:"session-test", loop_id:"loop-test", revision:1,
      graph: {
        nodes: {
          P: {status:"done", outcome:"done", retry:{attempts:0,max:5}},
          A: {status:$ao, outcome:$ao, retry:{attempts:0,max:5}},
          B: {status:$bo, outcome:$bo, retry:{attempts:0,max:5}},
          C: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
        },
        edges: [{from:"P",to:"A"},{from:"P",to:"B"},{from:"A",to:"C"},{from:"B",to:"C"}],
        joins: {C:{id:"C",mode:"all",inputs:["A","B"]}}
      }
    }
  ' >"$1"
}

# Wave 1: neither A nor B has finished yet, but their shared predecessor P is
# terminal-success -> both A and B are ready to dispatch; the join C is
# blocked because neither fan-out input is done yet.
build_fixture "$TMP/wave1.json" "pending" "pending"
run_check "wave1: A ready (predecessor P is done)" "$TMP/wave1.json" A ready 0
run_check "wave1: B ready (predecessor P is done)" "$TMP/wave1.json" B ready 0
run_check "wave1: C blocked (neither A nor B is done)" "$TMP/wave1.json" C blocked 1

# Wave 2: only A has finished -> join still blocked on B.
build_fixture "$TMP/wave2.json" "done" "pending"
run_check "wave2: C blocked while B is not done" "$TMP/wave2.json" C blocked 1

# Wave 2b: only B has finished -> join still blocked on A (symmetric case).
build_fixture "$TMP/wave2b.json" "pending" "done"
run_check "wave2b: C blocked while A is not done" "$TMP/wave2b.json" C blocked 1

# Wave 3: both A and B are done -> the join releases.
build_fixture "$TMP/wave3.json" "done" "done"
run_check "wave3: C ready once both A and B are done" "$TMP/wave3.json" C ready 0

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
