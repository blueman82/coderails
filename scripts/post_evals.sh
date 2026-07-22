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

    # Check 8: freeze-before-build. The task-evals skill stamps frozen_sha
    # "before implementation starts", but until now nothing verified it —
    # evals could be authored after the code and pointed at any commit. This
    # makes the rule mechanical: frozen_sha must be an ancestor of the
    # branch's merge-base with the default branch, i.e. a commit that already
    # existed before the branch's own implementation commits.
    #
    # pr scope only: loop-scope artifacts live outside any repo (beside
    # progress.json) and have no branch to compare against.
    if [[ "$scope" != "loop" ]]; then
        post_evals::validate_freeze "$path" || return 1
    fi

    return 0
}

# post_evals::validate_freeze <evals_json_path>
# Check 8's body, factored out to keep validate_structure readable.
#
# Skips (exit 0) when there is nothing to check: no frozen_sha field (every
# artifact predating this check, plus loop scope), or the file is not inside a
# git work tree so there is no branch to compare against. Those are absences of
# applicability, not violations — hard-failing them would break every existing
# caller.
#
# Fails closed on everything else: a frozen_sha git cannot resolve is a
# violation, not a pass, because "git couldn't answer" must never read as
# compliance.
#
# Escape hatch: a late freeze is permitted when it is DISCLOSED in writing —
# the precedent is PR #54, whose artifact stated plainly that its evals were
# authored after implementation and not backdated. The disclosure must be
# explicit prose in tier_justification or an amendment reason, deliberately not
# a boolean flag: a flag can be set silently, a sentence has to be written and
# is visible to any human reading the artifact.
post_evals::validate_freeze() {
    local path="$1"

    # Explicit, because the skip path below keys on an empty frozen_sha: if jq
    # is missing, every read returns empty and a violating artifact would look
    # exactly like one with no frozen_sha at all — the check would pass while
    # verifying nothing. Named here rather than left to an incidental non-zero
    # exit, so a later refactor cannot quietly turn this into a fail-open.
    if ! command -v jq >/dev/null 2>&1; then
        printf 'post_evals: jq is required to validate frozen_sha (freeze-before-build) and was not found\n' >&2
        return 1
    fi

    local frozen
    frozen=$(jq -r '.frozen_sha // "" | gsub("^\\s+|\\s+$"; "")' "$path")
    [[ -z "$frozen" ]] && return 0

    local dir
    dir=$(cd "$(dirname "$path")" 2>/dev/null && pwd) || return 0
    git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

    if ! git -C "$dir" cat-file -e "${frozen}^{commit}" 2>/dev/null; then
        printf 'post_evals: frozen_sha %s does not resolve to a commit in this repository\n' "$frozen" >&2
        return 1
    fi

    # The branch base: where this branch diverged from the default branch.
    # Try the remote default first, then a local one, so this works both in a
    # fetched clone and in a bare local repo with no remote.
    local base="" ref
    for ref in origin/HEAD origin/main origin/master main master; do
        if git -C "$dir" rev-parse --verify --quiet "$ref" >/dev/null 2>&1; then
            base=$(git -C "$dir" merge-base HEAD "$ref" 2>/dev/null) && [[ -n "$base" ]] && break
            base=""
        fi
    done
    # No default branch to compare against (detached, orphan, unusual layout):
    # nothing to enforce against, so skip rather than block honest work.
    [[ -z "$base" ]] && return 0

    if git -C "$dir" merge-base --is-ancestor "$frozen" "$base" 2>/dev/null; then
        return 0
    fi

    # Late freeze. Permitted only when disclosed in writing.
    local disclosure
    disclosure=$(jq -r '[(.tier_justification // ""), (.amendments[]?.why // "")] | join(" ") | ascii_downcase' "$path")
    if [[ "$disclosure" == *"freeze"* || "$disclosure" == *"frozen"* ]]; then
        return 0
    fi

    printf 'post_evals: frozen_sha %s is not an ancestor of the branch base %s — the evals were frozen after implementation began (freeze-before-build). Fix the freeze, or disclose the late freeze in tier_justification or an amendment reason.\n' "$frozen" "$base" >&2
    return 1
}

