#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  eval-artifact.sh │ Marker SSOT for the coderails eval artifact
#  Both the writer (/coderails:post-evals) and the reader (/merge gate)
#  source this file — one constructor, no drift. Mirrors review-artifact.sh.
#═══════════════════════════════════════════════════════════════════════════════

EVAL_ARTIFACT_MARKER_VERSION="v1"

# eval_artifact::marker <pr> <head_sha> <result> <tier>
# Echoes the exact marker line for the given PR, head SHA, result, and tier.
eval_artifact::marker() {
    local pr="$1" head_sha="$2" result="$3" tier="$4"
    printf '<!-- coderails-eval-summary %s pr=%s head_sha=%s result=%s tier=%s -->' \
        "$EVAL_ARTIFACT_MARKER_VERSION" "$pr" "$head_sha" "$result" "$tier"
}

# eval_artifact::_pattern <pr> <head_sha>
# Builds the anchored regex shared by matches_marker/parse_result/parse_tier so
# the three functions can't drift on grammar. PR numbers are digits and SHAs
# are hex — both safe to interpolate directly into a regex (no metacharacters).
eval_artifact::_pattern() {
    local pr="$1" head_sha="$2"
    printf '^<!-- coderails-eval-summary %s pr=%s head_sha=%s result=(GO|NO-GO) tier=[0-2] -->$' \
        "$EVAL_ARTIFACT_MARKER_VERSION" "$pr" "$head_sha"
}

# eval_artifact::matches_marker <line> <pr> <head_sha>
# Exit 0 iff <line> is the eval marker for <pr>/<head_sha> at ANY result/tier.
# Anchored regex — not substring grep — so junk prefix/suffix fails. An
# unknown/future version or malformed result/tier grammar never matches
# (fail-closed).
eval_artifact::matches_marker() {
    local line="$1" pr="$2" head_sha="$3"
    local pattern; pattern=$(eval_artifact::_pattern "$pr" "$head_sha")
    [[ "$line" =~ $pattern ]]
}

# eval_artifact::parse_result <line>
# Echoes GO or NO-GO extracted from a line matching the marker grammar for
# ANY pr/sha, or empty string if the line doesn't match.
eval_artifact::parse_result() {
    local line="$1"
    local pattern='^<!-- coderails-eval-summary '"$EVAL_ARTIFACT_MARKER_VERSION"' pr=[^ ]+ head_sha=[^ ]+ result=(GO|NO-GO) tier=[0-2] -->$'
    if [[ "$line" =~ $pattern ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    fi
}

# eval_artifact::parse_tier <line>
# Echoes the tier digit (0, 1, or 2) extracted from a matching line, or empty
# string if the line doesn't match.
eval_artifact::parse_tier() {
    local line="$1"
    local pattern='^<!-- coderails-eval-summary '"$EVAL_ARTIFACT_MARKER_VERSION"' pr=[^ ]+ head_sha=[^ ]+ result=(GO|NO-GO) tier=([0-2]) -->$'
    if [[ "$line" =~ $pattern ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
    fi
}

# eval_artifact::compute_go <evals_json_path>
# Exit 0 (GO) iff every eval object with .priority=="P0" has .status=="pass".
# Exit 1 (NO-GO) otherwise, including when the JSON is malformed or the
# .evals array is absent/not an array (fail-closed on structural garbage).
# This is the ONE place `result` is derived from per-eval statuses.
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
