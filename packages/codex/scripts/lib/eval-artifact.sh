#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  eval-artifact.sh │ Marker SSOT for the coderails eval artifact
#  Both the writer ($coderails-codex:post-evals) and the merge gate
#  source this file — one constructor, no drift. Mirrors review-artifact.sh.
#═══════════════════════════════════════════════════════════════════════════════

EVAL_ARTIFACT_MARKER_VERSION="v1"

# eval_artifact::marker <pr> <head_sha> <result> <verification_level>
# Echoes the exact marker line for the given PR, head SHA, result, and verification_level.
eval_artifact::marker() {
    local pr="$1" head_sha="$2" result="$3" verification_level="$4"
    printf '<!-- coderails-eval-summary %s pr=%s head_sha=%s result=%s verification_level=%s -->' \
        "$EVAL_ARTIFACT_MARKER_VERSION" "$pr" "$head_sha" "$result" "$verification_level"
}

# eval_artifact::_prefix <pr> <head_sha>
# Echoes the literal marker prefix (through "head_sha=<sha> ") for <pr>/<sha>.
# <pr> and <head_sha> are never interpolated into a regex — this is a plain
# string, compared with string equality in matches_marker below.
eval_artifact::_prefix() {
    local pr="$1" head_sha="$2"
    printf '<!-- coderails-eval-summary %s pr=%s head_sha=%s result=' \
        "$EVAL_ARTIFACT_MARKER_VERSION" "$pr" "$head_sha"
}

# eval_artifact::matches_marker <line> <pr> <head_sha>
# Exit 0 iff <line> is the eval marker for <pr>/<head_sha> at ANY result/verification_level.
# Matches via LITERAL prefix string-equality (mirroring
# review_artifact::matches_marker) — never a regex with interpolated pr/sha
# values, so a pr or sha carrying regex metacharacters can't be misinterpreted
# as a pattern. Only after the literal prefix matches do we defer to
# parse_result/parse_verification_level to validate the remaining result=/verification_level= grammar and
# the closing " -->" (anchored regex there is safe: it never interpolates the
# untrusted pr/sha). An unknown/future version or malformed result/verification_level
# grammar never matches (fail-closed).
eval_artifact::matches_marker() {
    local line="$1" pr="$2" head_sha="$3"
    local prefix
    prefix=$(eval_artifact::_prefix "$pr" "$head_sha")
    case "$line" in
    "$prefix"*) ;;
    *) return 1 ;;
    esac
    [[ -n "$(eval_artifact::parse_result "$line")" ]]
}

# eval_artifact::parse_result <line>
# Echoes GO or NO-GO extracted from a line matching the marker grammar for
# ANY pr/sha, or empty string if the line doesn't match.
eval_artifact::parse_result() {
    local line="$1"
    local pattern='^<!-- coderails-eval-summary '"$EVAL_ARTIFACT_MARKER_VERSION"' pr=[^ ]+ head_sha=[^ ]+ result=(GO|NO-GO) verification_level=[0-2] -->$'
    if [[ "$line" =~ $pattern ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    fi
}

# eval_artifact::parse_verification_level <line>
# Echoes the verification_level digit (0, 1, or 2) extracted from a matching line, or empty
# string if the line doesn't match.
eval_artifact::parse_verification_level() {
    local line="$1"
    local pattern='^<!-- coderails-eval-summary '"$EVAL_ARTIFACT_MARKER_VERSION"' pr=[^ ]+ head_sha=[^ ]+ result=(GO|NO-GO) verification_level=([0-2]) -->$'
    if [[ "$line" =~ $pattern ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
    fi
}

# eval_artifact::compute_go <evals_json_path>
# Exit 0 (GO) iff every eval object with .priority=="P0" has .status=="pass".
# Exit 1 (NO-GO) otherwise, including when the JSON is malformed or the
# .evals array is absent/not an array (fail-closed on structural garbage).
# This is the ONE place `result` is derived from per-eval statuses.
# Note: an eval with .priority absent (neither "P0" nor otherwise) is excluded
# from the P0 gate by design — it is simply not selected by `.priority == "P0"`.
# post_evals::validate_structure's check 7 is the layer that refuses a
# verification_level>=1 artifact with zero actual P0 evals; this function stays a pure,
# unopinionated gate over whatever P0 evals are present.
eval_artifact::compute_go() {
    local path="$1"
    jq -e '(.evals | type) == "array"
           and ([.evals[] | select(.priority == "P0") | select(.status != "pass")] | length) == 0
          ' "$path" >/dev/null 2>&1
    local rc=$?
    # jq exits 5 on a parse error (invalid JSON) and non-1 codes on other
    # internal errors — normalise any non-zero outcome to 1 (fail-closed).
    [[ $rc -eq 0 ]]
}

# eval_artifact::grading_checksum <evals_json_path> <result>
# Binds the ordered eval identities, priorities, and statuses to the computed result.
eval_artifact::grading_checksum() {
    local path="$1" result="$2"
    local canon
    canon=$(jq -cS '[.evals[]? | {id, priority, status}]' "$path" 2>/dev/null)
    printf '%s\n%s' "$canon" "$result" | shasum -a 256 | awk '{print $1}'
}

# Validates and atomically stamps one loop-scope grade.
post_evals::grade_loop() {
    local path="$1"
    post_evals::validate_structure "$path" "" "" "loop" || return 1

    local amend_count prior_stamped
    amend_count=$(jq -r '(.amendments // []) | length' "$path")
    if ! [[ "$amend_count" =~ ^[0-9]+$ ]]; then
        printf 'post_evals: grade-loop refused for %s — .amendments is malformed (not an array).\n' "$path" >&2
        return 1
    fi
    if jq -e '(.grading // .graded_at // .result) != null' "$path" >/dev/null 2>&1; then
        prior_stamped=$(jq -r '(.grading.amendments_at_grade // 0) | tonumber? // 0' "$path")
        [[ "$prior_stamped" =~ ^[0-9]+$ ]] || prior_stamped=0
        if [[ "$amend_count" -gt "$prior_stamped" ]]; then
            local unattested
            unattested=$(jq --argjson n "$prior_stamped" \
                '[.amendments[$n:][] | select(((.regraded_by? // "") | (type == "string" and test("\\S"))) | not)] | length' "$path" 2>/dev/null)
            if ! [[ "$unattested" =~ ^[0-9]+$ ]] || [[ "$unattested" -gt 0 ]]; then
                printf 'post_evals: grade-loop refused for %s — post-grade amendments require a non-blank regraded_by.\n' "$path" >&2
                return 1
            fi
        fi
    fi

    local result checksum graded_at tmp
    result=$(post_evals::compute_and_validate_result "$path")
    checksum=$(eval_artifact::grading_checksum "$path" "$result")
    graded_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    tmp="${path}.tmp.$$"
    if ! jq --arg result "$result" \
        --arg graded_at "$graded_at" \
        --arg by "post_evals.sh grade-loop" \
        --arg checksum "$checksum" \
        --argjson amendments_at_grade "$amend_count" \
        '.result = $result | .graded_at = $graded_at | .grading = {by: $by, checksum: $checksum, amendments_at_grade: $amendments_at_grade}' \
        "$path" >"$tmp"; then
        rm -f "$tmp"
        printf 'post_evals: grade-loop failed to write graded output for %s\n' "$path" >&2
        return 1
    fi
    if ! mv "$tmp" "$path"; then
        printf 'post_evals: grade-loop failed to install graded output for %s (tmp file left at %s)\n' "$path" "$tmp" >&2
        return 1
    fi
    printf '%s' "$result"
}
