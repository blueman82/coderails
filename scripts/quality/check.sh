#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
strict=0
changed_only=0
quality_root="$repo_root"
next_is_root=0
for arg in "$@"; do
    [[ "$arg" == "--strict" ]] && strict=1
    [[ "$arg" == "--changed" ]] && changed_only=1
    if ((next_is_root)); then
        quality_root="$arg"
        next_is_root=0
    elif [[ "$arg" == "--root" ]]; then
        next_is_root=1
    fi
done

python3 "$repo_root/scripts/quality/check.py" "$@"

findings=0
shell_files=()
python_files=()

read_python_files() {
    python_files=()
    if ((changed_only)); then
        while IFS= read -r python_file; do
            [[ "$python_file" == *.py && -f "$quality_root/$python_file" ]] || continue
            case "$python_file" in
            skills/agentic-loop/scripts/graph_semantics.py | packages/codex/skills/agentic-loop/scripts/graph_semantics.py) continue ;;
            esac
            python_files+=("$quality_root/$python_file")
        done < <((
            git -C "$quality_root" diff --name-only HEAD
            git -C "$quality_root" diff --cached --name-only
        ) | sort -u)
        return
    fi
    while IFS= read -r python_file; do
        case "$python_file" in
        "$quality_root"/skills/agentic-loop/scripts/graph_semantics.py | "$quality_root"/packages/codex/skills/agentic-loop/scripts/graph_semantics.py) continue ;;
        esac
        python_files+=("$python_file")
    done < <(find "$quality_root" -type f -name '*.py' \
        ! -path '*/assets/*' ! -path '*/dist/*' ! -path '*/fixtures/*' ! -path '*/node_modules/*')
}

run_python_quality() {
    read_python_files
    ((${#python_files[@]} == 0)) && return
    for tool in ruff black pyright mypy; do
        if ! python3 -m "$tool" --version >/dev/null 2>&1; then
            printf 'quality: required Python tool unavailable: %s\n' "$tool" >&2
            findings=1
            return
        fi
    done
    python3 -m ruff check --no-cache --config "$repo_root/pyproject.toml" "${python_files[@]}" || findings=1
    python3 -m black --check --config "$repo_root/pyproject.toml" "${python_files[@]}" || findings=1
    python3 -m pyright --project "$repo_root/pyproject.toml" "${python_files[@]}" || findings=1
    python3 -m mypy --config-file "$repo_root/pyproject.toml" "${python_files[@]}" || findings=1
}

run_python_quality

if ((strict)); then
    graph_source="$quality_root/packages/graph-semantics/graph_semantics.py"
    if [[ -f "$graph_source" ]]; then
        for graph_copy in "$quality_root/skills/agentic-loop/scripts/graph_semantics.py" "$quality_root/packages/codex/skills/agentic-loop/scripts/graph_semantics.py"; do
            cmp -s "$graph_source" "$graph_copy" || {
                printf 'quality: generated graph semantics drift: %s\n' "$graph_copy" >&2
                findings=1
            }
        done
    fi
fi

read_shell_files() {
    shell_files=()
    if ((changed_only)); then
        while IFS= read -r shell_file; do
            case "$shell_file" in
            hooks/*.sh | hooks/*.bash | scripts/*.sh | scripts/*.bash)
                [[ -f "$repo_root/$shell_file" ]] && shell_files+=("$repo_root/$shell_file")
                ;;
            esac
        done < <((
            git diff --name-only HEAD
            git diff --cached --name-only
        ) | sort -u)
    else
        while IFS= read -r shell_file; do
            shell_files+=("$shell_file")
        done < <(find "$quality_root" -type f \( -name '*.sh' -o -name '*.bash' \) -print)
    fi
}

if command -v shellcheck >/dev/null 2>&1; then
    read_shell_files
    if ((${#shell_files[@]} > 0)); then
        shellcheck "${shell_files[@]}" || findings=1
    fi
else
    printf '%s\n' 'quality: shellcheck unavailable; Bash semantic lint is advisory until installed.' >&2
fi

if command -v shfmt >/dev/null 2>&1; then
    read_shell_files
    ((${#shell_files[@]} == 0)) || shfmt -i 4 -d "${shell_files[@]}" || findings=1
else
    printf '%s\n' 'quality: shfmt unavailable; Bash formatting is covered by whitespace checks only.' >&2
fi

dashboard_changed=0
while IFS= read -r changed_file; do
    case "$changed_file" in
    skills/dashboard/*.[jt]s | skills/dashboard/*.[jt]sx) dashboard_changed=1 ;;
    esac
done < <(
    git diff --name-only HEAD
    git diff --cached --name-only
)

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
