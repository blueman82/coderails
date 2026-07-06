#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  git-common.sh │ Shared utilities for elegant git workflows
#═══════════════════════════════════════════════════════════════════════════════

# Source review-artifact.sh (sibling lib) for marker matching.
# BASH_SOURCE-relative so this works regardless of cwd.
source "$(dirname "${BASH_SOURCE[0]}")/review-artifact.sh"
source "$(dirname "${BASH_SOURCE[0]}")/eval-artifact.sh"

# ━━━ Terminal ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if [[ -z "${_GIT_COMMON_COLORS_LOADED:-}" ]]; then
    [[ -t 1 ]] && {
        readonly C_RED=$'\e[31m' C_GRN=$'\e[32m' C_YLW=$'\e[33m' C_BLU=$'\e[34m'
        readonly C_DIM=$'\e[2m'  C_BLD=$'\e[1m'  C_RST=$'\e[0m'
    } || {
        readonly C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_BLD='' C_RST=''
    }
    readonly _GIT_COMMON_COLORS_LOADED=1
fi

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

# pr::head_sha <num>
# Echoes the current headRefOid for the given PR. Empty on gh failure.
pr::head_sha() {
    local out
    if out=$(gh pr view "$1" --json headRefOid -q .headRefOid 2>/dev/null); then
        printf '%s' "$out"
    fi
}

# pr::_trusted_login
# Echoes the authenticated gh user's login, resolved once per process and
# cached in _PR_TRUSTED_LOGIN so repeated reader calls don't refetch. This is
# the identity both gate readers trust — any comment from another login, or
# from this login without OWNER association, is untrusted and skipped before
# marker matching (comment-spoofing defence).
# Returns non-zero if the identity fetch fails (caller must fail-closed).
pr::_trusted_login() {
    if [[ -z "${_PR_TRUSTED_LOGIN:-}" ]]; then
        _PR_TRUSTED_LOGIN=$(gh api user -q .login 2>/dev/null) || return 1
        [[ -n "$_PR_TRUSTED_LOGIN" ]] || return 1
    fi
    printf '%s' "$_PR_TRUSTED_LOGIN"
}

# pr::_trusted_comment_bodies <num>
# Fetches ALL comments for <num> via the paginated REST endpoint (no 100-comment
# cap, unlike the old --json comments GraphQL fetch), keeps only comments whose author
# login matches the trusted identity AND whose authorAssociation is OWNER, and
# echoes their bodies in creation-ascending order (one body per line, base64
# encoded so multi-line bodies survive as a single reader line). Untrusted
# comments are dropped here, before any marker matching, so they can neither
# win nor suppress a match.
# Returns non-zero if the identity or comments fetch fails (fail-closed).
pr::_trusted_comment_bodies() {
    local num="$1" trusted
    trusted=$(pr::_trusted_login) || return 1
    gh api "repos/$(repo)/issues/${num}/comments" --paginate \
        --jq '.[] | select(.user.login == "'"$trusted"'" and .author_association == "OWNER") | (.body | @base64)' \
        2>/dev/null
}

# pr::has_coderails_review_for_head <num> <sha>
# Checks whether any LINE (across all trusted comment bodies) is exactly the
# coderails review marker for <num>/<sha>. Comments from untrusted authors are
# excluded before matching (see pr::_trusted_comment_bodies).
# Exit codes:
#   0 = found a matching marker
#   1 = fetched ok, but no matching marker found
#   2 = gh fetch failed (fail-closed)
pr::has_coderails_review_for_head() {
    local num="$1" sha="$2"
    local encoded_bodies
    if ! encoded_bodies=$(pr::_trusted_comment_bodies "$num"); then
        return 2
    fi
    local encoded body line
    while IFS= read -r encoded; do
        [[ -n "$encoded" ]] || continue
        body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null)
        while IFS= read -r line; do
            if review_artifact::matches_marker "$line" "$num" "$sha"; then
                return 0
            fi
        done <<< "$body"
    done <<< "$encoded_bodies"
    return 1
}

# pr::has_coderails_eval_for_head <num> <sha>
# Checks whether any LINE (across all trusted comment bodies) is the coderails
# eval marker for <num>/<sha>. Comments from untrusted authors are excluded
# before matching (see pr::_trusted_comment_bodies). A PR can accumulate
# multiple eval-artifact comments over its lifetime, so the LAST matching
# marker line in comment order is authoritative — NOT the first. On any
# matching line, sets the global PR_EVAL_TIER to the parsed tier digit of the
# newest match.
# Exit codes (same shape as pr::has_coderails_review_for_head):
#   0 = newest matching artifact has result=GO
#   1 = fetched ok, no matching artifact at all, or the newest matching
#       artifact is NO-GO (PR_EVAL_TIER is still set in the latter case so
#       the caller can report which tier failed)
#   2 = gh fetch failed (fail-closed)
pr::has_coderails_eval_for_head() {
    local num="$1" sha="$2"
    unset PR_EVAL_TIER
    local encoded_bodies
    if ! encoded_bodies=$(pr::_trusted_comment_bodies "$num"); then
        return 2
    fi
    local newest_result=""
    local encoded body line
    while IFS= read -r encoded; do
        [[ -n "$encoded" ]] || continue
        body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null)
        while IFS= read -r line; do
            if eval_artifact::matches_marker "$line" "$num" "$sha"; then
                newest_result=$(eval_artifact::parse_result "$line")
                PR_EVAL_TIER=$(eval_artifact::parse_tier "$line")
            fi
        done <<< "$body"
    done <<< "$encoded_bodies"
    [[ "$newest_result" == "GO" ]] && return 0
    return 1
}

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
