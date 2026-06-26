#!/bin/bash
# PreToolUse hook (Write|Edit|MultiEdit): block edits to source files on the default branch.
# Enforces the worktree/branch discipline /workflow describes — main/master is for merges,
# not direct source edits. Gated: code extensions, plus plugin source that lives in markdown
# (skills/*/SKILL.md, commands/*.md) — those are source, not docs, so they get the same block.
# Plain docs and config still pass (the narrowed docs carve-out). Escape: create a feature
# branch first (/coderails:prep or a git worktree), or add a Write/Edit permission rule to
# settings.json. Emits permissionDecision=deny, the same PreToolUse idiom as destructive_bash_gate.sh.
#
# Cross-repo correctness: BOTH the gated-ness and the branch check key off the FILE's own
# repo, never the session cwd (cwd is used only to resolve a relative path). The markdown arm
# additionally requires the file's repo to be a plugin — its root must carry
# `.claude-plugin/plugin.json`. This stops a sibling repo's lookalike commands/ or skills/
# dirs (e.g. the coderails wiki's doc pages) from being falsely gated, while keeping the code
# arm a universal "no code on main in any repo" discipline. ${CLAUDE_PLUGIN_ROOT} is NOT used
# to identify plugin source: it points at the installed plugin copy, not the working checkout.

input=$(cat)

file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

# Classify the edit into a gated arm; everything else (plain docs, config) passes.
# Path arms are anchored on a "/" boundary so a stray dir like "myskills/" can't match;
# a bare relative arm covers a path the tool passes without a leading directory.
case "$file" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.go)        arm=code ;;
  */skills/*/SKILL.md|skills/*/SKILL.md)  arm=md ;;
  */commands/*.md|commands/*.md)          arm=md ;;
  *) exit 0 ;;
esac

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

reason="Blocked: editing a source file ($file) directly on '$branch'. Create a feature branch first (e.g. /coderails:prep or a git worktree), then edit there. For a genuine one-line hotfix, add a Write/Edit permission rule to settings.json."

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
