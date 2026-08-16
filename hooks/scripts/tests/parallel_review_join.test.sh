#!/bin/bash
# Behavioural tests for hooks/scripts/lib/parallel_review_join.sh — the
# neutral fan-out digest writer + join evaluator
# (design/mixed-provider-review-contract, frozen commit 0c7b4639, §3.1/§4/
# §5/§6). Real files on disk, not fixture-only assertions.
#
# Supports -k <pattern>: only run test blocks whose description matches
# <pattern> (grep -q). If a pattern is given and NO block matches it, this
# is treated as a failure (fail-closed) — a silent zero-assertion PASS
# would defeat the frozen evals that invoke this with -k.
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
. "$LIB_DIR/parallel_review_join.sh"

PATTERN=""
while getopts "k:" opt; do
  case "$opt" in
    k) PATTERN="$OPTARG" ;;
    *) echo "usage: $0 [-k pattern]" >&2; exit 2 ;;
  esac
done

fails=0
ran=0
matched_blocks=0

# run_block <description> — returns 0 (run it) if no pattern given or the
# description matches; returns 1 (skip it) otherwise.
run_block() {
  ran=$((ran+1))
  if [ -z "$PATTERN" ]; then
    matched_blocks=$((matched_blocks+1))
    return 0
  fi
  if printf '%s' "$1" | grep -q -- "$PATTERN"; then
    matched_blocks=$((matched_blocks+1))
    return 0
  fi
  return 1
}

ok() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n      %s\n' "$1" "$2"; fails=$((fails+1)); }

check() { # desc expected actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1" "expected: $2 / actual: $3"; fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

RUN_ID="run-1"
REVISION="abc123"
HEAD_SHA="deadbeef"
NODE="J4b-review[0]"

# ─── shared fixtures ────────────────────────────────────────────────────────
ARTIFACT="$TMP/artifact.txt"
printf 'frozen stage artifact contents\n' > "$ARTIFACT"
REAL_DIGEST=$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')

# write_evidence <out_path> <provider> <outcome> [digest] [run_id] [revision] [head]
write_evidence() {
  local out="$1" provider="$2" outcome="$3"
  local digest="${4:-$REAL_DIGEST}" run_id="${5:-$RUN_ID}" revision="${6:-$REVISION}" head_sha="${7:-$HEAD_SHA}"
  mkdir -p "$(dirname "$out")"
  jq -n \
    --arg provider "$provider" --arg run_id "$run_id" --arg revision "$revision" \
    --arg head "$head_sha" --arg digest "$digest" --arg outcome "$outcome" \
    '{
      schema_version: 1, gate: "parallel-review", node: "J4b-review[0]",
      provider: $provider, run_id: $run_id, revision: $revision, head: $head,
      frozen_input_digest: $digest, digest_algorithm: "sha256",
      verdict: { outcome: $outcome, reasoning: "test reasoning, non-empty" },
      written_at: "2026-01-01T00:00:00Z"
    }' > "$out"
}

# ═══════════════════════════ fanout ═══════════════════════════════════════
if run_block "fanout: writer produces a real sha256"; then
  DIGEST_OUT="$TMP/canonical.json"
  PARALLEL_REVIEW_DISPATCHER="orchestrator" parallel_review_fanout::write_digest \
    "$ARTIFACT" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$DIGEST_OUT"
  rc=$?
  check "fanout: write_digest exits 0" 0 "$rc"
  check "fanout: record written" 0 "$([ -f "$DIGEST_OUT" ] && echo 0 || echo 1)"
  check "fanout: digest matches independently computed sha256" "$REAL_DIGEST" "$(jq -r '.digest' "$DIGEST_OUT")"
fi

