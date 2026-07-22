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
    # Repo name capture is greedy (dots allowed, e.g. owner/my.repo.git) — a
    # trailing slash and/or .git suffix is stripped after the match instead of
    # excluded from it, so a dotted repo name is never truncated.
    if [[ $url =~ github\.com[:/]([^/]+)/(.+)$ ]]; then
        local name="${BASH_REMATCH[2]}"
        name="${name%/}"
        name="${name%.git}"
        echo "${BASH_REMATCH[1]}/${name}"
    fi
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
# Echoes the authenticated gh user's login. NOTE: despite the _PR_TRUSTED_LOGIN
# variable, this does NOT cache across processes — each reader call site
# invokes this from a fresh command substitution subshell, so any value set
# here never survives back to the caller's shell (confirmed: `gh api user`
# runs once per pr::_trusted_comment_bodies call, not once per process). The
# variable only guards against redundant fetches within a single subshell's
# lifetime. This is the identity both gate readers trust — any comment from
# another login is untrusted and skipped before marker matching
# (comment-spoofing defence; see pr::_trusted_permission for the second,
# repo-permission conjunct).
# The login is validated against GitHub's login charset before use whether it
# came from cache or a fresh fetch, because it is spliced directly into a jq
# --jq program string: an unvalidated value (e.g. pre-seeded via env as
# `x" or true`) could break out of the string literal and turn the trust
# filter into a tautology. A value that fails validation is treated as unset
# (fail-closed) rather than trusted.
# Returns non-zero if the identity fetch fails or fails validation (caller
# must fail-closed).
pr::_trusted_login() {
    if [[ -z "${_PR_TRUSTED_LOGIN:-}" ]]; then
        _PR_TRUSTED_LOGIN=$(gh api user -q .login 2>/dev/null) || return 1
    fi
    [[ "$_PR_TRUSTED_LOGIN" =~ ^[A-Za-z0-9-]+$ ]] || return 1
    printf '%s' "$_PR_TRUSTED_LOGIN"
}

# pr::_trusted_permission
# Echoes the authenticated identity's permission level on the current repo
# (ADMIN/MAINTAIN/WRITE/READ/TRIAGE/NONE), via viewerPermission — the
# permission conjunct of the trust rule (the login conjunct is
# pr::_trusted_login, unchanged and still the anti-spoof property: a
# different login is rejected regardless of this value). Same per-subshell
# reuse-guard shape as pr::_trusted_login (does NOT cache across processes).
# Returns non-zero if the lookup fails (caller must fail-closed).
pr::_trusted_permission() {
    if [[ -z "${_PR_TRUSTED_PERMISSION:-}" ]]; then
        _PR_TRUSTED_PERMISSION=$(gh repo view "$(repo)" --json viewerPermission -q .viewerPermission 2>/dev/null) || return 1
    fi
    [[ -n "$_PR_TRUSTED_PERMISSION" ]] || return 1
    printf '%s' "$_PR_TRUSTED_PERMISSION"
}

# pr::_permission_is_write_or_better <permission>
# True iff <permission> grants write access or better (ADMIN, MAINTAIN, WRITE).
# READ and TRIAGE do not qualify.
pr::_permission_is_write_or_better() {
    case "$1" in
        ADMIN|MAINTAIN|WRITE) return 0 ;;
        *) return 1 ;;
    esac
}

# pr::_trusted_comment_bodies <num>
# Fetches ALL comments for <num> via the paginated REST endpoint (no 100-comment
# cap, unlike the old --json comments GraphQL fetch), keeps only comments whose
# author login matches the trusted identity, and echoes their bodies in
# creation-ascending order (one body per line, base64 encoded so multi-line
# bodies survive as a single reader line). Untrusted comments are dropped
# here, before any marker matching, so they can neither win nor suppress a
# match.
# Trust rule: the login must match the authenticated identity (anti-spoof —
# unchanged from before) AND that identity must hold write access or better on
# this repo (replaces the old repo-ownership-badge conjunct, which failed
# closed on org-owned repos where the same user's own comments carry a
# non-owner association instead — see INSTALLATION.md).
# Insufficient permission (READ/TRIAGE/NONE, successfully looked up) is NOT a
# fetch failure — it is treated the same as "no trusted comments found": this
# function echoes nothing and returns 0, so callers see an empty body list
# (their existing not-found path), not a fail-closed 2. Only an actual lookup
# FAILURE (the API call itself erroring) is fail-closed, matching the
# identity-fetch-failure posture.
# On any FAILURE (identity/permission/comments fetch errors), prints a
# `TRUST_FETCH_FAIL_REASON=identity|permission|comments` line to STDERR (not
# swallowed by the inner `2>/dev/null` calls, which only silence `gh`'s own
# diagnostics) so a caller capturing this function's stderr separately from
# its stdout can tell which fetch failed. This can't be a plain global
# variable: every call site invokes this function via `$(...)` command
# substitution, and — like the documented _PR_TRUSTED_LOGIN cache above — a
# variable assignment made inside a `$(...)` subshell never survives back to
# the caller's shell. The return-code contract itself (non-zero, fail-closed)
# is unchanged; this stderr line is purely an added diagnostic signal.
# Returns non-zero only if the identity fetch, permission fetch, or comments
# fetch itself fails (fail-closed).
pr::_trusted_comment_bodies() {
    local num="$1" trusted permission
    trusted=$(pr::_trusted_login) || { echo "TRUST_FETCH_FAIL_REASON=identity" >&2; return 1; }
    permission=$(pr::_trusted_permission) || { echo "TRUST_FETCH_FAIL_REASON=permission" >&2; return 1; }
    pr::_permission_is_write_or_better "$permission" || return 0
    gh api "repos/$(repo)/issues/${num}/comments" --paginate \
        --jq '.[] | select(.user.login == "'"$trusted"'") | (.body | @base64)' \
        2>/dev/null || { echo "TRUST_FETCH_FAIL_REASON=comments" >&2; return 1; }
}

