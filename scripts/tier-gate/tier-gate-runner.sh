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

# ─── GitHub I/O (reads through `gh` on PATH; the credentialled status WRITE
#     goes through curl instead — see tg_post_status's own header comment) ───

# TIER_GATE_CURL_BIN: PATH-pinned by default to the root-owned system curl.
# `gh` lives in /opt/homebrew/bin, which is uid-501-writable — a root daemon
# exec'ing it for a credentialled write would let anything able to write
# there intercept the machine-user token. curl at /usr/bin is root:wheel.
# Overridable so tests can point it at a stub.
TIER_GATE_CURL_BIN="${TIER_GATE_CURL_BIN:-/usr/bin/curl}"

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

# tg_repo_slug
# Echoes "<owner>/<repo>" resolved from `git remote get-url origin`. Native
# reimplementation of git-common.sh's repo() (same regex) rather than
# sourcing it — see this file's header comment on why the daemon never
# sources scripts/lib/*.sh at runtime. Needed because the credentialled
# status POST (tg_post_status, below) moved off `gh api repos/{owner}/{repo}/
# ...`, whose {owner}/{repo} placeholder gh resolves for us automatically —
# curl has no equivalent, so this function is curl's replacement for it.
tg_repo_slug() {
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
# shape as tg_judge_read_api_key (below) but reads a distinct credential
# from the same root-owned file (install.sh's tgi_check_credentials already
# requires both keys present).
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

# ─── Judge (Task 3): blind verdict via direct Anthropic API call ─────────────

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

# tg_judge_read_api_key <creds_path>
# Echoes the ANTHROPIC_API_KEY value from the credentials file, or empty
# string with a named error on stderr if the file is missing or the key is
# absent. The credentials file is a simple KEY=value file (one root-owned
# file holds both the machine-user PAT and the Anthropic key; the judge only
# ever reads its own key out of it).
tg_judge_read_api_key() {
    local creds_path="$1"
    if [[ ! -f "$creds_path" ]]; then
        printf 'tg_judge: error: TIER_GATE_CREDS file not found at %s\n' "$creds_path" >&2
        return 1
    fi
    local key
    key=$(grep -E '^ANTHROPIC_API_KEY=' "$creds_path" | head -1 | cut -d= -f2-)
    if [[ -z "$key" ]]; then
        printf 'tg_judge: error: ANTHROPIC_API_KEY not present in credentials file %s\n' "$creds_path" >&2
        return 1
    fi
    printf '%s' "$key"
}

# tg_judge_build_prompt <claimed_tier> <diff>
# Echoes the static judge-prompt.md instructions followed by the two blind
# inputs, joined by plain concatenation (printf, never substitution into the
# template). This is the injection fix, not a mitigation on top of the old
# mechanism: judge-prompt.md carries no placeholders at all (verified by
# J13), so there is no template-substitution step left for a `&` in the
# replacement or an embedded fence/heading in the diff to corrupt — nothing
# here re-parses the diff text as anything other than an opaque data blob
# appended after the instructions. tg_judge_call_api is what makes this safe
# on the wire: it passes the resulting string to `jq --arg`, which JSON-
# encodes it as a single string value, so it reaches the model as inert data
# regardless of what markdown/JSON-looking content it contains.
tg_judge_build_prompt() {
    local claimed_tier="$1" diff="$2"
    local instructions
    instructions=$(cat "$TIER_GATE_JUDGE_PROMPT_PATH")
    printf '%s\n\n### Claimed tier\n\n%s\n\n### PR diff\n\n%s' \
        "$instructions" "$claimed_tier" "$diff"
}

# tg_judge_call_api <api_key> <prompt_text>
# Makes ONE direct curl call to the Anthropic Messages API (never the claude
# CLI — see the spec's central constraint: user-owned CLI auth/state would
# pull the judge back into the agent's trust domain). Echoes the raw response
# body; rc is curl's own exit code (0 on any HTTP response, including 4xx/5xx
# bodies — HTTP-level failures are caught by the caller's JSON/verdict parse).
# The request declares output_config.format (json_schema, Fix 4): the API
# enforces the {verdict, reason} shape and the verdict enum server-side, so
# tg_judge_parse_verdict's own enum check is a second, redundant guard rather
# than the only one — a model that tried to return a fifth verdict value
# would be rejected by the API itself before this ever ran.
tg_judge_call_api() {
    local api_key="$1" prompt_text="$2"
    local body
    body=$(jq -n --arg model "$TIER_GATE_JUDGE_MODEL" --arg prompt "$prompt_text" '{
        model: $model,
        max_tokens: 1024,
        temperature: 0,
        messages: [{role: "user", content: $prompt}],
        output_config: {
            format: {
                type: "json_schema",
                schema: {
                    type: "object",
                    properties: {
                        verdict: {type: "string", enum: ["legitimate", "illegitimate", "insufficient"]},
                        reason: {type: "string"}
                    },
                    required: ["verdict", "reason"],
                    additionalProperties: false
                }
            }
        }
    }')
    tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- \
        curl -sS --max-time "$TIER_GATE_WATCHDOG_TIMEOUT" \
        https://api.anthropic.com/v1/messages \
        -H "content-type: application/json" \
        -H "x-api-key: ${api_key}" \
        -H "anthropic-version: 2023-06-01" \
        -d "$body"
}

# tg_judge_parse_verdict <response_body>
# Extracts {verdict, reason} from the Messages API response's first text
# block and echoes "<verdict>\n<reason>". Returns 1 (caller retries) if the
# response isn't valid JSON, has no text content block, or the inner JSON
# doesn't parse to a recognised verdict. The verdict enum check here is a
# second guard on top of the request's own output_config.format schema
# (Fix 4) — belt-and-suspenders: an unparseable or off-enum response is
# always rc 1 (error/block), never treated as a pass, however it arose.
tg_judge_parse_verdict() {
    local response_body="$1"
    local inner_text
    inner_text=$(printf '%s' "$response_body" | jq -r '.content[0].text // empty' 2>/dev/null)
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
    local api_key
    api_key=$(tg_judge_read_api_key "$creds_path") || return 1

    local prompt_text
    prompt_text=$(tg_judge_build_prompt "$claimed_tier" "$diff")

    local attempt response parsed
    for attempt in 1 2; do
        response=$(tg_judge_call_api "$api_key" "$prompt_text")
        parsed=$(tg_judge_parse_verdict "$response") && { printf '%s' "$parsed"; return 0; }
    done

    printf 'tg_judge: error: API/parse failure after retry\n' >&2
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
TIER_GATE_MAX_DIFF_BYTES="${TIER_GATE_MAX_DIFF_BYTES:-204800}"

# TIER_GATE_PATH_DENYLIST: ERE alternation of path prefixes that are
# outward-facing or irreversible surfaces by construction (tier-0's own
# predicate names these as automatically disqualifying — see
# judge-prompt.md). Matched against each line of the PR's file list.
# Deliberately conservative and easy to extend; a path matching here blocks
# without ever reaching the model.
TIER_GATE_PATH_DENYLIST='^(skills/dashboard/|launchd/|scripts/tier-gate/|\.github/workflows/)'

# tg_prefilter <filelist> <line_count>
# Mechanical, model-free gate. <filelist> is newline-separated paths (as
# from `gh pr diff --name-only`); <line_count> is the diff's total changed
# line count (as from `gh pr diff --stat`, or any equivalent count). Exit 0
# and empty stdout on pass; exit 1 and a named reason on stdout on block.
# Injection-immune by construction: no model call happens in this function,
# so there is nothing here for diff CONTENT to inject into — only file
# paths and a line count are inspected, both mechanically derived facts
# about the diff's shape, never text the defendant wrote is read as
# instructions.
tg_prefilter() {
    local filelist="$1" line_count="$2"

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

    if [[ "$file_count" -gt "$TIER_GATE_MAX_FILES" || "$line_count" -gt "$TIER_GATE_MAX_LINES" ]]; then
        printf 'blocked: size cap exceeded files=%s/%s lines=%s/%s\n' \
            "$file_count" "$TIER_GATE_MAX_FILES" "$line_count" "$TIER_GATE_MAX_LINES"
        return 1
    fi

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

    # Well-formedness gate only: a tier-0 artifact with no embedded
    # evals.json is a malformed-artifact error, independent of the judge.
    # The extracted content itself is NEVER passed to the judge (Fix 1) —
    # its presence is all this checks.
    local evals_json; evals_json=$(tg_extract_evals_json "$body")
    if [[ -z "$evals_json" ]]; then
        tg_post_status "$sha" "error" "verdict=error host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=0 verdict=error state=error reason=no_embedded_evals_json\n' "$pr" "$sha"
        return 1
    fi

    # Fix 2: mechanical pre-filter BEFORE any model call. filelist/line
    # count only — never diff content — so this step cannot be influenced
    # by anything the defendant wrote.
    local filelist line_count
    filelist=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr diff "$pr" --name-only 2>/dev/null)
    line_count=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr diff "$pr" --stat 2>/dev/null \
        | grep -oE '[0-9]+ insertion|[0-9]+ deletion' | grep -oE '[0-9]+' | awk '{s+=$1} END {print s+0}')

    local prefilter_out
    prefilter_out=$(tg_prefilter "$filelist" "$line_count")
    if [[ $? -ne 0 ]]; then
        tg_post_status "$sha" "failure" "verdict=illegitimate host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=0 verdict=illegitimate state=failure reason=prefilter_%s\n' \
            "$pr" "$sha" "$(printf '%s' "$prefilter_out" | tr -s ' \n' '_')"
        return 0
    fi

    # Fix 3: capped REAL diff content (not just name-only/--stat metadata).
    # Byte cap mirrors Fix 2's fail-closed posture: over-cap blocks outright
    # rather than truncating and judging a partial diff (a truncated diff
    # is never a valid basis for a permissive read).
    local diff diff_bytes
    diff=$(tg_with_watchdog "$TIER_GATE_WATCHDOG_TIMEOUT" -- gh pr diff "$pr" 2>/dev/null)
    diff_bytes=$(printf '%s' "$diff" | wc -c | tr -d ' ')
    if [[ "$diff_bytes" -gt "$TIER_GATE_MAX_DIFF_BYTES" ]]; then
        tg_post_status "$sha" "failure" "verdict=illegitimate host=$(hostname)"
        printf 'gated: pr=%s sha=%s tier=0 verdict=illegitimate state=failure reason=diff_bytes_%s_over_%s\n' \
            "$pr" "$sha" "$diff_bytes" "$TIER_GATE_MAX_DIFF_BYTES"
        return 0
    fi

    local judge_out judge_rc
    judge_out=$(tg_judge "$tier" "$diff")
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