if run_block "fanout: mutated artifact produces a different digest"; then
  ARTIFACT2="$TMP/artifact_mutated.txt"
  printf 'frozen stage artifact contents, mutated\n' > "$ARTIFACT2"
  MUTATED_DIGEST=$(shasum -a 256 "$ARTIFACT2" | awk '{print $1}')
  DIGEST_OUT2="$TMP/canonical_mutated.json"
  PARALLEL_REVIEW_DISPATCHER="orchestrator" parallel_review_fanout::write_digest \
    "$ARTIFACT2" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$DIGEST_OUT2"
  check "fanout: mutated artifact digest matches its own sha256" "$MUTATED_DIGEST" "$(jq -r '.digest' "$DIGEST_OUT2")"
  check "fanout: mutated vs original digests differ" "0" \
    "$([ "$MUTATED_DIGEST" != "$REAL_DIGEST" ] && echo 0 || echo 1)"
fi

if run_block "fanout: shape matches §3.1 exactly"; then
  DIGEST_OUT3="$TMP/canonical_shape.json"
  PARALLEL_REVIEW_DISPATCHER="orchestrator" parallel_review_fanout::write_digest \
    "$ARTIFACT" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$DIGEST_OUT3"
  check "fanout shape: exact key set" \
    '["artifact_ref","digest","digest_algorithm","distributed_at","distributed_by","node","schema_version"]' \
    "$(jq -cS 'keys' "$DIGEST_OUT3")"
  check "fanout shape: schema_version is number 1" "1" "$(jq -r '.schema_version' "$DIGEST_OUT3")"
  check "fanout shape: schema_version type is number" "number" "$(jq -r '.schema_version | type' "$DIGEST_OUT3")"
  check "fanout shape: node passthrough" "$NODE" "$(jq -r '.node' "$DIGEST_OUT3")"
  check "fanout shape: digest_algorithm literal" "sha256" "$(jq -r '.digest_algorithm' "$DIGEST_OUT3")"
  check "fanout shape: distributed_by passthrough" "orchestrator" "$(jq -r '.distributed_by' "$DIGEST_OUT3")"
  check "fanout shape: distributed_at ISO-8601 shape" "match" \
    "$(jq -r '.distributed_at' "$DIGEST_OUT3" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' && echo match || echo nomatch)"
fi

if run_block "fanout: refuses when PARALLEL_REVIEW_DISPATCHER is unset"; then
  DIGEST_OUT4="$TMP/canonical_nodispatcher.json"
  unset PARALLEL_REVIEW_DISPATCHER
  parallel_review_fanout::write_digest "$ARTIFACT" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$DIGEST_OUT4"
  rc=$?
  check "fanout: unset dispatcher exits non-zero" 1 "$rc"
  check "fanout: unset dispatcher writes nothing" 0 "$([ ! -f "$DIGEST_OUT4" ] && echo 0 || echo 1)"
fi

if run_block "fanout: refuses on missing artifact"; then
  DIGEST_OUT5="$TMP/canonical_noartifact.json"
  PARALLEL_REVIEW_DISPATCHER="orchestrator" parallel_review_fanout::write_digest \
    "$TMP/does-not-exist.txt" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$DIGEST_OUT5"
  rc=$?
  check "fanout: missing artifact exits non-zero" 1 "$rc"
  check "fanout: missing artifact writes nothing" 0 "$([ ! -f "$DIGEST_OUT5" ] && echo 0 || echo 1)"
fi

# canonical digest record reused by every join test below
CANONICAL="$TMP/canonical.json"
if [ ! -f "$CANONICAL" ]; then
  PARALLEL_REVIEW_DISPATCHER="orchestrator" parallel_review_fanout::write_digest \
    "$ARTIFACT" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$CANONICAL" >/dev/null
fi

# ═══════════════════════════ join: pass case ═══════════════════════════════
if run_block "join: unanimous approve -> pass"; then
  CLAUDE_OK="$TMP/claude_ok.json"; CODEX_OK="$TMP/codex_ok.json"
  write_evidence "$CLAUDE_OK" claude approve
  write_evidence "$CODEX_OK" codex approve
  OUT="$TMP/join_pass.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_OK" "$CODEX_OK" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  rc=$?
  check "join pass: exits 0" 0 "$rc"
  check "join pass: outcome is pass" "pass" "$(jq -r '.outcome' "$OUT")"
  check "join pass: hard_stop_reason is null" "null" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

