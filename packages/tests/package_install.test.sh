#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0
check_cmd() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then printf 'ok   - %s\n' "$label"; else printf 'FAIL - %s\n' "$label"; fails=$((fails+1)); fi; }
check_value() { local label="$1" actual="$2" expected="$3"; if [ "$actual" = "$expected" ]; then printf 'ok   - %s\n' "$label"; else printf 'FAIL - %s\n' "$label"; fails=$((fails+1)); fi; }
for provider in claude codex; do
  p="$ROOT/packages/$provider"
  check_cmd "$provider manifest parses" jq -e . "$p/manifest.json"
  check_cmd "$provider install metadata parses" jq -e . "$p/install.json"
  check_value "$provider manifest names provider" "$(jq -r .provider "$p/manifest.json")" "$provider"
  check_value "$provider install metadata names provider" "$(jq -r .provider "$p/install.json")" "$provider"
  check_value "$provider uses host OAuth" "$(jq -r .credentials "$p/install.json")" host_oauth
  check_cmd "$provider has install command" test "$(jq -r .command "$p/install.json")" != null
done
check_cmd "Claude plugin layout remains at root" test -f "$ROOT/.claude-plugin/plugin.json"
check_cmd "Claude installer remains at root" test -f "$ROOT/install.sh"
check_cmd "Claude installer parses" bash -n "$ROOT/install.sh"
check_cmd "Codex plugin manifest exists" test -f "$ROOT/.codex-plugin/plugin.json"
check_cmd "Codex runtime exists" test -f "$ROOT/codex/scripts/run_graph.py"
check_value "Codex package is independent" "$(jq -r .source_root "$ROOT/packages/codex/manifest.json")" .
[ "$fails" -eq 0 ] && { echo PASS; exit 0; }; echo "FAILED ($fails)"; exit 1
