#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
checker="$repo_root/scripts/quality/check.py"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/coderails-quality.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT

printf 'short = 1\n' >"$fixture/good.py"
python3 "$checker" --strict --root "$fixture" >/dev/null

printf 'x \n' >"$fixture/trailing.py"
if python3 "$checker" --strict --root "$fixture" >/dev/null 2>&1; then
    echo 'quality.test: formatting negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

if python3 "$checker" --root "$fixture" >/dev/null 2>&1; then
    :
else
    echo 'quality.test: warn-only mode unexpectedly blocked' >&2
    exit 1
fi

printf '{\n' >"$fixture/bad.json"
if python3 "$checker" --strict --root "$fixture" >/dev/null 2>&1; then
    echo 'quality.test: JSON negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

printf 'x\n%.0s' {1..5} >"$fixture/long.py"
if python3 "$checker" --strict --root "$fixture" --max-loc 3 >/dev/null 2>&1; then
    echo 'quality.test: LOC negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

python3 - "$fixture/long.py" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_text("def too_long():\n" + "    pass\n" * 5, encoding="utf-8")
PY
if python3 "$checker" --strict --root "$fixture" --max-function-lines 3 >/dev/null 2>&1; then
    echo 'quality.test: function-size negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

{
    printf 'too_long() {\n'
    printf '  :\n%.0s' {1..5}
    printf '}\n'
} >"$fixture/long.sh"
if python3 "$checker" --strict --root "$fixture" --max-function-lines 3 >/dev/null 2>&1; then
    echo 'quality.test: Bash function-size negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

mkdir -p "$fixture/prose"
printf '# return value = 1\n' >"$fixture/prose/prose.py"
python3 "$checker" --strict --root "$fixture/prose" >/dev/null

printf '# def removed():\n' >"$fixture/commented.py"
if python3 "$checker" --strict --root "$fixture" >/dev/null 2>&1; then
    echo 'quality.test: commented-code negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

printf 'return value = 1\n' >"$fixture/bad.py"
if python3 "$checker" --strict --root "$fixture" >/dev/null 2>&1; then
    echo 'quality.test: syntax negative control unexpectedly passed' >&2
    exit 1
else
    :
fi

echo 'quality.test: PASS'
