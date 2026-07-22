#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  merge.sh │ verify → merge → sync
#═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
source "$(dirname "$0")/lib/git-common.sh"
source "$(dirname "$0")/lib/config.sh"
source "$(dirname "$0")/lib/tier-floor.sh"

# coderails::_tier_review_machine_user <config_file>
# Echoes the value of the nested key tier_review.machine_user from a
# workflow.config.yaml, or nothing if the key/block is absent. No generic
# nested-key YAML reader exists in this repo (scripts/lib/config.sh only
# locates the file) — this is a minimal, single-purpose extractor for this
# one key, not a new config system.
coderails::_tier_review_machine_user() {
    local config_file="$1"
    [[ -f "$config_file" ]] || return 0
    awk '
        /^tier_review:[[:space:]]*$/ { in_block=1; next }
        in_block && /^[^[:space:]]/ { in_block=0 }
        in_block && /^[[:space:]]+machine_user:/ {
            sub(/^[[:space:]]+machine_user:[[:space:]]*/, "")
            gsub(/^["'"'"']|["'"'"']$/, "")
            gsub(/[[:space:]]*#.*$/, "")
            gsub(/[[:space:]]+$/, "")
            print
            exit
        }
    ' "$config_file" 2>/dev/null
}

merge::main() {
    local arg="${1:-auto}" br=$(branch) m=$(main)

    require::repo

    step "$(repo)"

    # ─── Resolve PR ───────────────────────────────────────────────────────────
    local num
    case "$arg" in
        auto)
            [[ $br == "$m" ]] && err "On $m ─ specify PR# or branch"
            num=$(pr::num "$br") || err "No PR for $br"
            ;;
        [0-9]*)
            num=$arg
            ;;
        *)
            num=$(pr::num "$arg") || err "No PR for $arg"
            ;;
    esac

    info "PR #$num │ $(pr::title "$num")"

    # ─── Merge ────────────────────────────────────────────────────────────────
    case $(pr::state "$num") in
        MERGED) warn "Already merged" ;;
        CLOSED) err "PR closed (not merged)" ;;
        OPEN)
            protected && {
                [[ $(pr::review "$num") == APPROVED ]] || err "Not approved ($(pr::review "$num"))"
                ok "Approved"
            }
            if [[ -z "$(coderails::config_path "$PWD")" ]]; then
                info "No workflow.config.yaml — enforce_pr_workflow hook is inactive, but the review artifact gate still applies."
            fi

            # ─── Review artifact gate (fail-closed) ───────────────────────────
            # Requires a coderails review comment on the PR matching the current
            # head SHA. No match → block. No fallback to local files.
            local sha
            sha=$(pr::head_sha "$num")
            if [[ -z "$sha" ]]; then
                err "GitHub fetch failed — could not resolve PR head SHA. Retry, or check gh auth/network."
            fi
            local gate_rc
            gate_rc=0
            pr::has_coderails_review_for_head "$num" "$sha" || gate_rc=$?
            if [[ $gate_rc -eq 2 ]]; then
                case "${PR_TRUST_FETCH_FAIL_REASON:-}" in
                    identity)   err "GitHub fetch failed — could not resolve the authenticated identity (gh api user). Retry, or check gh auth/network." ;;
                    permission) err "GitHub fetch failed — could not resolve repo permission for the authenticated identity. Retry, or check gh auth/network." ;;
                    tempfile)   err "Local temporary file allocation failed (mktemp) before any GitHub fetch was attempted. Check /tmp disk space or permissions, then retry." ;;
                    *)          err "GitHub fetch failed — could not fetch PR comments. Retry, or check gh auth/network." ;;
                esac
            elif [[ $gate_rc -ne 0 ]]; then
                err "No coderails review artifact for current head $sha — run /coderails:post-review after /pr-review-toolkit:review-pr (or add a 'gh pr merge' permission to bypass)."
            fi
            ok "Review artifact verified (SHA: $sha)"

            # ─── Eval artifact gate (fail-closed) ─────────────────────────────
            # Requires a coderails eval comment on the PR matching the current
            # head SHA with result=GO. No match → block. No fallback, no
            # config opt-out (same posture as the review gate).
            local eval_gate_rc
            eval_gate_rc=0
            pr::has_coderails_eval_for_head "$num" "$sha" || eval_gate_rc=$?
            if [[ $eval_gate_rc -eq 2 ]]; then
                case "${PR_TRUST_FETCH_FAIL_REASON:-}" in
                    identity)   err "GitHub fetch failed — could not resolve the authenticated identity (gh api user) for the eval artifact gate. Retry, or check gh auth/network." ;;
                    permission) err "GitHub fetch failed — could not resolve repo permission for the eval artifact gate. Retry, or check gh auth/network." ;;
                    tempfile)   err "Local temporary file allocation failed (mktemp) before any GitHub fetch was attempted for the eval artifact gate. Check /tmp disk space or permissions, then retry." ;;
                    *)          err "GitHub fetch failed — could not fetch PR comments for eval artifact. Retry, or check gh auth/network." ;;
                esac
            elif [[ $eval_gate_rc -ne 0 ]]; then
                if [[ -n "${PR_EVAL_TIER:-}" ]]; then
                    err "Eval artifact for current head $sha is NO-GO (tier $PR_EVAL_TIER) — resolve failing P0 evals and re-run /coderails:post-evals."
                else
                    err "No coderails eval artifact for current head $sha — run /coderails:task-evals then /coderails:post-evals after /pr-review-toolkit:review-pr."
                fi
            fi
            ok "Eval artifact verified (SHA: $sha, tier ${PR_EVAL_TIER:-?})"

            # ─── Derived tier-floor gate (always on, never config-keyed) ──────
            # The tier just reported is SELF-DECLARED — parsed verbatim from a
            # marker line the same actor wrote. Every gate above consumes it as
            # a trusted value, so a smaller digit buys less scrutiny for free.
            # This derives a LOWER BOUND on the tier from the diff itself
            # (paths, file count, line count — facts fetched from GitHub, not
            # authored by the actor) and blocks a claim below it. Claiming
            # ABOVE the floor always passes: more scrutiny is never an attack.
            # There is deliberately no config key and no override — unlike the
            # tier-review status gate below, which is inactive unless
            # tier_review.machine_user is set, this runs on every install. An
            # opt-out the actor can write is the same hole one level up.
            local floor_out floor_rc=0
            floor_out=$(tier_floor::gate_pr "${PR_EVAL_TIER:-}" "$num") || floor_rc=$?
            case $floor_rc in
                0) ok "Tier floor verified (claimed tier ${PR_EVAL_TIER:-?} is at or above the diff-derived floor)" ;;
                3) warn "$floor_out" ;;   # infrastructure: the diff could not be read at all — do not block the world
                *) err "$floor_out" ;;    # rc 1 (claim below floor) and rc 2 (unusable evidence after a good fetch) both block
            esac

            # ─── Tier-review gate (redundant defence-in-depth, fail-closed) ───
            # This layer is REDUNDANT BY DESIGN once the server-side ruleset is
            # live (belt-and-braces): it exists to fail loudly on misconfiguration
            # and to hold the line during the pre-ruleset interim. It is NOT the
            # primary control — do not delete it as dead code once the ruleset is
            # active; it is the only local check that catches a machine-user
            # misconfiguration before GitHub itself would. Config-keyed and
            # inactive by default: only runs when config key
            # tier_review.machine_user is set — the daemon (tier-gate-runner)
            # now judges EVERY tier, not just tier 0, so this gate runs at
            # every tier too (no more `PR_EVAL_TIER == 0` restriction). A
            # missing/failed status now blocks merges at every tier — fail-
            # closed is symmetric across tiers, never bypassed.
            local tier_review_config; tier_review_config=$(coderails::config_path "$PWD")
            local tier_review_machine_user=""
            if [[ -n "$tier_review_config" ]]; then
                tier_review_machine_user=$(coderails::_tier_review_machine_user "$tier_review_config")
            fi
            if [[ -n "$tier_review_machine_user" ]]; then
                local tr_statuses tr_rc=0
                tr_statuses=$(gh api "repos/$(repo)/commits/${sha}/statuses" --paginate \
                    --jq '[.[] | select(.context == "tier-review")]' 2>/dev/null) || tr_rc=$?
                if [[ $tr_rc -ne 0 ]]; then
                    err "GitHub fetch failed — could not fetch tier-review status for $sha. Retry, or check gh auth/network."
                fi
                local tr_state tr_creator tr_desc
                tr_state=$(printf '%s' "$tr_statuses" | jq -r '.[0].state // empty' 2>/dev/null)
                tr_creator=$(printf '%s' "$tr_statuses" | jq -r '.[0].creator.login // empty' 2>/dev/null)
                tr_desc=$(printf '%s' "$tr_statuses" | jq -r '.[0].description // empty' 2>/dev/null)
                if [[ -z "$tr_state" ]]; then
                    err "No tier-review status found for $sha — the tier-gate daemon has not judged this SHA yet. Wait for it, or kickstart it, then retry."
                elif [[ "$tr_state" != "success" ]]; then
                    err "tier-review status for $sha is '$tr_state' (not success) — the tier-gate daemon has not approved this SHA. Resolve and retry."
                elif [[ "$tr_creator" != "$tier_review_machine_user" ]]; then
                    err "tier-review status for $sha was posted by '$tr_creator', not the configured machine user '$tier_review_machine_user' — this is a misconfiguration-or-forgery signal, not a valid verdict. Do not bypass; investigate the creator mismatch."
                elif [[ "$tr_desc" != *"verdict=legitimate"* ]]; then
                    # state=success is necessary but NOT sufficient: only a
                    # genuine `legitimate` judgment carries verdict=legitimate
                    # in its description (tier-gate-runner tg_gate_pr).
                    # Requiring it here closes the verdict-laundering path
                    # where an otherwise-minted success is reused as a pass —
                    # a bare state check cannot distinguish those, the
                    # description can.
                    err "tier-review status for $sha is success but its description ('$tr_desc') does not carry verdict=legitimate — this is not a genuine approval (e.g. a laundered or non-judged status). Do not bypass; investigate."
                elif ! [[ "$tr_desc" =~ (^|[[:space:]])tier=${PR_EVAL_TIER}($|[[:space:]]) ]]; then
                    # Tier-binding (anti-laundering): the status description
                    # must carry a tier=N token matching THIS artifact's own
                    # claimed tier. Space/end-of-string delimited so tier=1
                    # can never satisfy tier=12 (or vice versa) via a bare
                    # substring match. A status minted against one claimed
                    # tier must never satisfy a different claim — this is the
                    # reason tier-gate-runner puts the token in every
                    # description; this is the first thing that consumes it.
                    err "tier-review status for $sha carries description ('$tr_desc') that does not match this artifact's claimed tier ${PR_EVAL_TIER} — a status minted for a different tier cannot satisfy this claim. Do not bypass; investigate."
                fi
                ok "Tier-review verified (SHA: $sha, creator: $tr_creator, verdict=legitimate, tier=${PR_EVAL_TIER})"
            fi

            step "Merging"
            gh pr merge "$num" --merge          # remote merge ONLY — its failure must abort; branch cleanup is separate + non-fatal
            ok "Merged"
            ;;
        *) err "Unknown state" ;;
    esac

    # ─── Sync ─────────────────────────────────────────────────────────────────
    # sync::main_branch handles both the primary tree (checkout main; pull) and a
    # linked worktree (pull main in the primary tree — a checkout here would abort
    # under set -e because main is already checked out elsewhere). See git-common.sh.
    sync::main_branch

    # ─── Branch cleanup (best-effort — a merged PR must NEVER report failure) ──
    # --delete-branch was dropped above: it deletes the local branch too, which
    # fails (and, under set -e, aborts the whole script) when another worktree has
    # the branch checked out — reporting an already-merged PR as failed. Cleanup is
    # decoupled and non-fatal here instead.
    local head; head=$(gh pr view "$num" --json headRefName -q .headRefName 2>/dev/null || true)
    if [[ -n "${head:-}" && "$head" != "$m" ]]; then
        git push origin --delete "$head" &>/dev/null \
            && ok "Deleted remote branch $head" \
            || warn "Remote branch $head not deleted (already gone?)"
        if git branch -D "$head" &>/dev/null; then
            ok "Deleted local branch $head"
        else
            local wt; wt=$(git worktree list --porcelain \
                | awk -v b="branch refs/heads/$head" '/^worktree /{p=$2} $0==b{print p}' || true)
            warn "Local branch $head kept${wt:+ (worktree $wt holds it — remove manually)}"
        fi
    fi

    dim "$(git log --oneline -5 | sed 's/^/  /')"
    banner "Done"
}

merge::main "$@"
