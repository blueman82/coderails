#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' EXIT

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
input="$(cat 2>/dev/null || true)"
file_path="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
tool_input = data.get("tool_input") or {}
tool_response = data.get("tool_response") or {}
print(tool_input.get("file_path") or tool_response.get("filePath") or "")
' 2>/dev/null || true)"

[[ -n "$file_path" && -f "$file_path" ]] || exit 0
case "$file_path" in
    *.bash|*.cfg|*.js|*.json|*.jsx|*.md|*.py|*.sh|*.toml|*.ts|*.tsx|*.yaml|*.yml) ;;
    *) exit 0 ;;
esac

if output="$(python3 "$repo_root/scripts/quality/check.py" --root "$repo_root" --paths "$file_path" 2>&1)"; then
    [[ "$output" == *"0 finding(s)"* ]] || printf '%s\n' "$output"
else
    printf '%s\n' "coderails quality feedback (warn-only): $output"
fi
