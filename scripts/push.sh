#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  push.sh │ stage → commit → push → PR
#═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
source "$(dirname "$0")/lib/git-common.sh"

REVIEWERS="${GIT_REVIEWERS:-mhudson,pieczyra,omeara}"

push::main() {
    local msg="${1:-}" br=$(branch)

    require::feature
    require::repo

    # ─── Adobe enterprise auth check ─────────────────────────────────────────
    if ! gh auth status 2>&1 | grep -q "git.corp.adobe.com"; then
        err "Not authenticated with git.corp.adobe.com — run: gh auth login --hostname git.corp.adobe.com"
    fi

    # ─── JIRA key from branch config (set by /prep) ───────────────────────────
    local jira_key
    jira_key=$(git config "branch.${br}.jira-ticket" 2>/dev/null || true)

    step "$(repo) ─ $br → $(main)${jira_key:+ [$jira_key]}"

    # ─── Commit ───────────────────────────────────────────────────────────────
    if dirty; then
        git add -A
        if [[ -z "$msg" ]]; then
            local file_count; file_count=$(git diff --cached --name-only | wc -l | tr -d ' ')
            msg="Update ${file_count} files"
        fi
        # Prefix commit message with JIRA key so it appears in GitHub commit list
        # and JIRA's GitHub integration links it even after squash merge
        [[ -n "$jira_key" ]] && msg="${jira_key} ${msg}"
        git commit -m "$msg" && ok "Committed: $msg"
    elif [[ $(ahead) -eq 0 ]]; then
        pr::exists && ok "Up to date │ $(pr::url)" || info "Nothing to push"
        return 0
    fi

    # ─── Push ─────────────────────────────────────────────────────────────────
    step "Pushing"
    git push -u origin "$br" 2>&1 | grep -v '^remote:' || true
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

        protected && {
            gh pr edit --add-reviewer "$REVIEWERS" &>/dev/null && ok "Reviewers added" || warn "Some unavailable"
        }
    fi

    banner "Done"
}

push::main "$@"
