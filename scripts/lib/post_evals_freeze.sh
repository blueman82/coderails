#!/bin/bash
# post_evals_freeze.sh — check 8 (freeze-before-build), embed validation,
# and the discriminating-check gate (validate_freeze, validate_embed,
# _run_formula, validate_discriminating).
# Split out of post_evals.sh to keep files under the repo LOC ceiling.
# Sourced by post_evals.sh — not meant to be run directly.
# Note: no set -euo pipefail — sourced; functions return exit codes.


# post_evals::validate_freeze <evals_json_path>
# Check 8's body, factored out to keep validate_structure readable.
#
# Skips (exit 0) when there is nothing to check: no frozen_sha field (every
# artifact predating this check, plus loop scope), or the file is not inside a
# repo working tree so there is no branch to compare against. Those are
# absences of applicability, not violations — hard-failing them would break
# every existing caller.
#
# Fails closed on everything else: a frozen_sha git cannot resolve is a
# violation, not a pass, because "git couldn't answer" must never read as
# compliance.
#
# Escape hatch: a late freeze is permitted when it is DISCLOSED in writing —
# the precedent is PR #54, whose artifact stated plainly that its evals were
# authored after implementation and not backdated. The disclosure must be
# explicit prose in verification_justification or an amendment reason, deliberately not
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
    disclosure=$(jq -r '[(.verification_justification // ""), (.amendments[]?.why // "")] | join(" ") | ascii_downcase' "$path")
    if [[ "$disclosure" == *"freeze"* || "$disclosure" == *"frozen"* ]]; then
        return 0
    fi

    printf 'post_evals: frozen_sha %s is not an ancestor of the branch base %s — the evals were frozen after implementation began (freeze-before-build). Fix the freeze, or disclose the late freeze in verification_justification or an amendment reason.\n' "$frozen" "$base" >&2
    return 1
}

# post_evals::validate_embed <evals_json_path> <body_path>
# Validates the POSTED COMMENT BODY (not the source file alone): the body
# must carry a marker line whose verification_level this function reads via
# eval_artifact::parse_verification_level (the SSOT the integrity-gate daemon itself triages
# on — never taken as an argument, so a body whose marker disagrees with its
# own embedded block can't slip past). verification_level!=0 → not required, exit 0
# immediately (verification_level-1/2 artifacts are short-circuited by the daemon). At
# verification_level 0: the body must contain EXACTLY ONE fenced ```json block, it must
# parse as JSON, its .verification_level must equal the marker's verification_level, and its .task_ref
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
    local marker_verification_level
    marker_verification_level=$(eval_artifact::parse_verification_level "$marker_line")
    if [[ -z "$marker_verification_level" ]]; then
        printf 'post_evals: validate_embed: body marker line does not parse (missing or malformed marker): %s\n' "$body_path" >&2
        return 1
    fi

    # Not required at verification_level 1/2 — the daemon short-circuits those to
    # success/not-verification_level-0 without extracting an embedded artifact.
    if [[ "$marker_verification_level" != "0" ]]; then
        return 0
    fi

    local block_count
    block_count=$(grep -c '^```json[[:space:]]*$' "$body_path")
    if [[ "$block_count" -ne 1 ]]; then
        printf 'post_evals: validate_embed: verification_level-0 body must contain exactly one fenced json block, found %s\n' "$block_count" >&2
        return 1
    fi

    local block
    block=$(awk '/^```json[[:space:]]*$/{f=1;next} /^```[[:space:]]*$/{if(f){f=0}} f' "$body_path")
    if ! jq -e . >/dev/null 2>&1 <<<"$block"; then
        printf 'post_evals: validate_embed: fenced json block does not parse as JSON\n' >&2
        return 1
    fi

    local block_verification_level
    block_verification_level=$(jq -r '.verification_level // ""' <<<"$block")
    if [[ "$block_verification_level" != "$marker_verification_level" ]]; then
        printf 'post_evals: validate_embed: embedded block verification_level (%s) does not match marker verification_level (%s)\n' "$block_verification_level" "$marker_verification_level" >&2
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
