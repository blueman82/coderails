#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
validator="$ROOT/scripts/validate-skills-index.sh"
index="$ROOT/skills/index.yaml"

"$validator" "$index" >/dev/null
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp "$index" "$tmp/index.yaml"
sed -i '' 's/codex: planned/codex: active/g' "$tmp/index.yaml"
if "$validator" "$tmp/index.yaml" >/dev/null 2>&1; then
  echo "FAIL planned implementation was routable"
  exit 1
fi
echo "PASS skills index validation"
