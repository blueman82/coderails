#!/bin/bash
# post_evals_structure.sh — post_evals::validate_structure (checks 1-11).
# Split out of post_evals.sh to keep files under the repo LOC ceiling.
# Sourced by post_evals.sh — not meant to be run directly.
# Note: no set -euo pipefail — sourced; functions return exit codes.

post_evals::validate_structure() {
    # shellcheck disable=SC2034 # pr kept for call-site symmetry with other post_evals:: fns; unused here
    local path="$1" pr="$2" current_head_sha="$3" scope="${4:-pr}"

    # Check 1: file exists and is valid JSON.
    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    local verification_level
    verification_level=$(jq -r '.verification_level // ""' "$path")

    # Check 2: every verification_level requires a non-blank verification_justification — verification_level 0
    # justifies the exemption itself; verification_level>=1 justifies which verification_level predicate
    # fired (owner directive: tightens this from verification_level-0-only to all verification levels).
    # "Non-blank" is trim-then-check, not merely non-empty, so a
    # whitespace-only string doesn't slip through.
    local justification
    justification=$(jq -r '.verification_justification // "" | gsub("^\\s+|\\s+$"; "")' "$path")
    if [[ -z "$justification" ]]; then
        printf 'post_evals: verification_level %s requires a non-blank verification_justification\n' "${verification_level:-<unset>}" >&2
        return 1
    fi

    # Checks 3-5 only apply when there are scripted/P0 evals to check — a
    # verification_level-0 exemption file has an empty (or absent) .evals array, so none of
    # these can fire against it.

    # Check 3: verification_level>=1 scripted eval with empty negative_control.
    if [[ "$verification_level" != "0" ]]; then
        local bad_id
        bad_id=$(jq -r '[.evals[]? | select(.mode == "scripted") | select((.negative_control // "") == "") | .id] | first // ""' "$path")
        if [[ -n "$bad_id" ]]; then
            printf 'post_evals: verification_level>=1 scripted eval %s has empty negative_control\n' "$bad_id" >&2
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

    # Check 7: verification_level>=1 requires at least one P0 eval. Without this, a verification_level-1+
    # artifact with an empty (or only-P1) .evals array computes GO past every
    # other refusal — eval_artifact::compute_go's P0-only gate is vacuously
    # satisfied when there are no P0 evals to fail. Verification level 0 is exempt (that's
    # its whole point: the verification_justification in check 2 stands in for evals).
    if [[ "$verification_level" != "0" ]]; then
        local has_p0
        has_p0=$(jq -r '[.evals[]? | select(.priority == "P0")] | length > 0' "$path")
        if [[ "$has_p0" != "true" ]]; then
            printf 'post_evals: verification_level>=1 requires at least one P0 eval in .evals\n' >&2
            return 1
        fi
    fi

    # Check 8: freeze-before-build. The task-evals skill stamps frozen_sha
    # "before implementation starts", but until now nothing verified it —
    # evals could be authored after the code and pointed at any commit. This
    # makes the rule mechanical: frozen_sha must be an ancestor of the
    # branch's merge-base with the default branch, i.e. a commit that already
    # existed before the branch's own implementation commits.
    #
    # pr scope only: loop-scope artifacts live outside any repo (beside
    # progress.json) and have no branch to compare against.
    # Check 9: recorded freeze-time smoke evidence. pr scope only, matching
    # check 8's boundary. Not a technical limit — check 9 needs no repository,
    # only the recorded outcome — but a deliberate one: loop-scope artifacts
    # are gated by a separate surface (loop_state_guard), and extending this
    # contract there is its own decision with its own callers to migrate.
    # Check 10: gate-time re-execution. Check 9 gates the SHAPE of recorded
    # smoke evidence, but the author writes those numbers — a hand-written
    # `smoke` object of plausible shape for a cmd that never existed passes
    # check 9 without any command ever running. This check never trusts a
    # typed number: it executes cmd and negative_control itself, here, and
    # judges only what it observes. Same pr-scope boundary as checks 8/9.
    if [[ "$scope" != "loop" ]]; then
        post_evals::validate_freeze "$path" || return 1
        post_evals::validate_smoke "$path" || return 1
        post_evals::validate_smoke_execution "$path" || return 1
    fi

    # Check 11: new_cases[] join integrity. A later reviewer can discover a
    # case the frozen suite never anticipated — distinct from amendments[]
    # (edits an existing eval) and withdrawn_proofs (a proof that ran and
    # legitimately failed). Each new_cases[] entry names the .evals[].id it
    # was folded into; if that id doesn't exist in THIS file's .evals[], the
    # entry references a case that was never actually graded — refuse.
    # Absent/empty new_cases[] is a no-op (most PRs never use this field).
    # Scope-independent, like checks 1-7: no repo or execution needed.
    #
    # Shape-guarded like check 9/10's .evals guard: a non-array new_cases
    # (object/string/number) must not silently iterate zero elements and pass
    # — that would make a malformed new_cases[] indistinguishable from an
    # absent one. An entry with no id, an empty id, or a non-object entry is
    # counted as an offender too — .id defaulting to "" via `// ""` must
    # never fall through the "no match found" branch as if it matched.
    if jq -e 'has("new_cases") and ((.new_cases | type) != "array")' "$path" >/dev/null 2>&1; then
        printf 'post_evals: new_cases is not a JSON array (malformed) — refusing.\n' >&2
        return 1
    fi
    local offender_count orphan_new_case
    offender_count=$(jq -r '
        [.evals[]?.id] as $eval_ids
        | [.new_cases[]?
            | . as $entry
            | (($entry | type) == "object") as $is_obj
            | (if $is_obj then ($entry.id // "") else "" end) as $nc_id
            | select(($is_obj | not)
                      or ($nc_id == "")
                      or ($eval_ids | index($nc_id) | not))]
        | length
    ' "$path")
    if [[ "$offender_count" != "0" ]]; then
        orphan_new_case=$(jq -r '
            [.evals[]?.id] as $eval_ids
            | [.new_cases[]?
                | . as $entry
                | (($entry | type) == "object") as $is_obj
                | (if $is_obj then ($entry.id // "") else "" end) as $nc_id
                | select(($is_obj | not)
                          or ($nc_id == "")
                          or ($eval_ids | index($nc_id) | not))
                | (if $is_obj then ($entry.id // "<missing id>")
                   | if . == "" then "<empty id>" else . end
                   else "<non-object entry>" end)]
            | first
        ' "$path")
        printf 'post_evals: new_cases[] entry %s has no matching .evals[].id\n' "$orphan_new_case" >&2
        return 1
    fi

    return 0
}
