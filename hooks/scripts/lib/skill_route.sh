#!/bin/bash
# skill_route.sh — routing resolution for skills/index.yaml: given a skill_id
# and a provider, resolve the provider-native path or fail closed.
#
# Usage: skill_route.sh <path-to-index.yaml> <skill_id> <claude|codex>
# On success: prints the resolved path to stdout, exits 0.
# On failure: prints "NO_PROVIDER_MAPPING: <reason>" to stdout, exits 1.
#   Failure cases (per spec.md's routing contract): skill_id not found in the
#   index; the requested provider has no key at all; the requested provider's
#   status is anything other than "active" (i.e. "planned", or an
#   unrecognised value); the requested provider's path is null/empty even
#   when active. Never silently falls back to another provider and never
#   dispatches on a missing/ambiguous read.
#
# READ-ONLY: never writes index.yaml or any other file.
#
# Not a general YAML parser — skills/index.yaml is machine-generated with a
# fixed, known indentation shape (2-space skill_id, 4-space fields, 6-space
# claude/codex sub-fields; no anchors, no multi-line scalars). This extracts
# exactly the four fields routing needs (claude.path, claude.status,
# codex.path, codex.status) from one matching skill_id block. A general YAML
# parser would be over-build for a file this script itself does not own the
# schema of (skills/index.yaml's schema is spec.md's, not this script's).
set -u

path="${1:-}"
skill_id="${2:-}"
provider="${3:-}"

fail() {
  echo "NO_PROVIDER_MAPPING: $1"
  exit 1
}

[ -z "$path" ] && fail "missing index.yaml path argument"
[ -z "$skill_id" ] && fail "missing skill_id argument"
case "$provider" in
  claude|codex) ;;
  *) fail "provider must be 'claude' or 'codex', got '$provider'" ;;
esac
[ -f "$path" ] || fail "index.yaml not found at $path"

# Extract the block for this skill_id: from its "  <skill_id>:" line up to
# (not including) the next 2-space-indented "key:" line or EOF.
block=$(awk -v id="$skill_id" '
  BEGIN { in_block = 0 }
  /^  [A-Za-z0-9._-]+:[ \t]*$/ {
    if (in_block) { exit }
    key = $0
    sub(/^  /, "", key)
    sub(/:[ \t]*$/, "", key)
    if (key == id) { in_block = 1; next }
    next
  }
  in_block { print }
' "$path")

[ -z "$block" ] && fail "skill_id '$skill_id' not found in $path"

# Within the block, extract the requested provider's sub-block (6-space
# path/status lines directly under the 4-space "claude:"/"codex:" line).
provider_block=$(printf '%s\n' "$block" | awk -v prov="$provider" '
  BEGIN { in_prov = 0 }
  /^    [a-z_]+:[ \t]*$/ {
    if (in_prov) { exit }
    key = $0
    sub(/^    /, "", key)
    sub(/:[ \t]*$/, "", key)
    if (key == prov) { in_prov = 1; next }
    next
  }
  /^    [a-z_]+:/ { if (in_prov) { exit } }
  in_prov { print }
')

[ -z "$provider_block" ] && fail "skill_id '$skill_id' has no '$provider:' key"

status=$(printf '%s\n' "$provider_block" | awk -F': ' '/^      status:/ { print $2; exit }')
resolved_path=$(printf '%s\n' "$provider_block" | awk -F': ' '/^      path:/ { print $2; exit }')

[ "$status" = "active" ] || fail "skill_id '$skill_id' provider '$provider' status is '${status:-<missing>}', not active"
[ -z "$resolved_path" ] && fail "skill_id '$skill_id' provider '$provider' is active but has an empty/null path"
[ "$resolved_path" = "null" ] && fail "skill_id '$skill_id' provider '$provider' is active but path is null"

printf '%s\n' "$resolved_path"
exit 0
