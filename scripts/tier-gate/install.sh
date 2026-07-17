#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  install.sh │ Installs the tier-gate root daemon
#  - Preflight: gh/jq/curl present; credentials file exists with all three
#    keys (machine-user GH_TOKEN + CLAUDE_CODE_OAUTH_TOKEN + MACHINE_USER); machine
#    user resolvable as a repo collaborator; ruleset visibility (honest MODE).
#  - Renders com.coderails.tier-gate.plist.template with real paths.
#  - Prints a repo-vs-installed diff for the runner + judge prompt and refuses
#    to promote without confirmation — per spec decision 3, the live runner +
#    judge prompt are root-owned installed copies; repo copies are source
#    only, so a PR that tampers with the judge prompt must be SHOWN to the
#    owner before it is ever deployed, never silently promoted.
#  - sudo-installs the plist + root-owned 0600 credentials + the runner and
#    judge prompt themselves under the same root-owned install root (so the
#    daemon's default TIER_GATE_JUDGE_PROMPT_PATH — a sibling of its own
#    BASH_SOURCE — resolves to the installed copy, never the repo's).
#
#  Testable without root: preflight predicates, plist rendering, and the
#  diff-before-promote computation are pure functions with no side effects,
#  sourceable and callable directly (see tier_gate_install.test.sh). Every
#  side effect requiring root or an interactive confirmation — sudo install,
#  copying into /etc, launchctl bootstrap — lives behind the
#  `[[ "${BASH_SOURCE[0]}" == "${0}" ]]` main-guard below and is never
#  exercised by the tests.
#═══════════════════════════════════════════════════════════════════════════════
set -u

TGI_INSTALL_ROOT="${TGI_INSTALL_ROOT:-/etc/coderails-tier-gate}"
TGI_CREDS_FILENAME="credentials"
TGI_PLIST_DEST="${TGI_PLIST_DEST:-/Library/LaunchDaemons/com.coderails.tier-gate.plist}"

# ─── Preflight: tool presence ─────────────────────────────────────────────────

# tgi_check_tools
# Echoes nothing on success (rc 0). On failure, echoes ONE named, actionable
# line per missing tool to stdout and returns 1 — never a bare exit 1.
tgi_check_tools() {
    local missing=0 tool
    for tool in gh jq curl; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            printf 'preflight: missing required tool "%s" — install it (e.g. brew install %s) and re-run.\n' "$tool" "$tool"
            missing=1
        fi
    done
    [[ "$missing" -eq 0 ]]
}

# ─── Preflight: credentials file ──────────────────────────────────────────────

# tgi_check_credentials <path>
# Verifies <path> exists and contains all THREE required keys: GH_TOKEN (the
# machine-user identity's curl/gh calls), CLAUDE_CODE_OAUTH_TOKEN (the judge's
# subscription auth — the owner's Claude subscription, never a metered key), and
# MACHINE_USER (the login tg_post_status's live GET /user identity check
# must match before it will ever post — see tier-gate-runner.sh's
# tg_read_machine_user). MACHINE_USER lives here, in the same root-owned
# file, rather than as a plist env var, because the daemon's plist only ever
# passes TIER_GATE_CREDS (a path) — nothing else propagates into the
# installed launchd job. Named, actionable failure per missing piece; rc 0
# only when all three are present with non-empty values.
tgi_check_credentials() {
    local path="$1"
    if [[ ! -f "$path" ]]; then
        printf 'preflight: credentials file not found at %s — create it (KEY=value lines) with GH_TOKEN, MACHINE_USER, and CLAUDE_CODE_OAUTH_TOKEN before installing.\n' "$path"
        return 1
    fi
    local ok=1 key
    for key in GH_TOKEN MACHINE_USER CLAUDE_CODE_OAUTH_TOKEN; do
        local val
        val=$(grep -E "^${key}=" "$path" 2>/dev/null | head -1 | cut -d= -f2-)
        if [[ -z "$val" ]]; then
            printf 'preflight: credentials file %s is missing a non-empty %s= line.\n' "$path" "$key"
            ok=0
        fi
    done
    [[ "$ok" -eq 1 ]]
}