# ═══════════════════════════ join: both-skipped ═══════════════════════════
if run_block "join: both-skipped -> skipped, not a hard-stop"; then
  OUT="$TMP/join_both_skipped.json"
  parallel_review_join::evaluate "$CANONICAL" "" "" skipped skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  rc=$?
  check "join both-skipped: exits 0" 0 "$rc"
  check "join both-skipped: outcome is skipped" "skipped" "$(jq -r '.outcome' "$OUT")"
  check "join both-skipped: hard_stop_reason is null" "null" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: both-skipped even when files happen to be absent from disk (precedence over missing-evidence)"; then
  OUT="$TMP/join_both_skipped_precedence.json"
  parallel_review_join::evaluate "$CANONICAL" "$TMP/nope-claude.json" "$TMP/nope-codex.json" skipped skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "precedence 1-before-2: both-skipped wins over missing-evidence" "skipped" "$(jq -r '.outcome' "$OUT")"
fi

if run_block "join: both-skipped succeeds even when the canonical §3.1 record was never written (precedence over canonical-record existence)"; then
  # The realistic both-skipped scenario: the node was never under
  # parallel-review mode, so the fan-out step that writes the §3.1
  # canonical digest record never ran either. The both-skipped check
  # must not require that record to exist.
  OUT="$TMP/join_both_skipped_no_canonical.json"
  parallel_review_join::evaluate "$TMP/canonical-never-written.json" "" "" skipped skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  rc=$?
  check "precedence 1-before-canonical-read: exits 0 with no canonical record on disk" 0 "$rc"
  check "precedence 1-before-canonical-read: outcome is skipped" "skipped" "$(jq -r '.outcome' "$OUT")"
  check "precedence 1-before-canonical-read: frozen_input_digest is null" "null" "$(jq -r '.frozen_input_digest' "$OUT")"
fi

# ═══════════════════════════ join: missing-evidence ════════════════════════
if run_block "join: missing-evidence asymmetric skip"; then
  CLAUDE_OK2="$TMP/claude_ok2.json"
  write_evidence "$CLAUDE_OK2" claude approve
  OUT="$TMP/join_asym.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_OK2" "" done skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join missing-evidence (asymmetric): outcome hard-stop" "hard-stop" "$(jq -r '.outcome' "$OUT")"
  check "join missing-evidence (asymmetric): reason" "missing-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: missing-evidence file absent despite done"; then
  CLAUDE_OK3="$TMP/claude_ok3.json"
  write_evidence "$CLAUDE_OK3" claude approve
  OUT="$TMP/join_absent_despite_done.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_OK3" "$TMP/codex_never_written.json" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join missing-evidence (file absent despite done): outcome hard-stop" "hard-stop" "$(jq -r '.outcome' "$OUT")"
  check "join missing-evidence (file absent despite done): reason" "missing-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

