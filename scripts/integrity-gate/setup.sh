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

if (( DRY_RUN )); then
  printf 'Would configure the product-neutral integrity gate for %s.\n' "$REPO_SLUG"
  printf 'The owner would be prompted for the machine-user token, then sudo would install the root-owned daemon.\n'
  exit 0
fi

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
