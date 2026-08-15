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
check_value "Codex plugin name" "$(jq -r .name "$ROOT/.codex-plugin/plugin.json")" coderails-codex
for path in skills commands hooks; do
  check_value "Codex $path path" "$(jq -r ".$path" "$ROOT/.codex-plugin/plugin.json")" "./codex/$path/"
done
check_cmd "Codex runtime exists" test -f "$ROOT/codex/scripts/run_graph.py"
check_value "Codex package is independent" "$(jq -r .source_root "$ROOT/packages/codex/manifest.json")" .
if command -v codex >/dev/null 2>&1; then
  codex_test_home=$(mktemp -d)
  mkdir -p "$codex_test_home/.codex"
  if HOME="$codex_test_home" CODEX_HOME="$codex_test_home/.codex" \
    codex plugin marketplace add "$ROOT" >/dev/null 2>&1 && \
    HOME="$codex_test_home" CODEX_HOME="$codex_test_home/.codex" \
    codex plugin add coderails-codex@coderails >/dev/null 2>&1; then
    echo "ok   - Codex CLI marketplace install"
  else
    echo "FAIL - Codex CLI marketplace install"
    fails=$((fails+1))
  fi
else
  echo "skip - Codex CLI marketplace install (codex unavailable)"
fi
[ "$fails" -eq 0 ] && { echo PASS; exit 0; }; echo "FAILED ($fails)"; exit 1
