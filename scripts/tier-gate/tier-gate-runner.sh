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
# The fallback backgrounds <cmd...> in its OWN process group (`set -m` +
# subshell) so that on expiry `kill -9 -"$pid"` (negative PID = kill the
# whole group) reaps any child processes <cmd...> itself spawned — killing
# only the direct child would leave orphaned descendants holding the
# caller's stdout pipe open, hanging any `$(tg_with_watchdog ...)` command
# substitution forever even though this function itself has returned 124.
tg_with_watchdog() {
    local timeout_secs="$1"; shift
    [[ "$1" == "--" ]] && shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$timeout_secs" "$@"
        return $?
    fi
    local was_monitor=0
    case "$-" in *m*) was_monitor=1 ;; esac
    set -m
    "$@" &
    local pid=$!
    [[ $was_monitor -eq 0 ]] && set +m
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [[ $waited -ge $timeout_secs ]]; then
            kill -9 -"$pid" 2>/dev/null
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            return 124
        fi
    done
    wait "$pid"
}

# ─── GitHub I/O ─────────────────────────────────────────────────────────────
# Every call — reads and the credentialled status WRITE alike — goes through
# curl (TIER_GATE_CURL_BIN) to the GitHub REST API, carrying the machine-user
# GH_TOKEN as a Bearer credential. NOTHING here execs `gh`: gh lives under
# /opt/homebrew/bin, which is uid-501-writable, so a root daemon exec'ing it is
# a privilege-escalation surface (uid 501 swaps the binary, root runs it).
# There is no root-owned gh to pin, so the reads route through curl at /usr/bin
# (root:wheel) exactly like the write does — see tg_post_status's header.

# TIER_GATE_CURL_BIN: PATH-pinned by default to the root-owned system curl.
# curl at /usr/bin is root:wheel; overridable so tests can point it at a stub.
TIER_GATE_CURL_BIN="${TIER_GATE_CURL_BIN:-/usr/bin/curl}"

# tg_gh_get <api_path_or_url> [accept_header]
# Authenticated GET against the GitHub REST API. <api_path_or_url> is either a
# path RELATIVE to https://api.github.com/repos/<owner>/<repo>/ (e.g.
# "pulls/42/files") OR an absolute https:// URL (used to follow a Link
# rel="next" header, which GitHub returns as an absolute URL). Echoes the
# response body on a 2xx and returns 0; returns 1 (and echoes nothing) on any
# failure — the daemon's fail-closed primitive for reads.
#
# FAIL-CLOSED / the curl-vs-gh trap: `gh` exits nonzero on an HTTP 4xx/5xx, but
# curl exits 0 (its rc reflects the TRANSPORT, not the HTTP status) unless
# asked. So checking curl's rc alone would read a 404/500 error body as a
# successful response. We append the HTTP status via -w and reject any non-2xx
# BEFORE returning the body, so a failed read can never masquerade as data.
# An EMPTY 2xx body is NOT treated as failure here (a statuses list is
# legitimately []); call sites that must reject an empty body (the diff trio)
# enforce that themselves.
tg_gh_get() {
    local target="$1" accept="${2:-application/vnd.github+json}"
    local url
    case "$target" in
        https://*) url="$target" ;;
        *)
            local slug; slug=$(tg_repo_slug)
            [[ -z "$slug" ]] && { printf 'tg_gh_get: error: could not resolve owner/repo from git remote origin\n' >&2; return 1; }
            url="https://api.github.com/repos/${slug}/${target}"
            ;;
    esac
    local creds_path="${TIER_GATE_CREDS:-}"
    [[ -z "$creds_path" ]] && { printf 'tg_gh_get: error: TIER_GATE_CREDS is not set\n' >&2; return 1; }
    local token; token=$(tg_read_gh_token "$creds_path") || return 1

    local resp rc
    resp=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        "$TIER_GATE_CURL_BIN" -sS --max-time "$TIER_GATE_WATCHDOG_TIMEOUT" \
        -w '\n%{http_code}' \
        "$url" \
        -H "Authorization: Bearer ${token}" \
        -H "Accept: ${accept}")
    rc=$?
    [[ $rc -ne 0 ]] && return 1        # watchdog/curl transport failure
    local code="${resp##*$'\n'}" body="${resp%$'\n'*}"
    [[ "$code" =~ ^2[0-9][0-9]$ ]] || return 1   # HTTP 4xx/5xx -> fail closed
    printf '%s' "$body"
}

# tg_open_prs
# Echoes one PR number per line for every open PR.
tg_open_prs() {
    tg_gh_get "pulls?state=open&per_page=100" | jq -r '.[].number // empty' 2>/dev/null
}

# tg_pr_head_sha <pr>
# Echoes the current head SHA for <pr>.
tg_pr_head_sha() {
    local pr="$1"
    tg_gh_get "pulls/${pr}" | jq -r '.head.sha // empty' 2>/dev/null
}

