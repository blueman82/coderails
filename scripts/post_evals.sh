#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  post_evals.sh │ Mechanics for /coderails:post-evals
#  - Validates evals.json structure (anti-gaming structural refusals)
#  - Computes result (GO/NO-GO) — the ONLY place result is derived
#  - Subcommand dispatch for command prose
#  Function bodies live in scripts/lib/post_evals_*.sh (split out to stay
#  under the repo's LOC ceiling); this file sources them and owns only
#  compute_and_validate_result, grade_loop, and the CLI dispatcher.
#═══════════════════════════════════════════════════════════════════════════════
# Note: no 'set -euo pipefail' — sourced by tests; functions return exit codes.

# Source marker SSOT (needed for compute_and_validate_result).
# BASH_SOURCE-relative so this works regardless of cwd.
_POST_EVALS_DIR="$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091 # dynamic path, resolved at runtime relative to BASH_SOURCE
source "${_POST_EVALS_DIR}/lib/eval-artifact.sh"

# Timeout for smoke_verify's gate-time re-execution, distinct from (and much
# larger than) _run_recorded's 10s freeze-time default. MEASURED against real
# eval-shaped commands in this repo, not picked freehand: eval-artifact.test.sh
# ~114ms, merge_evals_gate.test.sh ~1.6s, post_evals.test.sh ~10.4s,
# discriminate.test.sh ~21.5s (the slowest observed). 120s is a defensible
# headroom over that 21.5s max — the freeze-time 10s alarm would false-fail
# discriminate.test.sh outright, which is exactly the failure mode this
# separate constant exists to avoid. Override-able for unusual environments;
# the default is what should hold in this repo.
POST_EVALS_SMOKE_VERIFY_TIMEOUT="${POST_EVALS_SMOKE_VERIFY_TIMEOUT:-120}"

# shellcheck disable=SC1091 # dynamic path, resolved at runtime relative to BASH_SOURCE
source "${_POST_EVALS_DIR}/lib/post_evals_structure.sh"
# shellcheck disable=SC1091 # dynamic path, resolved at runtime relative to BASH_SOURCE
source "${_POST_EVALS_DIR}/lib/post_evals_smoke_freeze.sh"
# shellcheck disable=SC1091 # dynamic path, resolved at runtime relative to BASH_SOURCE
source "${_POST_EVALS_DIR}/lib/post_evals_smoke_gate.sh"
# shellcheck disable=SC1091 # dynamic path, resolved at runtime relative to BASH_SOURCE
source "${_POST_EVALS_DIR}/lib/post_evals_smoke_run.sh"
# shellcheck disable=SC1091 # dynamic path, resolved at runtime relative to BASH_SOURCE
source "${_POST_EVALS_DIR}/lib/post_evals_freeze.sh"

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
# .grading = {by, checksum, amendments_at_grade}, and — read fresh from the
# sibling progress.json at grade time — .session_id/.loop_id/.revision, into
# the file. Echoes GO/NO-GO on success;
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
    if ! [[ "$amend_count" =~ ^[0-9]+$ ]]; then
        printf 'post_evals: grade-loop refused for %s — .amendments is malformed (not an array). Fix the amendments array, then re-run grade-loop.\n' "$path" >&2
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
                printf 'post_evals: grade-loop refused for %s — amendment(s) added after the prior grade lack a non-blank regraded_by (or the amendments array is malformed). Dispatch a fresh grader for the amended eval(s), record regraded_by in each post-verdict amendment, and amend the graded file in place — do not regenerate it — then re-run grade-loop.\n' "$path" >&2
                return 1
            fi
        fi
    fi

    local result; result=$(post_evals::compute_and_validate_result "$path")
    local checksum; checksum=$(eval_artifact::grading_checksum "$path" "$result")
    local graded_at; graded_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # Completion evidence (loop_state_guard/loop_stall_guard) binds
    # session_id+loop_id+revision between progress.json and evals.json, but
    # nothing upstream (task-evals freeze, this function) ever wrote those
    # into evals.json — read them fresh from the sibling progress.json (same
    # dir as $path, per agentic_loop_path.sh) at grade time, the latest point
    # revision can be read since it advances every wave. Absent/unreadable
    # progress.json fails open (grade still proceeds; these are additive
    # fields, not gating ones) since progress.json is loop-state, not always
    # present in isolated/test contexts.
    local progress_json; progress_json="$(dirname "$path")/progress.json"
    if [[ -f "$progress_json" ]] && ! jq -e . "$progress_json" >/dev/null 2>&1; then
        printf 'post_evals: warning — %s exists but does not parse; identity fields not stamped\n' "$progress_json" >&2
    fi
    local psession ploop prevision
    psession=$(jq -r '.session_id // empty' "$progress_json" 2>/dev/null)
    ploop=$(jq -r '.loop_id // empty' "$progress_json" 2>/dev/null)
    prevision=$(jq -r '.revision // empty' "$progress_json" 2>/dev/null)
    [[ "$prevision" =~ ^-?[0-9]+$ ]] || prevision=null

    local tmp; tmp="${path}.tmp.$$"
    if ! jq --arg result "$result" \
       --arg graded_at "$graded_at" \
       --arg by "post_evals.sh grade-loop" \
       --arg checksum "$checksum" \
       --argjson amendments_at_grade "$amend_count" \
       --arg session_id "$psession" \
       --arg loop_id "$ploop" \
       --argjson revision "$prevision" \
       '.result = $result | .graded_at = $graded_at | .grading = {by: $by, checksum: $checksum, amendments_at_grade: $amendments_at_grade}
        | (if $session_id != "" then .session_id = $session_id else . end)
        | (if $loop_id != "" then .loop_id = $loop_id else . end)
        | (if $revision != null then .revision = $revision else . end)' \
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
#   ./scripts/post_evals.sh validate-discriminating <path>
#   ./scripts/post_evals.sh compute-result <path>
#   ./scripts/post_evals.sh grade-loop <path>
#   ./scripts/post_evals.sh smoke-verify <embed_json_path> <head_sha>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        validate-structure)
            post_evals::validate_structure "${2:?validate-structure requires a file argument}" "${3:?}" "${4:?}"
            ;;
        validate-discriminating)
            post_evals::validate_discriminating "${2:?validate-discriminating requires a file argument}"
            ;;
        smoke-run)
            post_evals::smoke_run "${2:?smoke-run requires a file argument}"
            ;;
        smoke-verify)
            post_evals::smoke_verify "${2:?smoke-verify requires a file argument}" "${3:?smoke-verify requires a head_sha argument}"
            ;;
        compute-result)
            post_evals::compute_and_validate_result "${2:?compute-result requires a file argument}"
            ;;
        validate-embed)
            post_evals::validate_embed "${2:?validate-embed requires a file argument}" "${3:?validate-embed requires a body path argument}"
            ;;
        grade-loop)
            post_evals::grade_loop "${2:?grade-loop requires a file argument}"
            ;;
        *)
            printf 'Usage: post_evals.sh validate-structure <path> <pr> <sha>\n' >&2
            printf '       post_evals.sh validate-discriminating <path>\n' >&2
            printf '       post_evals.sh smoke-run <path>\n' >&2
            printf '       post_evals.sh smoke-verify <embed_json_path> <head_sha>\n' >&2
            printf '       post_evals.sh compute-result <path>\n' >&2
            printf '       post_evals.sh validate-embed <path> <body_path>\n' >&2
            printf '       post_evals.sh grade-loop <path>\n' >&2
            exit 1
            ;;
    esac
fi
