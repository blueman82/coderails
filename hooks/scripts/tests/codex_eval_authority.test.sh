#!/usr/bin/env bash
# Literal snippets are matched against source/docs; shell expansion would be wrong.
# shellcheck disable=SC2016
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
POST_EVALS_DOC="$ROOT/codex/commands/post-evals.md"
TASK_EVALS_DOC="$ROOT/codex/skills/task-evals.md"
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

for doc in "$POST_EVALS_DOC" "$TASK_EVALS_DOC"; do
    check_contains "$doc" 'Committed `docs/evals/*.json` files and local `evals.json` files are working material only; they are never live PR-readiness evidence.' \
        "$(basename "$doc"): local eval JSON is non-authoritative"
    check_contains "$doc" 'For PR readiness, fetch the current PR head and require the newest trusted SHA-bound `coderails-eval-summary` PR comment/embed for that exact head.' \
        "$(basename "$doc"): PR readiness requires trusted exact-head comment/embed"
    check_contains "$doc" 'Missing, stale, mismatched, rejected, untrusted, or fetch-failed eval evidence is `NO-GO`.' \
        "$(basename "$doc"): stale or untrusted eval evidence is NO-GO"
done

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
