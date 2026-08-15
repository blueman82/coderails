#!/bin/bash
# codex_dispatch.sh — Unit 6: constructs a Codex-native dispatch descriptor
# from a skill_id, without spawning anything. First real caller of
# skill_route.sh (hooks/scripts/lib/skill_route.sh), which resolves
# skill_id + provider -> path but, by its own documented contract
# (docs/REFERENCE.md), does not check the resolved path exists on disk or
# stays inside the repo's expected skill/agent/command directories — that
# is this file's job, per REFERENCE.md's "see Unit 6's dispatch-command
# construction for the Codex-arm file-existence checks" note.
#
# SOURCED, not executed directly — provides one function:
#
#   codex_dispatch_construct <path-to-index.yaml> <skill_id>
#     Resolves <skill_id> against the codex provider via skill_route.sh,
#     confines the resolved path to one of the expected directory prefixes
#     (skills/, .codex/skills/, agents/, commands/) under the index file's
#     own repo root, verifies the path exists as a real file on disk, maps
#     source_kind -> the Codex tool that would carry the dispatch (per
#     skills/using-coderails/references/codex-tools.md's action table), and
#     prints a JSON descriptor to stdout on success:
#       {"skill_id":..., "provider":"codex", "source_kind":...,
#        "codex_tool":..., "resolved_path":...}
#     Exit 0 on success.
#
#     On any failure, prints an error to stdout and exits 1 — never
#     constructs a partial descriptor:
#       - skill_route.sh itself fails closed (unknown skill_id, no codex
#         key, codex status not active, null/empty path): passes through
#         skill_route.sh's own "NO_PROVIDER_MAPPING: <reason>" verbatim.
#       - resolved path escapes the repo root or is outside the four
#         expected prefixes: "DISPATCH_REFUSED: path confinement failed
#         for '<resolved_path>'".
#       - resolved path is a symlink: real skills/agents/commands are
#         plain files today, so a symlink under an otherwise-confined
#         prefix is refused rather than resolved-and-trusted. Ponytail:
#         this is a blunt symlink ban, not a full symlink-target
#         confinement check; upgrade to resolving the symlink target and
#         re-running the prefix check if a legitimate symlinked skill file
#         is ever needed.
#       - resolved path does not exist as a regular file on disk:
#         "DISPATCH_REFUSED: resolved path '<resolved_path>' does not
#         exist".
#       - source_kind is "command": no Codex tool mapping is documented
#         for commands in codex-tools.md (only skill/agent map to
#         "loads natively"/spawn_agent) — refuse rather than guess:
#         "DISPATCH_REFUSED: no Codex tool mapping for source_kind
#         'command'".
#
# This never spawns Codex, never writes any file, and never touches
# skill_route.sh's own contract — it only consumes skill_route.sh's output
# and adds the confinement + existence + tool-mapping checks that were
# explicitly deferred to this unit.

CODEX_DISPATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_DISPATCH_SKILL_ROUTE="$CODEX_DISPATCH_DIR/skill_route.sh"

codex_dispatch_construct() {
  local index_path="$1" skill_id="$2"
  local resolved rc

  resolved=$(bash "$CODEX_DISPATCH_SKILL_ROUTE" "$index_path" "$skill_id" codex)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$resolved"
    return 1
  fi

  # Repo root = the index file's own grandparent-of-parent in the real
  # tree (skills/index.yaml -> repo root is one dir up); derived from the
  # index path itself so a fixture index under a fake repo root exercises
  # the identical confinement logic as the real tree, never hardcoded.
  local index_dir repo_root
  index_dir="$(cd "$(dirname "$index_path")" && pwd -P)" || {
    printf 'DISPATCH_REFUSED: cannot resolve index.yaml directory\n'
    return 1
  }
  repo_root="$(cd "$index_dir/.." && pwd -P)" || {
    printf 'DISPATCH_REFUSED: cannot resolve repo root from index.yaml path\n'
    return 1
  }

  local candidate="$repo_root/$resolved"

  # Symlink check happens before physical resolution (which would follow
  # the symlink and hide it) — reject outright per this file's documented
  # ceiling rather than resolve-and-trust the target.
  if [ -L "$candidate" ]; then
    printf "DISPATCH_REFUSED: resolved path '%s' is a symlink, refused\n" "$resolved"
    return 1
  fi

  if [ ! -f "$candidate" ]; then
    printf "DISPATCH_REFUSED: resolved path '%s' does not exist\n" "$resolved"
    return 1
  fi

  # Physical-path confinement: resolve the candidate's containing
  # directory to its real absolute path FIRST (collapsing any ../ or
  # symlinked intermediate directories), THEN prefix-check against the
  # repo root — never the reverse. A string-only prefix check on the
  # unresolved path (e.g. "skills/../../../etc/passwd") would pass a
  # naive check and then physically escape; resolving first closes that.
  local real_dir real_path rel
  real_dir="$(cd "$(dirname "$candidate")" && pwd -P)" || {
    printf "DISPATCH_REFUSED: path confinement failed for '%s'\n" "$resolved"
    return 1
  }
  real_path="$real_dir/$(basename "$candidate")"

  case "$real_path" in
    "$repo_root"/*) rel="${real_path#"$repo_root"/}" ;;
    *)
      printf "DISPATCH_REFUSED: path confinement failed for '%s'\n" "$resolved"
      return 1
      ;;
  esac

  # Anchored prefix match against the four expected directories — a glob
  # like *skills/* would wrongly admit "skills-evil/" or ".codexevil/skills/";
  # this matches only an exact, slash-anchored leading path segment.
  case "$rel" in
    skills/*|.codex/skills/*|agents/*|commands/*) ;;
    *)
      printf "DISPATCH_REFUSED: path confinement failed for '%s'\n" "$resolved"
      return 1
      ;;
  esac

  # source_kind lookup: same fixed-indentation awk extraction skill_route.sh
  # uses (this file does not own skills/index.yaml's schema either), pulled
  # from the top-level (2-space) skill_id block.
  local source_kind
  source_kind=$(awk -v id="$skill_id" '
    BEGIN { in_block = 0 }
    /^  [A-Za-z0-9._-]+:[ \t]*$/ {
      if (in_block) { exit }
      key = $0
      sub(/^  /, "", key)
      sub(/:[ \t]*$/, "", key)
      if (key == id) { in_block = 1; next }
      next
    }
    in_block && /^    source_kind:/ { sub(/^    source_kind: /, ""); print; exit }
  ' "$index_path")

  local codex_tool
  case "$source_kind" in
    skill) codex_tool="native" ;;
    agent) codex_tool="spawn_agent" ;;
    *)
      printf "DISPATCH_REFUSED: no Codex tool mapping for source_kind '%s'\n" "${source_kind:-<missing>}"
      return 1
      ;;
  esac

  jq -n -c \
    --arg skill_id "$skill_id" \
    --arg source_kind "$source_kind" \
    --arg codex_tool "$codex_tool" \
    --arg resolved_path "$resolved" \
    '{skill_id: $skill_id, provider: "codex", source_kind: $source_kind, codex_tool: $codex_tool, resolved_path: $resolved_path}'
}
