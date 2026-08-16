#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  parallel_review_harness.sh │ cross-script wiring proof for parallel-review
#
#  Drives the real fan-out -> dual-write -> join call sequence across
#  parallel_review.sh (Claude's provider-side writer) and
#  parallel_review_join.sh (the neutral fan-out+join module) with real files
#  on disk. This is NOT a re-test of either module's own logic — PR #415's
#  test suite already covers every hard-stop case at the join-module level,
#  and parallel_review.test.sh already covers parallel_review::run's own
#  validation. This harness's only job: prove the call-site contract (same
#  run_id/revision/head triple passed to every call) is actually honored by
#  real code, not just assumed. One pass-case function only — every
#  hard-stop/negative case is already exercised by parallel_review_join.sh's
#  own tests.
#
#  The Codex evidence leg (step 3 below) is a HAND-AUTHORED FIXTURE, never a
#  live Codex reviewer invocation — this machine cannot run Codex. It is
#  shaped to match codex/tests/test_graph_runtime.py's own record() helper
#  (branch codex/mixed-provider-review-implementation @ a6018c86), read-only
#  reference, never imported or sourced.
#═══════════════════════════════════════════════════════════════════════════════

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HARNESS_DIR/parallel_review.sh"
. "$HARNESS_DIR/parallel_review_join.sh"

# parallel_review_harness::run_pass_case <artifact_path> <run_id> <revision> <head> <node> <work_dir>
# Writes canonical.json, claude.json, codex.json under <work_dir>, then
# evaluates the join. Prints the join record's .outcome to stdout.
# Exit 0 if outcome is "pass", exit 1 otherwise (including any write/eval
# failure along the way).
parallel_review_harness::run_pass_case() {
  local artifact="$1" run_id="$2" revision="$3" head_sha="$4" node="$5" work_dir="$6"

  mkdir -p "$work_dir"
  local canonical_out="$work_dir/canonical.json"
  local claude_out="$work_dir/claude.json"
  local codex_out="$work_dir/codex.json"

  # Step 1: neutral dispatcher writes the canonical frozen-input digest.
  if ! PARALLEL_REVIEW_DISPATCHER="orchestrator" parallel_review_fanout::write_digest \
      "$artifact" "$run_id" "$revision" "$head_sha" "$node" "$canonical_out"; then
    echo "parallel_review_harness::run_pass_case: fan-out digest write failed" >&2
    return 1
  fi

  # Step 2: Claude's REAL evidence writer, via a canned reviewer callback.
  # The callback is a stand-in for a real deploy-safety-reviewer agent
  # invocation — this harness proves the WIRING, not that a real reviewer
  # agent produces a real verdict (out of scope).
  _parallel_review_harness_canned_approve() {
    printf '%s\n' '{"outcome":"approve","reasoning":"harness stand-in reviewer: wiring check only"}'
  }
  if ! PARALLEL_REVIEW_REVIEWER=_parallel_review_harness_canned_approve parallel_review::run \
      "$artifact" "$run_id" "$revision" "$head_sha" "$node" "$claude_out"; then
    echo "parallel_review_harness::run_pass_case: claude evidence write failed" >&2
    return 1
  fi

  # Step 3: FIXTURE — not a live Codex reviewer invocation; this machine
  # cannot run Codex. Hand-authored to match codex/tests/test_graph_runtime.py's
  # record() helper shape (branch codex/mixed-provider-review-implementation
  # @ a6018c86), using the SAME provenance triple and canonical digest as
  # steps 1-2 so the join's matching-triple contract is actually exercised.
  local canonical_digest
  canonical_digest=$(jq -r '.digest' "$canonical_out")
  if ! jq -n \
    --arg node "$node" \
    --arg run_id "$run_id" \
    --arg revision "$revision" \
    --arg head "$head_sha" \
    --arg digest "$canonical_digest" \
    '{
      schema_version: 1,
      gate: "parallel-review",
      node: $node,
      provider: "codex",
      run_id: $run_id,
      revision: $revision,
      head: $head,
      frozen_input_digest: $digest,
      digest_algorithm: "sha256",
      verdict: { outcome: "approve", reasoning: "FIXTURE — hand-authored stand-in, not a live Codex reviewer verdict" },
      written_at: "1970-01-01T00:00:00Z"
    }' > "$codex_out"; then
    echo "parallel_review_harness::run_pass_case: codex fixture write failed" >&2
    return 1
  fi

  # Step 4: neutral join, same run_id/revision/head triple as steps 1-2.
  local join_out="$work_dir/join.json"
  if ! parallel_review_join::evaluate "$canonical_out" "$claude_out" "$codex_out" done done \
      "$run_id" "$revision" "$head_sha" "orchestrator" "$node" "$join_out"; then
    echo "parallel_review_harness::run_pass_case: join evaluation failed" >&2
    return 1
  fi

  local outcome
  outcome=$(jq -r '.outcome' "$join_out")
  echo "$outcome"
  [ "$outcome" = "pass" ]
}
