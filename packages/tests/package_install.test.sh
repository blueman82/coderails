#!/bin/bash
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0

check() {
  local label="$1" condition="$2"
  if [ "$condition" = true ]; then printf 'ok   - %s\n' "$label"
  else printf 'FAIL - %s\n' "$label"; fails=$((fails + 1)); fi
}

for provider in claude codex; do
  package="$ROOT/packages/$provider"
  manifest="$package/manifest.json"
  install="$package/install.json"
  check "$provider manifest parses" "$(jq -e . "$manifest" >/dev/null 2>&1; echo $?)" = 0
  check "$provider install metadata parses" "$(jq -e . "$install" >/dev/null 2>&1; echo $?)" = 0
  check "$provider manifest names provider" "$(jq -r .provider "$manifest")" = "$provider"
  check "$provider install metadata names provider" "$(jq -r .provider "$install")" = "$provider"
  check "$provider uses host OAuth" "$(jq -r .credentials "$install")" = host_oauth
  check "$provider has install command" "$(jq -r .command "$install")" != null
done

# Claude remains the repository root package; this catches accidental moves.
check "Claude plugin manifest remains at root" "[ -f "$ROOT/.claude-plugin/plugin.json" ] && [ "$(jq -r .name "$ROOT/.claude-plugin/plugin.json")" = coderails ]"
check "Claude installer remains at root" "[ -x "$ROOT/install.sh" ]"
check "Codex package is independent" "[ "$(jq -r .source_root "$ROOT/packages/codex/manifest.json")" = packages/codex ]"

[ "$fails" -eq 0 ] && { echo PASS; exit 0; }
echo "FAILED ($fails)"
exit 1
