#!/bin/bash
# shellcheck disable=SC2015  # test assertions intentionally use condition && ok || fail
# graph_dispatch_j12_s9.test.sh — closes PR #412's own disclosed gap
# ("S9-wiki/S9-docs sequential, no acceptance evidence exercises this link")
# and extends the J2-style explicit join-release pattern to J12-all-units.
# Real (non-fixture) plan/record calls against a throwaway seeded
# progress.json and the real Claude role map. Covers:
#   1. S9-wiki -> S9-docs sequential resolution: graph_dispatch_plan
#      resolves S9-wiki to wiki-writer, graph_dispatch_record folds a
#      "done" result for it, graph_readiness.sh then reports S9-docs
#      ready (it wasn't before), and graph_dispatch_plan resolves S9-docs
#      to docs-auditor. Plain sequential edge, no join involved.
#   2/3. J12-all-units join, red half then green half: two
#      U4b-merge-gate[i]-equivalent predecessor nodes are recorded done
#      via graph_dispatch_record, but S9-wiki (downstream of the join)
#      stays blocked until the orchestrator performs the explicit second
#      write setting J12-all-units's own .status/.outcome to done —
#      mirrors PR #412's J2 red/green halves exactly.
#   4. graph_dispatch_plan reports J12-all-units as kind:"join", never a
#      dispatch target — same assertion style as PR #412's J2.8 coverage.
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

record_ready_wave() {
    local progress="$1" results="$2" wave_id envelope
    graph_dispatch_begin_wave "$progress" >/dev/null || return 1
    wave_id=$(jq -r '.graph.active_wave.wave_id' "$progress")
    envelope=$(jq -cn --arg wave_id "$wave_id" --argjson results "$results" \
        '{wave_id:$wave_id,results:$results}')
    graph_dispatch_record "$progress" "$envelope"
}

# --- 1a: plan resolves S9-wiki for real (skill_id only, no mock); S9-docs
# is not yet in the wave (blocked on S9-wiki) ---
jq -n '{ graph: { nodes: {
    "J12-all-units": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "S9-wiki": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S9-docs": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"J12-all-units",to:"S9-wiki"},{from:"S9-wiki",to:"S9-docs"}], joins: {} } }' >"$TMP/s9.json"
plan1=$(graph_dispatch_plan "$TMP/s9.json")
s9wiki_id=$(printf '%s' "$plan1" | jq -r 'select(.node_id=="S9-wiki") | .skill_id')
s9wiki_unresolved=$(printf '%s' "$plan1" | jq -r 'select(.node_id=="S9-wiki") | .unresolved')
s9docs_listed=$(printf '%s' "$plan1" | jq -r 'select(.node_id=="S9-docs") | .node_id')
[ "$s9wiki_id" = "wiki-writer" ] && [ "$s9wiki_unresolved" = "false" ] && [ -z "$s9docs_listed" ] &&
    ok "S9-wiki -> wiki-writer; S9-docs not ready (blocked on S9-wiki) so not in the wave" ||
    fail "S9-wiki plan / S9-docs absent" "s9wiki_id=$s9wiki_id unresolved=$s9wiki_unresolved s9docs_listed=$s9docs_listed"

# --- 1b: S9-docs blocked before S9-wiki reports; ready after
# graph_dispatch_record folds a real "done" result for S9-wiki ---
pre_s9docs=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/s9.json" "S9-docs")
record_ready_wave "$TMP/s9.json" '{"S9-wiki":{"outcome":"done","evidence":"acceptance-test throwaway wiki ingest"}}' >/dev/null
post_s9docs=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/s9.json" "S9-docs")
[ "$pre_s9docs" = "blocked" ] && [ "$post_s9docs" = "ready" ] &&
    ok "S9-wiki -> S9-docs sequential link — S9-docs blocked pre-S9-wiki, ready post-S9-wiki-done" ||
    fail "S9-wiki->S9-docs sequential link" "pre_s9docs=$pre_s9docs post_s9docs=$post_s9docs"

# --- 1c: plan now resolves S9-docs for real ---
plan2=$(graph_dispatch_plan "$TMP/s9.json")
s9docs_id=$(printf '%s' "$plan2" | jq -r 'select(.node_id=="S9-docs") | .skill_id')
s9docs_unresolved=$(printf '%s' "$plan2" | jq -r 'select(.node_id=="S9-docs") | .unresolved')
[ "$s9docs_id" = "docs-auditor" ] && [ "$s9docs_unresolved" = "false" ] &&
    ok "plan resolves S9-docs -> docs-auditor once S9-wiki is terminal-success" ||
    fail "S9-docs plan" "s9docs_id=$s9docs_id unresolved=$s9docs_unresolved"

# --- 2: both U4b-merge-gate[i] predecessors complete in one exact wave;
# the locked result write releases J12-all-units and its downstream work. ---
jq -n '{ graph: { nodes: {
    "U4b-merge-gate[1]": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "U4b-merge-gate[2]": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "J12-all-units": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S9-wiki": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"J12-all-units",to:"S9-wiki"}],
     joins: {"J12-all-units":{mode:"all", inputs:["U4b-merge-gate[1]","U4b-merge-gate[2]"]}} } }' >"$TMP/j12.json"
record_ready_wave "$TMP/j12.json" '{"U4b-merge-gate[1]":{"outcome":"done"},"U4b-merge-gate[2]":{"outcome":"done"}}' >/dev/null
post_release=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/j12.json" "S9-wiki")
j12_released=$(jq -r '.graph.joins["J12-all-units"].released' "$TMP/j12.json")
[ "$post_release" = "ready" ] && [ "$j12_released" = "true" ] &&
    ok "completed wave releases J12-all-units and makes S9-wiki ready" ||
    fail "J12-all-units should release with its completed wave" "ready=$post_release released=$j12_released"

# --- 4: plan reports J12-all-units as kind:"join", never a dispatch
# target, once its join inputs are already terminal-success ---
jq -n '{ graph: { nodes: {
    "U4b-merge-gate[1]": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "U4b-merge-gate[2]": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
    "J12-all-units": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S9-wiki": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"J12-all-units",to:"S9-wiki"}],
     joins: {"J12-all-units":{mode:"all", inputs:["U4b-merge-gate[1]","U4b-merge-gate[2]"]}} } }' >"$TMP/j12b.json"
plan_j12=$(graph_dispatch_plan "$TMP/j12b.json")
j12_kind=$(printf '%s' "$plan_j12" | jq -r 'select(.node_id=="J12-all-units") | .kind')
j12_skill=$(printf '%s' "$plan_j12" | jq -r 'select(.node_id=="J12-all-units") | .skill_id')
[ "$j12_kind" = "join" ] && [ "$j12_skill" = "null" ] &&
    ok "plan reports J12-all-units as kind:join, never a dispatch target" ||
    fail "J12-all-units plan kind" "j12_kind=$j12_kind j12_skill=$j12_skill"

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
