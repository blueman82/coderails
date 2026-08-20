#!/bin/bash
# PreToolUse hook (Write|Edit|MultiEdit): block writes into an unsanctioned
# top-level directory of an LLM wiki vault.
#
# The taxonomy is READ FROM THE PLUGIN'S OWN wiki schema
# (AGENTS-wiki-schema.md, "## Page types"), never hardcoded — this hook parses
# whatever that table currently says, so editing it changes enforcement
# automatically with no hook edit. Hardcoding the list would create exactly
# the drift-between-doc-and-enforcement this hook exists to prevent.
#
# WHY THAT FILE: AGENTS.md names AGENTS-wiki-schema.md as the wiki schema
# reference, and its Page types table is the SAME table wiki-ingest,
# wiki-query, wiki-lint and wiki-init read. Enforcing the table the skills
# read is the whole point of the hook.
#
# HISTORY, because the previous shape looked deliberate and was not: this hook
# used to resolve AGENTS.md from the WRITTEN FILE's own repo root — i.e. from
# the wiki vault — and additionally required a literal "wiki-vault: true"
# marker line in it. No design document specifies either. The vault has no
# root AGENTS.md at all, so the marker check exited 0 on every single write
# and the gate never once engaged. It was inert, not lenient: a write into an
# unsanctioned directory was permitted silently, which is indistinguishable
# from the gate approving it.
#
# A vault is identified POSITIVELY, from the project's configured wiki_path —
# never from directory shape. Structure alone was tried and over-blocks:
# measured, an ordinary Claude plugin (commands/ + hooks/ + skills/) and a
# data pipeline (sources/ + investigations/) each clear a ">=2 sanctioned
# dirs" test, and both had unrelated writes DENIED. Excluding just this plugin
# does not help — every Claude plugin has that shape, and a git worktree of
# the plugin has a different root again, so it blocks edits to the plugin's
# own source. Identification is therefore:
#   1. Read wiki_path from the plugin's .coderails/workflow.config.yaml.
#   2. Require the written file's repo root to BE that resolved path.
#   3. Structural corroboration only as a secondary sanity check, so a
#      misconfigured wiki_path pointing somewhere unrelated fails open rather
#      than blocking every write in whatever it names.
#
# Fail OPEN on any ambiguity: schema absent, config absent (a project not yet
# run through /coderails:init — matching how enforce_pr_workflow already
# no-ops without a config), wiki_path null or unresolvable, no Page types
# section, a table shape yielding zero parsed directories (an unexpected
# format must never be misread as "empty taxonomy, block everything" — worse
# than the drift it prevents), the write landing outside the configured vault,
# or fewer than 2 sanctioned directories present in it. Blocking only fires
# when a vault is POSITIVELY identified AND the target directory is
# POSITIVELY unsanctioned.
#
# Always allowed in addition to the parsed table:
#   raw/            — documented as immutable drop-zone input, not a page type
#   vault-root files — index.md, log.md, AGENTS.md, README.md (no directory)
#   dotfile dirs     — .git/, .obsidian/, .claude/ (tooling, not content)

IFS= read -r -d '' -t 5 input || true

file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"
case "$file" in
/*) absfile="$file" ;;
*) absfile="$cwd/$file" ;;
esac

# The file (and its parent dirs) may not exist yet — walk up to the nearest
# existing ancestor so `git -C` has a real directory inside the file's repo,
# tracking how many path segments were stripped off so absfile can be
# rebuilt from the resolved ancestor below.
probe=$(dirname "$absfile")
suffix=""
while [ ! -d "$probe" ] && [ "$probe" != "/" ] && [ -n "$probe" ]; do
    suffix="${probe##*/}/$suffix"
    probe=$(dirname "$probe")
done

root=$(git -C "$probe" rev-parse --show-toplevel 2>/dev/null)
[ -z "$root" ] && exit 0

# Resolve symlinks via the nearest existing ancestor, then rebuild absfile
# from it — on macOS /tmp is a symlink to /private/tmp, so `git rev-parse
# --show-toplevel` (which resolves it) and $absfile (built from the raw
# path) would otherwise never share a literal prefix even when they're the
# same directory. $probe is guaranteed to exist (the walk-up loop only
# stops at an existing dir or "/"), so `cd` here cannot fail the same way.
resolved_probe=$(cd "$probe" 2>/dev/null && pwd -P)
if [ -n "$resolved_probe" ]; then
    absfile="$resolved_probe/$suffix${absfile##*/}"
fi

# The taxonomy is read from the PLUGIN's own wiki schema, not from a file at
# the written file's repo root. This is where the schema actually lives:
# AGENTS.md names AGENTS-wiki-schema.md as the wiki schema reference, and its
# "## Page types" table is the same table wiki-ingest, wiki-query, wiki-lint
# and wiki-init already read. Enforcing the table the skills read is the whole
# point — an earlier version resolved AGENTS.md from the WRITTEN FILE's repo
# root, i.e. the vault, which has no such file and which no design document
# asks for, so the gate silently failed open on every write and never once
# engaged.
schema="${CLAUDE_PLUGIN_ROOT:-}/AGENTS-wiki-schema.md"
[ -f "$schema" ] || exit 0

