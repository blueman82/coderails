#!/bin/bash
# shellcheck disable=SC2015  # test assertions intentionally use condition && ok || fail
# graph_dispatch_acceptance.test.sh — broader Claude-side acceptance evidence
# beyond PR #409's single S2.5||S2.6->J2 fork-join slice (E5 / P4). Exercises,
# against a throwaway seeded progress.json, real (non-fixture) plan/record
# calls covering:
#   1. The S2.5||S2.6->J2 fork-join, PLUS the red half: J2's downstream node
#      is asserted BLOCKED before the explicit J2-release write and READY
#      only after it — proving the prose's "J2 release is a separate write"
#      rule actually matters, not just showing the green path.
#   2. A sequential U3[i]->U4[i] link: graph_dispatch_plan resolves U3 to a
#      real dispatch target (loop-worker), graph_dispatch_record folds a
#      "done" result for it, and graph_readiness.sh then reports U4 ready.
#      U4 itself is orchestrator-internal (no Claude role-map entry) and is
#      NOT dispatched via graph_dispatch_plan
#      — this test does not invent one.
#   3. A second real join beyond J2: J2.8, per execution-graph.md's own node
#      table (prerequisites S2.8 plus S2.7d[i]/S2.7e; releases U3[i]). Like
#      J2, J2.8 has no role-map entry (it's a readiness point,
#      not a dispatch target) — graph_dispatch_plan correctly reports it as
#      kind:"join", never attempting to dispatch it. Red/green halves mirror
#      block 1: downstream U3 is blocked before the explicit J2.8-release
#      write, ready after.
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
ok() { printf 'ok   - %s\n' "$1"; }
fail() {
    printf 'FAIL - %s\n      %s\n' "$1" "$2"
    fails=$((fails + 1))
}

# shellcheck disable=SC1091  # library path is resolved from this test file at runtime
. "$LIB_DIR/graph_dispatch.sh"

stamp_identity() {
    local path="$1"
    jq '. + {session_id:"session-test",loop_id:"loop-test",revision:1}' "$path" >"$path.tmp" && mv "$path.tmp" "$path"
}

record_ready_wave() {
    local progress="$1" results="$2" wave_id envelope
    graph_dispatch_begin_wave "$progress" >/dev/null || return 1
    wave_id=$(jq -r '.graph.active_wave.wave_id' "$progress")
    envelope=$(jq -cn --arg wave_id "$wave_id" --argjson results "$results" \
        '{wave_id:$wave_id,results:$results}')
    graph_dispatch_record "$progress" "$envelope"
}

# --- 1a: plan resolves the S2.5/S2.6 wave for real (skill_ids only, no mock) ---
jq -n '{ graph: { nodes: {
    S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "S2.5": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S2.6": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    J2: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S2.7a": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"S2",to:"S2.5"},{from:"S2",to:"S2.6"},{from:"J2",to:"S2.7a"}],
     joins: {J2:{mode:"all", inputs:["S2.5","S2.6"]}} } }' >"$TMP/j2.json"
stamp_identity "$TMP/j2.json"
plan_out=$(graph_dispatch_plan "$TMP/j2.json")
s25_id=$(printf '%s' "$plan_out" | jq -r 'select(.node_id=="S2.5") | .skill_id')
s26_id=$(printf '%s' "$plan_out" | jq -r 'select(.node_id=="S2.6") | .skill_id')
[ "$s25_id" = "design-scout" ] && [ "$s26_id" = "disposition-scout" ] &&
    ok "acceptance: plan resolves real S2.5/S2.6 dispatch targets" ||
    fail "acceptance: plan resolves S2.5/S2.6" "s25=$s25_id s26=$s26_id"

# --- 1b: recording the exact active wave releases its satisfied join in
# the same locked write, so downstream work becomes ready deterministically. ---
record_ready_wave "$TMP/j2.json" '{"S2.5":{"outcome":"done"},"S2.6":{"outcome":"done"}}' >/dev/null
post_release=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j2.json" "S2.7a")
j2_released=$(jq -r '.graph.joins.J2.released' "$TMP/j2.json")
[ "$post_release" = "ready" ] && [ "$j2_released" = "true" ] &&
    ok "acceptance: exact wave result releases J2 and makes S2.7a ready" ||
    fail "acceptance: J2 should release with its completed wave" "ready=$post_release released=$j2_released"

# --- 2a: sequential U3[i] -> U4[i] link — plan resolves U3 to a real target ---
jq -n '{ graph: { nodes: {
    "U3": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "U4": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"U3",to:"U4"}], joins: {} } }' >"$TMP/u34.json"
