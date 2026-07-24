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

# post_evals::validate_structure <evals_json_path> <pr> <current_head_sha> [scope]
# Exit 0 if the file passes every structural refusal check; exit 1 + a
# specific stderr reason otherwise. Refusals checked in order, first failure
# wins. [scope] defaults to "pr" (existing behaviour, check 6 = head_sha vs
# PR head); "loop" swaps check 6 to "head_sha non-blank" and ignores <pr> —
# the loop-scope grade-loop caller passes "" for <pr> in that case. One
# function, one set of check bodies, no duplication between scopes.
#
# smoke_verify (the merge-time gate) deliberately does NOT call this function:
# checks 1-9 are structural validation that already ran at post time in the
# posting agent's own session, and re-imposing them at merge (tried and
# reverted — see git history) added false-blocks unrelated to the security
# property (check 2's tier_justification, check 6's head_sha match) without
# adding anything a fabricator can't already fake. smoke_verify re-executes
# cmd/negative_control directly in its own worktree with its own timeout;
# that re-execution IS the property this system enforces at merge.
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

    return 0
}

# post_evals::validate_smoke <evals_json_path>
# Check 9's body. Requires every tier>=1 scripted eval to carry a `smoke`
# object recording what happened when its `cmd` and `negative_control` were
# actually executed at freeze, and refuses the outcomes that mean the check
# tested nothing.
#
# WHY SHAPE, NOT POLARITY, ON cmd: check 8 makes freeze-before-build
# mechanical, so at freeze the feature is not built and `cmd` is EXPECTED to
# exit non-zero. A gate requiring cmd to pass would contradict check 8 and
# block every honest freeze. What actually separates a broken cmd from a
# legitimately not-yet-passing one is the shape of the outcome: a cmd naming a
# script that never existed exits 127 (command/file not found) — the check
# never reached the artifact it claims to test — whereas a real assertion
# failure exits 1. SKILL.md already names this tell in prose ("a
# module-resolution error instead of an install log"); this makes it
# mechanical.
#
# WHY POLARITY IS CHECKABLE ON negative_control: the control is defined to
# fail, and that is true regardless of build state. So a control observed
# exiting 0 at freeze is vacuous by construction.
#
# THE TRAP THIS AVOIDS: an env-error is ALSO non-zero, so a bare `!= 0`
# assertion on the control would accept a control that errored out for an
# unrelated reason — the vacuous-pass bug relocated one level up. The control
# must therefore be non-zero AND not-environmental. That distinction (real
# failure vs. skip/error) is the tri-state applied exactly where it is
# load-bearing, without refactoring every check in the system to carry it.
#
# The environmental taxonomy (127 not-found, 142 our timeout sentinel, 126
# permission denied, >=128 signal deaths) is the same one
# validate_discriminating already uses on its fixtures legs.
post_evals::validate_smoke() {
    local path="$1"

    # Explicit, for the reason PR #261 paid for on validate_freeze: without
    # this, a missing jq makes every read empty, a violating file becomes
    # indistinguishable from a compliant one, and the gate passes while
    # verifying nothing.
    if ! command -v jq >/dev/null 2>&1; then
        printf 'post_evals: jq is required to validate smoke evidence and was not found\n' >&2
        return 1
    fi

    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    local tier
    tier=$(jq -r '.tier // ""' "$path")
    # Tier 0 is the exemption path: its .evals array is empty by definition,
    # so there is nothing to smoke-test.
    [[ "$tier" == "0" ]] && return 0

    # Shape-guard .evals, same fail-closed guard as smoke_verify and
    # validate_smoke_execution. A non-array .evals makes the `.evals[]?`
    # extraction below yield no ids, and the "no ids → return 0" line then
    # passes without smoke-checking anything. On the live validate_structure
    # chain check 7 refuses a scalar/string first (no P0 found), but an object
    # .evals passes check 7 (`.evals[]?` iterates object values) and reaches
    # here — so this guard is load-bearing for the object shape. Guard on TYPE,
    # never on empty ids (a valid agent-run-only array legitimately has none).
    if ! jq -e '(.evals | type) == "array"' "$path" >/dev/null 2>&1; then
        printf 'post_evals: validate_smoke: .evals is not a JSON array (malformed or absent) — refusing.\n' >&2
        return 1
    fi

    # Only scripted evals carry commands. agent-run evals are graded by a
    # verifier subagent and have no cmd to execute.
    local ids
    ids=$(jq -r '[.evals[]? | select(.mode == "scripted") | .id] | .[]' "$path")
    [[ -z "$ids" ]] && return 0

    local id
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue

        local smoke_type
        smoke_type=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .smoke | type' "$path")

        if [[ "$smoke_type" == "null" ]]; then
            printf 'post_evals: scripted eval %s has no smoke evidence — run its cmd and negative_control at freeze and record the result.\n' "$id" >&2
            return 1
        fi
        # A string/number smoke value would fall through every per-field read
        # below into `// ""` and produce a misleading verdict.
        if [[ "$smoke_type" != "object" ]]; then
            printf 'post_evals: eval %s has malformed smoke evidence (must be an object) — got %s.\n' "$id" "$smoke_type" >&2
            return 1
        fi

        local cmd_rc nc_rc
        cmd_rc=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .smoke.cmd_exit // "" | if type == "number" then tostring else "" end' "$path")
        nc_rc=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .smoke.negative_control_exit // "" | if type == "number" then tostring else "" end' "$path")

        # Absent or non-numeric exit codes fail closed: "no recorded outcome"
        # must never read as a compliant one.
        if [[ -z "$cmd_rc" || -z "$nc_rc" ]]; then
            printf 'post_evals: eval %s smoke evidence needs numeric cmd_exit and negative_control_exit — got cmd_exit=%s, negative_control_exit=%s.\n' \
                "$id" "${cmd_rc:-<missing/non-numeric>}" "${nc_rc:-<missing/non-numeric>}" >&2
            return 1
        fi

        # cmd: environmental outcomes only. A non-zero content failure is
        # permitted and expected — see the freeze-before-build note above.
        if post_evals::_is_environmental_rc "$cmd_rc"; then
            printf 'post_evals: eval %s cmd did not execute at freeze (exit %s: command not found / crashed / timed out) — it never reached the artifact it claims to check. Fix the command, not this gate.\n' "$id" "$cmd_rc" >&2
            return 1
        fi

        # negative_control: must be observed failing, and failing for a
        # content reason rather than an environmental one.
        if [[ "$nc_rc" == "0" ]]; then
            printf 'post_evals: eval %s negative_control exited 0 at freeze — a control that passes proves nothing. It must be observed failing.\n' "$id" >&2
            return 1
        fi
        if post_evals::_is_environmental_rc "$nc_rc"; then
            printf 'post_evals: eval %s negative_control exited %s (command not found / crashed / timed out) — non-zero, but for an environmental reason, so it tested nothing. Fix the control, not this gate.\n' "$id" "$nc_rc" >&2
            return 1
        fi
    done <<< "$ids"

    return 0
}

