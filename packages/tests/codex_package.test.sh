#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0
check() { if "$@" >/dev/null 2>&1; then echo "ok - $1"; else echo "FAIL - $1"; fails=$((fails+1)); fi; }
check jq -e . "$ROOT/packages/codex/manifest.json"
check jq -e . "$ROOT/packages/codex/install.json"
check python3 -m py_compile "$ROOT/packages/codex/scripts/dispatch.py" "$ROOT/packages/codex/scripts/run_graph.py" "$ROOT/packages/codex/scripts/complete.py" "$ROOT/packages/codex/scripts/teardown.py" "$ROOT/packages/codex/hooks/lifecycle.py"
if python3 "$ROOT/packages/codex/tests/independence.py"; then echo "ok - copied package is independent"; else fails=$((fails+1)); fi
[ "$fails" -eq 0 ] && echo PASS && exit 0
echo "FAILED ($fails)"
exit 1
