#!/bin/bash
# AC-9: a "stale" outcome must never be written alone. Per loop-state.md's
# stale field docs and SKILL.md Phase 4 ("idle is not failure"), a bare idle
# signal is not sufficient evidence -- any node whose merged status OR
# outcome is "stale" must carry a sibling stale_check field
# ({"checked":true,"method":"<string>","result":"<string>"}) in THIS SAME
# wave's own result, or graph_executor_apply_wave refuses the write. "THIS
# SAME wave" is validated against the wave-results argument itself, not
# the post-merge node state -- an earlier wave's stale_check surviving in
# progress.json must not satisfy a later wave's own bare stale write (see
# the multi-wave test below).
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
ok() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n      %s\n' "$1" "$2"; fails=$((fails+1)); }

. "$LIB_DIR/graph_executor.sh"

fresh_fixture() { # outfile
  jq -n '
    { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
               edges: [], joins: {} },
      decisions_absorbed: [] }
  ' > "$1"
}

# --- refuses: stale with no stale_check at all ---
fresh_fixture "$TMP/f1.json"
graph_executor_apply_wave "$TMP/f1.json" '{"A":{"status":"stale","outcome":"stale"}}'
rc1=$?
status_after1=$(jq -r '.graph.nodes.A.status' "$TMP/f1.json")
[ "$rc1" -ne 0 ] && [ "$status_after1" = "pending" ] \
  && ok "bare stale (no stale_check) refused, node unchanged" \
  || fail "bare stale (no stale_check) refused" "rc=$rc1 status_after=$status_after1"

# --- refuses: stale_check present but checked:false ---
fresh_fixture "$TMP/f2.json"
graph_executor_apply_wave "$TMP/f2.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":false,"method":"gh pr view","result":"no PR found"}}}'
rc2=$?
[ "$rc2" -ne 0 ] && ok "stale_check.checked:false refused" || fail "stale_check.checked:false refused" "rc=$rc2"

# --- refuses: stale_check present but method/result missing or empty ---
fresh_fixture "$TMP/f3.json"
graph_executor_apply_wave "$TMP/f3.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":true,"method":"","result":"no PR found"}}}'
rc3=$?
[ "$rc3" -ne 0 ] && ok "stale_check.method empty refused" || fail "stale_check.method empty refused" "rc=$rc3"

fresh_fixture "$TMP/f4.json"
graph_executor_apply_wave "$TMP/f4.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":true,"method":"gh pr view"}}}'
rc4=$?
[ "$rc4" -ne 0 ] && ok "stale_check.result missing refused" || fail "stale_check.result missing refused" "rc=$rc4"

# --- succeeds: stale WITH a valid stale_check lands both fields together ---
fresh_fixture "$TMP/f5.json"
graph_executor_apply_wave "$TMP/f5.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":true,"method":"gh pr view","result":"no PR found"}}}'
rc5=$?
status_after5=$(jq -r '.graph.nodes.A.status' "$TMP/f5.json")
stale_check_after5=$(jq -c '.graph.nodes.A.stale_check' "$TMP/f5.json")
[ "$rc5" -eq 0 ] && [ "$status_after5" = "stale" ] \
  && [ "$stale_check_after5" = '{"checked":true,"method":"gh pr view","result":"no PR found"}' ] \
  && ok "stale WITH valid stale_check succeeds, both fields land together" \
  || fail "stale WITH valid stale_check succeeds" "rc=$rc5 status=$status_after5 stale_check=$stale_check_after5"

# --- unaffected: a non-stale write needs no stale_check ---
fresh_fixture "$TMP/f6.json"
graph_executor_apply_wave "$TMP/f6.json" '{"A":{"status":"done","outcome":"done"}}'
rc6=$?
[ "$rc6" -eq 0 ] && ok "non-stale write requires no stale_check (unaffected)" \
  || fail "non-stale write requires no stale_check" "rc=$rc6"

# --- refuses: outcome:"stale" alone (status not stale) still requires stale_check ---
fresh_fixture "$TMP/f7.json"
graph_executor_apply_wave "$TMP/f7.json" '{"A":{"status":"blocked","outcome":"stale"}}'
rc7=$?
[ "$rc7" -ne 0 ] && ok "outcome:stale alone (status not stale) still requires stale_check" \
  || fail "outcome:stale alone still requires stale_check" "rc=$rc7"

# --- multi-wave: a stale_check from an EARLIER wave must not satisfy a
# LATER wave's own stale write. The guard must validate THIS wave's own
# result payload, not the merged node state (which still carries the old
# stale_check from wave 1's successful write).
fresh_fixture "$TMP/f8.json"
graph_executor_apply_wave "$TMP/f8.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":true,"method":"gh pr view","result":"no PR found"}}}'
rc8a=$?
graph_executor_apply_wave "$TMP/f8.json" '{"A":{"status":"stale","outcome":"stale"}}'
rc8b=$?
stale_check_after8=$(jq -c '.graph.nodes.A.stale_check' "$TMP/f8.json")
[ "$rc8a" -eq 0 ] && [ "$rc8b" -ne 0 ] \
  && [ "$stale_check_after8" = '{"checked":true,"method":"gh pr view","result":"no PR found"}' ] \
  && ok "a later wave's bare stale write is refused even though an earlier wave's stale_check survives in merged state" \
  || fail "later wave without its own stale_check is refused" "rc8a=$rc8a rc8b=$rc8b stale_check_after=$stale_check_after8"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
