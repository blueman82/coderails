#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  parallel_review_join.sh │ neutral fan-out digest writer + join evaluator
#
#  Independent implementation of design/mixed-provider-review-contract
#  (frozen commit 0c7b4639) §3.1 (frozen-input digest), §4 (fan-out/join
#  sequencing), §5 (unanimous-approval policy, join record shape), and §6
#  (the four negative acceptance cases). Neither reviewer's own runtime —
#  this is the third, neutral step that reads both providers' evidence and
#  never writes as either provider.
#
#  Two functions:
#    parallel_review_fanout::write_digest — writes the §3.1 canonical
#      frozen-input digest record, once, before either reviewer runs.
#    parallel_review_join::evaluate — reads the canonical digest record and
#      both providers' evidence records (if present), applies the four
#      negative-case checks in spec order, and writes the §5.2 join record.
#
#  ponytail: §3.1's own record shape has no run_id/revision/head fields, so
#  write_digest cannot bind the expected provenance triple into the record
#  it writes. The stale-evidence check (§6.2) therefore trusts that the
#  caller passes the SAME triple to both write_digest and evaluate — a
#  caller that passes mismatched values to the two calls is not detected
#  by this module. Upgrade path: carry run_id/revision/head in the §3.1
#  record and have evaluate read expected values from there instead of
#  from its own arguments (a §3.1 schema change, out of scope here).
#═══════════════════════════════════════════════════════════════════════════════

# parallel_review_fanout::write_digest <artifact_path> <run_id> <revision> <head> <node> <out_path>
# Computes a real sha256 of the artifact bytes and writes the §3.1 canonical
# frozen-input digest record. run_id/revision/head are accepted for
# signature symmetry with parallel_review::run and are NOT part of the §3.1
# record shape (the join receives the expected provenance triple directly
# as its own arguments, not by reading it back out of this record).
# Env: PARALLEL_REVIEW_DISPATCHER — the neutral dispatcher identity written
#   into distributed_at's sibling field. No default — the caller must
#   supply one (mirrors parallel_review.sh's PARALLEL_REVIEW_REVIEWER
#   fail-closed pattern).
# Exit 0 and writes <out_path> only on success; exit 1 and writes nothing
# otherwise.
parallel_review_fanout::write_digest() {
    local artifact="$1" run_id="$2" revision="$3" head_sha="$4" node="$5" out_path="$6"

    if [ -z "${PARALLEL_REVIEW_DISPATCHER:-}" ]; then
        echo "parallel_review_fanout::write_digest: PARALLEL_REVIEW_DISPATCHER is not set" >&2
        return 1
    fi

    if [ ! -f "$artifact" ]; then
        echo "parallel_review_fanout::write_digest: frozen-input artifact not found: $artifact" >&2
        return 1
    fi

    local digest
    digest=$(shasum -a 256 "$artifact" | awk '{print $1}')
    if [ -z "$digest" ]; then
        echo "parallel_review_fanout::write_digest: failed to compute sha256 of $artifact" >&2
        return 1
    fi

    local distributed_at
    distributed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    local tmp_out
    tmp_out=$(mktemp)
    if ! jq -n \
        --arg node "$node" \
        --arg artifact_ref "$artifact" \
        --arg digest_algorithm "sha256" \
        --arg digest "$digest" \
        --arg distributed_at "$distributed_at" \
        --arg distributed_by "$PARALLEL_REVIEW_DISPATCHER" \
        '{
      schema_version: 1,
      node: $node,
      artifact_ref: $artifact_ref,
      digest_algorithm: $digest_algorithm,
      digest: $digest,
      distributed_at: $distributed_at,
      distributed_by: $distributed_by
    }' >"$tmp_out"; then
        echo "parallel_review_fanout::write_digest: failed to build digest record" >&2
        rm -f "$tmp_out"
        return 1
    fi

    mkdir -p "$(dirname "$out_path")"
    mv "$tmp_out" "$out_path"
}

