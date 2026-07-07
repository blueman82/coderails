#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  push.sh │ stage → commit → push → PR
#═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
source "$(dirname "$0")/lib/git-common.sh"

push::main() {
    local force_with_lease=0 msg=""
    # --force-with-lease is a long-form-only opt-in flag (no -f alias — -f
    # collides with git's own short force flag). require::feature below
    # already guarantees a non-main branch before the push step runs.
    for arg in "$@"; do
        if [[ "$arg" == "--force-with-lease" ]]; then
            force_with_lease=1
        elif [[ -z "$msg" ]]; then
            msg="$arg"
        fi
    done
    local br=$(branch)

    require::feature
    require::repo

    # ─── JIRA key from branch config (set by /prep) ───────────────────────────
    local jira_key
    jira_key=$(git config "branch.${br}.jira-ticket" 2>/dev/null || true)

    step "$(repo) ─ $br → $(main)${jira_key:+ [$jira_key]}"

    # ─── Commit ───────────────────────────────────────────────────────────────
    if dirty; then
        git add -u
        local untracked; untracked=$(git status --porcelain | grep '^??' | cut -c4- || true)
        if [[ -n "$untracked" ]]; then
            warn "Untracked files not staged (run 'git add' explicitly to include them):"
            while IFS= read -r f; do warn "  $f"; done <<< "$untracked"
        fi
        if [[ -n $(git diff --cached --name-only) ]]; then
            if [[ -z "$msg" ]]; then
                local file_count; file_count=$(git diff --cached --name-only | wc -l | tr -d ' ')
                msg="Update ${file_count} files"
            fi
            # Prefix commit message with JIRA key so it appears in GitHub commit list
            # and JIRA's GitHub integration links it even after squash merge
            [[ -n "$jira_key" ]] && msg="${jira_key} ${msg}"
            git commit -m "$msg" && ok "Committed: $msg"
        fi
    fi
    if [[ $(ahead) -eq 0 ]]; then
        pr::exists && ok "Up to date │ $(pr::url)" || info "Nothing to push"
        return 0
    fi

    # ─── Push ─────────────────────────────────────────────────────────────────
    step "Pushing"
    if [[ "$force_with_lease" -eq 1 ]]; then
        git push --force-with-lease -u origin "$br" 2>&1 | grep -v '^remote:' || true
    else
        git push -u origin "$br" 2>&1 | grep -v '^remote:' || true
    fi
    ok "Pushed $(ahead) commit(s)"


    # ─── PR ───────────────────────────────────────────────────────────────────
    if pr::exists; then
        local num=$(pr::num)
        gh pr comment "$num" -b "🔄 Pushed" &>/dev/null || true
        ok "Updated PR #$num │ $(pr::url)"
    else
        step "Creating PR"
        local title=${br//[-_]/ }
        title=${title#feature/}
        title=${title#bug/}
        title=${title#fix/}
        # Prefix PR title with JIRA key — JIRA GitHub app picks this up for linking
        [[ -n "$jira_key" ]] && title="${jira_key} ${title}"
        local url=$(gh pr create -t "$title" -b "$(ahead_list | head -10)" -B "$(main)")
        ok "Created │ $url"
    fi

    banner "Done"
}

push::main "$@"
