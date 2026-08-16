#!/bin/bash
# Behavioural tests for hooks/scripts/lib/parallel_review.sh — the Claude-owned
# parallel-review invocation boundary (design/mixed-provider-review-contract
# §3.3 evidence-record shape). Provider-side only: no join, no Codex.
set -u
LIB="$(cd "$(dirname "$0")/../.." && pwd)/scripts/lib/parallel_review.sh"
source "$LIB"

fails=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_str() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── fixtures ─────────────────────────────────────────────────────────────
ARTIFACT="$TMP/frozen_input.txt"
printf 'frozen stage artifact contents\n' > "$ARTIFACT"
EXPECTED_DIGEST=$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')

approve_reviewer() { # $1 = artifact path
  printf '{"outcome":"approve","reasoning":"looks safe, no rollback/blast-radius concerns"}\n'
}

reject_reviewer() {
  printf '{"outcome":"reject","reasoning":"unrevertable migration, no rollback path"}\n'
}

# ─── positive: approve ──────────────────────────────────────────────────────
OUT_A="$TMP/claude-approve.json"
PARALLEL_REVIEW_REVIEWER=approve_reviewer parallel_review::run \
  "$ARTIFACT" "run-1" "abc123" "deadbeef" "U4b-review[0]" "$OUT_A"
check "approve: run exits 0" 0 $?
check "approve: record written" 0 "$([ -f "$OUT_A" ] && echo 0 || echo 1)"

check_str "approve: schema_version is number 1" "1" "$(jq -r '.schema_version' "$OUT_A")"
check_str "approve: schema_version type is number" "number" "$(jq -r '.schema_version | type' "$OUT_A")"
check_str "approve: gate literal" "parallel-review" "$(jq -r '.gate' "$OUT_A")"
check_str "approve: node passthrough" "U4b-review[0]" "$(jq -r '.node' "$OUT_A")"
check_str "approve: provider literal" "claude" "$(jq -r '.provider' "$OUT_A")"
check_str "approve: run_id passthrough" "run-1" "$(jq -r '.run_id' "$OUT_A")"
check_str "approve: revision passthrough" "abc123" "$(jq -r '.revision' "$OUT_A")"
check_str "approve: revision type is string" "string" "$(jq -r '.revision | type' "$OUT_A")"
check_str "approve: head passthrough" "deadbeef" "$(jq -r '.head' "$OUT_A")"
check_str "approve: digest_algorithm literal" "sha256" "$(jq -r '.digest_algorithm' "$OUT_A")"
check_str "approve: outcome" "approve" "$(jq -r '.verdict.outcome' "$OUT_A")"
check_str "approve: reasoning non-empty" "0" "$([ -n "$(jq -r '.verdict.reasoning' "$OUT_A")" ] && echo 0 || echo 1)"
check_str "approve: written_at ISO-8601 shape" "match" \
  "$(jq -r '.written_at' "$OUT_A" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' && echo match || echo nomatch)"
check_str "approve: exact key set" \
  '["digest_algorithm","frozen_input_digest","gate","head","node","provider","revision","run_id","schema_version","verdict","written_at"]' \
  "$(jq -cS 'keys' "$OUT_A")"

# ─── real sha256 digest, not a passthrough ─────────────────────────────────
check_str "approve: frozen_input_digest matches independently computed sha256" \
  "$EXPECTED_DIGEST" "$(jq -r '.frozen_input_digest' "$OUT_A")"

# byte-mutation control: a changed artifact must produce a changed digest —
# proves the record isn't an echoed constant.
ARTIFACT2="$TMP/frozen_input_mutated.txt"
printf 'frozen stage artifact contents, mutated\n' > "$ARTIFACT2"
MUTATED_DIGEST=$(shasum -a 256 "$ARTIFACT2" | awk '{print $1}')
OUT_A2="$TMP/claude-approve-mutated.json"
PARALLEL_REVIEW_REVIEWER=approve_reviewer parallel_review::run \
  "$ARTIFACT2" "run-1" "abc123" "deadbeef" "U4b-review[0]" "$OUT_A2"
check_str "mutated artifact: digest changed" "$MUTATED_DIGEST" "$(jq -r '.frozen_input_digest' "$OUT_A2")"
check_str "mutated vs original: digests differ" "0" \
  "$([ "$(jq -r '.frozen_input_digest' "$OUT_A")" != "$(jq -r '.frozen_input_digest' "$OUT_A2")" ] && echo 0 || echo 1)"

# ─── revision stays a string even if numeric-looking ───────────────────────
OUT_NUM="$TMP/claude-numeric-revision.json"
PARALLEL_REVIEW_REVIEWER=approve_reviewer parallel_review::run \
  "$ARTIFACT" "run-1" "12345" "deadbeef" "U4b-review[0]" "$OUT_NUM"