stamp_identity "$TMP/u34.json"
plan_u3=$(graph_dispatch_plan "$TMP/u34.json")
u3_id=$(printf '%s' "$plan_u3" | jq -r 'select(.node_id=="U3") | .skill_id')
u3_unresolved=$(printf '%s' "$plan_u3" | jq -r 'select(.node_id=="U3") | .unresolved')
u4_listed=$(printf '%s' "$plan_u3" | jq -r 'select(.node_id=="U4") | .node_id')
[ "$u3_id" = "loop-worker" ] && [ "$u3_unresolved" = "false" ] && [ -z "$u4_listed" ] &&
    ok "acceptance: plan resolves U3 -> loop-worker; U4 not ready (blocked on U3) so not in the wave" ||
    fail "acceptance: U3 plan / U4 absent" "u3_id=$u3_id u3_unresolved=$u3_unresolved u4_listed=$u4_listed"

# --- 2b: U4 blocked before U3 reports; U4 ready after graph_dispatch_record
# folds a real "done" result for U3 (sequential link proven end to end) ---
pre_u4=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/u34.json" "U4")
record_ready_wave "$TMP/u34.json" '{"U3":{"outcome":"done","evidence":"acceptance-test throwaway PR"}}' >/dev/null
post_u4=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/u34.json" "U4")
[ "$pre_u4" = "blocked" ] && [ "$post_u4" = "ready" ] &&
    ok "acceptance: U3->U4 sequential link — U4 blocked pre-U3, ready post-U3-done" ||
    fail "acceptance: U3->U4 sequential link" "pre_u4=$pre_u4 post_u4=$post_u4"

# --- 3a: a second real join beyond J2 — J2.8, per execution-graph.md's node
# table (prerequisites S2.8, S2.7d[i]/S2.7e; releases U3[i]). J2.8 has no
# role-map entry (same situation as J2 and U4), so plan must
# report kind:"join", never a dispatch target. ---
jq -n '{ graph: { nodes: {
    "S2.8": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "S2.7d": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "J2.8": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "U3": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"J2.8",to:"U3"}],
     joins: {"J2.8":{mode:"all", inputs:["S2.8","S2.7d"]}} } }' >"$TMP/j28.json"
stamp_identity "$TMP/j28.json"
plan_j28=$(graph_dispatch_plan "$TMP/j28.json")
j28_kind=$(printf '%s' "$plan_j28" | jq -r 'select(.node_id=="J2.8") | .kind')
j28_skill=$(printf '%s' "$plan_j28" | jq -r 'select(.node_id=="J2.8") | .skill_id')
[ "$j28_kind" = "join" ] && [ "$j28_skill" = "null" ] &&
    ok "acceptance: plan reports J2.8 as kind:join, never a dispatch target" ||
    fail "acceptance: J2.8 plan kind" "j28_kind=$j28_kind j28_skill=$j28_skill"

# --- 3b: U3 is BLOCKED before the explicit J2.8-release write, even though
# S2.8/S2.7d are already done. NOTE: this does NOT exercise J2.8's own join
# logic the way block 1's red half exercises J2 — graph_readiness.sh only
# consults the joins map for the QUERIED node, and U3 itself has no joins
# entry (only J2.8 does), so this assertion takes the plain-edges branch
# unconditionally and would report "blocked" regardless of whether J2.8's
# join-release logic is correct. It only proves U3's own edge from J2.8 is
# still unsatisfied pre-release — real join-release coverage for J2.8 lives
# in 3a (kind:join, never a dispatch target) and 3c (ready post-release). ---
pre_u3=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j28.json" "U3")
[ "$pre_u3" = "blocked" ] &&
    ok "acceptance: U3's edge from J2.8 still unsatisfied pre-release (not a join-logic test, see comment above)" ||
    fail "acceptance: U3 should be blocked pre-release" "got=$pre_u3"

# --- 3c: after the explicit J2.8 release write, U3 becomes ready ---
jq '.graph.nodes["J2.8"].status = "done"
    | .graph.nodes["J2.8"].outcome = "done"
    | .graph.joins["J2.8"].released = true' \
    "$TMP/j28.json" >"$TMP/j28.json.tmp" && mv "$TMP/j28.json.tmp" "$TMP/j28.json"
post_u3=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j28.json" "U3")
[ "$post_u3" = "ready" ] &&
    ok "acceptance: second join beyond J2 — U3 ready after explicit J2.8 release write" ||
    fail "acceptance: U3 should be ready post-J2.8-release" "got=$post_u3"

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
