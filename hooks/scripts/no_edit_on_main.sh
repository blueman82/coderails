#!/bin/bash
# PreToolUse hook (Write|Edit|MultiEdit): block edits to source files on the default branch.
# Enforces the worktree/branch discipline /workflow describes — main/master is for merges,
# not direct source edits. Gated: everything EXCEPT an explicit allowlist of doc/config
# extensions (see below), plus plugin source that lives in markdown (skills/*/SKILL.md,
# commands/*.md) — those are source, not docs, so they get the same block even though .md
# is otherwise in the allowlist. Escape: create an isolated worktree + branch first
# (/coderails:prep or 'git worktree add'), or add a Write/Edit permission rule to settings.json. Emits
# permissionDecision=deny, the same PreToolUse idiom as destructive_bash_gate.sh.
#
# Allowlist (these stay editable on main):
#   docs  — .md (plain docs), .txt, .rst
#   config — .yaml, .yml, .json, .toml, .ini, .cfg
#   special — the literal .gitignore dotfile (by basename), LICENSE (bare filename)
#             Note: only the exact basename ".gitignore" passes; "deploy.gitignore" does not.
# Everything else on main → block.
#
# Cross-repo correctness: BOTH the gated-ness and the branch check key off the FILE's own
# repo, never the session cwd (cwd is used only to resolve a relative path). The markdown arm
# additionally requires the file's repo to be a plugin — its root must carry
# `.claude-plugin/plugin.json`. This stops a sibling repo's lookalike commands/ or skills/
# dirs (e.g. the coderails wiki's doc pages) from being falsely gated, while the code
# arm is a universal "no source on main in any repo" discipline. ${CLAUDE_PLUGIN_ROOT} is NOT
# used to identify plugin source: it points at the installed plugin copy, not the working
# checkout.

input=$(cat)

file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

# ── Claude Code permission-file arm ─────────────────────────────────────────
# .claude/settings.json and .claude/settings.local.json hold the permissions.allow
# rules that pre-approve commands UPSTREAM of every PreToolUse gate — editing them
# is the one move that can dismantle the whole discipline layer. Block on ANY branch
# (a settings escape is dangerous everywhere), in any repo, regardless of the plugin
# marker. Matched on the `.claude/` parent so an unrelated settings.json elsewhere is
# not caught; only the file directly under .claude/ is the permission file.
case "$file" in
  */.claude/settings.json|.claude/settings.json|\
  */.claude/settings.local.json|.claude/settings.local.json)
    reason="Blocked: editing the Claude Code permission file ($file). These settings can pre-approve commands and bypass the discipline gates, so they are never edited by the agent. If you genuinely need to change permissions, do it yourself outside the agent."
    jq -n --arg r "$reason" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $r
      }
    }'
    log="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
    printf 'hook=no_edit_on_main decision=deny reason=settings_file file=%s\n' "$file" >> "$log" 2>/dev/null
    exit 0
    ;;
esac

# ── Markdown plugin-source arm ──────────────────────────────────────────────
# Check plugin-source markdown FIRST, before the allowlist. skills/*/SKILL.md and
# commands/*.md are source; they must be blocked even though .md is in the allowlist.
# Path arms are anchored on a "/" boundary so a stray dir like "myskills/" can't match;
# a bare relative arm covers a path the tool passes without a leading directory.
case "$file" in
  */skills/*/SKILL.md|skills/*/SKILL.md) arm=md ;;
  */commands/*.md|commands/*.md)         arm=md ;;
  *)                                     arm=code ;;
esac

# ── Allowlist check (code arm only) ─────────────────────────────────────────
# If the file is in the allowlist, it always passes — no branch check needed.
# This runs before the repo/branch resolution to keep cheap exits early.
if [ "$arm" = "code" ]; then
  basename="${file##*/}"
  case "$file" in
    *.md|*.txt|*.rst)                        exit 0 ;;
    *.yaml|*.yml|*.json|*.toml|*.ini|*.cfg)  exit 0 ;;
  esac
  # Bare dotfiles / bare filenames — match the basename only, not an arbitrary suffix.
  # *.gitignore would allow deploy.gitignore; only the literal .gitignore dotfile passes.
  case "$basename" in
    .gitignore|LICENSE) exit 0 ;;
  esac
fi

# Resolve the file's OWN repo. cwd is used only to turn a relative file_path absolute —
# it is NOT the branch source (that was the cross-repo bug).
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"
case "$file" in
  /*) absfile="$file" ;;
  *)  absfile="$cwd/$file" ;;
esac

# The file (and its parent dirs) may not exist yet — walk up to the nearest existing
# ancestor so `git -C` has a real directory inside the file's repo. This relies on the
# repo's working-tree root always existing on disk, so the walk stays inside the file's
# own repo; it only reaches a non-repo ancestor when the path points outside any repo,
# which then fails open below (empty branch → exit 0) — the safe direction for a gate.
probe=$(dirname "$absfile")
while [ ! -d "$probe" ] && [ "$probe" != "/" ] && [ -n "$probe" ]; do
  probe=$(dirname "$probe")
done

branch=$(git -C "$probe" branch --show-current 2>/dev/null)
case "$branch" in
  main|master) ;;
  *) exit 0 ;;
esac

# Markdown arm only: gate genuine plugin source. The file's repo must carry the plugin
# marker; a non-plugin repo (wiki/docs) with lookalike commands/ or skills/ dirs passes.
if [ "$arm" = "md" ]; then
  root=$(git -C "$probe" rev-parse --show-toplevel 2>/dev/null)
  { [ -n "$root" ] && [ -f "$root/.claude-plugin/plugin.json" ]; } || exit 0
fi

reason="Blocked: editing a source file ($file) directly on '$branch'. Create an isolated worktree + branch first (e.g. /coderails:prep or 'git worktree add <path> -b <name>'), then edit there. For a genuine one-line hotfix, add a Write/Edit permission rule to settings.json."

jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'

# Structured discipline log (greppable key=value).
log="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
printf 'hook=no_edit_on_main decision=deny branch=%s file=%s\n' "$branch" "$file" >> "$log" 2>/dev/null

exit 0