# tg_pr_comments <pr>
# Echoes each issue comment body for <pr>, base64-encoded one per line, in
# comment order (oldest first) — same encoding idiom as git-common.sh's
# pr::_trusted_comment_bodies, so multi-line bodies survive the `read` loop.
#
# No author filter, and that is SAFE here — deliberately, not by omission.
# git-common.sh's reader filters to the merge-runner's own gh identity, but in
# this deployment the agent self-merges, so that "trusted" author IS uid 501 —
# the same identity as the adversary. Filtering by author cannot separate the
# honest eval-artifact author from a forger when they are one uid; it would only
# reject the honest artifact (authored by uid 501, not the machine user) and
# brick every genuine tier-0 PR. The real defences against a forged marker are
# elsewhere and do not depend on comment authorship:
#   - A tier-0 claim is judged on the SHA-bound REAL diff (Fix 1/3), never on the
#     marker's prose, so a forged `tier=0` marker still faces the judge + prefilter.
#   - A `tier != 0` claim posts NO status (tg_gate_pr), so a forged non-tier-0
#     marker mints no reusable success and merge.sh finds no tier-review approval
#     -> fails closed. A later in-place edit back to tier=0 finds no terminal
#     status and is re-judged (tg_should_gate).
#   - merge.sh requires the status description to carry verdict=legitimate, so a
#     bare state=success (however minted) is not a valid tier-0 approval.
#
# Paginated, and it MUST be: issue comments come oldest-first, so on a busy PR
# the newest eval artifact lands on a LATER page — a single per_page=100 page
# would miss it and the PR would never get judged. This follows the GitHub
# `Link: rel="next"` header (an ABSOLUTE URL) across every page.
#
# FAIL-CLOSED on a partial fetch: all pages are buffered and emitted only after
# the LAST page succeeds. If ANY page fails (transport or non-2xx), this emits
# NOTHING and returns 1 — never a truncated list. That matters because the sole
# caller (tg_newest_eval_comment_for_sha) reads this via `< <(...)`, a process
# substitution whose exit status is discarded, so it cannot see the rc; a
# truncated stream would be silently mistaken for "these are all the comments"
# and, oldest-first, would drop exactly the newest artifact. Emitting nothing
# instead makes a partial fetch read as "no eval artifact" -> tg_gate_pr skips
# (safe: next tick retries), never a judgement on a stale/partial view.
tg_pr_comments() {
    local pr="$1"
    local creds_path="${TIER_GATE_CREDS:-}"
    [[ -z "$creds_path" ]] && return 1
    local token; token=$(tg_read_gh_token "$creds_path") || return 1
    local slug; slug=$(tg_repo_slug)
    [[ -z "$slug" ]] && return 1

    local url="https://api.github.com/repos/${slug}/issues/${pr}/comments?per_page=100"
    local buffer="" hdr_file
    hdr_file=$(mktemp) || return 1
    while [[ -n "$url" ]]; do
        local resp rc body code
        resp=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
            "$TIER_GATE_CURL_BIN" -sS --max-time "$TIER_GATE_WATCHDOG_TIMEOUT" \
            -D "$hdr_file" -w '\n%{http_code}' \
            "$url" \
            -H "Authorization: Bearer ${token}" \
            -H "Accept: application/vnd.github+json")
        rc=$?
        if [[ $rc -ne 0 ]]; then rm -f "$hdr_file"; return 1; fi
        code="${resp##*$'\n'}"; body="${resp%$'\n'*}"
        if [[ ! "$code" =~ ^2[0-9][0-9]$ ]]; then rm -f "$hdr_file"; return 1; fi
        # Accumulate this page's base64-encoded comment bodies.
        local page_enc; page_enc=$(printf '%s' "$body" | jq -r '.[] | (.body | @base64)' 2>/dev/null) || { rm -f "$hdr_file"; return 1; }
        buffer+="${page_enc}"$'\n'
        # Follow Link: <url>; rel="next" if present (absolute URL from GitHub).
        url=$(grep -i '^Link:' "$hdr_file" | grep -oE '<[^>]*>; rel="next"' | head -1 | sed -E 's/^<([^>]*)>.*/\1/')
    done
    rm -f "$hdr_file"
    # Emit only after every page succeeded. Strip the trailing blank line so the
    # consumer's `[[ -n "$encoded" ]]` guard isn't fed an empty final record.
    printf '%s' "$buffer" | grep -v '^$' || true
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
#
# GATE-CRITICAL fail-closed: capture tg_gh_get's rc BEFORE jq. tg_should_gate
# (below) does `statuses_json=$(tg_commit_statuses "$sha") || return 1` and
# treats a returned "" as "no status -> gate", so a failed fetch that leaked
# through as empty-but-rc-0 would make the daemon RE-JUDGE a SHA whose terminal
# status it could not read. Piping tg_gh_get straight into jq would bind the
# `$(...)` rc to jq, not the fetch — so the fetch is captured first, its rc
# propagated, and only a real 2xx body is handed to jq.
# per_page=100 single page (no Link-following): statuses are newest-first, so
# page 1 already holds the freshest tier-review status, which is all the
# lifecycle logic below inspects. Capped at 100 by construction.
tg_commit_statuses() {
    local sha="$1"
    local raw
    raw=$(tg_gh_get "commits/${sha}/statuses?per_page=100") || return 1
    printf '%s' "$raw" | jq "[.[] | select(.context == \"$TIER_GATE_CONTEXT\")]" 2>/dev/null
}

# tg_repo_slug
# Echoes "<owner>/<repo>" — the repo this daemon gates. Resolved from the
# TIER_GATE_REPO env value (an owner/repo string the plist sets, rendered at
# install time) when present, else falls back to parsing `git remote get-url
# origin`. Native reimplementation of git-common.sh's repo() (same regex) for
# the fallback rather than sourcing it — see this file's header comment on why
# the daemon never sources scripts/lib/*.sh at runtime. Needed because the
# credentialled status POST (tg_post_status, below) moved off `gh api
# repos/{owner}/{repo}/...`, whose {owner}/{repo} placeholder gh resolves for
# us automatically — curl has no equivalent, so this function is curl's
# replacement for it.
#
# TIER_GATE_REPO is the production path: the INSTALLED daemon runs as root from
# its install dir (/etc/coderails-tier-gate/), which is NOT a git repo, so the
# git-remote fallback returns empty there and every read/status-post would fail
# closed with no repo to gate. The env value is validated to owner/repo shape
# before use — a malformed value is ignored and the git-remote fallback runs, so
# a garbage env can never be echoed as a slug. The fallback keeps a checkout
# (dev, the test suite) working with no env set.
tg_repo_slug() {
    if [[ "${TIER_GATE_REPO:-}" =~ ^[^/]+/[^/]+$ ]]; then
        printf '%s' "$TIER_GATE_REPO"
        return 0
    fi
    local url; url=$(git remote get-url origin 2>/dev/null) || return 1
    if [[ "$url" =~ github\.com[:/]([^/]+)/(.+)$ ]]; then
        local name="${BASH_REMATCH[2]}"
        name="${name%/}"
        name="${name%.git}"
        printf '%s/%s' "${BASH_REMATCH[1]}" "$name"
    fi
}

