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

# --- Doc-wiring checks: SKILL.md must instruct the orchestrator to call this
# script before dispatch, and the instruction must live in the "Execution
# graph" section specifically — not merely appear somewhere in the file.
# A bare whole-file `grep -q` cannot tell "in this section" from "anywhere",
# so each assertion below is section-anchored (extract the section's own
# text, then grep only that) and paired with a positive/negative synthetic
# fixture proving the extraction actually discriminates location, the same
# paired-negative-control discipline used for the fixtures above.

SKILL="$(cd "$(dirname "$0")/../../.." && pwd)/skills/agentic-loop/SKILL.md"
SECTION_START='The phases below are a dependency graph'
SECTION_END='^### Phases -2 through 2.7'

extract_section() { # file, start_regex, end_regex
  local file="$1" start="$2" end="$3"
  awk -v start="$start" -v end="$end" '
    $0 ~ start { insec=1 }
    insec && $0 ~ end && $0 !~ start { exit }
    insec { print }
  ' "$file"
}

assert_in_section() { # desc, file, pattern
  local desc="$1" file="$2" pattern="$3"
  if extract_section "$file" "$SECTION_START" "$SECTION_END" | grep -q -- "$pattern"; then
    printf 'ok   - %s\n' "$desc"
  else
    printf 'FAIL - %s\n      pattern not found within the Execution-graph section of %s\n' "$desc" "$file"
    fails=$((fails+1))
  fi
}

assert_not_in_section() { # desc, file, pattern
  local desc="$1" file="$2" pattern="$3"
  if extract_section "$file" "$SECTION_START" "$SECTION_END" | grep -q -- "$pattern"; then
    printf 'FAIL - %s\n      pattern unexpectedly found within the Execution-graph section of %s\n' "$desc" "$file"
    fails=$((fails+1))
  else
    printf 'ok   - %s\n' "$desc"
  fi
}

# Synthetic fixtures proving the section-anchored extraction actually
# discriminates "inside the section" from "elsewhere in the file" — a mutant
# check using bare `grep -q graph_readiness.sh "$file"` would pass on BOTH
# fixtures below, since the string appears somewhere in each; only the
# section-anchored check is expected to tell them apart.
cat > "$TMP/doc_positive.md" <<'EOF'
## The phases

table stuff here, irrelevant.

The phases below are a dependency graph, not a queue. A node is ready only when
its prerequisites and readiness predicate are true. Run ready independent nodes
in one wave, but preserve every listed dependency, using graph_readiness.sh to
determine per-node readiness before dispatch.

### Execution graph — stable contract

Node IDs are stable identifiers.

### Phases -2 through 2.7 — setup

Phase 3 talks about something else entirely, no mention of the script here.
EOF

cat > "$TMP/doc_negative.md" <<'EOF'
## The phases

table stuff here, irrelevant.

The phases below are a dependency graph, not a queue. A node is ready only when
its prerequisites and readiness predicate are true. Run ready independent nodes
in one wave, but preserve every listed dependency.

### Execution graph — stable contract

Node IDs are stable identifiers.

### Phases -2 through 2.7 — setup

Phase 3 mentions graph_readiness.sh here, outside the target section.
EOF

# Control: whole-file grep (the old, non-discriminating check) sees the
# script mention in BOTH fixtures — proving the string's mere presence in
# the file is not, by itself, evidence it's in the right section.
run_check_bool() { # desc, condition_true
  if [ "$2" = "true" ]; then printf 'ok   - %s\n' "$1"; else
    printf 'FAIL - %s\n' "$1"; fails=$((fails+1)); fi
}
grep -q 'graph_readiness.sh' "$TMP/doc_positive.md" && pos_whole=true || pos_whole=false
grep -q 'graph_readiness.sh' "$TMP/doc_negative.md" && neg_whole=true || neg_whole=false
run_check_bool "(control) whole-file grep matches positive fixture (as expected)" "$pos_whole"
run_check_bool "(control) whole-file grep ALSO matches negative fixture (proves bare grep -q does not discriminate section)" "$neg_whole"

assert_in_section "positive fixture: graph_readiness.sh correctly found inside the Execution-graph section" \
  "$TMP/doc_positive.md" 'graph_readiness.sh'
assert_not_in_section "negative fixture: graph_readiness.sh mentioned only in Phase 3 must NOT count as in-section (negative control proving extraction discriminates)" \
  "$TMP/doc_negative.md" 'graph_readiness.sh'

# The real assertion: SKILL.md's Execution-graph section names the script as
# the pre-dispatch readiness mechanism.
assert_in_section "SKILL.md's Execution-graph section names graph_readiness.sh as the pre-dispatch readiness mechanism" \
  "$SKILL" 'graph_readiness.sh'

# Vocabulary: the instruction must not call this script a "gate" (it is an
# advisory, read-only query, wired into no hook — "gate" is reserved in this
# repo's vocabulary for a hook-enforced deny). Checked on the specific line
# naming the script, not the whole section, since the section legitimately
# discusses unrelated merge gates elsewhere.
script_line=$(extract_section "$SKILL" "$SECTION_START" "$SECTION_END" | grep 'graph_readiness.sh' | head -1)
if [ -n "$script_line" ] && ! printf '%s' "$script_line" | grep -qi 'gate'; then
  printf 'ok   - %s\n' "graph_readiness.sh mention does not call the script a \"gate\""
else
  printf 'FAIL - %s\n      line: %s\n' "graph_readiness.sh mention wrongly calls the script a \"gate\", or the line was not found" "$script_line"
  fails=$((fails+1))
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
