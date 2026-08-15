#!/bin/bash
# Fixture tests for hooks/scripts/lib/codex_dispatch.sh (Unit 6, AC-7 fixture
# half): given a skill_id + provider=codex, prove the resolution chain
# (skill_route.sh -> confinement -> existence -> tool mapping) constructs a
# correct Codex-native dispatch descriptor, and fails closed on every
# escape/missing/unmapped case — WITHOUT spawning anything. Live Codex
# execution is explicitly out of scope for this unit.
#
# All escape-path fixtures live under a fresh mktemp -d "fake repo" (its own
# skills/index.yaml + .codex/skills/... tree), never the shared worktree's
# real tracked files — same isolation convention skill_route.test.sh already
# uses for its own synthetic fixture.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LIB="$REPO_ROOT/hooks/scripts/lib/codex_dispatch.sh"
REAL_INDEX="$REPO_ROOT/skills/index.yaml"

# shellcheck source=../lib/codex_dispatch.sh
. "$LIB"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
run_check() { # desc, index_path, skill_id, expected_exit, expect_substr
  local desc="$1" index="$2" id="$3" want_exit="$4" want_substr="$5"
  local out rc
  out=$(codex_dispatch_construct "$index" "$id"); rc=$?
  if [ "$rc" != "$want_exit" ]; then
    printf 'FAIL - %s\n      expected exit=%s, got exit=%s (out=%s)\n' "$desc" "$want_exit" "$rc" "$out"
    fails=$((fails+1))
    return
  fi
  if [ -n "$want_substr" ] && [[ "$out" != *"$want_substr"* ]]; then
    printf 'FAIL - %s\n      expected output to contain: %s\n      actual: %s\n' "$desc" "$want_substr" "$out"
    fails=$((fails+1))
    return
  fi
  printf 'ok   - %s\n' "$desc"
}

# --- Real-index case: disposition-scout is the one real active codex entry ---
# (same real-index precedent as skill_route.test.sh's AC-3).
run_check "real index: disposition-scout/codex constructs a valid descriptor" \
  "$REAL_INDEX" disposition-scout 0 '"resolved_path":".codex/skills/disposition-scout/SKILL.md"'
run_check "real index: descriptor carries source_kind and codex_tool mapping" \
  "$REAL_INDEX" disposition-scout 0 '"source_kind":"agent","codex_tool":"spawn_agent"'

# --- Fail-closed passthrough from skill_route.sh itself ---
run_check "skill_route fail-closed passes through: unknown skill_id" \
  "$REAL_INDEX" totally-unknown-skill-id 1 "NO_PROVIDER_MAPPING"

# Keep planned-provider coverage independent of the completed real catalog.
PLANNED_INDEX="$TMP/planned-index.yaml"
cat > "$PLANNED_INDEX" <<'YAML'
skills:
  planned-codex-skill:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/planned-codex-skill/SKILL.md
      status: active
    codex:
      path: codex/skills/planned-codex-skill.md
      status: planned
    required_inputs: [x]
    output_contract: fixture entry whose codex provider remains planned.
YAML
run_check "skill_route fail-closed passes through: agentic-loop codex is planned" \
  "$PLANNED_INDEX" planned-codex-skill 1 "NO_PROVIDER_MAPPING"

# --- Fake repo root for confinement/existence/tool-mapping fixtures ---
# Fixture layout mirrors the real tree exactly (index at <root>/skills/index.yaml)
# so codex_dispatch_construct's repo-root derivation exercises the identical
# code path as the real tree.
FAKE="$TMP/fakerepo"
mkdir -p "$FAKE/skills" "$FAKE/.codex/skills/real-skill" "$FAKE/agents" "$FAKE/hooks/scripts/lib"
echo "skill body" > "$FAKE/.codex/skills/real-skill/SKILL.md"
echo "agent body" > "$FAKE/agents/real-agent.md"
# A real, existing file OUTSIDE the four confined prefixes, to prove
# confinement is checked independently of mere existence.
echo "not a skill" > "$FAKE/hooks/scripts/lib/skill_route.sh"
# A prefix-lookalike directory that must NOT be admitted by a loose glob.
mkdir -p "$FAKE/skills-evil/x"
echo "evil" > "$FAKE/skills-evil/x/SKILL.md"