# tg_read_gh_token <creds_path>
# Echoes the GH_TOKEN value from the credentials file, or empty string with a
# named error on stderr if the file is missing or the key is absent. Same
# shape as tg_judge_read_oauth_token (below) but reads a distinct credential
# from the same root-owned file (install.sh's tgi_check_credentials already
# requires all three keys present).
tg_read_gh_token() {
    local creds_path="$1"
    if [[ ! -f "$creds_path" ]]; then
        printf 'tg_post_status: error: TIER_GATE_CREDS file not found at %s\n' "$creds_path" >&2
        return 1
    fi
    local token
    token=$(grep -E '^GH_TOKEN=' "$creds_path" | head -1 | cut -d= -f2-)
    if [[ -z "$token" ]]; then
        printf 'tg_post_status: error: GH_TOKEN not present in credentials file %s\n' "$creds_path" >&2
        return 1
    fi
    printf '%s' "$token"
}

# tg_read_machine_user <creds_path>
# Echoes the MACHINE_USER value from the credentials file, or empty string
# with a named error on stderr if the file is missing or the key is absent.
# Lives in the SAME root-owned creds file as the other credentials — NOT an
# env var. The daemon's plist (com.coderails.tier-gate.plist.template)
# only ever passes TIER_GATE_CREDS (a path) via EnvironmentVariables; nothing
# propagates a separate bare env var into the installed launchd job. Reading
# the expected login from inside the creds file (rather than trusting an
# env var the daemon never actually receives) is what makes the identity
# check in tg_post_status functional in production, not just in a test
# harness that happens to export one.
tg_read_machine_user() {
    local creds_path="$1"
    if [[ ! -f "$creds_path" ]]; then
        printf 'tg_post_status: error: TIER_GATE_CREDS file not found at %s\n' "$creds_path" >&2
        return 1
    fi
    local login
    login=$(grep -E '^MACHINE_USER=' "$creds_path" | head -1 | cut -d= -f2-)
    if [[ -z "$login" ]]; then
        printf 'tg_post_status: error: MACHINE_USER not present in credentials file %s\n' "$creds_path" >&2
        return 1
    fi
    printf '%s' "$login"
}

# tg_verify_identity <token>
# Calls GET /user with <token> and echoes the authenticated login on success.
# Returns 1 (empty stdout) on any fetch/parse failure — caller treats that
# the same as a mismatch (fail closed).
tg_verify_identity() {
    local token="$1"
    local response
    response=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        "$TIER_GATE_CURL_BIN" -sS --max-time "$TIER_GATE_WATCHDOG_TIMEOUT" \
        https://api.github.com/user \
        -H "Authorization: Bearer ${token}" \
        -H "Accept: application/vnd.github+json" \
        -H "content-type: application/json")
    printf '%s' "$response" | jq -r '.login // empty' 2>/dev/null
}