# ═══════════════════════════ join: stale-evidence ══════════════════════════
if run_block "join: stale-evidence run_id mismatch"; then
  CLAUDE_STALE="$TMP/claude_stale.json"; CODEX_OK4="$TMP/codex_ok4.json"
  write_evidence "$CLAUDE_STALE" claude approve "$REAL_DIGEST" "old-run" "$REVISION" "$HEAD_SHA"
  write_evidence "$CODEX_OK4" codex approve
  OUT="$TMP/join_stale.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_STALE" "$CODEX_OK4" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join stale-evidence (run_id): outcome hard-stop" "hard-stop" "$(jq -r '.outcome' "$OUT")"
  check "join stale-evidence (run_id): reason" "stale-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: stale-evidence revision mismatch"; then
  CLAUDE_STALE2="$TMP/claude_stale2.json"; CODEX_OK5="$TMP/codex_ok5.json"
  write_evidence "$CLAUDE_STALE2" claude approve "$REAL_DIGEST" "$RUN_ID" "old-rev" "$HEAD_SHA"
  write_evidence "$CODEX_OK5" codex approve
  OUT="$TMP/join_stale_rev.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_STALE2" "$CODEX_OK5" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join stale-evidence (revision): reason" "stale-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: stale-evidence head mismatch"; then
  CLAUDE_STALE3="$TMP/claude_stale3.json"; CODEX_OK6="$TMP/codex_ok6.json"
  write_evidence "$CLAUDE_STALE3" claude approve "$REAL_DIGEST" "$RUN_ID" "$REVISION" "old-head"
  write_evidence "$CODEX_OK6" codex approve
  OUT="$TMP/join_stale_head.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_STALE3" "$CODEX_OK6" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join stale-evidence (head): reason" "stale-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: precedence stale-evidence before mismatched-evidence"; then
  # both stale AND digest-mismatched -> stale-evidence must win (check 3 before 4)
  CLAUDE_BOTH="$TMP/claude_stale_and_mismatched.json"; CODEX_OK7="$TMP/codex_ok7.json"
  write_evidence "$CLAUDE_BOTH" claude approve "not-the-real-digest" "old-run" "$REVISION" "$HEAD_SHA"
  write_evidence "$CODEX_OK7" codex approve
  OUT="$TMP/join_precedence_3_4.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_BOTH" "$CODEX_OK7" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "precedence 3-before-4: stale wins over mismatched" "stale-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: precedence missing-evidence before stale-evidence"; then
  # one skipped (missing-evidence case), other done-but-stale -> missing-evidence must win (check 2 before 3)
  CODEX_STALE="$TMP/codex_stale_for_precedence.json"
  write_evidence "$CODEX_STALE" codex approve "$REAL_DIGEST" "old-run" "$REVISION" "$HEAD_SHA"
  OUT="$TMP/join_precedence_2_3.json"
  parallel_review_join::evaluate "$CANONICAL" "" "$CODEX_STALE" skipped done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "precedence 2-before-3: missing-evidence wins over stale" "missing-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

# ═══════════════════════════ join: mismatched-evidence ═════════════════════
if run_block "join: mismatched-evidence vs canonical, even when reviewers agree with each other"; then
  # both records share the SAME wrong digest — proves comparison is against
  # canonical, not reviewer-vs-reviewer.
  CLAUDE_WRONG="$TMP/claude_wrong_digest.json"; CODEX_WRONG="$TMP/codex_wrong_digest.json"
  WRONG_DIGEST="0000000000000000000000000000000000000000000000000000000000000000"
  write_evidence "$CLAUDE_WRONG" claude approve "$WRONG_DIGEST"
  write_evidence "$CODEX_WRONG" codex approve "$WRONG_DIGEST"
  OUT="$TMP/join_mismatched.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_WRONG" "$CODEX_WRONG" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join mismatched-evidence: outcome hard-stop" "hard-stop" "$(jq -r '.outcome' "$OUT")"
  check "join mismatched-evidence: reason" "mismatched-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: precedence mismatched-evidence before conflicting-verdicts"; then
  # one record digest-mismatched AND its verdict is reject -> mismatched-evidence must win (check 4 before 5)
  CLAUDE_MISMATCH_REJECT="$TMP/claude_mismatch_reject.json"; CODEX_OK8="$TMP/codex_ok8.json"
  write_evidence "$CLAUDE_MISMATCH_REJECT" claude reject "not-the-real-digest"
  write_evidence "$CODEX_OK8" codex approve
  OUT="$TMP/join_precedence_4_5.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_MISMATCH_REJECT" "$CODEX_OK8" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "precedence 4-before-5: mismatched wins over conflicting-verdicts" "mismatched-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

# ═══════════════════════════ join: conflicting-verdicts ═════════════════════
if run_block "join: conflicting-verdicts one reject"; then
  CLAUDE_REJECT="$TMP/claude_reject.json"; CODEX_OK9="$TMP/codex_ok9.json"
  write_evidence "$CLAUDE_REJECT" claude reject
  write_evidence "$CODEX_OK9" codex approve
  OUT="$TMP/join_reject.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_REJECT" "$CODEX_OK9" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join conflicting-verdicts (reject): outcome hard-stop" "hard-stop" "$(jq -r '.outcome' "$OUT")"
  check "join conflicting-verdicts (reject): reason" "conflicting-verdicts" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