cat > "$FAKE/skills/index.yaml" <<'YAML'
skills:
  real-skill:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/real-skill/SKILL.md
      status: active
    codex:
      path: .codex/skills/real-skill/SKILL.md
      status: active
    required_inputs: [x]
    output_contract: fixture real skill.
  real-agent:
    graph_role: null
    source_kind: agent
    claude:
      path: agents/real-agent.md
      status: active
    codex:
      path: agents/real-agent.md
      status: active
    required_inputs: [x]
    output_contract: fixture real agent.
  ghost-skill:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/ghost/SKILL.md
      status: active
    codex:
      path: .codex/skills/ghost/SKILL.md
      status: active
    required_inputs: [x]
    output_contract: fixture entry whose codex path does not exist on disk.
  traversal-escape:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/real-skill/SKILL.md
      status: active
    codex:
      path: skills/../../../../../../../../../etc/passwd
      status: active
    required_inputs: [x]
    output_contract: fixture entry whose codex path traverses out of the repo root.
  absolute-escape:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/real-skill/SKILL.md
      status: active
    codex:
      path: /etc/passwd
      status: active
    required_inputs: [x]
    output_contract: fixture entry whose codex path is an absolute path outside the repo.
  out-of-prefix:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/real-skill/SKILL.md
      status: active
    codex:
      path: hooks/scripts/lib/skill_route.sh
      status: active
    required_inputs: [x]
    output_contract: fixture entry whose codex path exists in-repo but outside the four confined prefixes.
  prefix-lookalike:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/real-skill/SKILL.md
      status: active
    codex:
      path: skills-evil/x/SKILL.md
      status: active
    required_inputs: [x]
    output_contract: fixture entry whose codex path lives under a skills-prefixed sibling directory, not skills/ itself.
  unmapped-command:
    graph_role: null
    source_kind: command
    claude:
      path: commands/real-command.md
      status: active
    codex:
      path: commands/real-command.md
      status: active
    required_inputs: [x]
    output_contract: fixture entry with source_kind command, which has no documented Codex tool mapping.
YAML
mkdir -p "$FAKE/commands"
echo "command body" > "$FAKE/commands/real-command.md"

FAKE_INDEX="$FAKE/skills/index.yaml"

run_check "fixture: real-skill/codex constructs a valid descriptor, confined + exists" \
  "$FAKE_INDEX" real-skill 0 '"resolved_path":".codex/skills/real-skill/SKILL.md"'
run_check "fixture: real-agent/codex maps source_kind agent -> spawn_agent" \
  "$FAKE_INDEX" real-agent 0 '"codex_tool":"spawn_agent"'

run_check "fixture: ghost-skill confined path does not exist on disk -> refused" \
  "$FAKE_INDEX" ghost-skill 1 "DISPATCH_REFUSED"

run_check "fixture: traversal escape (../../.. out of repo root) -> refused" \
  "$FAKE_INDEX" traversal-escape 1 "DISPATCH_REFUSED"

run_check "fixture: absolute path escape (/etc/passwd) -> refused" \
  "$FAKE_INDEX" absolute-escape 1 "DISPATCH_REFUSED"

run_check "fixture: in-repo but outside the four confined prefixes -> refused" \
  "$FAKE_INDEX" out-of-prefix 1 "DISPATCH_REFUSED"

run_check "fixture: prefix-lookalike dir (skills-evil/) -> refused, not admitted by loose glob" \
  "$FAKE_INDEX" prefix-lookalike 1 "DISPATCH_REFUSED"

run_check "fixture: source_kind command has no Codex tool mapping -> refused" \
  "$FAKE_INDEX" unmapped-command 1 "no Codex tool mapping"

# --- Symlink refusal: a confined, existing symlink is still refused ---
ln -s "$FAKE/.codex/skills/real-skill/SKILL.md" "$FAKE/.codex/skills/real-skill/SYMLINK.md"
cat >> "$FAKE_INDEX" <<'YAML'
  symlink-skill:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/real-skill/SKILL.md
      status: active
    codex:
      path: .codex/skills/real-skill/SYMLINK.md
      status: active
    required_inputs: [x]
    output_contract: fixture entry whose codex path is a symlink under a confined, existing location.
YAML
run_check "fixture: symlink under a confined+existing path is still refused" \
  "$FAKE_INDEX" symlink-skill 1 "DISPATCH_REFUSED"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
