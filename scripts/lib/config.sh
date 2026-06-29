#!/usr/bin/env bash
#═══════════════════════════════════════════════════════════════════════════════
#  config.sh │ shared workflow.config.yaml resolution
#═══════════════════════════════════════════════════════════════════════════════
# Single source of truth for locating a project's workflow.config.yaml.
#
# Sourced by:
#   - commands/{prep,push,workflow}.md frontmatter `Config:` substitution
#     (via `${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.sh` — ${CLAUDE_PLUGIN_ROOT}
#     is string-substituted by Claude Code in command frontmatter, so the path
#     is always the real plugin dir; see changelog "Fixed ${CLAUDE_PLUGIN_ROOT}
#     not being substituted in plugin allowed-tools frontmatter")
#   - scripts/merge.sh                       (via `$(dirname "$0")/lib/config.sh`)
#   - hooks/scripts/enforce_pr_workflow.sh   (via `$(dirname "$0")/../../scripts/lib/config.sh`)
#
# Resolution walks up from a start directory to the git root; the first
# .claude/workflow.config.yaml found wins. Layout-agnostic: standalone repos,
# classic projects/<name>/ monorepos, and arbitrary layouts (apps/web,
# services/api, …) all resolve from any subdir. Nearest wins — replacement, not
# inheritance/merge. The hook's opt-in detection MUST use this same resolver so
# the merge gate's "is enforcement active?" answer agrees with the commands.
#
# Guard-script compatible: no `set -euo pipefail` (sourced into scripts that
# intentionally don't); functions always return 0 and signal "not found" via
# empty output, not non-zero exit.

# coderails::config_path [start_dir]
#   Echo the first .claude/workflow.config.yaml found walking from start_dir
#   (default: $PWD) up to its git root; echo nothing if none / not in a repo.
coderails::config_path() {
  local start="${1:-$PWD}"
  local git_root d
  git_root=$(git -C "$start" rev-parse --show-toplevel 2>/dev/null)
  [[ -z "$git_root" ]] && return 0
  # Canonicalise start so it shares git_root's namespace. `git rev-parse` returns a
  # symlink-resolved path (macOS /tmp -> /private/tmp); without this, start stays in
  # the unresolved namespace, `d == git_root` never matches, and the walk-up runs
  # past the root to "/" — where `dirname /` == "/" loops forever. (bug: PR #67/#71)
  start=$(cd "$start" 2>/dev/null && pwd -P) || return 0
  d="$start"
  while :; do
    [[ -f "$d/.claude/workflow.config.yaml" ]] && { printf '%s\n' "$d/.claude/workflow.config.yaml"; return 0; }
    # Hard floor on "/" as well as git_root: even if a namespace mismatch slips
    # through, the loop can never spin past the filesystem root.
    [[ "$d" == "$git_root" || "$d" == "/" ]] && break
    d=$(dirname "$d")
  done
  return 0
}

# coderails::resolve_config [start_dir]
#   Echo the resolved config file contents, or "NO_CONFIG" if none found.
#   (NO_CONFIG is the sentinel the workflow commands degrade gracefully on.)
coderails::resolve_config() {
  local p
  p=$(coderails::config_path "${1:-$PWD}")
  if [[ -n "$p" ]]; then
    cat "$p"
  else
    echo "NO_CONFIG"
  fi
}
