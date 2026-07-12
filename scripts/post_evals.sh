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

# post_evals::validate_structure <evals_json_path> <pr> <current_head_sha> [scope]
# Exit 0 if the file passes every structural refusal check; exit 1 + a
# specific stderr reason otherwise. Refusals checked in order, first failure
# wins. [scope] defaults to "pr" (existing behaviour, check 6 = head_sha vs
# PR head); "loop" swaps check 6 to "head_sha non-blank" and ignores <pr> —
# the loop-scope grade-loop caller passes "" for <pr> in that case. One
# function, one set of check bodies, no duplication between scopes.
post_evals::validate_structure() {
    local path="$1" pr="$2" current_head_sha="$3" scope="${4:-pr}"

    # Check 1: file exists and is valid JSON.
    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    local tier
    tier=$(jq -r '.tier // ""' "$path")

    # Check 2: every tier requires a non-blank tier_justification — tier 0
    # justifies the exemption itself; tier>=1 justifies which tier predicate
    # fired (owner directive: tightens this from tier-0-only to all tiers).
    # "Non-blank" is trim-then-check, not merely non-empty, so a
    # whitespace-only string doesn't slip through.
    local justification
    justification=$(jq -r '.tier_justification // "" | gsub("^\\s+|\\s+$"; "")' "$path")
    if [[ -z "$justification" ]]; then
        printf 'post_evals: tier %s requires a non-blank tier_justification\n' "${tier:-<unset>}" >&2
        return 1
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

    # Check 4: negative_control vacuous relative to cmd. Two sub-checks, both
    # on whitespace-normalised (trimmed + internal runs collapsed) text:
    #   (a) identical to cmd after normalisation (catches trailing-space etc.)
    #   (b) normalised negative_control contains the full normalised cmd as a
    #       WORD-BOUNDED substring — cmd must appear as a whole shell segment,
    #       delimited by string start/end or a shell separator (space, ; & |),
    #       not merely embedded inside a longer identifier. This catches
    #       "true; cmd", "echo x && cmd", "cmd " wrappers while NOT flagging a
    #       genuinely distinct negative control like "cmd-broken" (a different
    #       identifier that happens to share cmd as a text prefix).
    # This is a structural floor, not a semantic one: a genuinely different-but-
    # vacuous control (e.g. one that happens to always pass for unrelated
    # reasons) still passes this check. The verifier/human review layer owns
    # semantic quality of the negative control; this only catches the control
    # being the command itself, verbatim or trivially wrapped.
    local vacuous_id
    vacuous_id=$(jq -r '
        def norm: gsub("^\\s+|\\s+$"; "") | gsub("\\s+"; " ");
        def esc: gsub("(?<c>[.^$*+?()\\[\\]{}|\\\\])"; "\\\(.c)");
        [.evals[]? | select(.mode == "scripted")
                    | select((.negative_control // "") != "")
                    | select((.cmd // "") != "")
                    | (.negative_control | norm) as $nc
                    | (.cmd | norm) as $cmd
                    | (($cmd | esc)) as $cmd_re
                    | select($nc == $cmd
                             or ($nc | test("(^|[\\s;&|])" + $cmd_re + "($|[\\s;&|])")))
                    | .id] | first // ""
    ' "$path")
    if [[ -n "$vacuous_id" ]]; then
        printf 'post_evals: eval %s negative_control is identical to cmd\n' "$vacuous_id" >&2
        return 1
    fi

    # Check 5: any P0 eval with empty evidence.
    local no_evidence_id
    no_evidence_id=$(jq -r '[.evals[]? | select(.priority == "P0") | select((.evidence // "") == "") | .id] | first // ""' "$path")
    if [[ -n "$no_evidence_id" ]]; then
        printf 'post_evals: P0 eval %s has empty evidence\n' "$no_evidence_id" >&2
        return 1
    fi

    # Check 6: pr scope — head_sha must match the PR's current head. loop
    # scope has no PR to compare against, so the check narrows to "head_sha
    # non-blank" (a loop artifact still must record which commit it graded).
    local file_sha
    file_sha=$(jq -r '.head_sha // ""' "$path")
    if [[ "$scope" == "loop" ]]; then
        if [[ -z "$file_sha" ]]; then
            printf 'post_evals: evals.json head_sha must be non-blank (loop scope)\n' >&2
            return 1
        fi
    elif [[ "$file_sha" != "$current_head_sha" ]]; then
        printf 'post_evals: evals.json head_sha (%s) does not match current PR head (%s)\n' "$file_sha" "$current_head_sha" >&2
        return 1
    fi

    # Check 7: tier>=1 requires at least one P0 eval. Without this, a tier-1+
    # artifact with an empty (or only-P1) .evals array computes GO past every
    # other refusal — eval_artifact::compute_go's P0-only gate is vacuously
    # satisfied when there are no P0 evals to fail. Tier 0 is exempt (that's
    # its whole point: the tier_justification in check 2 stands in for evals).
    if [[ "$tier" != "0" ]]; then
        local has_p0
        has_p0=$(jq -r '[.evals[]? | select(.priority == "P0")] | length > 0' "$path")
        if [[ "$has_p0" != "true" ]]; then
            printf 'post_evals: tier>=1 requires at least one P0 eval in .evals\n' >&2
            return 1
        fi
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

# post_evals::grade_loop <evals_json_path>
# Neutral loop-scope grading: validates structure (loop variant — no PR arg,
# check 6 = head_sha non-blank), computes result via eval_artifact::compute_go
# (unchanged SSOT), then atomically writes .result, .graded_at (ISO8601 UTC),
# and .grading = {by, checksum, amendments_at_grade} into the file. Echoes GO/NO-GO on success;
# exit 0 on a successful grade (even NO-GO — a graded NO-GO is still a
# completed, stamped grade), exit 1 on validation refusal (nothing written)
# OR on a write/install failure (jq or mv) — both checked explicitly so a
# failed write is never echoed/exited as if the grade had succeeded.
# Regrade-on-amendment backstop: refuses unattested post-verdict amendments
# (those lacking non-blank regraded_by), preventing grade-loop stamp write.
post_evals::grade_loop() {
    local path="$1"
    post_evals::validate_structure "$path" "" "" "loop" || return 1

    # Regrade-on-amendment backstop: an eval amended AFTER a grader verdict
    # must return to a fresh grader, attested by a non-blank regraded_by on
    # each post-verdict amendment. Prior-verdict detection keys on grade
    # residue (.grading OR .graded_at OR .result), not .grading alone, so
    # shedding the stamp doesn't re-arm the first-grade path. Fail-closed:
    # malformed amendments refuse rather than grade. Honest boundary: this
    # verifies the attestation exists, not that it is true — and it keys on
    # amendment COUNT GROWTH after a grade-loop stamp, so a status flipped
    # with no accompanying amendment, an existing amendment edited in place,
    # or a flip folded in before the first grade-loop run are all outside
    # its reach (rule-5 text + Phase 13 audit territory).
    local amend_count prior_stamped
    amend_count=$(jq -r '(.amendments // []) | length' "$path")
    if jq -e '(.grading // .graded_at // .result) != null' "$path" >/dev/null 2>&1; then
        prior_stamped=$(jq -r '(.grading.amendments_at_grade // 0) | tonumber? // 0' "$path")
        [[ "$prior_stamped" =~ ^[0-9]+$ ]] || prior_stamped=0
        if [[ "$amend_count" -gt "$prior_stamped" ]]; then
            local unattested
            unattested=$(jq --argjson n "$prior_stamped" \
                '[.amendments[$n:][] | select(((.regraded_by? // "") | tostring | test("\\S")) | not)] | length' "$path" 2>/dev/null)
            if ! [[ "$unattested" =~ ^[0-9]+$ ]] || [[ "$unattested" -gt 0 ]]; then
                printf 'post_evals: grade-loop refused for %s — amendment(s) added after the prior grade lack a non-blank regraded_by (or the amendments array is malformed). Dispatch a fresh grader for the amended eval(s), record regraded_by in each post-verdict amendment, and amend the graded file in place — do not regenerate it — then re-run grade-loop.\n' "$path" >&2
                return 1
            fi
        fi
    fi

    local result; result=$(post_evals::compute_and_validate_result "$path")
    local checksum; checksum=$(eval_artifact::grading_checksum "$path" "$result")
    local graded_at; graded_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    local tmp; tmp="${path}.tmp.$$"
    if ! jq --arg result "$result" \
       --arg graded_at "$graded_at" \
       --arg by "post_evals.sh grade-loop" \
       --arg checksum "$checksum" \
       --argjson amendments_at_grade "$amend_count" \
       '.result = $result | .graded_at = $graded_at | .grading = {by: $by, checksum: $checksum, amendments_at_grade: $amendments_at_grade}' \
       "$path" > "$tmp"; then
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

# ─── Subcommand dispatch ───────────────────────────────────────────────────────
# Called by the post-evals command prose as:
#   ./scripts/post_evals.sh validate-structure <path> <pr> <sha>
#   ./scripts/post_evals.sh compute-result <path>
#   ./scripts/post_evals.sh grade-loop <path>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        validate-structure)
            post_evals::validate_structure "${2:?validate-structure requires a file argument}" "${3:?}" "${4:?}"
            ;;
        compute-result)
            post_evals::compute_and_validate_result "${2:?compute-result requires a file argument}"
            ;;
        grade-loop)
            post_evals::grade_loop "${2:?grade-loop requires a file argument}"
            ;;
        *)
            printf 'Usage: post_evals.sh validate-structure <path> <pr> <sha>\n' >&2
            printf '       post_evals.sh compute-result <path>\n' >&2
            printf '       post_evals.sh grade-loop <path>\n' >&2
            exit 1
            ;;
    esac
fi
