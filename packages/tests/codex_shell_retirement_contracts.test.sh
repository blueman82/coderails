#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PACKAGE="$ROOT/packages/codex"
CONTRACTS="$ROOT/packages/tests/codex_shell_retirement_contracts.tsv"

assert_no_shell() {
  local paths
  paths=$(find "$PACKAGE" -type f -name '*.sh' | sort)
  if [[ -n "$paths" ]]; then
    printf '%s\n' "$paths" >&2
    return 1
  fi
}

if [[ "${1:-}" == "--assert-no-shell" ]]; then
  assert_no_shell
  exit
fi

[[ "$(tail -n +2 "$CONTRACTS" | cut -f1 | sort | wc -l | tr -d ' ')" -eq 36 ]]
[[ "$(find "$PACKAGE" -type f -name '*.sh' | wc -l | tr -d ' ')" -eq 36 ]]
diff -u <(tail -n +2 "$CONTRACTS" | cut -f1 | sort) <(find "$PACKAGE" -type f -name '*.sh' | sed "s#^$PACKAGE/##" | sort)
awk -F '\t' 'NR > 1 && (NF != 8 || $3 == "" || $4 == "" || $5 == "" || $6 == "" || $7 == "" || $8 == "") { exit 1 }' "$CONTRACTS"

if "$0" --assert-no-shell >/dev/null 2>&1; then
  printf '%s\n' 'expected shell-retirement negative control to fail' >&2
  exit 1
fi

printf 'ok - frozen Codex shell-retirement roster and contracts\n'