if run_block "join: conflicting-verdicts both reject still hard-stop"; then
  CLAUDE_REJECT2="$TMP/claude_reject2.json"; CODEX_REJECT="$TMP/codex_reject.json"
  write_evidence "$CLAUDE_REJECT2" claude reject
  write_evidence "$CODEX_REJECT" codex reject
  OUT="$TMP/join_both_reject.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_REJECT2" "$CODEX_REJECT" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "join conflicting-verdicts (both reject): reason" "conflicting-verdicts" "$(jq -r '.hard_stop_reason' "$OUT")"
fi

# ═══════════════════════════ join: neutral-evaluator enforcement ═══════════
if run_block "join: refuses evaluated_by=claude"; then
  CLAUDE_OK10="$TMP/claude_ok10.json"; CODEX_OK10="$TMP/codex_ok10.json"
  write_evidence "$CLAUDE_OK10" claude approve
  write_evidence "$CODEX_OK10" codex approve
  OUT="$TMP/join_evaluator_claude.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_OK10" "$CODEX_OK10" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "claude" "$NODE" "$OUT"
  rc=$?
  check "join: evaluated_by=claude exits non-zero" 1 "$rc"
  check "join: evaluated_by=claude writes nothing" 0 "$([ ! -f "$OUT" ] && echo 0 || echo 1)"
fi

if run_block "join: refuses evaluated_by=codex"; then
  CLAUDE_OK11="$TMP/claude_ok11.json"; CODEX_OK11="$TMP/codex_ok11.json"
  write_evidence "$CLAUDE_OK11" claude approve
  write_evidence "$CODEX_OK11" codex approve
  OUT="$TMP/join_evaluator_codex.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_OK11" "$CODEX_OK11" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "codex" "$NODE" "$OUT"
  rc=$?
  check "join: evaluated_by=codex exits non-zero" 1 "$rc"
  check "join: evaluated_by=codex writes nothing" 0 "$([ ! -f "$OUT" ] && echo 0 || echo 1)"
fi

if run_block "join: neutral-evaluator guard runs before the both-skipped skip"; then
  # both skipped AND evaluated_by=claude -> must still refuse, not skip.
  OUT="$TMP/join_evaluator_claude_bothskipped.json"
  parallel_review_join::evaluate "$CANONICAL" "" "" skipped skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "claude" "$NODE" "$OUT"
  rc=$?
  check "join: neutrality guard precedes both-skipped skip (exit)" 1 "$rc"
  check "join: neutrality guard precedes both-skipped skip (no write)" 0 "$([ ! -f "$OUT" ] && echo 0 || echo 1)"
fi

# ═══════════════════════════ shape ══════════════════════════════════════
if run_block "shape: pass record matches §5.2 exactly"; then
  CLAUDE_SH="$TMP/claude_shape.json"; CODEX_SH="$TMP/codex_shape.json"
  write_evidence "$CLAUDE_SH" claude approve
  write_evidence "$CODEX_SH" codex approve
  OUT="$TMP/join_shape_pass.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_SH" "$CODEX_SH" done done \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "shape pass: exact top-level key set" \
    '["evaluated_at","evaluated_by","frozen_input_digest","hard_stop_reason","inputs","node","outcome","policy","schema_version"]' \
    "$(jq -cS 'keys' "$OUT")"
  check "shape pass: schema_version is number 1" "1" "$(jq -r '.schema_version' "$OUT")"
  check "shape pass: schema_version type is number" "number" "$(jq -r '.schema_version | type' "$OUT")"
  check "shape pass: node passthrough" "$NODE" "$(jq -r '.node' "$OUT")"
  check "shape pass: policy literal" "unanimous" "$(jq -r '.policy' "$OUT")"
  check "shape pass: frozen_input_digest is canonical digest" "$REAL_DIGEST" "$(jq -r '.frozen_input_digest' "$OUT")"
  check "shape pass: evaluated_by passthrough" "orchestrator" "$(jq -r '.evaluated_by' "$OUT")"
  check "shape pass: evaluated_at ISO-8601 shape" "match" \
    "$(jq -r '.evaluated_at' "$OUT" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' && echo match || echo nomatch)"
  check "shape pass: inputs.claude key set" \
    '["head","outcome","revision","run_id","verdict_ref"]' \
    "$(jq -cS '.inputs.claude | keys' "$OUT")"
  check "shape pass: inputs.codex key set" \
    '["head","outcome","revision","run_id","verdict_ref"]' \
    "$(jq -cS '.inputs.codex | keys' "$OUT")"
  check "shape pass: inputs.claude.outcome is approve" "approve" "$(jq -r '.inputs.claude.outcome' "$OUT")"
  check "shape pass: inputs.claude.verdict_ref is a path" "$CLAUDE_SH" "$(jq -r '.inputs.claude.verdict_ref' "$OUT")"
  check "shape pass: inputs.claude.run_id passthrough" "$RUN_ID" "$(jq -r '.inputs.claude.run_id' "$OUT")"