# post_evals::validate_smoke_execution <evals_json_path>
# Check 10's body: gate-time re-execution. For every tier>=1 scripted eval,
# EXECUTES `cmd` and `negative_control` right now and refuses on what it
# observes — it never reads the recorded `smoke` numbers at all.
#
# WHY THIS CAN RUN AT THE GATE despite freeze-before-build: check 9's own
# doctrine already splits the recorded evidence into two kinds of fact.
# cmd POLARITY is build-dependent — a cmd that failed at freeze legitimately
# passes at merge, so recomputing it here would be incoherent and it stays
# free. But RESOLVABILITY (the command can execute at all: not 126/127/
# timeout/signal) and CONTROL POLARITY (the control is defined to fail
# "regardless of build state" — check 9's words) are build-independent, so
# they CAN be recomputed at the gate. The fabrication this closes: an author
# who never runs the commands and types plausible smoke numbers (`cmd_exit:
# 1`, control 1) for a script that was only ever intended to exist. Check 9
# passes that shape; this check runs the command, observes 127, and refuses.
#
# WHAT REFUSES — two distinct mechanisms:
#   1. Blank-before-execution (trim-then-check, never reaches the runner):
#      - empty or whitespace-only cmd (a scripted eval with nothing to
#        execute; `bash -c "   "` would exit 0 and slip past the ungated
#        cmd polarity, so this must be caught before execution)
#      - empty or whitespace-only negative_control (same reasoning)
#   2. Observed at execution:
#      - cmd or negative_control environmental (126/127/142/>=128)
#      - negative_control exiting 0 (vacuous at the gate, whatever the
#        typed smoke claims)
# WHAT DOES NOT: cmd exiting 0 or non-zero for a content reason — polarity
# on cmd is the build-dependent part and stays ungated, exactly as check 9
# permits it on the recorded value.
#
# EXECUTION CONTEXT: commands run in the caller's cwd through the same 10s
# alarm wrapper smoke_run uses. Nothing here cd's: agreement with the
# freeze-time smoke-run is a property of the documented flow (the post-evals
# command runs validate-structure from the repo root, and the skill has
# smoke-run invoked the same way), not something this function enforces. An
# invocation from a different cwd can only fail closed — a relative cmd that
# no longer resolves is a false refusal, never a false pass. Added latency
# is bounded at ~20s per scripted eval (two capped runs): _run_recorded
# kills the child's whole process group at the cap, so ordinary forking
# commands (bash scripts, test runners) are bounded too — see its header
# for the one honest exception (a descendant that detaches into its own
# session escapes the group kill and can hold the pipe open longer).
#
# SAFETY: this executes author-supplied command strings from a JSON file.
# That adds no privilege the author lacks — the same principal that wrote
# evals.json already runs arbitrary commands in this environment (smoke-run
# executes these exact strings at freeze, the test gate runs the repo's
# suites), and the gate runs them unprivileged, output-discarded, under the
# alarm cap. The alternative (statically resolving the target path) would
# mean parsing shell, which fails open on anything compound. Side effects are
# bounded by the same contract evals already carry: an eval cmd is a check,
# and it has always been executed by the sanctioned freeze flow.
post_evals::validate_smoke_execution() {
    local path="$1"

    # Explicit, for the reason PR #261 paid for: a missing jq must never make
    # a violating file indistinguishable from a compliant one.
    if ! command -v jq >/dev/null 2>&1; then
        printf 'post_evals: jq is required for gate-time re-execution of eval commands and was not found\n' >&2
        return 1
    fi

    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    local tier
    tier=$(jq -r '.tier // ""' "$path")
    # Tier 0 is the exemption path: no evals to execute.
    [[ "$tier" == "0" ]] && return 0

    # Shape-guard .evals, same fail-closed guard as smoke_verify (the merge
    # gate). A non-array .evals makes the extraction below yield no indices and
    # the "no indices → return 0" line then passes without executing anything.
    # Check 7 (tier>=1 requires >=1 P0 eval) backstops the SCALAR and STRING
    # shapes on the live validate_structure chain — its `.evals[]?` finds no P0
    # in a scalar/string, so check 7 refuses those first. But it does NOT
    # backstop the OBJECT shape: `.evals[]?` iterates an object's VALUES, so an
    # object carrying a P0 passes check 7 and reaches here — this guard is what
    # actually refuses it. So the guard is load-bearing for the object case and
    # belt-and-braces only for scalar/string; either way it holds on its own.
    # Guard on TYPE, never on empty indices (a valid agent-run-only array
    # legitimately has none).
    if ! jq -e '(.evals | type) == "array"' "$path" >/dev/null 2>&1; then
        printf 'post_evals: validate_smoke_execution: .evals is not a JSON array (malformed or absent) — refusing.\n' >&2
        return 1
    fi

    # Only scripted evals carry commands — agent-run evals are graded by a
    # verifier subagent. Same boundary as check 9.
    #
    # BY ARRAY INDEX, not by id: an id-based `select(.id == $id)` emits
    # EVERY match, so two evals sharing an id would have their cmds joined
    # into one compound script — and the last line's exit code masks an
    # earlier 127. Index iteration executes each scripted eval exactly once
    # regardless of id collisions; the id appears only in messages. (Checks
    # 9 and the writer-side tools still look up by id — a duplicate id fails
    # closed there as malformed smoke, so the chain refuses either way, but
    # this function must hold on its own.)
    local idxs
    idxs=$(jq -r '.evals // [] | to_entries | map(select(.value.mode == "scripted")) | .[].key' "$path")
    [[ -z "$idxs" ]] && return 0

    local idx
    while IFS= read -r idx; do
        [[ -z "$idx" ]] && continue

        local id
        id=$(jq -r --argjson i "$idx" '.evals[$i].id // "<unnamed>"' "$path")

        # Trim-then-check, same idiom as check 2 on tier_justification: a
        # whitespace-only cmd is `bash -c "   "` — a no-op exiting 0, which
        # is non-environmental, and cmd polarity is deliberately ungated, so
        # without the trim a check that does literally nothing would be
        # accepted. Blank means empty means refused.
        local cmd nc
        cmd=$(jq -r --argjson i "$idx" '.evals[$i].cmd // "" | gsub("^\\s+|\\s+$"; "")' "$path")
        nc=$(jq -r --argjson i "$idx" '.evals[$i].negative_control // "" | gsub("^\\s+|\\s+$"; "")' "$path")

        # Nothing to execute is not compliance — fail closed. (Check 3
        # already refuses an absent/empty-string negative_control at tier>=1;
        # this additionally owns the whitespace-only case and the empty cmd,
        # which had no owner before this check.)
        if [[ -z "$cmd" ]]; then
            printf 'post_evals: scripted eval %s has empty cmd — nothing can execute at the gate.\n' "$id" >&2
            return 1
        fi
        if [[ -z "$nc" ]]; then
            printf 'post_evals: scripted eval %s has empty negative_control — nothing can execute at the gate.\n' "$id" >&2
            return 1
        fi

        local out rc
        out=$(post_evals::_run_recorded "$cmd")
        rc="${out%%:*}"
        out="${out#*:}"
        if post_evals::_is_environmental_rc "$rc"; then
            printf 'post_evals: eval %s cmd did not execute at the gate (exit %s: command not found / crashed / timed out) — recorded smoke evidence cannot stand in for a command the gate can run. Output: %s\n' "$id" "$rc" "$out" >&2
            return 1
        fi

        out=$(post_evals::_run_recorded "$nc")
        rc="${out%%:*}"
        out="${out#*:}"
        if [[ "$rc" == "0" ]]; then
            printf 'post_evals: eval %s negative_control exited 0 at the gate — a control that passes proves nothing, whatever the recorded smoke claims. Output: %s\n' "$id" "$out" >&2
            return 1
        fi
        if post_evals::_is_environmental_rc "$rc"; then
            printf 'post_evals: eval %s negative_control did not execute at the gate (exit %s: command not found / crashed / timed out) — non-zero, but for an environmental reason, so it tested nothing. Output: %s\n' "$id" "$rc" "$out" >&2
            return 1
        fi
    done <<< "$idxs"

    return 0
}

