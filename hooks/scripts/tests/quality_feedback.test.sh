#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
hook="$repo_root/hooks/scripts/quality_feedback.sh"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/coderails-quality-feedback.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT

[[ -z "$(printf '{}' | "$hook")" ]]
printf 'x \n' >"$fixture/bad.py"
output="$(printf '{\"tool_input\":{\"file_path\":\"%s\"}}' "$fixture/bad.py" | "$hook")"
[[ "$output" == *'warn-only'* ]]
[[ "$output" == *'trailing whitespace'* ]]

echo 'quality_feedback.test: PASS'