check_str "numeric-looking revision stays JSON string" "string" "$(jq -r '.revision | type' "$OUT_NUM")"
check_str "numeric-looking revision value preserved" "12345" "$(jq -r '.revision' "$OUT_NUM")"

# ─── positive: reject ───────────────────────────────────────────────────────
OUT_R="$TMP/claude-reject.json"
PARALLEL_REVIEW_REVIEWER=reject_reviewer parallel_review::run \
  "$ARTIFACT" "run-2" "def456" "cafef00d" "U4b-review[0]" "$OUT_R"
check "reject: run exits 0" 0 $?
check_str "reject: outcome" "reject" "$(jq -r '.verdict.outcome' "$OUT_R")"
check_str "reject: reasoning non-empty" "0" "$([ -n "$(jq -r '.verdict.reasoning' "$OUT_R")" ] && echo 0 || echo 1)"

# ─── negative: invalid outcome value → refuse to write ────────────────────
bad_outcome_reviewer() { printf '{"outcome":"needs-changes","reasoning":"partial"}\n'; }
OUT_BAD1="$TMP/claude-bad-outcome.json"
PARALLEL_REVIEW_REVIEWER=bad_outcome_reviewer parallel_review::run \
  "$ARTIFACT" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD1"
check "invalid outcome value: run exits non-zero" 1 $?
check "invalid outcome value: no record written" 0 "$([ ! -f "$OUT_BAD1" ] && echo 0 || echo 1)"

# ─── negative: missing/blank reasoning → refuse to write ───────────────────
blank_reasoning_reviewer() { printf '{"outcome":"approve","reasoning":"   "}\n'; }
OUT_BAD2="$TMP/claude-blank-reasoning.json"
PARALLEL_REVIEW_REVIEWER=blank_reasoning_reviewer parallel_review::run \
  "$ARTIFACT" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD2"
check "blank reasoning: run exits non-zero" 1 $?
check "blank reasoning: no record written" 0 "$([ ! -f "$OUT_BAD2" ] && echo 0 || echo 1)"

missing_reasoning_reviewer() { printf '{"outcome":"approve"}\n'; }
OUT_BAD3="$TMP/claude-missing-reasoning.json"
PARALLEL_REVIEW_REVIEWER=missing_reasoning_reviewer parallel_review::run \
  "$ARTIFACT" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD3"
check "missing reasoning: run exits non-zero" 1 $?
check "missing reasoning: no record written" 0 "$([ ! -f "$OUT_BAD3" ] && echo 0 || echo 1)"

# ─── negative: reviewer exits non-zero → refuse to write ───────────────────
failing_reviewer() { printf 'boom\n' >&2; return 1; }
OUT_BAD4="$TMP/claude-reviewer-failed.json"
PARALLEL_REVIEW_REVIEWER=failing_reviewer parallel_review::run \
  "$ARTIFACT" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD4"
check "reviewer non-zero exit: run exits non-zero" 1 $?
check "reviewer non-zero exit: no record written" 0 "$([ ! -f "$OUT_BAD4" ] && echo 0 || echo 1)"

# ─── negative: reviewer emits non-JSON / empty stdout → refuse to write ────
garbage_reviewer() { printf 'not json at all\n'; }
OUT_BAD5="$TMP/claude-garbage.json"
PARALLEL_REVIEW_REVIEWER=garbage_reviewer parallel_review::run \
  "$ARTIFACT" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD5"
check "non-JSON reviewer output: run exits non-zero" 1 $?
check "non-JSON reviewer output: no record written" 0 "$([ ! -f "$OUT_BAD5" ] && echo 0 || echo 1)"

empty_reviewer() { printf ''; }
OUT_BAD6="$TMP/claude-empty.json"
PARALLEL_REVIEW_REVIEWER=empty_reviewer parallel_review::run \
  "$ARTIFACT" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD6"
check "empty reviewer output: run exits non-zero" 1 $?
check "empty reviewer output: no record written" 0 "$([ ! -f "$OUT_BAD6" ] && echo 0 || echo 1)"

# ─── negative: missing frozen-input artifact → refuse (nothing to digest) ──
OUT_BAD7="$TMP/claude-missing-artifact.json"
PARALLEL_REVIEW_REVIEWER=approve_reviewer parallel_review::run \
  "$TMP/does-not-exist.txt" "run-3" "rev" "head" "U4b-review[0]" "$OUT_BAD7"
check "missing artifact: run exits non-zero" 1 $?
check "missing artifact: no record written" 0 "$([ ! -f "$OUT_BAD7" ] && echo 0 || echo 1)"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
