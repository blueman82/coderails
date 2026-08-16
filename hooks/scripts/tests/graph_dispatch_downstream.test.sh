#!/bin/bash
# Characterization test for graph_dispatch_plan's CURRENT resolution
# outcome at ten downstream graph nodes, against the REAL
# skills/index.yaml (not a stub). This does not assert what SHOULD
# resolve — it documents what DOES resolve today, so any future change
# to skills/index.yaml's graph_role seeding is a visible, deliberate
# diff against this test, not a silent behaviour change.
#
#   S9-wiki, S9-docs        -> resolve cleanly (one agent-tier match each)
#   U4b-review               -> unresolved (3 same-tier matches)
#   U4b-merge-gate            -> unresolved (2 command-tier matches)
#   U5, U5-repair, U10-respawn, S13-proof, S13-retro, S13-complete
#                             -> unresolved (no graph_role entry in index.yaml)
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

# Seed all ten downstream node ids as ready, each with an edge from a
# "done" ancestor S2 (mirrors graph_dispatch.test.sh's own convention).
jq -n '
  { graph: { nodes: (
      { S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}, graph_role:"S2"} }
      + (
        ["S13-complete","S13-proof","S13-retro","S9-docs","S9-wiki",
         "U10-respawn","U4b-merge-gate","U4b-review","U5","U5-repair"]
        | map({(.): {status:"pending", outcome:"pending", retry:{attempts:0,max:5}, graph_role:.}})
        | add
      )
    ),
    edges: (
      ["S13-complete","S13-proof","S13-retro","S9-docs","S9-wiki",
       "U10-respawn","U4b-merge-gate","U4b-review","U5","U5-repair"]
      | map({from:"S2", to:.})
    ),
    joins: {} } }
' > "$TMP/plan.json"

out=$(graph_dispatch_plan "$TMP/plan.json" "$INDEX_YAML")

assert_resolved() { # node_id expected_skill_id
  local node="$1" expected="$2"
  local skill_id unresolved
  skill_id=$(printf '%s' "$out" | jq -r --arg n "$node" 'select(.node_id==$n) | .skill_id')
  unresolved=$(printf '%s' "$out" | jq -r --arg n "$node" 'select(.node_id==$n) | .unresolved')
  [ "$skill_id" = "$expected" ] && [ "$unresolved" = "false" ] \
    && ok "$node -> $expected (resolved)" \
    || fail "$node -> $expected (resolved)" "skill_id=$skill_id unresolved=$unresolved"
}

assert_unresolved() { # node_id
  local node="$1"
  local skill_id unresolved
  skill_id=$(printf '%s' "$out" | jq -r --arg n "$node" 'select(.node_id==$n) | .skill_id')
  unresolved=$(printf '%s' "$out" | jq -r --arg n "$node" 'select(.node_id==$n) | .unresolved')
  [ "$skill_id" = "null" ] && [ "$unresolved" = "true" ] \
    && ok "$node -> unresolved" \
    || fail "$node -> unresolved" "skill_id=$skill_id unresolved=$unresolved"
}

assert_resolved "S9-wiki" "wiki-writer"
assert_resolved "S9-docs" "docs-auditor"

assert_unresolved "U4b-review"
assert_unresolved "U4b-merge-gate"
assert_unresolved "U5"
assert_unresolved "U5-repair"
assert_unresolved "U10-respawn"
assert_unresolved "S13-proof"
assert_unresolved "S13-retro"
assert_unresolved "S13-complete"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
