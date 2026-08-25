#!/bin/bash
# post_evals_smoke_freeze.sh — check 9: freeze-time smoke-evidence shape
# validators (validate_smoke, _scripted_indices, validate_smoke_execution).
# Split out of post_evals.sh to keep files under the repo LOC ceiling.
# Sourced by post_evals.sh — not meant to be run directly.
# Note: no set -euo pipefail — sourced; functions return exit codes.

# post_evals::validate_smoke <evals_json_path>
# Check 9's body. Requires every verification_level>=1 scripted eval to carry a `smoke`
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

    local verification_level
    verification_level=$(jq -r '.verification_level // ""' "$path")
    # Verification level 0 is the exemption path: its .evals array is empty by definition,
    # so there is nothing to smoke-test.
    [[ "$verification_level" == "0" ]] && return 0

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

# post_evals::_scripted_indices <evals_json_path> <error_label> <mode_error_prefix>
# Validate the shared eval shape before returning scripted array indices. The
# caller supplies prefixes so the existing fail-closed diagnostics stay stable.
post_evals::_scripted_indices() {
    local path="$1" error_label="$2" mode_error_prefix="$3"

    if ! jq -e '(.evals | type) == "array"' "$path" >/dev/null 2>&1; then
        local shape_error="post_evals: ${error_label}: .evals is not a JSON array (malformed or absent) — refusing."
        [[ "$error_label" == smoke_verify ]] && shape_error='post_evals: smoke_verify: .evals is not a JSON array (malformed or absent) — refusing to trust an eval artifact whose evals cannot be enumerated for re-execution.'
        printf '%s\n' "$shape_error" >&2
        return 1
    fi

    local bad_mode
    bad_mode=$(jq -r '[.evals[]? | select(((.mode // "") | IN("scripted","agent-run")) | not) | .id // "<unnamed>"] | first // ""' "$path")
    if [[ -n "$bad_mode" ]]; then
        printf '%s eval %s has an unrecognised mode (must be "scripted" or "agent-run") — refusing: an unrecognised or absent mode silently excludes the eval from every gate check.\n' "$mode_error_prefix" "$bad_mode" >&2
        return 1
    fi

    jq -r '(.evals // []) | to_entries
        | map(select(.value.mode == "scripted") | .key)
        | .[]' "$path"
}

# post_evals::validate_smoke_execution <evals_json_path>
# Check 10's body: gate-time re-execution. For every verification_level>=1 scripted eval,
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

    local verification_level
    verification_level=$(jq -r '.verification_level // ""' "$path")
    # Verification level 0 is the exemption path: no evals to execute.
    [[ "$verification_level" == "0" ]] && return 0

    # Shape-guard .evals, same fail-closed guard as smoke_verify (the merge
    # gate). A non-array .evals makes the extraction below yield no indices and
    # the "no indices → return 0" line then passes without executing anything.
    # Check 7 (verification_level>=1 requires >=1 P0 eval) backstops the SCALAR and STRING
    # shapes on the live validate_structure chain — its `.evals[]?` finds no P0
    # in a scalar/string, so check 7 refuses those first. But it does NOT
    # backstop the OBJECT shape: `.evals[]?` iterates an object's VALUES, so an
    # object carrying a P0 passes check 7 and reaches here — this guard is what
    # actually refuses it. So the guard is load-bearing for the object case and
    # belt-and-braces only for scalar/string; either way it holds on its own.
    # Guard on TYPE, never on empty indices (a valid agent-run-only array
    # legitimately has none).
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
    # `mode` is written by the posting agent and every scripted-eval check in
    # this file is a `select(.mode == "scripted")` filter — so a mode that is
    # not exactly that string is invisible to ALL of them at once (checks 3, 4,
    # 9, 10 and smoke_verify), and the empty list then hits the `return 0`
    # below as silent success. Verified: a vacuous negative_control refused at
    # rc=1 under mode:"scripted" passes at rc=0 under mode:"Scripted" or with
    # mode omitted entirely — the omitted form needs no adversary, just a
    # schema-sloppy agent. Same principle this function already applies to
    # `id` (iterate by index, never trust a gated-party field to select what
    # gets checked); `mode` was the remaining instance. The enum is
    # authoritative in skills/task-evals/SKILL.md: scripted | agent-run.
    local idxs
    if ! idxs=$(post_evals::_scripted_indices "$path" validate_smoke_execution 'post_evals:'); then
        return 1
    fi
    [[ -z "$idxs" ]] && return 0

    local idx
    while IFS= read -r idx; do
        [[ -z "$idx" ]] && continue

        local id
        id=$(jq -r --argjson i "$idx" '.evals[$i].id // "<unnamed>"' "$path")

        # Trim-then-check, same idiom as check 2 on verification_justification: a
        # whitespace-only cmd is `bash -c "   "` — a no-op exiting 0, which
        # is non-environmental, and cmd polarity is deliberately ungated, so
        # without the trim a check that does literally nothing would be
        # accepted. Blank means empty means refused.
        local cmd nc
        cmd=$(jq -r --argjson i "$idx" '.evals[$i].cmd // "" | gsub("^\\s+|\\s+$"; "")' "$path")
        nc=$(jq -r --argjson i "$idx" '.evals[$i].negative_control // "" | gsub("^\\s+|\\s+$"; "")' "$path")

        # Nothing to execute is not compliance — fail closed. (Check 3
        # already refuses an absent/empty-string negative_control at verification_level>=1;
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
