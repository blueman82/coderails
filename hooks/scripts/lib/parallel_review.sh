#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  parallel_review.sh │ Claude-owned parallel-review invocation boundary
#
#  Provider-side implementation of design/mixed-provider-review-contract
#  (frozen commit 0c7b4639) §3.3's Claude evidence-record shape ONLY. This
#  does NOT implement the join (§4/§5/§7.1) — it never reads a sibling
#  provider's record or a canonical §3.1 dispatcher digest, and it never
#  compares two verdicts. One Claude-side reviewer invocation, one evidence
#  record, written once.
#
#  parallel_review::run computes a REAL sha256 of the frozen-input artifact
#  it is given (never a caller-supplied digest — the whole point of the
#  digest is that the reviewer attests what it actually reviewed), invokes
#  a pluggable reviewer (default: the PARALLEL_REVIEW_REVIEWER command/
#  function; in a real deployment this would dispatch the
#  deploy-safety-reviewer agent against the frozen artifact), validates the
#  verdict, and writes the record. On any invalid input it refuses to write
#  a partial/malformed record — write-then-validate is the wrong order for
#  a record claiming a verdict it doesn't have.
#═══════════════════════════════════════════════════════════════════════════════

# parallel_review::run <artifact_path> <run_id> <revision> <head> <node> <out_path>
# Env: PARALLEL_REVIEW_REVIEWER — command/function invoked as
#   "$PARALLEL_REVIEW_REVIEWER" "<artifact_path>", must print
#   {"outcome": "approve"|"reject", "reasoning": "<non-empty string>"} on
#   stdout and exit 0. No default — the caller must supply a reviewer
#   (mirrors codex/runtime/gate_producer.py's executor=invoke pattern: the
#   invocation boundary is a swappable callback, never hardcoded here).
# Exit 0 and writes <out_path> only on a fully valid record. Exit 1 and
# writes nothing otherwise.
parallel_review::run() {
  local artifact="$1" run_id="$2" revision="$3" head_sha="$4" node="$5" out_path="$6"

  if [ -z "${PARALLEL_REVIEW_REVIEWER:-}" ]; then
    echo "parallel_review::run: PARALLEL_REVIEW_REVIEWER is not set" >&2
    return 1
  fi

  if [ ! -f "$artifact" ]; then
    echo "parallel_review::run: frozen-input artifact not found: $artifact" >&2
    return 1
  fi

  local digest
  digest=$(shasum -a 256 "$artifact" | awk '{print $1}')
  if [ -z "$digest" ]; then
    echo "parallel_review::run: failed to compute sha256 of $artifact" >&2
    return 1
  fi

  local reviewer_output reviewer_rc
  reviewer_output=$("$PARALLEL_REVIEW_REVIEWER" "$artifact")
  reviewer_rc=$?
  if [ "$reviewer_rc" -ne 0 ]; then
    echo "parallel_review::run: reviewer exited non-zero ($reviewer_rc)" >&2
    return 1
  fi

  if [ -z "$reviewer_output" ] || ! jq -e . >/dev/null 2>&1 <<<"$reviewer_output"; then
    echo "parallel_review::run: reviewer produced non-JSON or empty output" >&2
    return 1
  fi

  local outcome reasoning
  outcome=$(jq -r '.outcome // empty' <<<"$reviewer_output")
  reasoning=$(jq -r '.reasoning // empty' <<<"$reviewer_output")

  if [ "$outcome" != "approve" ] && [ "$outcome" != "reject" ]; then
    echo "parallel_review::run: reviewer outcome must be exactly 'approve' or 'reject', got: ${outcome:-<empty>}" >&2
    return 1
  fi

  # Reject blank/whitespace-only reasoning, not just absent.
  if [ -z "$(printf '%s' "$reasoning" | tr -d '[:space:]')" ]; then
    echo "parallel_review::run: reviewer reasoning must be a non-empty string" >&2
    return 1
  fi

  local written_at
  written_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  local tmp_out
  tmp_out=$(mktemp)
  if ! jq -n \
    --arg gate "parallel-review" \
    --arg node "$node" \
    --arg provider "claude" \
    --arg run_id "$run_id" \
    --arg revision "$revision" \
    --arg head "$head_sha" \
    --arg digest "$digest" \
    --arg digest_algorithm "sha256" \
    --arg outcome "$outcome" \
    --arg reasoning "$reasoning" \
    --arg written_at "$written_at" \
    '{
      schema_version: 1,
      gate: $gate,
      node: $node,
      provider: $provider,
      run_id: $run_id,
      revision: $revision,
      head: $head,
      frozen_input_digest: $digest,
      digest_algorithm: $digest_algorithm,
      verdict: { outcome: $outcome, reasoning: $reasoning },
      written_at: $written_at
    }' > "$tmp_out"; then
    echo "parallel_review::run: failed to build evidence record" >&2
    rm -f "$tmp_out"
    return 1
  fi

  mkdir -p "$(dirname "$out_path")"
  mv "$tmp_out" "$out_path"
}
