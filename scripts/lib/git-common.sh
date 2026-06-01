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
main()       { git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@.*/@@' || echo main; }
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

# ━━━ Guards ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
require::feature() { [[ $(branch) =~ ^(main|master)$ ]] && err "Switch to a feature branch first" || true; }
require::clean()   { dirty && err "Uncommitted changes - commit or stash first" || true; }
require::repo()    { repo >/dev/null || err "Not a GitHub repository"; }
