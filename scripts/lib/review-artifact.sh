#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  review-artifact.sh │ Marker SSOT for the coderails review artifact
#  Both the writer (/coderails:post-review) and the reader (/merge gate)
#  source this file — one constructor, no drift.
#═══════════════════════════════════════════════════════════════════════════════

REVIEW_ARTIFACT_MARKER_VERSION="v1"

# review_artifact::marker <pr> <head_sha>
# Echoes the exact marker line for the given PR and head SHA.
review_artifact::marker() {
    local pr="$1" head_sha="$2"
    printf '<!-- coderails-review-summary %s pr=%s head_sha=%s -->' \
        "$REVIEW_ARTIFACT_MARKER_VERSION" "$pr" "$head_sha"
}

# review_artifact::matches_marker <line> <pr> <head_sha>
# Exit 0 iff <line> is EXACTLY equal to the marker for <pr>/<head_sha>.
# Uses string equality — NOT substring grep — so a line with junk prefix/suffix fails.
# An unknown/future version never matches (fail-closed).
review_artifact::matches_marker() {
    local line="$1" pr="$2" head_sha="$3"
    [ "$line" = "$(review_artifact::marker "$pr" "$head_sha")" ]
}