# parallel_review_join::evaluate <canonical_digest_record_path> \
#   <claude_record_path_or_empty> <codex_record_path_or_empty> \
#   <claude_outcome> <codex_outcome> \
#   <expected_run_id> <expected_revision> <expected_head> \
#   <evaluated_by> <node> <out_path>
#
# claude_outcome/codex_outcome are each "done" or "skipped" — the GRAPH
# NODE outcome (what ready() sees), distinct from the reviewer's own
# verdict.outcome inside its evidence record.
#
# Checks run in this exact spec order (§6, load-bearing):
#   1. both-skipped -> join skips, never a hard-stop (checked before any
#      file-existence check)
#   2. missing-evidence: asymmetric skip, or a "done" node whose record
#      file does not actually exist on disk
#   3. stale-evidence: run_id/revision/head mismatch vs expected
#   4. mismatched-evidence: record's own frozen_input_digest vs canonical
#      §3.1 digest (never reviewer-vs-reviewer)
#   5. conflicting-verdicts: either reject, or the two disagree
#
# Refuses (non-zero, no output written) if evaluated_by is "claude" or
# "codex" — the join must be neutral.
# Exit 0 and writes <out_path> only on a fully valid evaluation; exit 1 and
# writes nothing otherwise.
parallel_review_join::evaluate() {
    local canonical_path="$1" claude_path="$2" codex_path="$3" \
        claude_outcome="$4" codex_outcome="$5" \
        expected_run_id="$6" expected_revision="$7" expected_head="$8" \
        evaluated_by="$9" node="${10}" out_path="${11}"

    if [ "$evaluated_by" = "claude" ] || [ "$evaluated_by" = "codex" ]; then
        echo "parallel_review_join::evaluate: evaluated_by must be neutral, got: $evaluated_by" >&2
        return 1
    fi

    local node_outcome
    for node_outcome in "$claude_outcome" "$codex_outcome"; do
        if [ "$node_outcome" != "done" ] && [ "$node_outcome" != "skipped" ]; then
            echo "parallel_review_join::evaluate: node outcome must be exactly 'done' or 'skipped', got: $node_outcome" >&2
            return 1
        fi
    done

    local outcome="" hard_stop_reason="null" canonical_digest=""

    if [ "$claude_outcome" = "skipped" ] && [ "$codex_outcome" = "skipped" ]; then
        outcome="skipped"
        hard_stop_reason="null"
        [ -f "$canonical_path" ] && canonical_digest=$(jq -r '.digest // empty' "$canonical_path")
    else
        if [ ! -f "$canonical_path" ]; then
            echo "parallel_review_join::evaluate: canonical digest record not found: $canonical_path" >&2
            return 1
        fi

        canonical_digest=$(jq -r '.digest // empty' "$canonical_path")
        if [ -z "$canonical_digest" ]; then
            echo "parallel_review_join::evaluate: canonical digest record has no .digest: $canonical_path" >&2
            return 1
        fi

        local claude_exists=0 codex_exists=0
        [ -n "$claude_path" ] && [ -f "$claude_path" ] && claude_exists=1
        [ -n "$codex_path" ] && [ -f "$codex_path" ] && codex_exists=1

        if [ "$claude_outcome" = "skipped" ] && [ "$codex_outcome" = "done" ]; then
            outcome="hard-stop"
            hard_stop_reason="missing-evidence"
        elif [ "$claude_outcome" = "done" ] && [ "$codex_outcome" = "skipped" ]; then
            outcome="hard-stop"
            hard_stop_reason="missing-evidence"
        elif [ "$claude_exists" -eq 0 ] || [ "$codex_exists" -eq 0 ]; then
            outcome="hard-stop"
            hard_stop_reason="missing-evidence"
        fi

        if [ -z "$outcome" ]; then
            local record_path
            for record_path in "$claude_path" "$codex_path"; do
                local run_id revision head_sha
                run_id=$(jq -r '.run_id // empty' "$record_path")
                revision=$(jq -r '.revision // empty' "$record_path")
                head_sha=$(jq -r '.head // empty' "$record_path")
                if [ "$run_id" != "$expected_run_id" ] || [ "$revision" != "$expected_revision" ] || [ "$head_sha" != "$expected_head" ]; then
                    outcome="hard-stop"
                    hard_stop_reason="stale-evidence"
                    break
                fi
            done
        fi

        if [ -z "$outcome" ]; then
            local record_path
            for record_path in "$claude_path" "$codex_path"; do
                local record_digest
                record_digest=$(jq -r '.frozen_input_digest // empty' "$record_path")
                if [ "$record_digest" != "$canonical_digest" ]; then
                    outcome="hard-stop"
                    hard_stop_reason="mismatched-evidence"
                    break
                fi
            done
        fi

        if [ -z "$outcome" ]; then
            local claude_verdict codex_verdict
            claude_verdict=$(jq -r '.verdict.outcome // empty' "$claude_path")
            codex_verdict=$(jq -r '.verdict.outcome // empty' "$codex_path")
            if [ "$claude_verdict" = "reject" ] || [ "$codex_verdict" = "reject" ] || [ "$claude_verdict" != "$codex_verdict" ]; then
                outcome="hard-stop"
                hard_stop_reason="conflicting-verdicts"
            else
                outcome="pass"
                hard_stop_reason="null"
            fi
        fi
    fi

    parallel_review_join::_write "$canonical_digest" "$claude_path" "$codex_path" \
        "$outcome" "$hard_stop_reason" "$evaluated_by" "$node" "$out_path"
}

parallel_review_join::_write() {
    local digest="$1" claude_path="$2" codex_path="$3" outcome="$4" reason="$5" provider="$6" node="$7" out_path="$8"
    local claude_inputs codex_inputs tmp_out evaluated_at
    claude_inputs=$(parallel_review_join::_provider_inputs "$claude_path")
    codex_inputs=$(parallel_review_join::_provider_inputs "$codex_path")
    evaluated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    tmp_out=$(mktemp)
    if ! jq -n --arg node "$node" --arg digest "$digest" --argjson claude_inputs "$claude_inputs" \
        --argjson codex_inputs "$codex_inputs" --arg outcome "$outcome" --arg reason "$reason" \
        --arg evaluated_at "$evaluated_at" --arg provider "$provider" '{schema_version:1,node:$node,policy:"unanimous",frozen_input_digest:(if $digest == "" then null else $digest end),inputs:{claude:$claude_inputs,codex:$codex_inputs},outcome:$outcome,hard_stop_reason:(if $reason == "null" then null else $reason end),evaluated_at:$evaluated_at,evaluated_by:$provider}' >"$tmp_out"; then
        rm -f "$tmp_out"
        return 1
    fi
    mkdir -p "$(dirname "$out_path")" && mv "$tmp_out" "$out_path"
}

# parallel_review_join::_provider_inputs <record_path_or_empty>
# Emits the §5.2 per-provider inputs sub-object as JSON on stdout. All
# fields are present; each is null when the record path is empty or the
# file doesn't exist on disk.
parallel_review_join::_provider_inputs() {
    local path="$1"
    if [ -z "$path" ] || [ ! -f "$path" ]; then
        jq -n '{ run_id: null, revision: null, head: null, outcome: null, verdict_ref: null }'
        return 0
    fi
    jq --arg verdict_ref "$path" '{
    run_id: (.run_id // null),
    revision: (.revision // null),
    head: (.head // null),
    outcome: (.verdict.outcome // null),
    verdict_ref: $verdict_ref
  }' "$path"
}