# pr::_trusted_comment_bodies_or_fail <num>
# Thin wrapper around pr::_trusted_comment_bodies that also recovers its
# stderr-carried failure reason into PR_TRUST_FETCH_FAIL_REASON in THIS
# (caller's) shell — not inside a command substitution, so the assignment
# actually survives. Both public readers call this instead of
# pr::_trusted_comment_bodies directly so the reason-capture plumbing lives in
# exactly one place. Same return-code contract: non-zero iff the underlying
# fetch failed.
# Must NOT be called via `$(...)` — it sets PR_TRUST_FETCH_FAIL_REASON (and,
# on success, _PR_TRUSTED_COMMENT_BODIES) as globals in the CALLER's shell, and
# a command-substitution subshell would swallow both, same failure mode as the
# documented _PR_TRUSTED_LOGIN non-cache above. Callers read
# _PR_TRUSTED_COMMENT_BODIES after a zero return instead of capturing this
# function's stdout.
pr::_trusted_comment_bodies_or_fail() {
    local num="$1" stderr_file
    unset PR_TRUST_FETCH_FAIL_REASON _PR_TRUSTED_COMMENT_BODIES
    if ! stderr_file=$(mktemp); then
        PR_TRUST_FETCH_FAIL_REASON="tempfile"
        return 1
    fi
    if _PR_TRUSTED_COMMENT_BODIES=$(pr::_trusted_comment_bodies "$num" 2>"$stderr_file"); then
        rm -f "$stderr_file"
        return 0
    fi
    PR_TRUST_FETCH_FAIL_REASON=$(sed -n 's/^TRUST_FETCH_FAIL_REASON=//p' "$stderr_file" | tail -1)
    rm -f "$stderr_file"
    return 1
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
    if ! pr::_trusted_comment_bodies_or_fail "$num"; then
        return 2
    fi
    encoded_bodies="$_PR_TRUSTED_COMMENT_BODIES"
    local encoded body line
    while IFS= read -r encoded; do
        [[ -n "$encoded" ]] || continue
        if ! body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null); then
            printf '%s! Skipping a trusted comment body: base64 decode failed%s\n' "$C_YLW" "$C_RST" >&2
            continue
        fi
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
    if ! pr::_trusted_comment_bodies_or_fail "$num"; then
        return 2
    fi
    encoded_bodies="$_PR_TRUSTED_COMMENT_BODIES"
    local newest_result=""
    local encoded body line
    while IFS= read -r encoded; do
        [[ -n "$encoded" ]] || continue
        if ! body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null); then
            printf '%s! Skipping a trusted comment body: base64 decode failed%s\n' "$C_YLW" "$C_RST" >&2
            continue
        fi
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

# pr::coderails_eval_embed_for_head <num> <sha>
# Echoes the fenced ```json evals.json embed from the NEWEST trusted comment
# whose marker line matches <num>/<sha> (same "newest wins" rule as
# pr::has_coderails_eval_for_head — a PR can accumulate multiple eval-artifact
# comments, and only the latest is authoritative). This is what
# post_evals::smoke_verify re-executes against at merge time: the artifact as
# actually posted to the trusted PR comment, never a local evals.json file
# the caller might not even have (the posting agent's working copy could be
# anywhere, or gone).
# Exit codes (same shape as pr::has_coderails_eval_for_head):
#   0 = found a matching marker; embed printed to stdout (may be empty if the
#       matching comment body carried no fenced json block — caller must
#       treat an empty embed as a failure, this function only reports
#       whether a MARKER matched, not whether the embed itself is well-formed)
#   1 = fetched ok, no matching marker found at all
#   2 = gh fetch failed (fail-closed)
pr::coderails_eval_embed_for_head() {
    local num="$1" sha="$2"
    local encoded_bodies
    if ! pr::_trusted_comment_bodies_or_fail "$num"; then
        return 2
    fi
    encoded_bodies="$_PR_TRUSTED_COMMENT_BODIES"
    local newest_body=""
    local found=1
    local encoded body line
    while IFS= read -r encoded; do
        [[ -n "$encoded" ]] || continue
        if ! body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null); then
            printf '%s! Skipping a trusted comment body: base64 decode failed%s\n' "$C_YLW" "$C_RST" >&2
            continue
        fi
        while IFS= read -r line; do
            if eval_artifact::matches_marker "$line" "$num" "$sha"; then
                newest_body="$body"
                found=0
            fi
        done <<< "$body"
    done <<< "$encoded_bodies"
    [[ $found -eq 0 ]] || return 1
    # Same fenced-block extraction idiom as tier-gate-runner.sh's
    # tg_extract_evals_json (Task 4 embed contract): echo the FIRST fenced
    # ```json block; post_evals.sh's own validator refuses a posted artifact
    # with more than one, so this extractor never has to arbitrate that case.
    printf '%s\n' "$newest_body" | awk '
        /^```json[[:space:]]*$/ { infence=1; next }
        /^```[[:space:]]*$/ { if (infence) exit; next }
        infence { print }
    '
    return 0
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