# ─── Preflight: machine user is a repo collaborator ───────────────────────────

# tgi_check_machine_user_collaborator <login> [gh_bin]
# Verifies <login> resolves as a collaborator on the current repo via `gh api
# repos/{owner}/{repo}/collaborators/<login>` (204 = is a collaborator, 404 =
# is not). [gh_bin] defaults to "gh" — tests override with a stub. Named
# failure on: empty login, gh call failure, or a non-collaborator login.
tgi_check_machine_user_collaborator() {
    local login="$1" gh_bin="${2:-gh}"
    if [[ -z "$login" ]]; then
        printf 'preflight: no machine-user login provided — set TGI_MACHINE_USER (or pass one) to the tier-review machine-user GitHub login.\n'
        return 1
    fi
    if ! "$gh_bin" api "repos/{owner}/{repo}/collaborators/${login}" >/dev/null 2>&1; then
        printf 'preflight: machine user "%s" is not resolvable as a collaborator on this repo — invite it first, then re-run.\n' "$login"
        return 1
    fi
}

# ─── Plist render ──────────────────────────────────────────────────────────────

# tgi_render_plist <template_path> <runner_path> <creds_path>
# Echoes the rendered plist content: substitutes __TIER_GATE_RUNNER_PATH__ and
# __TIER_GATE_CREDS_PATH__ with the given absolute paths. Uses awk (not sed)
# so a path containing a slash never collides with sed's delimiter.
tgi_render_plist() {
    local template_path="$1" runner_path="$2" creds_path="$3"
    awk -v runner="$runner_path" -v creds="$creds_path" '
        { line = $0
          gsub(/__TIER_GATE_RUNNER_PATH__/, runner, line)
          gsub(/__TIER_GATE_CREDS_PATH__/, creds, line)
          print line
        }
    ' "$template_path"
}

# ─── Preflight: ruleset visibility (honest MODE line) ────────────────────────

# tgi_classify_mode <rules_json>
# Classifies enforcement mode from the response body of
# `gh api repos/{owner}/{repo}/rules/branches/main` (works on plain read
# scope, no admin permission required). A non-empty JSON array means a
# ruleset protects main -> the merge gate is server-enforced on top of the
# unforgeable verdict. An empty array, or any response this can't parse as a
# JSON array (free-plan private repos return `[]`; a malformed/empty body is
# treated the same way), means no ruleset exists -> the server-side
# enforcement leg is absent and the merge gate is local-only and bypassable.
# Fails closed toward the honest under-claim: any doubt classifies as audit,
# never enforced — this is a WARN line, not a refusal, so getting it wrong in
# the pessimistic direction costs nothing but getting it wrong optimistically
# would tell an adopter they're protected when they are not.
tgi_classify_mode() {
    local rules_json="$1"
    local count
    count=$(printf '%s' "$rules_json" | jq 'length' 2>/dev/null)
    if [[ "$count" =~ ^[0-9]+$ ]] && [[ "$count" -gt 0 ]]; then
        printf 'MODE: enforced'
    else
        printf 'MODE: audit (server leg absent) — verdict unforgeable, merge gate local-only and bypassable'
    fi
}

# ─── Repo-vs-installed diff, printed BEFORE promote ───────────────────────────

# tgi_diff_before_promote <repo_path> <installed_path> <label>
# Prints a labelled delta between <repo_path> (source) and <installed_path>
# (the currently-live root-owned copy, if any) to stdout. Returns 0 when
# identical (or no installed copy exists yet — nothing to tamper with, still
# reported as "new install"), 1 when they differ (caller must gate promotion
# on explicit confirmation). Never writes anything itself — pure diff/report.
tgi_diff_before_promote() {
    local repo_path="$1" installed_path="$2" label="$3"
    if [[ ! -f "$installed_path" ]]; then
        printf '%s: no installed copy yet at %s — this is a first install.\n' "$label" "$installed_path"
        return 0
    fi
    if diff -q "$repo_path" "$installed_path" >/dev/null 2>&1; then
        printf '%s: repo copy matches installed copy — no change.\n' "$label"
        return 0
    fi
    printf '%s: repo copy DIFFERS from installed copy at %s:\n' "$label" "$installed_path"
    diff -u "$installed_path" "$repo_path" 2>&1
    return 1
}

