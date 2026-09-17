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

contract_shells=$(awk -F '\t' 'NR > 1 && $1 ~ /\.sh$/ { print $1 }' "$CONTRACTS" | sort)
actual_shells=$(find "$PACKAGE" -type f -name '*.sh' | sed "s#^$PACKAGE/##" | sort)
diff -u <(printf '%s\n' "$contract_shells") <(printf '%s\n' "$actual_shells")

while IFS= read -r python_path; do
  [[ -z "$python_path" || -f "$PACKAGE/$python_path" ]] || {
    printf 'missing migrated Python contract path: %s\n' "$python_path" >&2
    exit 1
  }
done < <(awk -F '\t' 'NR > 1 && $1 ~ /\.py$/ { print $1 }' "$CONTRACTS")
awk -F '\t' 'NR > 1 && (NF != 8 || $3 == "" || $4 == "" || $5 == "" || $6 == "" || $7 == "" || $8 == "") { exit 1 }' "$CONTRACTS"

if "$0" --assert-no-shell >/dev/null 2>&1; then
  printf '%s\n' 'expected shell-retirement negative control to fail' >&2
  exit 1
fi

printf 'ok - frozen Codex shell-retirement roster and contracts\n'
