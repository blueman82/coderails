#!/usr/bin/env bash
# Owner-run, product-neutral setup for the optional integrity attestor.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALLER="$SCRIPT_DIR/install.sh"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

die() { printf 'setup failed: %s\n' "$1" >&2; exit 1; }
[[ -x "$INSTALLER" ]] || die "missing executable $INSTALLER"
for tool in gh jq curl git; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is required"
done

REPO_SLUG=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) \
  || die "run this from a GitHub repository with gh authenticated"

RULESET_NAME="coderails-integrity-review"

ruleset_payload() {
  jq -n --arg name "$RULESET_NAME" '{name:$name,target:"branch",enforcement:"active",bypass_actors:[],conditions:{ref_name:{include:["refs/heads/main"],exclude:[]}},rules:[{type:"pull_request",parameters:{required_approving_review_count:0,dismiss_stale_reviews_on_push:false,require_code_owner_review:false,require_last_push_approval:false,required_review_thread_resolution:false}},{type:"required_status_checks",parameters:{strict_required_status_checks_policy:false,do_not_enforce_on_create:false,required_status_checks:[{context:"integrity-review",integration_id:-1}]}}]}'
}

ruleset_matches() {
  jq -e --arg name "$RULESET_NAME" '.name == $name and .target == "branch" and .enforcement == "active" and ((.bypass_actors // []) | length) == 0 and ((.conditions.ref_name.include // []) | index("refs/heads/main")) != null and ([.rules[] | select(.type == "pull_request")] | length) == 1 and ([.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[] | select(.context == "integrity-review")] | length) == 1' >/dev/null
}

configure_ruleset() {
  local rulesets existing payload answer
  rulesets=$(gh api "repos/$REPO_SLUG/rulesets?per_page=100" 2>/dev/null) || die "could not read repository rulesets; owner gh auth needs repository administration access"
  existing=$(printf '%s' "$rulesets" | jq -c --arg name "$RULESET_NAME" '[.[] | select(.name == $name)] | .[0] // empty')
  if [[ -n "$existing" ]]; then
    if ruleset_matches <<<"$existing"; then
      printf 'GitHub ruleset %s already exists and matches the required policy.\n' "$RULESET_NAME"
      return 0
    fi
    die "ruleset $RULESET_NAME exists but differs; refusing to overwrite it"
  fi
  payload=$(ruleset_payload)
  printf '\nProposed GitHub ruleset for main:\n%s\n' "$payload" | jq '{name,enforcement,conditions,rules}'
  read -r -p 'Create this ruleset using the owner gh account? [y/N] ' answer
  [[ "$answer" =~ ^[Yy]$ ]] || die 'ruleset creation cancelled; validator installation not started'
  gh api "repos/$REPO_SLUG/rulesets" --method POST --input - <<<"$payload" >/dev/null || die 'GitHub rejected ruleset creation; check owner administration permission and repository plan'
  rulesets=$(gh api "repos/$REPO_SLUG/rulesets?per_page=100" 2>/dev/null) || die 'ruleset was created but could not be re-read'
  existing=$(printf '%s' "$rulesets" | jq -c --arg name "$RULESET_NAME" '[.[] | select(.name == $name)] | .[0] // empty')
  ruleset_matches <<<"$existing" || die 'created ruleset failed verification'
  printf 'GitHub ruleset created and verified: %s\n' "$RULESET_NAME"
}

if (( DRY_RUN )); then
  printf 'Would configure the product-neutral integrity gate for %s.\n' "$REPO_SLUG"
  printf 'Would offer to create/verify the GitHub ruleset %s on main.\n' "$RULESET_NAME"
  printf 'The owner would be prompted for the machine-user token, then sudo would install the root-owned daemon.\n'
  exit 0
fi

configure_ruleset

printf '\nOptional integrity gate for %s\n' "$REPO_SLUG"
printf 'This protects merges for Claude, Codex, or any other client.\n'
printf 'Use a dedicated GitHub machine-user login with status-write access only.\n\n'
read -r -p 'Machine-user GitHub login: ' machine_user
[[ "$machine_user" =~ ^[A-Za-z0-9-]+$ ]] || die 'invalid GitHub login'
read -r -s -p 'Machine-user token: ' gh_token
printf '\n'
[[ -n "$gh_token" ]] || die 'token cannot be empty'

token_login=$(curl -fsS -H "Authorization: Bearer $gh_token" \
  -H 'Accept: application/vnd.github+json' https://api.github.com/user |
  jq -r '.login // empty') || die 'token could not authenticate with GitHub'
[[ "$token_login" == "$machine_user" ]] || die "token belongs to '$token_login', not '$machine_user'"

creds=$(mktemp "${TMPDIR:-/tmp}/coderails-integrity-credentials.XXXXXX")
cleanup() { rm -f "$creds"; }
trap cleanup EXIT
umask 077
printf 'GH_TOKEN=%s\nMACHINE_USER=%s\n' "$gh_token" "$machine_user" > "$creds"
unset gh_token

printf '\nThe next command installs a root-owned launchd daemon and protected credentials.\n'
read -r -p 'Press Enter to continue; sudo may ask for your password (Ctrl-C cancels): ' _
sudo -v
TGI_CREDS_SRC="$creds" bash "$INSTALLER"

printf '\nInstalled the independent integrity gate for %s.\n' "$REPO_SLUG"
printf 'GitHub must still require integrity-review on main for server-side enforcement.\n'