# ─── Entry point (root/sudo/interactive side effects — never unit-tested) ─────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

    echo "== tier-gate install: preflight =="
    preflight_failed=0
    tgi_check_tools || preflight_failed=1
    tgi_check_credentials "${TGI_CREDS_SRC:-$TGI_INSTALL_ROOT/$TGI_CREDS_FILENAME}" || preflight_failed=1
    tgi_check_machine_user_collaborator "${TGI_MACHINE_USER:-}" || preflight_failed=1
    if [[ "$preflight_failed" -eq 1 ]]; then
        echo "preflight FAILED — resolve the issues above and re-run." >&2
        exit 1
    fi
    echo "preflight OK"

    echo "== tier-gate install: ruleset visibility =="
    rules_json=$(gh api "repos/{owner}/{repo}/rules/branches/main" 2>/dev/null || printf '')
    tgi_classify_mode "$rules_json"
    echo
    echo "(WARN only — install proceeds either way; this states which mode the merge gate runs in.)"

    echo "== tier-gate install: render plist =="
    RENDERED_PLIST=$(tgi_render_plist \
        "$SCRIPT_DIR/com.coderails.tier-gate.plist.template" \
        "$TGI_INSTALL_ROOT/tier-gate-runner.sh" \
        "$TGI_INSTALL_ROOT/$TGI_CREDS_FILENAME")

    echo "== tier-gate install: repo-vs-installed diff (BEFORE promote) =="
    diff_clean=1
    tgi_diff_before_promote "$SCRIPT_DIR/tier-gate-runner.sh" "$TGI_INSTALL_ROOT/tier-gate-runner.sh" "runner" || diff_clean=0
    tgi_diff_before_promote "$SCRIPT_DIR/judge-prompt.md" "$TGI_INSTALL_ROOT/judge-prompt.md" "judge-prompt" || diff_clean=0

    if [[ "$diff_clean" -eq 0 ]]; then
        printf '\nThe installed copy differs from the repo copy shown above.\n'
        printf 'Promote the repo copy to the root-owned install? [y/N] '
        read -r answer || answer="n"
        answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')
        if [[ "$answer" != "y" ]]; then
            echo "Aborted — installed copy left unchanged." >&2
            exit 1
        fi
    fi

    echo "== tier-gate install: sudo install =="
    sudo mkdir -p "$TGI_INSTALL_ROOT"
    sudo install -m 0755 "$SCRIPT_DIR/tier-gate-runner.sh" "$TGI_INSTALL_ROOT/tier-gate-runner.sh"
    sudo install -m 0644 "$SCRIPT_DIR/judge-prompt.md" "$TGI_INSTALL_ROOT/judge-prompt.md"
    sudo install -m 0600 "${TGI_CREDS_SRC:-$TGI_INSTALL_ROOT/$TGI_CREDS_FILENAME}" "$TGI_INSTALL_ROOT/$TGI_CREDS_FILENAME"
    printf '%s' "$RENDERED_PLIST" | sudo tee "$TGI_PLIST_DEST" >/dev/null
    sudo chown root:wheel "$TGI_INSTALL_ROOT/$TGI_CREDS_FILENAME"

    echo "== tier-gate install: launchd =="
    sudo launchctl bootout "system/com.coderails.tier-gate" 2>/dev/null || true
    sudo launchctl bootstrap system "$TGI_PLIST_DEST"

    echo "INSTALL COMPLETE — daemon: com.coderails.tier-gate"
fi
