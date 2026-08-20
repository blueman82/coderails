#!/usr/bin/env bash
# Literal snippets are matched against source/docs; shell expansion would be wrong.
# shellcheck disable=SC2016
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
POST_EVALS_DOC="$ROOT/packages/codex/skills/post-evals/SKILL.md"
TASK_EVALS_DOC="$ROOT/packages/codex/skills/task-evals/SKILL.md"
MERGE_SH="$ROOT/scripts/merge.sh"

fails=0

check_contains() {
    local file="$1"
    local pattern="$2"
    local label="$3"

    if grep -Fq "$pattern" "$file"; then
        printf 'ok - %s\n' "$label"
    else
        printf 'FAIL - %s\n' "$label"
        printf '  missing in %s: %s\n' "$file" "$pattern"
        fails=$((fails + 1))
    fi
}

check_not_contains() {
    local file="$1"
    local pattern="$2"
    local label="$3"

    if grep -Fq "$pattern" "$file"; then
        printf 'FAIL - %s\n' "$label"
        printf '  unexpected in %s: %s\n' "$file" "$pattern"
        fails=$((fails + 1))
    else
        printf 'ok - %s\n' "$label"
    fi
}

check_contains "$POST_EVALS_DOC" 'Local or committed eval files are working material, not PR-readiness evidence.' \
    'post-evals: local eval JSON is non-authoritative'
check_contains "$POST_EVALS_DOC" 'Fetch the current head with `gh pr view <pr> --json headRefOid -q .headRefOid`.' \
    'post-evals: PR readiness fetches the exact head'
check_contains "$POST_EVALS_DOC" 'The marker must remain bound to the validated pull request and its currently fetched head.' \
    'post-evals: durable marker stays exact-head bound'
check_contains "$POST_EVALS_DOC" 'Never treat missing, stale, mismatched, rejected, untrusted, or unavailable evidence as success.' \
    'post-evals: stale or untrusted evidence cannot pass'
check_contains "$TASK_EVALS_DOC" 'PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment' \
    'task-evals: PR-scope file is working material and the comment is authoritative'

check_contains "$MERGE_SH" 'sha=$(pr::head_sha "$num")' \
    'merge gate fetches current PR head SHA'
check_contains "$MERGE_SH" 'pr::has_coderails_eval_for_head "$num" "$sha"' \
    'merge gate requires trusted eval marker for current head'
check_contains "$MERGE_SH" 'embed=$(pr::coderails_eval_embed_for_head "$num" "$sha")' \
    'merge gate extracts the trusted eval embed for current head'
check_contains "$MERGE_SH" 'post_evals::smoke_verify "$embed_file" "$sha"' \
    'merge gate smoke-verifies the trusted embed at current head'
check_not_contains "$MERGE_SH" 'docs/evals' \
    'merge gate does not use committed docs/evals files as readiness input'

[[ "$fails" -eq 0 ]] && {
    printf 'PASS\n'
    exit 0
}
printf 'FAIL (%d)\n' "$fails"
exit 1