# post_evals::validate_embed <evals_json_path> <body_path>
# Validates the POSTED COMMENT BODY (not the source file alone): the body
# must carry a marker line whose tier this function reads via
# eval_artifact::parse_tier (the SSOT the tier-gate daemon itself triages
# on — never taken as an argument, so a body whose marker disagrees with its
# own embedded block can't slip past). tier!=0 → not required, exit 0
# immediately (tier-1/2 artifacts are short-circuited by the daemon). At
# tier 0: the body must contain EXACTLY ONE fenced ```json block, it must
# parse as JSON, its .tier must equal the marker's tier, and its .task_ref
# must equal <evals_json_path>'s own .task_ref (the file already validated
# by validate_structure earlier in the same posting flow — comparing against
# the numeric PR argument would be wrong since task_ref may legitimately be
# a branch name, frozen before a PR exists). Fail-closed throughout: any
# missing/ambiguous/mismatched state returns 1 with a named reason.
post_evals::validate_embed() {
    local path="$1" body_path="$2"

    if [[ ! -f "$body_path" ]]; then
        printf 'post_evals: validate_embed: body file not found: %s\n' "$body_path" >&2
        return 1
    fi

    local marker_line
    marker_line=$(head -n 1 "$body_path")
    local marker_tier
    marker_tier=$(eval_artifact::parse_tier "$marker_line")
    if [[ -z "$marker_tier" ]]; then
        printf 'post_evals: validate_embed: body marker line does not parse (missing or malformed marker): %s\n' "$body_path" >&2
        return 1
    fi

    # Not required at tier 1/2 — the daemon short-circuits those to
    # success/not-tier-0 without extracting an embedded artifact.
    if [[ "$marker_tier" != "0" ]]; then
        return 0
    fi

    local block_count
    block_count=$(grep -c '^```json[[:space:]]*$' "$body_path")
    if [[ "$block_count" -ne 1 ]]; then
        printf 'post_evals: validate_embed: tier-0 body must contain exactly one fenced json block, found %s\n' "$block_count" >&2
        return 1
    fi

    local block
    block=$(awk '/^```json[[:space:]]*$/{f=1;next} /^```[[:space:]]*$/{if(f){f=0}} f' "$body_path")
    if ! jq -e . >/dev/null 2>&1 <<<"$block"; then
        printf 'post_evals: validate_embed: fenced json block does not parse as JSON\n' >&2
        return 1
    fi

    local block_tier
    block_tier=$(jq -r '.tier // ""' <<<"$block")
    if [[ "$block_tier" != "$marker_tier" ]]; then
        printf 'post_evals: validate_embed: embedded block tier (%s) does not match marker tier (%s)\n' "$block_tier" "$marker_tier" >&2
        return 1
    fi

    local file_task_ref block_task_ref
    file_task_ref=$(jq -r '.task_ref // ""' "$path")
    block_task_ref=$(jq -r '.task_ref // ""' <<<"$block")
    if [[ -z "$block_task_ref" || "$block_task_ref" != "$file_task_ref" ]]; then
        printf 'post_evals: validate_embed: embedded block task_ref (%s) does not match source evals.json task_ref (%s)\n' "$block_task_ref" "$file_task_ref" >&2
        return 1
    fi

    return 0
}

# post_evals::_run_formula <formula> <input>
# Echoes <input> piped into `bash -c <formula>`, capped at a 10s timeout via
# perl's alarm (present on every macOS and Linux box this gate runs on — no
# hand-rolled bash job-control race). Echoes the exit code: 142 signals a
# timeout (128 + SIGALRM), 127 signals command-not-found — both are
# environmental outcomes the caller must not read as a discrimination result.
post_evals::_run_formula() {
    local formula="$1" input="$2"
    printf '%s' "$input" | perl -e 'alarm shift; exec "/bin/bash", "-c", shift' 10 "$formula" >/dev/null 2>&1
    printf '%s' "$?"
}

