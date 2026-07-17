#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  tier-gate-runner.sh │ Root daemon: unforgeable tier-0 verdict poster
#  - Polls open PRs, finds the newest eval-artifact comment for the current
#    head SHA, judges tier-0 artifacts blind, posts a `tier-review` commit
#    status as the machine-user identity.
#  - Deliberately self-contained: does NOT source scripts/lib/*.sh. Those
#    files live in the login user's writable repo checkout; sourcing them at
#    daemon runtime would let a repo edit reach back into verdict production,
#    which is the exact trust-domain hole this daemon exists to close. The
#    marker grammar and comment-fetch idiom are therefore re-implemented
#    natively here rather than shared.
#  - No 'set -euo pipefail': this is a long-running poll loop where individual
#    step failures must be handled (posted as `error`), never abort the process.
#═══════════════════════════════════════════════════════════════════════════════

TIER_GATE_CONTEXT="tier-review"
TIER_GATE_MARKER_VERSION="v1"
TIER_GATE_PENDING_TTL="${TIER_GATE_PENDING_TTL:-720}"
TIER_GATE_WATCHDOG_TIMEOUT="${TIER_GATE_WATCHDOG_TIMEOUT:-60}"

# ─── Marker grammar (native re-implementation of eval_artifact.sh) ───────────

# tg_marker_prefix <pr> <head_sha>
# Echoes the literal marker prefix (through "head_sha=<sha> ") for <pr>/<sha>.
tg_marker_prefix() {
    local pr="$1" head_sha="$2"
    printf '<!-- coderails-eval-summary %s pr=%s head_sha=%s result=' \
        "$TIER_GATE_MARKER_VERSION" "$pr" "$head_sha"
}

# tg_marker_parse_tier <line>
# Echoes the tier digit (0, 1, or 2) if <line> matches the eval-artifact
# marker grammar for any pr/sha; empty string otherwise.
tg_marker_parse_tier() {
    local line="$1"
    local pattern='^<!-- coderails-eval-summary '"$TIER_GATE_MARKER_VERSION"' pr=[^ ]+ head_sha=[^ ]+ result=(GO|NO-GO) tier=([0-2]) -->$'
    if [[ "$line" =~ $pattern ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
    fi
}

# tg_marker_matches <line> <pr> <head_sha>
# Exit 0 iff <line> is the eval marker for <pr>/<head_sha> at any result/tier.
tg_marker_matches() {
    local line="$1" pr="$2" head_sha="$3"
    local prefix; prefix=$(tg_marker_prefix "$pr" "$head_sha")
    case "$line" in
        "$prefix"*) ;;
        *) return 1 ;;
    esac
    [[ -n "$(tg_marker_parse_tier "$line")" ]]
}

# tg_extract_evals_json <comment_body>
# Echoes the fenced ```json block embedded in the artifact comment body (the
# Task 4 embed contract), or empty string if no fenced json block is present.
# Multiple fenced json blocks: echoes the FIRST one — post_evals.sh's own
# validator (Task 4) refuses a posted artifact with more than one, so this
# extractor never has to arbitrate that case itself.
tg_extract_evals_json() {
    local body="$1"
    printf '%s\n' "$body" | awk '
        /^```json[[:space:]]*$/ { infence=1; next }
        /^```[[:space:]]*$/ { if (infence) exit; next }
        infence { print }
    '
}

# ─── Watchdog ─────────────────────────────────────────────────────────────────

# tg_with_watchdog <timeout_secs> -- <cmd...>
# Runs <cmd...> bounded by <timeout_secs>. Exit 124 on expiry (matching
# coreutils `timeout`'s convention) so callers can distinguish "the external
# call itself failed" from "the external call never returned". Falls back to
# a manual background+kill loop if `timeout` isn't on PATH (e.g. some macOS
# base installs lack GNU timeout without coreutils).
tg_with_watchdog() {
    local timeout_secs="$1"; shift
    [[ "$1" == "--" ]] && shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$timeout_secs" "$@"
        return $?
    fi
    "$@" &
    local pid=$!
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [[ $waited -ge $timeout_secs ]]; then
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            return 124
        fi
    done
    wait "$pid"
}

# ─── GitHub I/O (all through `gh` on PATH — stubbable in tests) ──────────────

# tg_open_prs
# Echoes one PR number per line for every open PR.
tg_open_prs() {
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr list --state open --json number -q '.[].number'
}

# tg_pr_head_sha <pr>
# Echoes the current head SHA for <pr>.
tg_pr_head_sha() {
    local pr="$1"
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr view "$pr" --json headRefOid -q .headRefOid
}

# tg_pr_comments <pr>
# Echoes each issue comment body for <pr>, base64-encoded one per line, in
# comment order (oldest first) — same encoding idiom as git-common.sh's
# pr::_trusted_comment_bodies, so multi-line bodies survive the `read` loop.
tg_pr_comments() {
    local pr="$1"
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        gh api "repos/{owner}/{repo}/issues/${pr}/comments" --paginate \
        --jq '.[] | (.body | @base64)'
}