# post_evals::smoke_verify <embed_json_path> <head_sha>
# THE MERGE-TIME GATE. Makes checks 1-9 (post_evals::validate_structure,
# "merge" scope) plus gate-time re-execution BINDING at merge, closing the gap
# checks 1-10 left open: they only ever ran in the AGENT'S OWN session at post
# time (via /coderails:post-evals), never at merge — merge.sh and
# enforce_pr_workflow.sh only parsed the posted marker comment's result=GO
# text. An artifact carrying a hand-written smoke object of allowed shape
# ({"cmd_exit":1,"negative_control_exit":1}) for a cmd naming a script that
# never existed passed that path at rc=0. This function is called with the
# EMBED extracted from the trusted marker comment (pr::coderails_eval_embed_for_head)
# — never a local evals.json file, which the caller might not even have — and
# <head_sha> is the caller's own already-resolved trusted PR head, never
# read from the embed's own .head_sha field (that field is agent-controlled;
# checks 1-9 already compare it against the trusted sha for consistency, but
# the worktree checkout target here is the trusted sha directly).
#
# WHY A DETACHED WORKTREE, NOT THE CALLER'S OWN CHECKOUT: load-bearing twice
# over. (1) The caller (merge.sh / enforce_pr_workflow.sh) may be invoked from
# a checkout that doesn't have the PR branch's scripts checked out at all,
# which would produce a false 127 unrelated to the artifact's honesty. (2) It
# neutralises priming: an agent could plant a stub script in its own working
# tree that was never committed, so a real cmd resolves locally but wouldn't
# exist for anyone else. Checking out the exact trusted SHA into a fresh
# worktree means only what was actually committed at that SHA can run.
#
# WHY NOT validate_structure's pr-scope check 10: that re-executes in the
# CALLER's cwd under a hardcoded 10s alarm — wrong directory (defeats both
# reasons above) and wrong timeout (see POST_EVALS_SMOKE_VERIFY_TIMEOUT's
# comment). "merge" scope stops before check 10 for exactly this reason; this
# function is the re-execution that replaces it, with its own worktree and
# its own timeout.
#
# NO SURFACE EXEMPTION. Every scripted eval is re-executed, regardless of its
# `surface` field. An earlier version skipped surface "deployed"/"fresh-clone"
# on the reasoning that neither runs in a local worktree — but `surface` is
# written by the same posting agent this gate exists to distrust, and nothing
# in checks 1-9 constrains it. That made the exemption an attacker-writable
# bypass: a scripted eval with a fabricated cmd plus surface="deployed" dodged
# re-execution entirely and passed at rc=0 — the exact "hand-written smoke
# object for a script that never existed" family this gate closes. The
# exemption also diverged from check 10 (validate_smoke_execution), which has
# no surface filter. The axis that legitimately excludes an eval here is
# `mode`, not `surface`: a scripted eval has a runnable cmd by definition and
# must be verified; agent-run evals (no cmd) are excluded by the mode filter
# below and graded by the verifier, not here. smoke_verify runs only at
# pr/merge scope, so this cannot touch loop-scope deployed evals.
#
# FAILS CLOSED, NAMED REASON, on: jq missing, the embed not parsing as JSON,
# `git worktree add` failing (unresolvable/unfetched head_sha), and every
# check 10 refusal shape (environmental cmd/negative_control, or a
# negative_control observed exiting 0) — applied to what this function
# OBSERVES running the commands itself, never to any typed/recorded value.
# Cleans up the worktree on every path, success or failure.
post_evals::smoke_verify() {
    local path="$1" head_sha="$2"

    if ! command -v jq >/dev/null 2>&1; then
        printf 'post_evals: jq is required for smoke_verify (merge-time re-execution) and was not found\n' >&2
        return 1
    fi

    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: smoke_verify: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    if [[ -z "$head_sha" ]]; then
        printf 'post_evals: smoke_verify: head_sha argument is required\n' >&2
        return 1
    fi

    # NOT a call to validate_structure. Checks 1-9 already ran at post time
    # (the posting agent's own /coderails:post-evals session) — they are
    # structural validation, not the re-execution property, and re-imposing
    # them here adds failure modes that have nothing to do with fabrication:
    # check 2 (tier_justification) and check 6 (embed .head_sha vs the
    # trusted sha) both false-blocked a genuine, resolvable P4 acceptance
    # fixture during verification, for reasons unrelated to whether its cmd
    # is real. The security property this function exists to enforce is
    # re-execution — a fabricated cmd resolves to 127 (environmental) at any
    # commit, an honest cmd resolves to its real exit code — and that lives
    # entirely in the loop below, not in validate_structure.
    local tier
    tier=$(jq -r '.tier // ""' "$path")
    # Tier 0 is the exemption path: no evals to re-execute.
    [[ "$tier" == "0" ]] && return 0

    # Shape-guard .evals before trusting the index extraction below. A .evals
    # that is not a JSON array — a scalar, string, or object — makes the
    # `to_entries` extraction either jq-error to stderr with empty stdout (a
    # scalar/string) or walk object keys as if they were array indices (an
    # object). In the empty-stdout case the "no indices → return 0" line below
    # then passes the merge gate WITHOUT re-executing anything: the exact
    # fail-open this gate exists to prevent, one shape it did not guard. Refuse
    # (fail closed) unless .evals is an array. Guard on TYPE, never on empty
    # indices: a valid array whose only evals are agent-run legitimately yields
    # no scripted indices and must still be accepted by the return below.
    if ! jq -e '(.evals | type) == "array"' "$path" >/dev/null 2>&1; then
        printf 'post_evals: smoke_verify: .evals is not a JSON array (malformed or absent) — refusing to trust an eval artifact whose evals cannot be enumerated for re-execution.\n' >&2
        return 1
    fi

    # Iterate scripted evals by ARRAY INDEX, never by extracting a list of
    # `id`s. `id` is agent-written and unvalidated at this gate, so keying the
    # re-execution loop on it is another attacker-writable leash: an eval with
    # id:"" yields a blank line that a skip-empties loop drops, and a duplicate
    # id would run one eval's cmd twice while never running the other's. Index
    # position is intrinsic to the array and cannot be forged, so every scripted
    # eval is re-executed exactly once regardless of its id. (Same defect class
    # as the surface exemption removed above: gate authority must never rest on
    # a field the gated party controls.)
    local indices
    indices=$(jq -r '(.evals // []) | to_entries
        | map(select(.value.mode == "scripted") | .key)
        | .[]' "$path")
    [[ -z "$indices" ]] && return 0

    local worktree
    worktree=$(mktemp -d) || {
        printf 'post_evals: smoke_verify: could not allocate a temp directory for the worktree\n' >&2
        return 1
    }
    # Remove the empty dir mktemp created — `git worktree add` requires the
    # target path not already exist.
    rmdir "$worktree" 2>/dev/null

    # Ensure the trusted head commit is in the local object store before
    # checking it out. head_sha comes from the PR (GitHub), not necessarily
    # from local history: the merge hook fires on `gh pr merge <num>` run from
    # a checkout that may not have the branch, so the object can be absent and
    # `git worktree add` would fail a LEGITIMATE merge. Fetch it first. A fetch
    # failure stays fail-CLOSED (return 1) — never a fall-through to skip
    # verification; the point of fetching is to make an honest merge succeed,
    # not to weaken the gate when the network is down.
    if ! git cat-file -e "${head_sha}^{commit}" 2>/dev/null; then
        if ! git fetch origin "$head_sha" >/dev/null 2>&1; then
            printf 'post_evals: smoke_verify: could not fetch trusted head %s to re-execute against (not in local store and fetch failed). Retry, or drive the merge from a checkout that has the head.\n' "$head_sha" >&2
            rm -rf "$worktree" 2>/dev/null
            return 1
        fi
    fi

    if ! git worktree add --detach "$worktree" "$head_sha" >/dev/null 2>&1; then
        printf 'post_evals: smoke_verify: git worktree add failed for head_sha %s — could not check out the trusted commit to re-execute against. Fetch the SHA, or verify it exists in this repo, then retry.\n' "$head_sha" >&2
        rm -rf "$worktree" 2>/dev/null
        return 1
    fi

    local rc=0 idx
    while IFS= read -r idx; do
        [[ -z "$idx" ]] && continue

        # Look the eval up by its array index, not its id. `id` is used only for
        # human-readable messages below; it never selects which eval runs.
        local cmd nc id
        cmd=$(jq -r --argjson i "$idx" '.evals[$i].cmd // ""' "$path")
        nc=$(jq -r --argjson i "$idx" '.evals[$i].negative_control // ""' "$path")
        id=$(jq -r --argjson i "$idx" '.evals[$i].id // ("#" + ($i | tostring))' "$path")

        if [[ -z "$cmd" ]]; then
            printf 'post_evals: smoke_verify: scripted eval %s has empty cmd — nothing can execute at the gate.\n' "$id" >&2
            rc=1; break
        fi
        if [[ -z "$nc" ]]; then
            printf 'post_evals: smoke_verify: scripted eval %s has empty negative_control — nothing can execute at the gate.\n' "$id" >&2
            rc=1; break
        fi

        local out cmd_rc cmd_out
        out=$(post_evals::_run_recorded "$cmd" "$POST_EVALS_SMOKE_VERIFY_TIMEOUT" "$worktree")
        cmd_rc="${out%%:*}"
        cmd_out="${out#*:}"
        if post_evals::_is_environmental_rc "$cmd_rc"; then
            printf 'post_evals: smoke_verify: eval %s cmd did not execute at the gate (exit %s: command not found / crashed / timed out) at trusted head %s — recorded smoke evidence cannot stand in for a command the gate can run. Output: %s\n' "$id" "$cmd_rc" "$head_sha" "$cmd_out" >&2
            rc=1; break
        fi

        local nc_rc nc_out
        out=$(post_evals::_run_recorded "$nc" "$POST_EVALS_SMOKE_VERIFY_TIMEOUT" "$worktree")
        nc_rc="${out%%:*}"
        nc_out="${out#*:}"
        if [[ "$nc_rc" == "0" ]]; then
            printf 'post_evals: smoke_verify: eval %s negative_control exited 0 at the gate at trusted head %s — a control that passes proves nothing, whatever the recorded smoke claims. Output: %s\n' "$id" "$head_sha" "$nc_out" >&2
            rc=1; break
        fi
        if post_evals::_is_environmental_rc "$nc_rc"; then
            printf 'post_evals: smoke_verify: eval %s negative_control did not execute at the gate (exit %s: command not found / crashed / timed out) at trusted head %s — non-zero, but for an environmental reason, so it tested nothing. Output: %s\n' "$id" "$nc_rc" "$head_sha" "$nc_out" >&2
            rc=1; break
        fi
    done <<< "$indices"

    git worktree remove --force "$worktree" >/dev/null 2>&1
    rm -rf "$worktree" 2>/dev/null

    return $rc
}

# post_evals::smoke_run <evals_json_path>
# EXECUTES every scripted eval's cmd and negative_control and writes the
# observed exit codes and output excerpts into the file's `smoke` objects,
# overwriting whatever was there.
#
# WHY THIS EXISTS SEPARATELY FROM validate_smoke: validate_smoke checks
# recorded exit codes, which is necessary but not sufficient, because the agent
# writes those numbers. An agent that freezes a cmd for a script it merely
# INTENDS to create records the code it EXPECTS ("1 — the assertion fails until
# I build it"), never having run the command, and walks straight through a
# checker that trusts the field. That is exactly how the real instance-1 defect
# happened, and it is why rule 5 in SKILL.md already says a neutral script
# computes the result and the orchestrator never hand-writes it. This applies
# rule 5 to smoke evidence: run the commands, record what happened.
#
# Recording is NOT judging. This function returns 0 whenever it successfully
# ran the commands and wrote the file, even when what it observed is damning —
# refusing is validate_smoke's job. Keeping the two apart means the recorded
# evidence is the same whether or not anyone later gates on it.
#
# Commands run through _run_recorded's 10s group-killing cap, so a hanging
# command cannot hang the freeze: 127 (not found), 142 (timeout) and signal
# deaths fall out of the real run instead of being typed in by hand.
post_evals::smoke_run() {
    local path="$1"

    if ! command -v jq >/dev/null 2>&1; then
        printf 'post_evals: jq is required to record smoke evidence and was not found\n' >&2
        return 1
    fi

    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    # Guard id TYPE. The schema (SKILL.md) defines id as a string ("E1"); the
    # cmd/negative_control lookups below are `select(.id == $id)` against a
    # shell string from `--arg`, which never matches a JSON number. Without
    # this guard a numeric id makes cmd/nc silently empty, so nothing executes
    # and this function still records `smoke: null` and returns 0 — recording
    # success for evidence that was never run. Fail closed instead.
    local bad_id_type
    bad_id_type=$(jq -r '[.evals[]? | select(.mode == "scripted") | select((.id | type) != "string")] | length > 0' "$path")
    if [[ "$bad_id_type" == "true" ]]; then
        printf 'post_evals: smoke_run: a scripted eval has a non-string id (schema requires id to be a string) — refusing.\n' >&2
        return 1
    fi

    local ids
    ids=$(jq -r '[.evals[]? | select(.mode == "scripted") | .id] | .[]' "$path")
    [[ -z "$ids" ]] && return 0

    local id
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue

        local cmd nc
        cmd=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .cmd // ""' "$path")
        nc=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .negative_control // ""' "$path")

        local cmd_rc cmd_out nc_rc nc_out
        cmd_rc=""; cmd_out=""; nc_rc=""; nc_out=""

        if [[ -n "$cmd" ]]; then
            cmd_out=$(post_evals::_run_recorded "$cmd")
            cmd_rc="${cmd_out%%:*}"
            cmd_out="${cmd_out#*:}"
        fi
        if [[ -n "$nc" ]]; then
            nc_out=$(post_evals::_run_recorded "$nc")
            nc_rc="${nc_out%%:*}"
            nc_out="${nc_out#*:}"
        fi

        # Write in place via a temp file — a partial write must never leave a
        # corrupted artifact behind.
        local tmp
        tmp=$(mktemp) || return 1
        if ! jq --arg id "$id" \
               --argjson crc "${cmd_rc:-null}" --argjson nrc "${nc_rc:-null}" \
               --arg cout "$cmd_out" --arg nout "$nc_out" '
            (.evals[] | select(.id == $id) | .smoke) = {
                cmd_exit: $crc,
                negative_control_exit: $nrc,
                cmd_output: $cout,
                negative_control_output: $nout
            }' "$path" > "$tmp"; then
            rm -f "$tmp"
            printf 'post_evals: failed to record smoke evidence for eval %s in %s\n' "$id" "$path" >&2
            return 1
        fi
        if ! mv "$tmp" "$path"; then
            rm -f "$tmp"
            printf 'post_evals: failed to write %s\n' "$path" >&2
            return 1
        fi
    done <<< "$ids"

    return 0
}

# post_evals::_run_recorded <command> [timeout_secs] [cwd]
# Runs <command> under a wall-clock cap (default 10s) and echoes
# "<exit_code>:<output excerpt>". stdout and stderr are merged — the tell for a
# broken instrument is usually on stderr (a module-resolution error, a
# not-found message), so dropping it would discard the evidence a human needs.
# [timeout_secs] defaults to 10 (unchanged freeze-time behaviour — every
# existing caller passes one arg). [cwd], if given, runs <command> there
# instead of the caller's own working directory — needed by smoke_verify,
# which must execute inside its detached worktree, not wherever the merge
# gate happens to be invoked from.
#
# THE CAP KILLS THE PROCESS GROUP, not just the direct child. The earlier
# exec-based idiom (`perl -e 'alarm shift; exec ...'`) delivered SIGALRM only
# to the process perl became: a grandchild — the sleep inside `bash hang.sh`,
# a test runner's worker — was never signalled, got reparented to init, and
# kept the inherited stdout pipe open, so the caller's command substitution
# blocked until the orphan exited. Correct exit code (142), broken latency
# bound (observed 30s for a 10s cap). Since check 10 runs this on the merge
# hot path, the bound is load-bearing: the child is made its own process
# group leader (setpgrp) and the alarm handler KILLs the negative PGID, which
# takes the grandchildren and closes the pipe. Timeout still reports 142,
# the documented sentinel, regardless of the KILL. Honest caveat: a
# descendant that detaches into its own session (a daemonizing server)
# escapes the group kill and can still hold the pipe open — the cap bounds
# every ordinary forking shape, not a deliberate daemon.
#
# _run_formula keeps the old exec idiom deliberately: it redirects the
# command's output to /dev/null, so an orphan cannot hold its pipe open and
# the single-process alarm is a sufficient bound there.
#
# [timeout_seconds] exists for the test suite (a real 10s stall per run is
# too slow to assert on); production callers pass nothing and get 10.
#
# The excerpt keeps BOTH ENDS, not just the tail, because the diagnostic line
# sits at a different end depending on the failure. Measured against real
# output from this repo: a test runner's verdict is in the last few lines
# (post_evals.test.sh emits 10886 chars, PASS last), but a node stack trace
# puts "Cannot find module" in the FIRST line and 900+ chars of stack frames
# after it — a tail-only excerpt keeps the frames and discards the error,
# losing exactly the module-resolution tell SKILL.md names. Capping both ends
# also bounds the artifact against a chatty runner.
post_evals::_run_recorded() {
    local command_text="$1" timeout_secs="${2:-10}" cwd="${3:-}" out rc
    local -r _pg_kill_perl='
        my $t = shift; my $cmd = shift;
        my $pid = fork();
        exit 127 unless defined $pid;
        if ($pid == 0) { setpgrp(0, 0); exec "/bin/bash", "-c", $cmd; exit 127; }
        my $timed_out = 0;
        local $SIG{ALRM} = sub { $timed_out = 1; kill "KILL", -$pid; };
        alarm $t;
        waitpid($pid, 0);
        alarm 0;
        exit 142 if $timed_out;
        exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
    '
    if [[ -n "$cwd" ]]; then
        # A cd failure here (worktree vanished between `git worktree add` and
        # this call — a race or external rm) must NOT collapse to rc=1: rc=1 is
        # a legitimate content-failure exit, and _is_environmental_rc doesn't
        # cover it, so on the negative_control leg (where rc=1 reads as a pass)
        # a cd failure would fail OPEN. Map "could not enter the dir to run" to
        # 127 (command-not-found), which _is_environmental_rc DOES treat as
        # "never executed" — the honest classification for a command that never
        # ran. The `|| { echo ...; exit 127; }` runs inside the subshell.
        out=$(cd "$cwd" 2>/dev/null || { printf 'cd-failed: %s' "$cwd"; exit 127; }
              perl -e "$_pg_kill_perl" "$timeout_secs" "$command_text" 2>&1)
    else
        out=$(perl -e "$_pg_kill_perl" "$timeout_secs" "$command_text" 2>&1)
    fi
    rc=$?
    out=$(printf '%s' "$out" | tr '\n' ' ')
    if (( ${#out} > 500 )); then
        out="${out:0:250} [...] ${out: -250}"
    fi
    printf '%s:%s' "$rc" "$out"
}

# post_evals::_is_environmental_rc <exit_code>
# True when an exit code signals the command did not run to a verdict:
# 126 permission denied, 127 command not found, 142 our timeout sentinel,
# and >=128 signal deaths.
#
# validate_discriminating applies the same taxonomy to its fixtures legs but
# deliberately keeps its own inline checks rather than calling this: it reports
# not-found, timeout and crash with three distinct messages naming both legs'
# exit codes, which a shared boolean cannot express. The duplication is the
# price of those diagnostics. If the taxonomy changes, both must change.
post_evals::_is_environmental_rc() {
    local rc="$1"
    [[ "$rc" == "126" || "$rc" == "127" ]] && return 0
    [[ "$rc" =~ ^[0-9]+$ ]] && (( rc >= 128 )) && return 0
    return 1
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