# post_evals::validate_discriminating <evals_json_path>
# Freeze-time gate: for every scripted eval carrying an optional `fixtures`
# object, mechanically proves the check's formula can both pass (on
# fixtures.good) and fail (on fixtures.bad) — rejecting a check that is
# incapable of either. Evals with no `fixtures` field are grandfathered:
# untouched by this gate, exactly as before it existed (see
# skills/task-evals/SKILL.md's honest-boundary note). Exit 0 if every
# fixtures-carrying eval discriminates (or there are none); exit 1 + a
# specific stderr reason on the first failure.
post_evals::validate_discriminating() {
    local path="$1"

    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    local ids
    ids=$(jq -r '[.evals[]? | select(.mode == "scripted") | select(.fixtures != null) | .id] | .[]' "$path")
    [[ -z "$ids" ]] && return 0

    local id
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue

        # fixtures must be an object before extracting good/bad/formula from
        # it — a string/number fixtures value would otherwise error to
        # stderr on every per-field extraction below and fall through the
        # `// ""` fallback into a misleading "non-discriminating" verdict.
        local fixtures_type
        fixtures_type=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .fixtures | type' "$path")
        if [[ "$fixtures_type" != "object" ]]; then
            printf 'post_evals: eval %s has malformed fixtures (must be an object) — got %s.\n' "$id" "$fixtures_type" >&2
            return 1
        fi

        local cmd good bad formula
        cmd=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .cmd // ""' "$path")
        good=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .fixtures.good // ""' "$path")
        bad=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .fixtures.bad // ""' "$path")
        formula=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .fixtures.formula // ""' "$path")

        # Require both good AND bad when fixtures are present — an author
        # who supplies good+formula but omits bad gets bad="" by default,
        # and proving the formula "discriminates" against an empty string
        # nobody wrote is the unsafe direction (a false accept). Reject
        # explicitly rather than silently proving something the author
        # never asked for.
        if [[ -z "$good" || -z "$bad" ]]; then
            printf 'post_evals: eval %s fixtures present but good and bad are both required — got good=%s, bad=%s.\n' "$id" "$([[ -n "$good" ]] && echo present || echo missing)" "$([[ -n "$bad" ]] && echo present || echo missing)" >&2
            return 1
        fi

        # Determine the formula: explicit fixtures.formula wins; else the
        # substring of cmd after the LAST top-level pipe. Deliberately not a
        # shell parser — if cmd has no pipe and no explicit formula was
        # given, fail closed rather than guess.
        if [[ -z "$formula" ]]; then
            if [[ "$cmd" == *"|"* ]]; then
                formula="${cmd##*|}"
                # Trim leading/trailing whitespace left by the split.
                formula="${formula#"${formula%%[![:space:]]*}"}"
                formula="${formula%"${formula##*[![:space:]]}"}"
            else
                printf 'post_evals: eval %s has fixtures but no derivable formula — cmd has no pipe. Supply fixtures.formula explicitly.\n' "$id" >&2
                return 1
            fi
        fi

        local good_rc bad_rc
        good_rc=$(post_evals::_run_formula "$formula" "$good")
        bad_rc=$(post_evals::_run_formula "$formula" "$bad")

        # Environmental outcomes (127 = command not found, 142 = our timeout
        # sentinel) are reported distinctly — never conflated with a
        # discrimination verdict, on EITHER leg.
        if [[ "$good_rc" == "127" || "$bad_rc" == "127" ]]; then
            printf 'post_evals: eval %s formula execution failed (command not found) — good exit=%s, bad exit=%s. Fix the formula, not this gate.\n' "$id" "$good_rc" "$bad_rc" >&2
            return 1
        fi
        if [[ "$good_rc" == "142" || "$bad_rc" == "142" ]]; then
            printf 'post_evals: eval %s formula execution timed out (10s) — good exit=%s, bad exit=%s.\n' "$id" "$good_rc" "$bad_rc" >&2
            return 1
        fi
        # 126 (permission denied) and 128+n signal deaths (137=SIGKILL,
        # 139=SIGSEGV, ...) are environmental crashes, not discrimination
        # signals — without this check they fall through to the accept path
        # below (good_rc=0 && bad_rc!=0) and an environmental crash on the
        # bad leg reads as a legitimate discrimination fail. This check runs
        # AFTER the 142 check above so the 142-timeout message stays
        # distinct; 142 is itself >=128, so ordering here is load-bearing.
        # DECISION: a formula that CRASHES (e.g. 137) on bad input is
        # environmental-suspect and rejected — NOT treated as a valid
        # content fail, because a crash is not a discrimination signal.
        if [[ "$good_rc" == "126" || "$bad_rc" == "126" || "$good_rc" -ge 128 || "$bad_rc" -ge 128 ]]; then
            printf 'post_evals: eval %s formula execution crashed (environmental) — good exit=%s, bad exit=%s. Fix the formula, not this gate.\n' "$id" "$good_rc" "$bad_rc" >&2
            return 1
        fi

        if [[ "$good_rc" == "0" && "$bad_rc" != "0" ]]; then
            continue
        fi

        if [[ "$good_rc" == "$bad_rc" ]]; then
            printf 'post_evals: eval %s formula is non-discriminating — good and bad fixtures both exit %s. The check can never both pass and fail.\n' "$id" "$good_rc" >&2
            return 1
        fi

        printf 'post_evals: eval %s formula did not discriminate as required — good fixture exit=%s (want 0), bad fixture exit=%s (want non-zero).\n' "$id" "$good_rc" "$bad_rc" >&2
        return 1
    done <<< "$ids"

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
#   ./scripts/post_evals.sh validate-discriminating <path>
#   ./scripts/post_evals.sh compute-result <path>
#   ./scripts/post_evals.sh grade-loop <path>
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    case "${1:-}" in
        validate-structure)
            post_evals::validate_structure "${2:?validate-structure requires a file argument}" "${3:?}" "${4:?}"
            ;;
        validate-discriminating)
            post_evals::validate_discriminating "${2:?validate-discriminating requires a file argument}"
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
            printf '       post_evals.sh compute-result <path>\n' >&2
            printf '       post_evals.sh validate-embed <path> <body_path>\n' >&2
            printf '       post_evals.sh grade-loop <path>\n' >&2
            exit 1
            ;;
    esac
fi