# tg_post_status <sha> <state> <description>
# Posts a commit status on <sha> for TIER_GATE_CONTEXT with <state>
# (pending|success|failure|error) and <description>.
#
# Fix 7: this write carries the root-owned machine-user credential
# (TIER_GATE_CREDS' GH_TOKEN) via curl, PREFERRED over `gh` for exactly this
# call — gh lives under /opt/homebrew/bin (uid-501-writable); a root daemon
# exec'ing it for a credentialled write is a privilege-escalation surface
# that curl at /usr/bin (root:wheel) is not. Reads elsewhere in this file
# stay on gh; only this credentialled write moved.
#
# Before ever posting, this calls tg_verify_identity with the SAME
# credential and aborts — posts nothing, logs a named error — unless the
# returned login matches the creds file's MACHINE_USER exactly. A mismatch
# means the wrong credential is loaded (misconfiguration, or a tampered
# creds file): failing closed here is what makes the identity check
# meaningful — posting under an unverified identity would defeat the whole
# point of creator-binding downstream in merge.sh.
tg_post_status() {
    local sha="$1" state="$2" description="$3"

    local creds_path="${TIER_GATE_CREDS:-}"
    if [[ -z "$creds_path" ]]; then
        printf 'tg_post_status: error: TIER_GATE_CREDS is not set\n' >&2
        return 1
    fi
    local token
    token=$(tg_read_gh_token "$creds_path") || return 1
    local machine_user
    machine_user=$(tg_read_machine_user "$creds_path") || return 1

    local actual_login
    actual_login=$(tg_verify_identity "$token")
    if [[ -z "$actual_login" || "$actual_login" != "$machine_user" ]]; then
        printf 'tg_post_status: error: identity check failed — GET /user returned login "%s", expected machine user "%s". Aborting post under an unverified identity.\n' \
            "$actual_login" "$machine_user" >&2
        return 1
    fi

    local repo_slug; repo_slug=$(tg_repo_slug)
    if [[ -z "$repo_slug" ]]; then
        printf 'tg_post_status: error: could not resolve owner/repo from git remote origin\n' >&2
        return 1
    fi

    local body
    body=$(jq -n --arg state "$state" --arg context "$TIER_GATE_CONTEXT" --arg description "$description" \
        '{state: $state, context: $context, description: $description}')

    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        "$TIER_GATE_CURL_BIN" -sS --max-time "$TIER_GATE_WATCHDOG_TIMEOUT" \
        "https://api.github.com/repos/${repo_slug}/statuses/${sha}" \
        -H "Authorization: Bearer ${token}" \
        -H "Accept: application/vnd.github+json" \
        -H "content-type: application/json" \
        -d "$body" \
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

# ─── Judge (Task 3): blind verdict via a claude -p subscription subprocess ───

# TIER_GATE_JUDGE_MODEL: pinned model constant for the judge call.
# claude-haiku-4-5 — chosen deliberately over the "always use Opus 4.8"
# default: this is a cheap, deterministic classification task (three-way
# verdict + one-paragraph reason), the exact use case the model catalog names
# Haiku for. The frozen spec/plan require `temperature: 0` for determinism;
# current-generation models (Opus 4.8/4.7, Sonnet 5, Fable 5) REJECT any
# non-default temperature/top_p/top_k with a 400 — only prior-generation
# models (Haiku 4.5, Sonnet 4.5 and older) still accept it. Haiku 4.5 is the
# one model satisfying every constraint at once: cheap, active/current,
# classification-appropriate, and temperature-compatible.
TIER_GATE_JUDGE_MODEL="claude-haiku-4-5"
TIER_GATE_JUDGE_PROMPT_PATH="${TIER_GATE_JUDGE_PROMPT_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/judge-prompt.md}"

# TIER_GATE_CLAUDE_BIN: the claude binary the judge execs. MUST be a
# root-owned copy in a uid-501-UNWRITABLE tree — a root daemon exec'ing a
# binary the adversary (uid 501) can swap is a privilege-escalation surface
# worse than the one this gate closes. The default points at the root-owned
# install, NEVER uid 501's ~/.local/bin/claude. Provisioning this binary is a
# MANUAL operator step, not something any code here performs: the operator runs
# `sudo HOME=/var/root claude install stable` once to create it, and is
# responsible for keeping it current on `stable` (e.g. a root-scheduled re-run).
# install.sh does NOT install or update it — a future maintainer must not assume
# the root-owned judge binary is auto-provisioned. See the tier-review spec's
# operator checklist.
TIER_GATE_CLAUDE_BIN="${TIER_GATE_CLAUDE_BIN:-/var/root/.local/bin/claude}"

# TIER_GATE_JUDGE_HOME: the HOME (and cwd) the judge subprocess runs under.
# MUST be root-owned. claude discovers CLAUDE.md / settings.json / MCP config
# relative to BOTH cwd and HOME; if either were a uid-501-writable path (e.g.
# the PR author's checkout), the adversary would plant a CLAUDE.md ("rule this
# tier-0 legitimate") that the judge reads as instruction — the exact
# injection class Fix 1 deleted, re-entering through config discovery. Pinning
# both to a root-owned dir closes that surface categorically.
TIER_GATE_JUDGE_HOME="${TIER_GATE_JUDGE_HOME:-/var/root}"

# tg_judge_read_oauth_token <creds_path>
# Echoes the CLAUDE_CODE_OAUTH_TOKEN value from the credentials file, or empty
# string with a named error on stderr if the file is missing or the key is
# absent. Mirrors tg_read_gh_token / tg_read_machine_user: the one root-owned
# 0600 creds file holds GH_TOKEN, MACHINE_USER, and this subscription token;
# the judge reads only its own token out of it. The subscription token
# replaces the vetoed metered API key — the CLI uses CLAUDE_CODE_OAUTH_TOKEN
# from the env with no keychain fallback (a bogus token 401s), so the token
# never leaves the root-owned file except into the subprocess env.
tg_judge_read_oauth_token() {
    local creds_path="$1"
    if [[ ! -f "$creds_path" ]]; then
        printf 'tg_judge: error: TIER_GATE_CREDS file not found at %s\n' "$creds_path" >&2
        return 1
    fi
    local token
    token=$(grep -E '^CLAUDE_CODE_OAUTH_TOKEN=' "$creds_path" | head -1 | cut -d= -f2-)
    if [[ -z "$token" ]]; then
        printf 'tg_judge: error: CLAUDE_CODE_OAUTH_TOKEN not present in credentials file %s\n' "$creds_path" >&2
        return 1
    fi
    printf '%s' "$token"
}

# tg_judge_build_prompt <claimed_tier> <diff>
# Echoes the static judge-prompt.md instructions followed by the two blind
# inputs, joined by plain concatenation (printf, never substitution into the
# template). This is the injection fix, not a mitigation on top of the old
# mechanism: judge-prompt.md carries no placeholders at all (verified by
# J13), so there is no template-substitution step left for a `&` in the
# replacement or an embedded fence/heading in the diff to corrupt — nothing
# here re-parses the diff text as anything other than an opaque data blob
# appended after the instructions. tg_judge_call_claude is what makes this
# safe on the wire: it passes the resulting string as a single `-p` argument
# in the subprocess argv (never interpolated into a shell string or a
# template), so it reaches the model as one inert data value regardless of
# what markdown/JSON-looking content it contains.
tg_judge_build_prompt() {
    local claimed_tier="$1" diff="$2"
    local instructions
    instructions=$(cat "$TIER_GATE_JUDGE_PROMPT_PATH")
    printf '%s\n\n### Claimed tier\n\n%s\n\n### PR diff\n\n%s' \
        "$instructions" "$claimed_tier" "$diff"
}

# TIER_GATE_JUDGE_SCHEMA: the structured-output JSON Schema constraining the
# verdict to the enum. Passed to `claude -p --json-schema` — the CLI analogue
# of the old API request's output_config.format. tg_judge_parse_verdict's own
# enum check remains a second, redundant guard (belt-and-suspenders): an
# off-enum or unparseable response is always rc 1, never a pass.
TIER_GATE_JUDGE_SCHEMA='{"type":"object","properties":{"verdict":{"type":"string","enum":["legitimate","illegitimate","insufficient"]},"reason":{"type":"string"}},"required":["verdict","reason"],"additionalProperties":false}'

# tg_judge_call_claude <oauth_token> <prompt_text>
# Runs ONE `claude -p` subprocess against the owner's subscription (never the
# metered Anthropic API — permanent owner veto). Echoes claude's raw
# --output-format json envelope; rc is the CLI's own exit code. Auth is the
# root-held CLAUDE_CODE_OAUTH_TOKEN passed ONLY into this subprocess's env (no
# keychain fallback — a bad token surfaces as an is_error envelope the parser
# blocks on). SECURITY-CRITICAL: the subprocess runs with HOME **and** cwd
# pinned to TIER_GATE_JUDGE_HOME (root-owned) so claude cannot discover a
# uid-501-planted CLAUDE.md / settings.json / MCP config — the cwd/HOME
# re-entry of the injection class Fix 1 deleted. --json-schema constrains the
# verdict enum (Fix 4); --max-turns 1 and permission-mode plan keep it a pure
# read-and-classify call with no tool surface. The binary is
# TIER_GATE_CLAUDE_BIN (root-owned), never uid 501's.
# NOTE: claude has NO --cwd flag (verified against --help) — the working
# directory is inherited from the process, so the cwd pin is enforced by
# `cd`-ing into the root-owned dir in a subshell BEFORE exec, not by a claude
# argument. The subshell keeps the cd from leaking into the daemon's own cwd.
# `env -i` clears the environment so no uid-501 env var (e.g. an inherited
# CLAUDE_* or HOME) survives into the judge; only the whitelisted vars pass.
tg_judge_call_claude() {
    local oauth_token="$1" prompt_text="$2"
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        bash -c 'cd "$1" || exit 1; exec env -i \
            HOME="$1" \
            PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
            CLAUDE_CODE_OAUTH_TOKEN="$2" \
            "$3" \
            -p "$4" \
            --model "$5" \
            --output-format json \
            --json-schema "$6" \
            --permission-mode plan \
            --max-turns 1' \
        _ "$TIER_GATE_JUDGE_HOME" "$oauth_token" "$TIER_GATE_CLAUDE_BIN" \
          "$prompt_text" "$TIER_GATE_JUDGE_MODEL" "$TIER_GATE_JUDGE_SCHEMA"
}

# tg_judge_parse_verdict <response_body>
# Extracts {verdict, reason} from claude's `-p --output-format json` envelope
# and echoes "<verdict>\n<reason>". The envelope (observed live) is
# {type:"result", is_error:<bool>, result:"<string>", ...}; with --json-schema
# the structured payload lands in .result as a JSON string. Returns 1 (caller
# retries, then blocks) when: the envelope isn't valid JSON, is_error is true
# (e.g. "Not logged in" — a bad/absent token surfaces HERE, and must never be
# read as a pass), .result is absent, the inner JSON doesn't parse, or the
# verdict isn't in the enum. The enum check is a second guard on top of
# --json-schema (Fix 4): an unparseable or off-enum response is always rc 1
# (error/block), never a pass, however it arose.
tg_judge_parse_verdict() {
    local response_body="$1"
    # is_error true => the CLI call failed inside the envelope (auth, model,
    # tool error). Block outright — never mine a verdict out of a failed run.
    local is_error
    is_error=$(printf '%s' "$response_body" | jq -r '.is_error // empty' 2>/dev/null)
    [[ "$is_error" == "true" ]] && return 1

    local inner_text
    inner_text=$(printf '%s' "$response_body" | jq -r '.result // empty' 2>/dev/null)
    [[ -z "$inner_text" ]] && return 1

    local verdict reason
    verdict=$(printf '%s' "$inner_text" | jq -r '.verdict // empty' 2>/dev/null)
    reason=$(printf '%s' "$inner_text" | jq -r '.reason // empty' 2>/dev/null)
    case "$verdict" in
        legitimate|illegitimate|insufficient) ;;
        *) return 1 ;;
    esac
    printf '%s\n%s' "$verdict" "$reason"
}

