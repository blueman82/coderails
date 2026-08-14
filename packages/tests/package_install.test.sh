#!/bin/bash
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0

check_cmd() {
  local label="$1"; shift
  if "$@"; then printf 'ok   - %s\n' "$label"
  else printf 'FAIL - %s\n' "$label"; fails=$((fails + 1)); fi
}

check_value() {
  local label="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then printf 'ok   - %s\n' "$label"
  else printf 'FAIL - %s\n' "$label"; fails=$((fails + 1)); fi
}

for provider in claude codex; do
  package="$ROOT/packages/$provider"
  manifest="$package/manifest.json"
  install="$package/install.json"
  check_cmd "$provider manifest parses" jq -e . "$manifest"
  check_cmd "$provider install metadata parses" jq -e . "$install"
  check_value "$provider manifest names provider" "$(jq -r .provider "$manifest")" "$provider"
  check_value "$provider install metadata names provider" "$(jq -r .provider "$install")" "$provider"
  check_value "$provider uses host OAuth" "$(jq -r .credentials "$install")" host_oauth
  check_cmd "$provider has install command" test "$(jq -r .command "$install")" != null
done

# Claude remains the repository root package; this catches accidental moves.
check_cmd "Claude plugin manifest remains at root" test -f "$ROOT/.claude-plugin/plugin.json"
check_value "Claude plugin manifest keeps its name" "$(jq -r .name "$ROOT/.claude-plugin/plugin.json")" coderails
check_cmd "Claude installer remains at root" test -f "$ROOT/install.sh"
check_value "Codex package is independent" "$(jq -r .source_root "$ROOT/packages/codex/manifest.json")" packages/codex

[ "$fails" -eq 0 ] && { echo PASS; exit 0; }
echo "FAILED ($fails)"
exit 1
