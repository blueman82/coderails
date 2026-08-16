#!/bin/bash
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
#      U4 itself is orchestrator-internal (no index.yaml graph_role match,
#      confirmed this session) and is NOT dispatched via graph_dispatch_plan
#      — this test does not invent one.
#   3. A second real join beyond J2: J2.8, per execution-graph.md's own node
#      table (prerequisites S2.8 plus S2.7d[i]/S2.7e; releases U3[i]). Like
#      J2, J2.8 has no index.yaml graph_role entry (it's a readiness point,
#      not a dispatch target) — graph_dispatch_plan correctly reports it as
#      kind:"join", never attempting to dispatch it. Red/green halves mirror
#      block 1: downstream U3 is blocked before the explicit J2.8-release
#      write, ready after.
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
REPO_ROOT="$(cd "$LIB_DIR/../../.." && pwd)"
INDEX_YAML="$REPO_ROOT/skills/index.yaml"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
ok() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n      %s\n' "$1" "$2"; fails=$((fails+1)); }

. "$LIB_DIR/graph_dispatch.sh"
[ -f "$INDEX_YAML" ] || { echo "FATAL: skills/index.yaml not found at $INDEX_YAML"; exit 1; }

# --- 1a: plan resolves the S2.5/S2.6 wave for real (skill_ids only, no mock) ---
jq -n '{ graph: { nodes: {
    S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "S2.5": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S2.6": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    J2: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S2.7a": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"S2",to:"S2.5"},{from:"S2",to:"S2.6"},{from:"J2",to:"S2.7a"}],
     joins: {J2:{mode:"all", inputs:["S2.5","S2.6"]}} } }' > "$TMP/j2.json"
plan_out=$(graph_dispatch_plan "$TMP/j2.json" "$INDEX_YAML")
s25_id=$(printf '%s' "$plan_out" | jq -r 'select(.node_id=="S2.5") | .skill_id')
s26_id=$(printf '%s' "$plan_out" | jq -r 'select(.node_id=="S2.6") | .skill_id')
[ "$s25_id" = "design-scout" ] && [ "$s26_id" = "disposition-scout" ] \
  && ok "acceptance: plan resolves real S2.5/S2.6 dispatch targets" \
  || fail "acceptance: plan resolves S2.5/S2.6" "s25=$s25_id s26=$s26_id"

# --- 1b (RED HALF): S2.7a is BLOCKED before the explicit J2-release write,
# even though S2.5/S2.6 have both already been recorded done via
# graph_dispatch_record. This is the prose rule under test: record alone
# does not release the join. ---
graph_dispatch_record "$TMP/j2.json" '{"S2.5":{"outcome":"done"},"S2.6":{"outcome":"done"}}' >/dev/null
pre_release=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j2.json" "S2.7a")
[ "$pre_release" = "blocked" ] \
  && ok "acceptance (red half): S2.7a still blocked after record, before explicit J2 release" \
  || fail "acceptance red half: S2.7a should be blocked pre-release" "got=$pre_release"

# --- 1c: after the explicit second write releasing J2, S2.7a becomes ready ---
jq '.graph.nodes["J2"].status = "done" | .graph.nodes["J2"].outcome = "done"' "$TMP/j2.json" > "$TMP/j2.json.tmp" && mv "$TMP/j2.json.tmp" "$TMP/j2.json"
post_release=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j2.json" "S2.7a")
[ "$post_release" = "ready" ] \
  && ok "acceptance: S2.7a ready after explicit J2 release write" \
  || fail "acceptance: S2.7a should be ready post-release" "got=$post_release"

# --- 2a: sequential U3[i] -> U4[i] link — plan resolves U3 to a real target ---
jq -n '{ graph: { nodes: {
    "U3": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "U4": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"U3",to:"U4"}], joins: {} } }' > "$TMP/u34.json"
plan_u3=$(graph_dispatch_plan "$TMP/u34.json" "$INDEX_YAML")
u3_id=$(printf '%s' "$plan_u3" | jq -r 'select(.node_id=="U3") | .skill_id')
u3_unresolved=$(printf '%s' "$plan_u3" | jq -r 'select(.node_id=="U3") | .unresolved')
u4_listed=$(printf '%s' "$plan_u3" | jq -r 'select(.node_id=="U4") | .node_id')
[ "$u3_id" = "loop-worker" ] && [ "$u3_unresolved" = "false" ] && [ -z "$u4_listed" ] \
  && ok "acceptance: plan resolves U3 -> loop-worker; U4 not ready (blocked on U3) so not in the wave" \
  || fail "acceptance: U3 plan / U4 absent" "u3_id=$u3_id u3_unresolved=$u3_unresolved u4_listed=$u4_listed"

# --- 2b: U4 blocked before U3 reports; U4 ready after graph_dispatch_record
# folds a real "done" result for U3 (sequential link proven end to end) ---
pre_u4=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/u34.json" "U4")
graph_dispatch_record "$TMP/u34.json" '{"U3":{"outcome":"done","evidence":"acceptance-test throwaway PR"}}' >/dev/null
post_u4=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/u34.json" "U4")
[ "$pre_u4" = "blocked" ] && [ "$post_u4" = "ready" ] \
  && ok "acceptance: U3->U4 sequential link — U4 blocked pre-U3, ready post-U3-done" \
  || fail "acceptance: U3->U4 sequential link" "pre_u4=$pre_u4 post_u4=$post_u4"

# --- 3a: a second real join beyond J2 — J2.8, per execution-graph.md's node
# table (prerequisites S2.8, S2.7d[i]/S2.7e; releases U3[i]). J2.8 has no
# graph_role entry in index.yaml (same situation as J2 and U4), so plan must
# report kind:"join", never a dispatch target. ---
jq -n '{ graph: { nodes: {
    "S2.8": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "S2.7d": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "J2.8": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "U3": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"J2.8",to:"U3"}],
     joins: {"J2.8":{mode:"all", inputs:["S2.8","S2.7d"]}} } }' > "$TMP/j28.json"
plan_j28=$(graph_dispatch_plan "$TMP/j28.json" "$INDEX_YAML")
j28_kind=$(printf '%s' "$plan_j28" | jq -r 'select(.node_id=="J2.8") | .kind')
j28_skill=$(printf '%s' "$plan_j28" | jq -r 'select(.node_id=="J2.8") | .skill_id')
[ "$j28_kind" = "join" ] && [ "$j28_skill" = "null" ] \
  && ok "acceptance: plan reports J2.8 as kind:join, never a dispatch target" \
  || fail "acceptance: J2.8 plan kind" "j28_kind=$j28_kind j28_skill=$j28_skill"

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
[ "$pre_u3" = "blocked" ] \
  && ok "acceptance: U3's edge from J2.8 still unsatisfied pre-release (not a join-logic test, see comment above)" \
  || fail "acceptance: U3 should be blocked pre-release" "got=$pre_u3"

# --- 3c: after the explicit J2.8 release write, U3 becomes ready ---
jq '.graph.nodes["J2.8"].status = "done" | .graph.nodes["J2.8"].outcome = "done"' "$TMP/j28.json" > "$TMP/j28.json.tmp" && mv "$TMP/j28.json.tmp" "$TMP/j28.json"
post_u3=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j28.json" "U3")
[ "$post_u3" = "ready" ] \
  && ok "acceptance: second join beyond J2 — U3 ready after explicit J2.8 release write" \
  || fail "acceptance: U3 should be ready post-J2.8-release" "got=$post_u3"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
