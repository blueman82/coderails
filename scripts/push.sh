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
    # Capture git push's own output/status separately from display filtering:
    # `local push_output=$(...)` would mask git's exit status with `local`'s
    # own (always-zero) status, so declare first, assign on its own line, and
    # capture the real status via `||` (also keeps `set -e` from aborting
    # before we can branch on it). The display filter (`grep -v '^remote:'`)
    # runs afterwards on the captured text only, so its own exit code (1 when
    # a successful push's output is ALL `remote:` lines) can never be mistaken
    # for git push's status.
    local push_output push_rc=0
    if [[ "$force_with_lease" -eq 1 ]]; then
        push_output=$(git push --force-with-lease -u origin "$br" 2>&1) || push_rc=$?
    else
        push_output=$(git push -u origin "$br" 2>&1) || push_rc=$?
    fi
    # Filtering `remote:` lines de-noises a SUCCESSFUL push, but on failure
    # those same lines carry the server's actual reason (GH006, the ruleset
    # name, "Changes must be made through a pull request") — the one thing the
    # user needs. Filter on success only; print failures whole, to stderr.
    if [[ "$push_rc" -eq 0 ]]; then
        printf '%s\n' "$push_output" | grep -v '^remote:' || true
    else
        printf '%s\n' "$push_output" >&2
        err "Push failed (exit $push_rc) — see error above"
    fi

    # Positive verification: confirm the push actually landed. `git push`
    # updates the remote-tracking ref on success, so origin/$br should already
    # be current without a separate fetch.
    [[ "$(git rev-parse "origin/$br")" == "$(git rev-parse HEAD)" ]] \
        || err "Push reported success but origin/$br does not match local HEAD"
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
