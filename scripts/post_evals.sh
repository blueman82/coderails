#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  post_evals.sh │ Mechanics for /coderails:post-evals
#  - Validates evals.json structure (anti-gaming structural refusals)
#  - Computes result (GO/NO-GO) — the ONLY place result is derived
#  - Subcommand dispatch for command prose
#═══════════════════════════════════════════════════════════════════════════════
# Note: no 'set -euo pipefail' — sourced by tests; functions return exit codes.

# Source marker SSOT (needed for compute_and_validate_result).
# BASH_SOURCE-relative so this works regardless of cwd.
_POST_EVALS_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "${_POST_EVALS_DIR}/lib/eval-artifact.sh"

# post_evals::validate_structure <evals_json_path> <pr> <current_head_sha>
# Exit 0 if the file passes every structural refusal check; exit 1 + a
# specific stderr reason otherwise. Refusals checked in order, first failure
# wins.
post_evals::validate_structure() {
    local path="$1" pr="$2" current_head_sha="$3"

    # Check 1: file exists and is valid JSON.
    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    local tier
    tier=$(jq -r '.tier // ""' "$path")

    # Check 2: tier 0 requires non-empty tier_justification.
    if [[ "$tier" == "0" ]]; then
        local justification
        justification=$(jq -r '.tier_justification // ""' "$path")
        if [[ -z "$justification" ]]; then
            printf 'post_evals: tier 0 requires non-empty tier_justification\n' >&2
            return 1
        fi
    fi

    # Checks 3-5 only apply when there are scripted/P0 evals to check — a
    # tier-0 exemption file has an empty (or absent) .evals array, so none of
    # these can fire against it.

    # Check 3: tier>=1 scripted eval with empty negative_control.
    if [[ "$tier" != "0" ]]; then
        local bad_id
        bad_id=$(jq -r '[.evals[]? | select(.mode == "scripted") | select((.negative_control // "") == "") | .id] | first // ""' "$path")
        if [[ -n "$bad_id" ]]; then
            printf 'post_evals: tier>=1 scripted eval %s has empty negative_control\n' "$bad_id" >&2
            return 1
        fi
    fi

    # Check 4: negative_control textually identical to cmd.
    local identical_id
    identical_id=$(jq -r '[.evals[]? | select(.mode == "scripted") | select((.negative_control // "") == (.cmd // "") and (.negative_control // "") != "") | .id] | first // ""' "$path")
    if [[ -n "$identical_id" ]]; then
        printf 'post_evals: eval %s negative_control is identical to cmd\n' "$identical_id" >&2
        return 1
    fi

    # Check 5: any P0 eval with empty evidence.
    local no_evidence_id
    no_evidence_id=$(jq -r '[.evals[]? | select(.priority == "P0") | select((.evidence // "") == "") | .id] | first // ""' "$path")
    if [[ -n "$no_evidence_id" ]]; then
        printf 'post_evals: P0 eval %s has empty evidence\n' "$no_evidence_id" >&2
        return 1
    fi

    # Check 6: head_sha must match the PR's current head.
    local file_sha
    file_sha=$(jq -r '.head_sha // ""' "$path")
    if [[ "$file_sha" != "$current_head_sha" ]]; then
        printf 'post_evals: evals.json head_sha (%s) does not match current PR head (%s)\n' "$file_sha" "$current_head_sha" >&2
        return 1
    fi

    return 0
}

# post_evals::compute_and_validate_result <evals_json_path>
# Echoes GO or NO-GO by calling eval_artifact::compute_go. This is the ONLY
# place the artifact's result value is produced — never read from a
# caller-supplied field.
post_evals::compute_and_validate_result() {
    local path="$1"
    if eval_artifact::compute_go "$path"; then
        printf 'GO'
    else
        printf 'NO-GO'
    fi
}

# ─── Subcommand dispatch ───────────────────────────────────────────────────────
# Called by the post-evals command prose as:
#   ./scripts/post_evals.sh validate-structure <path> <pr> <sha>
#   ./scripts/post_evals.sh compute-result <path>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        validate-structure)
            post_evals::validate_structure "${2:?validate-structure requires a file argument}" "${3:?}" "${4:?}"
            ;;
        compute-result)
            post_evals::compute_and_validate_result "${2:?compute-result requires a file argument}"
            ;;
        *)
            printf 'Usage: post_evals.sh validate-structure <path> <pr> <sha>\n' >&2
            printf '       post_evals.sh compute-result <path>\n' >&2
            exit 1
            ;;
    esac
fi
