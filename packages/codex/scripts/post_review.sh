#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  post_review.sh │ Mechanics for $coderails-codex:post-review
#  - Validates summary grammar (anti-placeholder gate)
#  - Subcommand dispatch for the native Codex skill
#═══════════════════════════════════════════════════════════════════════════════
# Note: no 'set -euo pipefail' — sourced by tests; functions return exit codes.

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
    grep -qxF '## Critical' "$file" || missing+=("## Critical")
    grep -qxF '## Important' "$file" || missing+=("## Important")
    grep -qxF '## Suggestions' "$file" || missing+=("## Suggestions")

    if [[ ${#missing[@]} -gt 0 ]]; then
        printf 'validate_summary: missing required headings: %s\n' "${missing[*]}" >&2
        return 1
    fi

    # Each heading must have at least one bullet (^- ) or the literal 'None' before the next ##
    local rc=0
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

    check_heading "## Critical" || rc=1
    check_heading "## Important" || rc=1
    check_heading "## Suggestions" || rc=1

    return $rc
}

# ─── Subcommand dispatch ───────────────────────────────────────────────────────
# Called by the post-review skill as:
#   ./scripts/post_review.sh validate <file>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
    validate)
        post_review::validate_summary "${2:?validate requires a file argument}"
        ;;
    *)
        printf 'Usage: post_review.sh validate <file>\n' >&2
        exit 1
        ;;
    esac
fi
