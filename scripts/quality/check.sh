#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
strict=0
for arg in "$@"; do
    [[ "$arg" == "--strict" ]] && strict=1
done

python3 "$repo_root/scripts/quality/check.py" "$@"

findings=0

if command -v shellcheck >/dev/null 2>&1; then
    mapfile -t shell_files < <(find "$repo_root/hooks" "$repo_root/scripts" -type f \( -name '*.sh' -o -name '*.bash' \) -print)
    if ((${#shell_files[@]} > 0)); then
        shellcheck "${shell_files[@]}" || findings=1
    fi
else
    printf '%s\n' 'quality: shellcheck unavailable; Bash semantic lint is advisory until installed.' >&2
fi

if command -v shfmt >/dev/null 2>&1; then
    mapfile -t shell_files < <(find "$repo_root/hooks" "$repo_root/scripts" -type f \( -name '*.sh' -o -name '*.bash' \) -print)
    ((${#shell_files[@]} == 0)) || shfmt -d "${shell_files[@]}" || findings=1
else
    printf '%s\n' 'quality: shfmt unavailable; Bash formatting is covered by whitespace checks only.' >&2
fi

dashboard_changed=0
while IFS= read -r changed_file; do
    case "$changed_file" in
        skills/dashboard/*.[jt]s|skills/dashboard/*.[jt]sx) dashboard_changed=1 ;;
    esac
done < <(git diff --name-only HEAD; git diff --cached --name-only)

if ((dashboard_changed)); then
    for package_dir in app lib runner obsidian; do
        package_root="$repo_root/skills/dashboard/$package_dir"
        [[ -d "$package_root/node_modules" ]] || {
            printf 'quality: dashboard/%s dependencies are missing; install from its lockfile before strict TypeScript checks.\n' "$package_dir" >&2
            ((strict)) && findings=1
            continue
        }
        if [[ -f "$package_root/package.json" ]]; then
            npm --prefix "$package_root" run --if-present lint || findings=1
            npm --prefix "$package_root" run --if-present typecheck || findings=1
        fi
    done
fi

if ((strict && findings)); then
    printf '%s\n' 'quality: optional tool findings failed strict mode.' >&2
    exit 1
fi

if ((strict)); then
    printf '%s\n' 'quality: strict checks passed.'
else
    printf '%s\n' 'quality: warn-only checks completed.'
fi