# tg_judge <claimed_tier> <diff>
# Contract (per Fix 1): stdout `legitimate|illegitimate|insufficient` on the
# first line followed by a one-paragraph reason, rc 0 on a completed
# judgement; rc 1 on API/parse/creds failure (caller posts `error`, never
# `failure`). One retry on a malformed/unparseable response before giving up.
# Takes ONLY the trusted claimed tier and the PR diff — never the
# defendant's own evals.json/tier_justification prose (that channel is
# deleted entirely, not sanitised; see judge-prompt.md's header comment).
# Late-bound on purpose: bash resolves function calls at CALL time, so a test
# that redefines tg_judge after sourcing this file transparently replaces
# this implementation — no other code here needs to change (see Task 2's
# tg_gate_pr tests, which redefine tg_judge and never reach this code path).
tg_judge() {
    local claimed_tier="$1" diff="$2"

    local creds_path="${TIER_GATE_CREDS:-}"
    if [[ -z "$creds_path" ]]; then
        printf 'tg_judge: error: TIER_GATE_CREDS is not set\n' >&2
        return 1
    fi
    local oauth_token
    oauth_token=$(tg_judge_read_oauth_token "$creds_path") || return 1

    local prompt_text
    prompt_text=$(tg_judge_build_prompt "$claimed_tier" "$diff")

    local attempt response parsed
    for attempt in 1 2; do
        response=$(tg_judge_call_claude "$oauth_token" "$prompt_text")
        parsed=$(tg_judge_parse_verdict "$response") && { printf '%s' "$parsed"; return 0; }
    done

    printf 'tg_judge: error: claude/parse failure after retry\n' >&2
    return 1
}

# ─── Pre-filter (Fix 2): mechanical size/path gate BEFORE any model call ────

