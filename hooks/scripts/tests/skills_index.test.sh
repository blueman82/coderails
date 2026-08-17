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
  text.sub!(/(  agentic-loop:\n.*?    codex:\n      path: \.codex\/skills\/agentic-loop\/SKILL\.md\n      status:) active/m, "\\1 planned")
  abort "fixture mutation failed" unless text != File.read(path)
  File.write(path, text)
' "$tmp/index.yaml"
if "$validator" "$tmp/index.yaml" >/dev/null 2>&1; then
    echo "FAIL planned implementation was routable"
    exit 1
fi
cp "$index" "$tmp/wrong-kind.yaml"
ruby -e '
  path = ARGV.fetch(0)
  text = File.read(path)
  text.sub!("path: .codex/skills/agentic-loop/SKILL.md", "path: codex/agents/deploy-safety-reviewer.md")
  abort "fixture mutation failed" unless text != File.read(path)
  File.write(path, text)
' "$tmp/wrong-kind.yaml"
if "$validator" "$tmp/wrong-kind.yaml" >/dev/null 2>&1; then
    echo "FAIL wrong-kind implementation was routable"
    exit 1
fi
cp "$index" "$tmp/bad-graph-policy-mode.yaml"
ruby -e '
  path = ARGV.fetch(0)
  text = File.read(path)
  text.sub!("    mode: parallel-review", "    mode: dual-execution")
  abort "fixture mutation failed" unless text != File.read(path)
  File.write(path, text)
' "$tmp/bad-graph-policy-mode.yaml"
if "$validator" "$tmp/bad-graph-policy-mode.yaml" >/dev/null 2>&1; then
  echo "FAIL graph_policies mode other than parallel-review was accepted"
  exit 1
fi
echo "PASS skills index validation"