# Extract the "## Page types" section body (up to the next "## " heading or EOF).
section=$(awk '/^## Page types/{flag=1; next} /^## /{flag=0} flag' "$schema")
[ -z "$section" ] && exit 0

# Parse every backticked "name/" token out of the table rows — robust to
# column position (directory-first or type-first layouts) since it keys on
# token shape, not column index.
# Backticks are literal wiki markup in this regular expression.
# shellcheck disable=SC2016
sanctioned=$(printf '%s\n' "$section" | grep -oE '`[A-Za-z0-9_-]+/`' | tr -d '`')
[ -z "$sanctioned" ] && exit 0

# POSITIVE vault identification: the write must land in the CONFIGURED wiki
# vault, resolved from workflow.config.yaml's wiki_path (relative to the
# plugin root). Structure alone is NOT sufficient and never was — measured:
# an ordinary Claude plugin repo (commands/ + hooks/ + skills/) and a data
# pipeline (sources/ + investigations/) both clear a ">=2 sanctioned dirs"
# test, so a purely structural rule blocks unrelated writes in both. That is
# the same hazard the old "wiki-vault: true" marker existed to prevent;
# dropping the marker without a positive identifier re-opens it.
#
# Excluding only the plugin repo is not enough either: it stops this repo
# being misread, not every other repo that shares the directory names.
config="${CLAUDE_PLUGIN_ROOT:-}/.coderails/workflow.config.yaml"
[ -f "$config" ] || exit 0
# Strip surrounding quotes: `wiki_path: "../wiki"` is valid YAML, and keeping
# the quotes makes the cd below fail, which would fail open on a perfectly
# good config — the gate going inert for a formatting choice is exactly the
# silent-nothing failure this PR exists to remove.
wiki_rel=$(awk '/^wiki_path:/{print $2; exit}' "$config" | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')
[ -n "$wiki_rel" ] || exit 0
# `null` and `~` are YAML nulls — a project with no wiki configured. Not an
# error, just nothing to gate.
case "$wiki_rel" in
null | '~' | '') exit 0 ;;
esac
# wiki_path may be absolute or relative. Blindly joining an absolute value to
# the plugin root produces a doubled path that cannot resolve, so the gate
# would fail open on a config that is perfectly valid — and at least one
# project on this machine does configure it absolutely. init.md only scaffolds
# the relative form, so this handles a documented and an undocumented-but-real
# shape rather than assuming the documented one is the only one in use.
case "$wiki_rel" in
/*) vault_root=$(cd "$wiki_rel" 2>/dev/null && pwd -P) ;;
*) vault_root=$(cd "${CLAUDE_PLUGIN_ROOT}/$wiki_rel" 2>/dev/null && pwd -P) ;;
esac
[ -n "$vault_root" ] || exit 0
[ "$root" = "$vault_root" ] || exit 0

# Structural corroboration, kept as a secondary sanity check: even the
# configured vault must actually carry its taxonomy, so a misconfigured
# wiki_path pointing at an unrelated directory fails open rather than
# blocking every write in it.
present=0
for dir in $sanctioned; do
    [ -d "$root/$dir" ] && present=$((present + 1))
done
[ "$present" -lt 2 ] && exit 0

# This IS a vault (not the plugin repo, and corroborated by real sanctioned
# directories on disk) — resolve the target path relative to the vault root
# and classify it.
case "$absfile" in
"$root"/*) rel="${absfile#"$root"/}" ;;
*) exit 0 ;;
esac

# Vault-root files (no directory component) always pass.
case "$rel" in
*/*) ;;
*) exit 0 ;;
esac

topdir="${rel%%/*}/"

# Structural escapes: raw/ (documented drop-zone input) and dotfile tooling dirs.
case "$topdir" in
raw/ | .git/ | .obsidian/ | .claude/) exit 0 ;;
esac

# Sanctioned per the parsed table -> allow.
for dir in $sanctioned; do
    [ "$dir" = "$topdir" ] && exit 0
done

sanctioned_list=$(printf '%s' "$sanctioned" | tr '\n' ' ')
reason="Blocked: '$topdir' is not a sanctioned wiki page-type directory (file: $file). Sanctioned directories per $schema: $sanctioned_list. Either move this page into one of those directories, or add '$topdir' to that file's Page types table first (which then permits it automatically)."

jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'

log="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
printf 'hook=wiki_taxonomy_gate decision=deny reason=unsanctioned_dir file=%s\n' "$file" >>"$log" 2>/dev/null

exit 0