# TIER_GATE_MAX_FILES / TIER_GATE_MAX_LINES: the tier-0 size cap. Tier 0
# MEANS "single work-unit" (skills/task-evals/SKILL.md's own predicate) —
# a genuine single-work-unit diff is small. `diff > cap` is therefore NOT
# tier 0 by definition, so oversize blocks outright; this can never produce
# a permissive read (there is no "truncate and still judge" path — see
# tg_gate_pr, which never calls tg_judge once the prefilter blocks).
#
# Calibrated against the two real-world dishonest tier-0 PRs this exists to
# catch: PR #189 (205 lines / 1 file) and PR #191 (3 lines / 1 file). A
# file-count-only check passes #189 outright (it's a single file) — the
# LINE cap is what catches it. #191 is deliberately NOT caught here: at
# 3 lines it is indistinguishable in size from a genuinely tiny honest
# tier-0, so catching it is the model's job (content-based judgement), not
# the pre-filter's (size-based judgement) — tuning the cap down to reach it
# would block the large majority of honest tier-0s along with it.
#
# 80 lines: comfortably below 205 (so #189 blocks with margin, not by a
# hair) and comfortably above what a single self-contained work-unit
# realistically spans in a bugfix/small-feature diff in this repo (see the
# existing tier-0 predicate's own "single work-unit" framing) — high enough
# that a real one-file-one-function honest tier-0 clears it without needing
# per-PR tuning.
TIER_GATE_MAX_FILES="${TIER_GATE_MAX_FILES:-3}"
TIER_GATE_MAX_LINES="${TIER_GATE_MAX_LINES:-80}"

# TIER_GATE_MAX_DIFF_BYTES: cap on the real diff content (Fix 3) fed to the
# judge. Same fail-closed posture as the pre-filter — over-cap blocks
# outright, never truncates-and-judges. 200KB is generous headroom above
# the ~80-line/~3-file shape the line/file caps already enforce (a diff
# that size in bytes would already have failed those caps on almost any
# real content), so this exists as a defense-in-depth backstop against a
# pathological few-lines-but-enormous-content diff, not as the primary cap.
# Shared by every tier: the byte cap is a content-size backstop, not the
# tier-0-specific "single work-unit" discriminator the line/file caps are,
# so it does not need a separate tier-1/2 value the way TIER_GATE_MAX_LINES
# does (below).
TIER_GATE_MAX_DIFF_BYTES="${TIER_GATE_MAX_DIFF_BYTES:-204800}"

# TIER_GATE_MAX_LINES_HIGHER_TIER: the line cap for tier-1/2 claims, once
# every tier is judged (not just tier-0). Tier-0's 80-line cap encodes
# "single work-unit" and would wrongly block honest tier-1/2 work, which is
# routinely larger (tier 1/2 carry no size predicate — see
# skills/task-evals/SKILL.md: tier 2 is defined by work-unit COUNT or an
# outward/irreversible surface, never by line count). 500 lines is a
# generous ceiling above ordinary tier-1/2 diffs in this repo while still
# bounding the judge's input; a genuinely larger honest change fails closed
# to `insufficient` (human review) rather than being judged on a truncated
# diff or waved through uncapped. File count is NOT split per-tier: a
# self-contained tier-1/2 change spanning many files is unusual enough that
# the shared TIER_GATE_MAX_FILES cap catching it and falling back to
# `insufficient` is an acceptable, rare cost.
TIER_GATE_MAX_LINES_HIGHER_TIER="${TIER_GATE_MAX_LINES_HIGHER_TIER:-500}"

# TIER_GATE_PATH_DENYLIST: ERE alternation of path prefixes that are
# outward-facing or irreversible surfaces by construction (tier-0's own
# predicate names these as automatically disqualifying — see
# judge-prompt.md). Matched against each line of the PR's file list.
# Deliberately conservative and easy to extend; a path matching here blocks
# without ever reaching the model.
TIER_GATE_PATH_DENYLIST='^(skills/dashboard/|launchd/|scripts/tier-gate/|\.github/workflows/)'

# tg_prefilter <filelist> <line_count> [claimed_tier]
# Mechanical, model-free gate. <filelist> is newline-separated paths (as
# from `gh pr diff --name-only`); <line_count> is the diff's total changed
# line count (as from `gh pr diff --stat`, or any equivalent count).
# <claimed_tier> is OPTIONAL and defaults to "0" — every existing call site
# (and the prefilter test suite) that omits it keeps the original tier-0
# line cap unchanged. Exit 0 and empty stdout on pass; exit 1 and a named
# reason on stdout on block. Injection-immune by construction: no model
# call happens in this function, so there is nothing here for diff CONTENT
# to inject into — only file paths and a line count are inspected, both
# mechanically derived facts about the diff's shape, never text the
# defendant wrote is read as instructions.
#
# The line cap is tier-aware (TIER_GATE_MAX_LINES for tier 0,
# TIER_GATE_MAX_LINES_HIGHER_TIER for tier 1/2) now that every tier reaches
# this gate; TIER_GATE_MAX_FILES and the path denylist are NOT split per
# tier — the denylist is a self-edit leash that must hold at every tier
# identically, and the file-count cap is a defense-in-depth backstop
# distinct from the line-count discriminator, not worth a second constant.
tg_prefilter() {
    local filelist="$1" line_count="$2" claimed_tier="${3:-0}"

    local max_lines="$TIER_GATE_MAX_LINES"
    [[ "$claimed_tier" != "0" ]] && max_lines="$TIER_GATE_MAX_LINES_HIGHER_TIER"

    local file_count=0
    if [[ -n "$filelist" ]]; then
        file_count=$(printf '%s\n' "$filelist" | grep -c .)
    fi

    local bad_path
    bad_path=$(printf '%s\n' "$filelist" | grep -E "$TIER_GATE_PATH_DENYLIST" | head -1)
    if [[ -n "$bad_path" ]]; then
        printf 'blocked: denylist path=%s\n' "$bad_path"
        return 1
    fi

    if [[ "$file_count" -gt "$TIER_GATE_MAX_FILES" || "$line_count" -gt "$max_lines" ]]; then
        printf 'blocked: size cap exceeded files=%s/%s lines=%s/%s\n' \
            "$file_count" "$TIER_GATE_MAX_FILES" "$line_count" "$max_lines"
        return 1
    fi

    return 0
}

# ─── Per-SHA gate ─────────────────────────────────────────────────────────────

