#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  merge.sh │ verify → merge → sync
#═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
source "$(dirname "$0")/lib/git-common.sh"

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
            local git_root; git_root=$(git rev-parse --show-toplevel 2>/dev/null)
            cfg_found=""
            if [[ -n "$git_root" ]]; then
                d=$(pwd)
                while :; do
                    [[ -f "$d/.claude/workflow.config.yaml" ]] && { cfg_found=1; break; }
                    [[ "$d" == "$git_root" ]] && break
                    d=$(dirname "$d")
                done
            fi
            if [[ -n "$git_root" && -z "$cfg_found" ]]; then
                info "No workflow.config.yaml — review enforcement (enforce_pr_workflow) is inactive. Run /coderails:init to enable."
            fi
            step "Merging"
            gh pr merge "$num" --merge          # remote merge ONLY — its failure must abort; branch cleanup is separate + non-fatal
            ok "Merged"
            ;;
        *) err "Unknown state" ;;
    esac

    # ─── Sync ─────────────────────────────────────────────────────────────────
    [[ $br != "$m" ]] && git checkout "$m" &>/dev/null
    git pull origin "$m" --quiet
    ok "Synced to $m"

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
