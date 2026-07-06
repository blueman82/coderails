#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  merge.sh │ verify → merge → sync
#═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
source "$(dirname "$0")/lib/git-common.sh"
source "$(dirname "$0")/lib/config.sh"

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
                err "GitHub fetch failed — could not fetch PR comments. Retry, or check gh auth/network."
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
                err "GitHub fetch failed — could not fetch PR comments for eval artifact. Retry, or check gh auth/network."
            elif [[ $eval_gate_rc -ne 0 ]]; then
                if [[ -n "${PR_EVAL_TIER:-}" ]]; then
                    err "Eval artifact for current head $sha is NO-GO (tier $PR_EVAL_TIER) — resolve failing P0 evals and re-run /coderails:post-evals."
                else
                    err "No coderails eval artifact for current head $sha — run /coderails:task-evals then /coderails:post-evals after /pr-review-toolkit:review-pr."
                fi
            fi
            ok "Eval artifact verified (SHA: $sha, tier ${PR_EVAL_TIER:-?})"

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