# tg_newest_eval_comment_for_sha <pr> <head_sha>
# Echoes "<tier>\n<body>" for the newest comment whose marker line matches
# <pr>/<head_sha>, or nothing (empty stdout) if none found. Tier and body are
# both returned via stdout (never a global side-effect variable) because every
# call site invokes this via `$(...)` command substitution — a subshell — and
# a plain variable assignment made inside one never survives back to the
# caller's shell (the same pitfall git-common.sh documents for
# _PR_TRUSTED_LOGIN). Line 1 is the tier digit; every remaining line is the
# comment body verbatim (bodies routinely contain blank lines and fenced code,
# so the split is by first-newline, not by further line-parsing).
tg_newest_eval_comment_for_sha() {
    local pr="$1" head_sha="$2"
    local encoded body line
    local newest_body="" newest_tier=""
    while IFS= read -r encoded; do
        [[ -n "$encoded" ]] || continue
        body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null) || continue
        while IFS= read -r line; do
            if tg_marker_matches "$line" "$pr" "$head_sha"; then
                newest_body="$body"
                newest_tier=$(tg_marker_parse_tier "$line")
            fi
        done <<< "$body"
    done < <(tg_pr_comments "$pr")
    [[ -z "$newest_tier" ]] && return 0
    printf '%s\n%s' "$newest_tier" "$newest_body"
}

# tg_commit_statuses <sha>
# Echoes the JSON array of commit statuses for <sha> for context
# TIER_GATE_CONTEXT, newest first (GitHub's own list order), each object
# containing at minimum state/description/created_at.
tg_commit_statuses() {
    local sha="$1"
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        gh api "repos/{owner}/{repo}/commits/${sha}/statuses" --paginate \
        --jq "[.[] | select(.context == \"$TIER_GATE_CONTEXT\")]"
}

# tg_post_status <sha> <state> <description>
# Posts a commit status on <sha> for TIER_GATE_CONTEXT with <state>
# (pending|success|failure|error) and <description>.
tg_post_status() {
    local sha="$1" state="$2" description="$3"
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        gh api "repos/{owner}/{repo}/statuses/${sha}" \
        -f "state=${state}" \
        -f "context=${TIER_GATE_CONTEXT}" \
        -f "description=${description}" \
        >/dev/null
}

# ─── Status lifecycle decision ───────────────────────────────────────────────

# tg_latest_status_state <statuses_json>
# Echoes the state of the newest status object, or empty string if none.
tg_latest_status_state() {
    local statuses_json="$1"
    printf '%s' "$statuses_json" | jq -r '.[0].state // empty' 2>/dev/null
}

# tg_latest_status_age_secs <statuses_json> <now_epoch>
# Echoes how many seconds old the newest status's created_at is, relative to
# <now_epoch>. Empty string if no status or unparseable created_at.
tg_latest_status_age_secs() {
    local statuses_json="$1" now_epoch="$2"
    local created; created=$(printf '%s' "$statuses_json" | jq -r '.[0].created_at // empty' 2>/dev/null)
    [[ -z "$created" ]] && return 0
    # created_at is always UTC (GitHub's API convention, trailing Z). The
    # literal 'Z' in the format string does NOT make BSD `date -j` treat the
    # input as UTC — without an explicit -u it parses in the LOCAL timezone,
    # silently skewing age by the local UTC offset. -u is required on both
    # branches (BSD -j and GNU -d both accept it) so a fresh timestamp reads
    # as age ~0 regardless of the host's timezone.
    local created_epoch
    created_epoch=$(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$created" +%s 2>/dev/null) \
        || created_epoch=$(date -u -d "$created" +%s 2>/dev/null)
    [[ -z "$created_epoch" ]] && return 0
    printf '%s' "$((now_epoch - created_epoch))"
}

# tg_should_gate <sha>
# Exit 0 iff <sha> needs (re-)gating: no status at all, OR the newest status
# is `pending` and older than TIER_GATE_PENDING_TTL (a stale lease — daemon
# crashed or was killed mid-run). Exit 1 (skip) when a terminal status
# (success|failure|error) already exists, or a FRESH pending is in flight
# (another tick — or another daemon instance — is actively working this SHA;
# reclaiming it too would race two judges against the same SHA).
tg_should_gate() {
    local sha="$1"
    local statuses_json; statuses_json=$(tg_commit_statuses "$sha") || return 1
    local state; state=$(tg_latest_status_state "$statuses_json")
    case "$state" in
        ""|null)
            return 0
            ;;
        pending)
            local age; age=$(tg_latest_status_age_secs "$statuses_json" "$(date +%s)")
            [[ -n "$age" && "$age" -ge "$TIER_GATE_PENDING_TTL" ]]
            ;;
        success|failure|error)
            return 1
            ;;
        *)
            return 1
            ;;
    esac
}

