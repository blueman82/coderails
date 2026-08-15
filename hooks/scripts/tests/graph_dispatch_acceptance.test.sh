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
#   3. A second join beyond J2: S9-wiki and S9-docs, chained sequentially
#      per execution-graph.md's own S9-wiki -> S9-docs edge (both resolve
#      cleanly in skills/index.yaml: wiki-writer, docs-auditor).
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

# --- 3: a second join beyond J2 — S9-wiki -> S9-docs, both real index.yaml
# targets (wiki-writer, docs-auditor), chained sequentially per
# execution-graph.md's own S9-wiki -> S9-docs edge ---
jq -n '{ graph: { nodes: {
    "S9-wiki": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
    "S9-docs": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
  }, edges: [{from:"S9-wiki",to:"S9-docs"}], joins: {} } }' > "$TMP/s9.json"
plan_s9=$(graph_dispatch_plan "$TMP/s9.json" "$INDEX_YAML")
wiki_id=$(printf '%s' "$plan_s9" | jq -r 'select(.node_id=="S9-wiki") | .skill_id')
pre_docs=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/s9.json" "S9-docs")
graph_dispatch_record "$TMP/s9.json" '{"S9-wiki":{"outcome":"done","evidence":"acceptance-test throwaway wiki PR"}}' >/dev/null
post_docs_target=$(graph_dispatch_plan "$TMP/s9.json" "$INDEX_YAML" | jq -r 'select(.node_id=="S9-docs") | .skill_id')
post_docs_ready=$(bash "$LIB_DIR/graph_readiness.sh" "$TMP/s9.json" "S9-docs")
[ "$wiki_id" = "wiki-writer" ] && [ "$pre_docs" = "blocked" ] \
  && [ "$post_docs_target" = "docs-auditor" ] && [ "$post_docs_ready" = "ready" ] \
  && ok "acceptance: second join beyond J2 — S9-wiki(wiki-writer) -> S9-docs(docs-auditor) end to end" \
  || fail "acceptance: S9-wiki -> S9-docs" "wiki_id=$wiki_id pre_docs=$pre_docs post_docs_target=$post_docs_target post_docs_ready=$post_docs_ready"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