# tg_gate_pr <pr>
# Runs the full lifecycle for the current head of <pr>. EVERY tier is judged
# (no mechanical-only short-circuit at tier 1/2 — see the "judge every tier"
# comment inline below for why):
#   1. Resolve head SHA. Fetch failure -> no action (next tick retries).
#   2. Find the newest eval-artifact comment for that SHA. None -> no action
#      (nothing to gate yet).
#   3. tg_should_gate decides whether this SHA needs (re-)gating.
#   4. Fetch the PR's changed-file list ONCE (B3 fail-closed fetch, shared by
#      every tier) and run the self-edit leash against it — blocks any tier
#      touching scripts/tier-gate/ before anything else runs.
#   5. Post pending, extract embedded evals.json, prefilter (tier-aware size
#      cap — see tg_prefilter), judge (the claimed tier as the claim under
#      test, not just a tier-0 exemption), post the terminal status
#      (success|failure|error). A size-cap breach posts `illegitimate` at
#      tier 0 (size IS the tier-0 discriminator) but `insufficient` at tier
#      1/2 (size is NOT the tier-2 discriminator — never truncate-and-judge,
#      never brand an honest large diff dishonest).
# Every posted description carries a `tier=<claimed>` token so a status can
# never be replayed against a different claimed tier. Echoes a one-line
# summary of the action taken (or "skip: <reason>") to stdout for logging;
# callers/tests read this for assertions.
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

    # ── Shared B3 fail-closed file-list fetch ──────────────────────────────
    # Every tier needs this: the self-edit leash (below) must run BEFORE any
    # judging logic, or a tier claim could edit the daemon's own source
    # (scripts/tier-gate/) and self-merge ungated. Fetched ONCE and reused
    # by tg_prefilter below, never re-fetched.
    #
    # B3 fail-closed: both filelist/line_count are derived from ONE GET
    # /pulls/{pr}/files. curl exits 0 on an HTTP 4xx/5xx (unlike gh), so
    # tg_gh_get's own HTTP-status check is what makes a failed fetch
    # fail-closed here; we additionally treat an empty file list as a hard
    # error. Letting a failed/empty fetch through would set file_count=0 /
    # line_count=0, which SAILS THROUGH the prefilter (0 > cap is false) and
    # would also make the self-edit leash see an empty (non-matching)
    # filelist — a false "no self-edit" read. per_page=100 single page (no
    # Link-following): a tier-0 diff is <=3 files by the size cap, so a PR
    # that legitimately exceeds one page of files is already not tier-0;
    # tier-1/2 PRs are capped higher (TIER_GATE_MAX_LINES_HIGHER_TIER) but
    # still capped, and a self-edit only needs ONE matching filename to
    # appear on page 1 to be caught regardless of tier.
    local files_json
    files_json=$(tg_gh_get "pulls/${pr}/files?per_page=100") || {
        tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=files_fetch_failed\n' "$pr" "$sha" "$tier"
        return 1
    }
    local filelist line_count
    filelist=$(printf '%s' "$files_json" | jq -r '.[].filename // empty' 2>/dev/null)
    line_count=$(printf '%s' "$files_json" | jq '[.[] | .additions + .deletions] | add // 0' 2>/dev/null)
    if [[ -z "$filelist" ]]; then
        tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=empty_file_list\n' "$pr" "$sha" "$tier"
        return 1
    fi

    # Self-edit leash: a claim at ANY tier that touches scripts/tier-gate/
    # (the daemon's own source) is blocked outright, before any judging
    # logic runs. Reuses TIER_GATE_PATH_DENYLIST — the same paths
    # tg_prefilter's own denylist check would eventually hit — but greps it
    # directly here so the block posts the more specific verdict=self_edit
    # rather than the generic prefilter verdict=illegitimate: a self-edit is
    # a leash violation, categorically different from "diff too big" or
    # "content doesn't match the claimed tier", and worth distinguishing in
    # the posted status for anyone reading it later.
    local self_edit_path
    self_edit_path=$(printf '%s\n' "$filelist" | grep -E "$TIER_GATE_PATH_DENYLIST" | head -1)
    if [[ -n "$self_edit_path" ]]; then
        tg_post_status "$sha" "failure" "verdict=self_edit tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=self_edit state=failure reason=self_edit_path=%s\n' \
            "$pr" "$sha" "$tier" "$self_edit_path"
        return 0
    fi

    # Judge every tier (supersedes the old post-nothing / attest-all
    # short-circuits). post_evals.sh's eval OBLIGATION ladder is binary —
    # tier 0 is exempt from evals entirely, tier 1 and tier 2 carry
    # mechanically IDENTICAL obligations (skills/task-evals/SKILL.md) — so
    # the only lie that buys anything at the eval layer is claiming tier 0.
    # Judging every tier is not about catching a 1-vs-2 mistake; it is that
    # an independent judged status now posts on EVERY PR (no silent path to
    # merge that the daemon never looked at) and the daemon's tier-review
    # context becomes ALWAYS-REPORTED, which is the precondition for making
    # it a required status check on main (a daemon that posts nothing at
    # tier!=0 can never be a required check — every tier-1/2 PR would hang
    # pending forever).
    tg_post_status "$sha" "pending" "verdict=pending tier=${tier} host=$(hostname)"

    # Well-formedness gate only: an artifact with no embedded evals.json is
    # a malformed-artifact error, independent of the judge, at every tier
    # (tier 0 embeds tier_justification-only evals.json per the Task 4
    # embed contract; a missing block is malformed regardless of tier). The
    # extracted content itself is NEVER passed to the judge (Fix 1) — its
    # presence is all this checks.
    local evals_json; evals_json=$(tg_extract_evals_json "$body")
    if [[ -z "$evals_json" ]]; then
        tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=no_embedded_evals_json\n' "$pr" "$sha" "$tier"
        return 1
    fi

    # Fix 2: mechanical pre-filter BEFORE any model call. filelist/line
    # count only — never diff content — so this step cannot be influenced
    # by anything the defendant wrote. Uses the filelist/line_count already
    # fetched above (shared B3 fetch); not re-fetched here. Tier-aware: the
    # claimed tier selects TIER_GATE_MAX_LINES (tier 0) vs
    # TIER_GATE_MAX_LINES_HIGHER_TIER (tier 1/2) inside tg_prefilter itself.
    #
    # Verdict on breach is TIER-SPLIT and this is the crux of judging every
    # tier honestly: at tier 0, over-cap really isn't tier-0 work (tier 0
    # MEANS single work-unit, which is small) — genuinely illegitimate,
    # unchanged from the pre-existing behaviour. At tier 1/2, size is NOT
    # the discriminator (tier 2 is defined by work-unit COUNT or an
    # outward/irreversible surface, never by line count — SKILL.md), so an
    # honest large tier-1/2 change (e.g. a big single-module refactor with
    # no outward surface) breaching the cap is not evidence of dishonesty.
    # Branding it illegitimate would be the same size-implies-tier
    # conflation PR #191 warned against, inverted. It posts `insufficient`
    # instead — the same fail-closed-to-human-review semantics the judge
    # itself would use for "can't tell from the blind inputs" — without
    # ever calling the judge on a diff this large. This is still
    # never-truncate-and-judge: an over-cap diff at ANY tier never reaches
    # tg_judge.
    # tg_prefilter's OWN denylist check can never fire here — the leash
    # above already ran the identical regex against the identical filelist
    # and would have returned first — so any block reaching this point is
    # the size cap, never the denylist. Only the size-cap outcome is
    # branched on below.
    local prefilter_out prefilter_rc
    prefilter_out=$(tg_prefilter "$filelist" "$line_count" "$tier")
    prefilter_rc=$?
    if [[ $prefilter_rc -ne 0 ]]; then
        if [[ "$tier" == "0" ]]; then
            tg_post_status "$sha" "failure" "verdict=illegitimate tier=0 host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=0 verdict=illegitimate state=failure reason=prefilter_%s\n' \
                "$pr" "$sha" "$(printf '%s' "$prefilter_out" | tr -s ' \n' '_')"
        else
            tg_post_status "$sha" "failure" "verdict=insufficient tier=${tier} host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=%s verdict=insufficient state=failure reason=prefilter_%s\n' \
                "$pr" "$sha" "$tier" "$(printf '%s' "$prefilter_out" | tr -s ' \n' '_')"
        fi
        return 0
    fi

    # Fix 3: capped REAL diff content (not just name-only/--stat metadata).
    # Fetched as the raw unified diff via the GitHub diff media type. Byte cap
    # mirrors Fix 2's fail-closed posture: over-cap blocks outright rather than
    # truncating and judging a partial diff (a truncated diff is never a valid
    # basis for a permissive read). Shared across tiers — see
    # TIER_GATE_MAX_DIFF_BYTES's own comment for why it isn't split per tier.
    #
    # B3 fail-closed on the diff fetch itself: tg_gh_get returns nonzero on a
    # failed/non-2xx fetch (curl's exit-0-on-HTTP-error trap is handled inside
    # it), and we ALSO treat an empty diff body as a hard error. An empty diff
    # reaching the judge is the headline bug this closes: it would present zero
    # changed content as a legitimate basis at any tier.
    local diff diff_bytes
    diff=$(tg_gh_get "pulls/${pr}" "application/vnd.github.v3.diff") || {
        tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=diff_fetch_failed\n' "$pr" "$sha" "$tier"
        return 1
    }
    if [[ -z "$diff" ]]; then
        tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=empty_diff\n' "$pr" "$sha" "$tier"
        return 1
    fi
    diff_bytes=$(printf '%s' "$diff" | wc -c | tr -d ' ')
    if [[ "$diff_bytes" -gt "$TIER_GATE_MAX_DIFF_BYTES" ]]; then
        if [[ "$tier" == "0" ]]; then
            tg_post_status "$sha" "failure" "verdict=illegitimate tier=0 host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=0 verdict=illegitimate state=failure reason=diff_bytes_%s_over_%s\n' \
                "$pr" "$sha" "$diff_bytes" "$TIER_GATE_MAX_DIFF_BYTES"
        else
            tg_post_status "$sha" "failure" "verdict=insufficient tier=${tier} host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=%s verdict=insufficient state=failure reason=diff_bytes_%s_over_%s\n' \
                "$pr" "$sha" "$tier" "$diff_bytes" "$TIER_GATE_MAX_DIFF_BYTES"
        fi
        return 0
    fi

    # The judge now tests the CLAIM at every tier: "does this diff match
    # the claimed tier N?", not just "is this legitimate tier-0 exempt
    # work?" — judge-prompt.md carries all three tier predicates (Fix
    # judge-all-tiers). tg_judge's own contract (claimed_tier, diff) ->
    # verdict is unchanged; only the prompt content and what counts as a
    # legitimate answer at each tier changed.
    local judge_out judge_rc
    judge_out=$(tg_judge "$tier" "$diff")
    judge_rc=$?
    if [[ $judge_rc -ne 0 ]]; then
        tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=judge_rc_%s\n' "$pr" "$sha" "$tier" "$judge_rc"
        return 1
    fi

    local verdict; verdict=$(printf '%s' "$judge_out" | head -1 | tr -d '[:space:]')
    case "$verdict" in
        legitimate)
            tg_post_status "$sha" "success" "verdict=legitimate tier=${tier} host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=%s verdict=legitimate state=success\n' "$pr" "$sha" "$tier"
            ;;
        illegitimate|insufficient)
            tg_post_status "$sha" "failure" "verdict=${verdict} tier=${tier} host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=%s verdict=%s state=failure\n' "$pr" "$sha" "$tier" "$verdict"
            ;;
        *)
            tg_post_status "$sha" "error" "verdict=error tier=${tier} host=$(hostname)"
            printf 'gated: pr=%s sha=%s tier=%s verdict=error state=error reason=unrecognised_verdict_%s\n' "$pr" "$sha" "$tier" "$verdict"
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