# ─── Judge seam (Task 3 fills this in) ───────────────────────────────────────

# tg_judge <evals_json> <filelist> <diffstat>
# STUB for Task 2 — Task 3 replaces this with a real direct-API call.
# Contract (final, per plan Task 3): stdout `legitimate|illegitimate|insufficient`
# on the first line followed by a one-paragraph reason, rc 0 on a completed
# judgement; rc 1 on API/parse failure (caller posts `error`, never `failure`).
# Late-bound on purpose: bash resolves function calls at CALL time, so a test
# (or Task 3's real implementation) that redefines tg_judge after sourcing this
# file transparently replaces this stub — no other code here needs to change.
tg_judge() {
    printf 'insufficient\nSTUB: judge not yet implemented (Task 3).\n'
    return 0
}

# ─── Per-SHA gate ─────────────────────────────────────────────────────────────

# tg_gate_pr <pr>
# Runs the full lifecycle for the current head of <pr>:
#   1. Resolve head SHA. Fetch failure -> no action (next tick retries).
#   2. Find the newest eval-artifact comment for that SHA. None -> no action
#      (nothing to gate yet).
#   3. tg_should_gate decides whether this SHA needs (re-)gating.
#   4. tier-1/2 artifact -> short-circuit success/not-tier-0, no judge call.
#   5. tier-0 artifact -> post pending, extract embedded evals.json, judge,
#      post the terminal status (success|failure|error).
# Echoes a one-line summary of the action taken (or "skip: <reason>") to
# stdout for logging; callers/tests read this for assertions.
tg_gate_pr() {
    local pr="$1"
    local sha; sha=$(tg_pr_head_sha "$pr")
    if [[ -z "$sha" ]]; then
        printf 'skip: pr=%s reason=head_sha_fetch_failed\n' "$pr"
        return 1
    fi

    local found; found=$(tg_newest_eval_comment_for_sha "$pr" "$sha")
    if [[ -z "$found" ]]; then
        printf 'skip: pr=%s sha=%s reason=no_eval_artifact\n' "$pr" "$sha"
        return 0
    fi
    local tier="${found%%$'\n'*}"
    local body="${found#*$'\n'}"

    if ! tg_should_gate "$sha"; then
        printf 'skip: pr=%s sha=%s reason=already_terminal_or_fresh_pending\n' "$pr" "$sha"
        return 0
    fi

    if [[ "$tier" != "0" ]]; then
        tg_post_status "$sha" "success" "verdict=not-tier-0 host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=not-tier-0 state=success\n' "$pr" "$sha" "$tier"
        return 0
    fi

    tg_post_status "$sha" "pending" "verdict=pending host=$(hostname)"

    local evals_json; evals_json=$(tg_extract_evals_json "$body")
    if [[ -z "$evals_json" ]]; then
        tg_post_status "$sha" "error" "verdict=error host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=0 verdict=error state=error reason=no_embedded_evals_json\n' "$pr" "$sha"
        return 1
    fi

    local filelist diffstat
    filelist=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr diff "$pr" --name-only 2>/dev/null)
    diffstat=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr diff "$pr" --stat 2>/dev/null)

    local judge_out judge_rc
    judge_out=$(tg_judge "$evals_json" "$filelist" "$diffstat")
    judge_rc=$?
    if [[ $judge_rc -ne 0 ]]; then
        tg_post_status "$sha" "error" "verdict=error host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=0 verdict=error state=error reason=judge_rc_%s\n' "$pr" "$sha" "$judge_rc"
        return 1
    fi

    local verdict; verdict=$(printf '%s' "$judge_out" | head -1 | tr -d '[:space:]')
    case "$verdict" in
        legitimate)
            tg_post_status "$sha" "success" "verdict=legitimate host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=0 verdict=legitimate state=success\n' "$pr" "$sha"
            ;;
        illegitimate|insufficient)
            tg_post_status "$sha" "failure" "verdict=${verdict} host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=0 verdict=%s state=failure\n' "$pr" "$sha" "$verdict"
            ;;
        *)
            tg_post_status "$sha" "error" "verdict=error host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=0 verdict=error state=error reason=unrecognised_verdict_%s\n' "$pr" "$sha" "$verdict"
            return 1
            ;;
    esac
}

# ─── Poll loop ────────────────────────────────────────────────────────────────

# tg_poll_once
# One full pass over every open PR. Never aborts on a single PR's failure —
# logs and continues (a daemon tick must not die because one PR's gh call
# failed transiently).
tg_poll_once() {
    local pr
    while IFS= read -r pr; do
        [[ -n "$pr" ]] || continue
        tg_gate_pr "$pr"
    done < <(tg_open_prs)
}

# ─── Entry point ──────────────────────────────────────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    tg_poll_once
fi
