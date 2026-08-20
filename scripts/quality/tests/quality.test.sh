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

legacy_loc="$fixture/legacy-loc/packages/codex/scripts"
mkdir -p "$legacy_loc"
printf ':\n%.0s' {1..512} >"$legacy_loc/merge.sh"
python3 "$checker" --strict --root "$fixture/legacy-loc" >/dev/null
printf ':\n' >>"$legacy_loc/merge.sh"
if output="$(python3 "$checker" --strict --root "$fixture/legacy-loc" 2>&1)"; then
    echo 'quality.test: legacy LOC growth unexpectedly passed' >&2
    exit 1
elif [[ "$output" != *"513 lines (max 512)"* ]]; then
    echo 'quality.test: legacy LOC growth reported the wrong ceiling' >&2
    exit 1
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

legacy_function="$fixture/legacy-function/packages/codex/scripts"
mkdir -p "$legacy_function"
{
    printf 'push::main() {\n'
    printf '  :\n%.0s' {1..118}
    printf '}\n'
} >"$legacy_function/push.sh"
python3 "$checker" --strict --root "$fixture/legacy-function" >/dev/null
{
    printf 'push::main() {\n'
    printf '  :\n%.0s' {1..119}
    printf '}\n'
} >"$legacy_function/push.sh"
if output="$(python3 "$checker" --strict --root "$fixture/legacy-function" 2>&1)"; then
    echo 'quality.test: legacy function growth unexpectedly passed' >&2
    exit 1
elif [[ "$output" != *"function push::main is 121 lines (max 120)"* ]]; then
    echo 'quality.test: legacy function growth reported the wrong ceiling' >&2
    exit 1
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

changed_only_repo="$fixture/changed-only"
mkdir -p "$changed_only_repo/scripts/quality" "$changed_only_repo/docs"
cp "$repo_root/scripts/quality/check.sh" "$checker" "$changed_only_repo/scripts/quality/"
printf 'baseline\n' >"$changed_only_repo/docs/note.md"
git -C "$changed_only_repo" init -q
git -C "$changed_only_repo" config user.email 'quality.test@example.invalid'
git -C "$changed_only_repo" config user.name 'Quality Test'
git -C "$changed_only_repo" add .
git -C "$changed_only_repo" commit -qm baseline
printf 'changed\n' >>"$changed_only_repo/docs/note.md"
if ! (cd "$changed_only_repo" && /bin/bash scripts/quality/check.sh --strict --changed >/dev/null); then
    echo 'quality.test: changed-only non-shell scan unexpectedly failed' >&2
    exit 1
fi

echo 'quality.test: PASS'
