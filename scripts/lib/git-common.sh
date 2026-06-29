#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  git-common.sh │ Shared utilities for elegant git workflows
#═══════════════════════════════════════════════════════════════════════════════

# ━━━ Terminal ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[[ -t 1 ]] && {
    readonly C_RED=$'\e[31m' C_GRN=$'\e[32m' C_YLW=$'\e[33m' C_BLU=$'\e[34m'
    readonly C_DIM=$'\e[2m'  C_BLD=$'\e[1m'  C_RST=$'\e[0m'
} || {
    readonly C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_BLD='' C_RST=''
}

# ━━━ Output ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
info()    { printf '%s• %s%s\n' "$C_BLU" "$1" "$C_RST"; }
ok()      { printf '%s✓ %s%s\n' "$C_GRN" "$1" "$C_RST"; }
warn()    { printf '%s! %s%s\n' "$C_YLW" "$1" "$C_RST"; }
err()     { printf '%s✗ %s%s\n' "$C_RED" "$1" "$C_RST" >&2; exit 1; }
dim()     { printf '%s%s%s\n' "$C_DIM" "$1" "$C_RST"; }
step()    { printf '\n%s→ %s%s\n' "$C_BLU" "$1" "$C_RST"; }
banner()  { printf '\n%s━━━ %s ━━━%s\n' "$C_GRN" "$1" "$C_RST"; }

# ━━━ Git Core ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
branch()     { git branch --show-current 2>/dev/null; }
dirty()      { [[ -n $(git status -s 2>/dev/null) ]]; }
clean()      { ! dirty; }
main()       { local m; m=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@.*/@@'); echo "${m:-main}"; }
ahead()      { git rev-list --count "origin/$(main)..HEAD" 2>/dev/null || echo 0; }
ahead_list() { git log "origin/$(main)..HEAD" --oneline 2>/dev/null; }

# ━━━ Repository ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
repo() {
    local url; url=$(git remote get-url origin 2>/dev/null) || return 1
    [[ $url =~ github\.com[:/]([^/]+)/([^/.]+) ]] && echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
}

protected() {
    gh api "repos/$(repo)/branches/$(main)/protection" 2>/dev/null | grep -q required_pull_request_reviews
}

# ━━━ Pull Requests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pr::num()    { gh pr list --head "${1:-$(branch)}" --json number -q '.[0].number' 2>/dev/null; }
pr::url()    { gh pr view "${1:-}" --json url -q .url 2>/dev/null; }
pr::state()  { gh pr view "$1" --json state -q .state 2>/dev/null || echo UNKNOWN; }
pr::title()  { gh pr view "$1" --json title -q .title 2>/dev/null || echo "PR #$1"; }
pr::review() { gh pr view "$1" --json reviewDecision -q .reviewDecision 2>/dev/null || echo NONE; }
pr::exists() { [[ -n $(pr::num "${1:-}") ]]; }

# ━━━ Sync ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Post-merge sync: bring the default branch up to date with origin. From the
# primary worktree this is just `checkout main; pull`. From a LINKED worktree,
# `git checkout main` is impossible (main is already checked out in the primary
# tree — git refuses), so we sync main *where it lives* via `git -C <primary>`
# instead of switching this worktree. Never aborts on the worktree case.
sync::main_branch() {
    local m; m=$(main)
    local gd cd; gd=$(git rev-parse --git-dir 2>/dev/null); cd=$(git rev-parse --git-common-dir 2>/dev/null)
    # Best-effort throughout: the remote merge has already landed by the time this
    # runs, so a sync failure must NEVER abort the caller (merge.sh runs under
    # `set -e`). Every git call is guarded; the function always returns 0.
    if [[ "$gd" != "$cd" ]]; then
        # Linked worktree: `git checkout main` is impossible here (main is checked
        # out in the primary tree), so sync main where it lives. Read the primary
        # tree as the first `worktree ` line, stripped via parameter expansion so a
        # path containing spaces survives (awk '{print $2}' would truncate it).
        local primary line
        line=$(git worktree list --porcelain 2>/dev/null | grep -m1 '^worktree ')
        primary=${line#worktree }
        if [[ -n "$primary" ]] \
            && git -C "$primary" checkout "$m" &>/dev/null \
            && git -C "$primary" pull origin "$m" --quiet; then
            ok "Synced $m in primary tree ($primary)"
        else
            warn "Could not sync $m in primary tree — sync it manually"
        fi
    else
        { [[ $(branch) != "$m" ]] && ! git checkout "$m" &>/dev/null; } \
            && { warn "Could not checkout $m — sync it manually"; return 0; }
        git pull origin "$m" --quiet && ok "Synced to $m" \
            || warn "Could not pull $m — sync it manually"
    fi
    return 0
}

# ━━━ Guards ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
require::feature() { [[ $(branch) =~ ^(main|master)$ ]] && err "Switch to a feature branch first" || true; }
require::clean()   { dirty && err "Uncommitted changes - commit or stash first" || true; }
require::repo()    { repo >/dev/null || err "Not a GitHub repository"; }
