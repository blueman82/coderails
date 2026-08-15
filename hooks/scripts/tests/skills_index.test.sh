#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
validator="$ROOT/scripts/validate-skills-index.sh"
index="$ROOT/skills/index.yaml"

"$validator" "$index" >/dev/null
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp "$index" "$tmp/index.yaml"
ruby -e '
  path = ARGV.fetch(0)
  text = File.read(path)
  text.sub!(/(  agentic-loop:\n.*?    codex:\n      path: codex\/skills\/catalog\.md\n      status:) active/m, "\\1 planned")
  abort "fixture mutation failed" unless text != File.read(path)
  File.write(path, text)
' "$tmp/index.yaml"
if "$validator" "$tmp/index.yaml" >/dev/null 2>&1; then
  echo "FAIL planned implementation was routable"
  exit 1
fi
echo "PASS skills index validation"