fi

if run_block "shape: hard-stop record matches §5.2 exactly, including null-safe inputs"; then
  CLAUDE_SH2="$TMP/claude_shape2.json"
  write_evidence "$CLAUDE_SH2" claude approve
  OUT="$TMP/join_shape_hardstop.json"
  parallel_review_join::evaluate "$CANONICAL" "$CLAUDE_SH2" "" done skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "shape hard-stop: exact top-level key set" \
    '["evaluated_at","evaluated_by","frozen_input_digest","hard_stop_reason","inputs","node","outcome","policy","schema_version"]' \
    "$(jq -cS 'keys' "$OUT")"
  check "shape hard-stop: outcome is hard-stop" "hard-stop" "$(jq -r '.outcome' "$OUT")"
  check "shape hard-stop: hard_stop_reason type is string" "string" "$(jq -r '.hard_stop_reason | type' "$OUT")"
  check "shape hard-stop: hard_stop_reason is missing-evidence" "missing-evidence" "$(jq -r '.hard_stop_reason' "$OUT")"
  check "shape hard-stop: inputs.codex key set present even though absent on disk" \
    '["head","outcome","revision","run_id","verdict_ref"]' \
    "$(jq -cS '.inputs.codex | keys' "$OUT")"
  check "shape hard-stop: inputs.codex.outcome is null" "null" "$(jq -r '.inputs.codex.outcome' "$OUT")"
  check "shape hard-stop: inputs.codex.verdict_ref is null" "null" "$(jq -r '.inputs.codex.verdict_ref' "$OUT")"
fi

if run_block "shape: skipped record matches §5.2 exactly"; then
  OUT="$TMP/join_shape_skipped.json"
  parallel_review_join::evaluate "$CANONICAL" "" "" skipped skipped \
    "$RUN_ID" "$REVISION" "$HEAD_SHA" "orchestrator" "$NODE" "$OUT"
  check "shape skipped: exact top-level key set" \
    '["evaluated_at","evaluated_by","frozen_input_digest","hard_stop_reason","inputs","node","outcome","policy","schema_version"]' \
    "$(jq -cS 'keys' "$OUT")"
  check "shape skipped: outcome is skipped" "skipped" "$(jq -r '.outcome' "$OUT")"
  check "shape skipped: hard_stop_reason type is null" "null" "$(jq -r '.hard_stop_reason | type' "$OUT")"
  check "shape skipped: inputs.claude.outcome is null" "null" "$(jq -r '.inputs.claude.outcome' "$OUT")"
  check "shape skipped: inputs.codex.outcome is null" "null" "$(jq -r '.inputs.codex.outcome' "$OUT")"
fi

# ─── -k pattern fail-closed: no matching block must be a failure, not a
# silent zero-assertion PASS ──────────────────────────────────────────────
if [ -n "$PATTERN" ] && [ "$matched_blocks" -eq 0 ]; then
  fail "-k $PATTERN matched zero test blocks" "ran=$ran matched=$matched_blocks — refusing to report a silent PASS"
fi

if [ -n "$PATTERN" ]; then
  echo "-- pattern '$PATTERN' matched $matched_blocks of $ran test blocks --"
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
