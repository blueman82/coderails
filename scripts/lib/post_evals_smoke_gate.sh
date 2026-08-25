#!/bin/bash
# post_evals_smoke_gate.sh — check 10: post_evals::smoke_verify, the
# merge-time gate that re-executes cmd/negative_control itself.
# Split out of post_evals.sh to keep files under the repo LOC ceiling.
# Sourced by post_evals.sh — not meant to be run directly. Uses
# POST_EVALS_SMOKE_VERIFY_TIMEOUT, set in post_evals.sh before this is sourced.
# Note: no set -euo pipefail — sourced; functions return exit codes.


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
    # check 2 (verification_justification) and check 6 (embed .head_sha vs the
    # trusted sha) both false-blocked a genuine, resolvable P4 acceptance
    # fixture during verification, for reasons unrelated to whether its cmd
    # is real. The security property this function exists to enforce is
    # re-execution — a fabricated cmd resolves to 127 (environmental) at any
    # commit, an honest cmd resolves to its real exit code — and that lives
    # entirely in the loop below, not in validate_structure.
    local verification_level
    verification_level=$(jq -r '.verification_level // ""' "$path")
    # Verification level 0 is the exemption path: no evals to re-execute.
    [[ "$verification_level" == "0" ]] && return 0

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
    # Iterate scripted evals by ARRAY INDEX, never by extracting a list of
    # `id`s. `id` is agent-written and unvalidated at this gate, so keying the
    # re-execution loop on it is another attacker-writable leash: an eval with
    # id:"" yields a blank line that a skip-empties loop drops, and a duplicate
    # id would run one eval's cmd twice while never running the other's. Index
    # position is intrinsic to the array and cannot be forged, so every scripted
    # eval is re-executed exactly once regardless of its id. (Same defect class
    # as the surface exemption removed above: gate authority must never rest on
    # a field the gated party controls.)
    # `mode` is the remaining instance of the defect class named directly above:
    # it selects WHICH evals this gate re-executes, and the gated party writes
    # it. A mode that is not exactly "scripted" drops the eval out of every
    # check in this file at once, and an all-dropped array reaches the
    # `return 0` below as silent success. Verified against this gate: an
    # artifact whose sole P0 carries a vacuous negative_control is refused at
    # rc=1 with mode:"scripted" and accepted at rc=0 with mode:"Scripted" or
    # with no mode field at all. Refuse the unrecognised value rather than
    # guessing an intent for it.
    local indices
    if ! indices=$(post_evals::_scripted_indices "$path" smoke_verify 'post_evals: smoke_verify:'); then
        return 1
    fi
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
