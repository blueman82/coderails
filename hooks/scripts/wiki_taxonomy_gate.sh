#!/bin/bash
# PreToolUse hook (Write|Edit|MultiEdit): block writes into an unsanctioned
# top-level directory of an LLM wiki vault.
#
# The taxonomy is READ FROM THE VAULT'S OWN AGENTS.md, never hardcoded — this
# hook parses whatever the "## Page types" table currently says, so editing
# that table changes enforcement automatically with no hook edit. Hardcoding
# the list would create exactly the drift-between-doc-and-enforcement this
# hook exists to prevent.
#
# A vault is identified by carrying an AGENTS.md with a "## Page types"
# section AT ITS OWN REPO ROOT. Identification keys off the FILE's own repo
# root, never the session cwd — matches the cross-repo pattern in
# no_edit_on_main.sh (an agent may write into a wiki from a different repo's
# worktree, which is exactly the incident this hook exists to prevent).
#
# A root AGENTS.md with a parseable Page types table is NOT sufficient on its
# own: a code repo can legitimately DOCUMENT a wiki's taxonomy (e.g. the code
# repo that builds the agent maintaining that wiki) without BEING the vault.
# This bit a real repo (assistant-agent) whose AGENTS.md describes its wiki's
# taxonomy from the outside — the hook denied every source write in it. So a
# vault also requires STRUCTURAL CORROBORATION: at least 2 of the parsed
# sanctioned directories must actually exist at the repo root. A genuine
# vault has (most or all of) its taxonomy's directories present; a repo that
# merely describes one elsewhere's taxonomy has none of them.
#
# Structural corroboration alone is not airtight either: a repo whose own
# source dirs happen to share names with a taxonomy it documents (e.g. a
# plugin repo with commands/, hooks/, skills/ dirs whose AGENTS.md documents
# a companion wiki using those same names) would still pass the >=2 check.
# So a vault ALSO requires a POSITIVE MARKER: a literal "wiki-vault: true"
# line anywhere in AGENTS.md. This is the vault self-identifying its
# contract, rather than the hook inferring vault-ness from structure alone —
# a repo does not carry this line by accident.
#
# Fail OPEN on any ambiguity: AGENTS.md absent, no wiki-vault: true marker,
# no Page types section, a section present but the table shape yields zero
# parsed directories (an unexpected format must never be misread as "empty
# taxonomy, block everything" — that would be worse than the drift it
# prevents), or fewer than 2 sanctioned directories actually present at the
# root (documentation, not a vault). Blocking only fires when a vault is
# POSITIVELY identified (marker + parseable table + structural corroboration,
# all required) AND the target directory is POSITIVELY unsanctioned.
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
  *)  absfile="$cwd/$file" ;;
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

agents="$root/AGENTS.md"
[ -f "$agents" ] || exit 0

# Positive vault marker: a literal "wiki-vault: true" line. Required in
# addition to the Page types table + structural corroboration below — see
# the header comment for why structure alone isn't enough to rule out a
# code/plugin repo whose own dirs happen to overlap a taxonomy it documents.
grep -q '^wiki-vault: true$' "$agents" || exit 0

# Extract the "## Page types" section body (up to the next "## " heading or EOF).
section=$(awk '/^## Page types/{flag=1; next} /^## /{flag=0} flag' "$agents")
[ -z "$section" ] && exit 0

# Parse every backticked "name/" token out of the table rows — robust to
# column position (directory-first or type-first layouts) since it keys on
# token shape, not column index.
sanctioned=$(printf '%s\n' "$section" | grep -oE '`[A-Za-z0-9_-]+/`' | tr -d '`')
[ -z "$sanctioned" ] && exit 0

# Structural corroboration: require at least 2 of the parsed sanctioned
# directories to actually exist at the root, so a repo whose AGENTS.md merely
# describes a taxonomy (documentation) is not mistaken for the vault itself.
present=0
for dir in $sanctioned; do
  [ -d "$root/$dir" ] && present=$((present + 1))
done
[ "$present" -lt 2 ] && exit 0

# This IS a vault (marker present, parseable Page types table, corroborated
# by real sanctioned directories on disk) — resolve the target path relative
# to the vault root and classify it.
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
  raw/|.git/|.obsidian/|.claude/) exit 0 ;;
esac

# Sanctioned per the parsed table -> allow.
for dir in $sanctioned; do
  [ "$dir" = "$topdir" ] && exit 0
done

sanctioned_list=$(printf '%s' "$sanctioned" | tr '\n' ' ')
reason="Blocked: '$topdir' is not a sanctioned wiki page-type directory (file: $file). Sanctioned directories per $agents: $sanctioned_list. Either move this page into one of those directories, or add '$topdir' to AGENTS.md's Page types table first (which then permits it automatically)."

jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'

log="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
printf 'hook=wiki_taxonomy_gate decision=deny reason=unsanctioned_dir file=%s\n' "$file" >> "$log" 2>/dev/null

exit 0
