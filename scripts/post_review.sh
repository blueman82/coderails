#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  post_review.sh │ Mechanics for /coderails:post-review
#  - Validates summary grammar (anti-placeholder gate)
#  - Best-effort cache write to progress.json
#  - Subcommand dispatch for command prose
#═══════════════════════════════════════════════════════════════════════════════
# Note: no 'set -euo pipefail' — sourced by tests; functions return exit codes.

# Source marker SSOT (needed by write_cache to record the marker version).
# BASH_SOURCE-relative so this works regardless of cwd.
_POST_REVIEW_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "${_POST_REVIEW_DIR}/lib/review-artifact.sh"

# post_review::validate_summary <file>
# Reads summary body from <file>; exit 0 if it satisfies the grammar, exit 1 + stderr reason.
#
# Grammar:
#   EITHER the body contains the line '## No findings'
#   OR     it contains ALL THREE of: ## Critical, ## Important, ## Suggestions
#          each followed (before the next ## or EOF) by at least one line matching
#          '^- ' (a bullet) or the literal line 'None'.
#   A heading with an empty section fails.
post_review::validate_summary() {
    local file="$1"

    if [[ ! -f "$file" ]]; then
        printf 'validate_summary: file not found: %s\n' "$file" >&2
        return 1
    fi

    # Check for '## No findings' path
    if grep -qxF '## No findings' "$file"; then
        if grep -qxF '## Critical' "$file" || grep -qxF '## Important' "$file" || grep -qxF '## Suggestions' "$file"; then
            printf 'validate_summary: ambiguous — "## No findings" present alongside structured headings\n' >&2
            return 1
        fi
        return 0
    fi

    # Must have all three headings
    local missing=()
    grep -qxF '## Critical'    "$file" || missing+=("## Critical")
    grep -qxF '## Important'   "$file" || missing+=("## Important")
    grep -qxF '## Suggestions' "$file" || missing+=("## Suggestions")

    if [[ ${#missing[@]} -gt 0 ]]; then
        printf 'validate_summary: missing required headings: %s\n' "${missing[*]}" >&2
        return 1
    fi

    # Each heading must have at least one bullet (^- ) or the literal 'None' before the next ##
    local rc=0
    local check_heading
    check_heading() {
        local heading="$1"
        # Use awk: after finding the heading, collect lines until the next ## or EOF,
        # then check whether any line is a bullet or 'None'.
        local found
        found=$(awk -v h="$heading" '
            $0 == h { in_section=1; next }
            in_section && /^## / { exit }
            in_section && (/^- / || $0 == "None") { found=1; exit }
        END { if (found) print "ok" }
        ' "$file")
        if [[ "$found" != "ok" ]]; then
            printf 'validate_summary: section "%s" has no bullet or None\n' "$heading" >&2
            return 1
        fi
    }

    check_heading "## Critical"    || rc=1
    check_heading "## Important"   || rc=1
    check_heading "## Suggestions" || rc=1

    return $rc
}

# post_review::write_cache <progress_path> <pr> <head_sha> <url> <author> <iso8601>
# Best-effort: if <progress_path> exists, writes the review cache block via jq.
# If absent, prints a warning to stderr and returns 0 (cache is never required).
post_review::write_cache() {
    local path="$1" pr="$2" head_sha="$3" url="$4" author="$5" posted_at="$6"

    if [[ ! -f "$path" ]]; then
        printf 'write_cache: progress.json not found at %s — skipping cache write\n' "$path" >&2
        return 0
    fi

    local tmp="${path}.tmp"
    if jq --arg pr "$pr" \
          --arg sha "$head_sha" \
          --arg url "$url" \
          --arg author "$author" \
          --arg posted_at "$posted_at" \
          '.review = {
              ran: true,
              pr: ($pr | tonumber),
              head_sha: $sha,
              summary_posted: true,
              summary_url: $url,
              summary_author: $author,
              posted_at: $posted_at
          }' "$path" > "$tmp"; then
        if ! mv "$tmp" "$path"; then
            printf 'write_cache: mv failed — progress.json left unchanged\n' >&2
            rm -f "$tmp" 2>/dev/null || true
            return 1
        fi
    else
        rm -f "$tmp"
        printf 'write_cache: jq failed — progress.json left unchanged\n' >&2
        return 1
    fi
}

# ─── Subcommand dispatch ───────────────────────────────────────────────────────
# Called by the post-review command prose as:
#   ./scripts/post_review.sh validate <file>
#   ./scripts/post_review.sh write-cache <path> <pr> <sha> <url> <author> <iso8601>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        validate)
            post_review::validate_summary "${2:?validate requires a file argument}"
            ;;
        write-cache)
            post_review::write_cache "${2:?}" "${3:?}" "${4:?}" "${5:?}" "${6:?}" "${7:?}"
            ;;
        *)
            printf 'Usage: post_review.sh validate <file>\n' >&2
            printf '       post_review.sh write-cache <path> <pr> <sha> <url> <author> <iso8601>\n' >&2
            exit 1
            ;;
    esac
fi
