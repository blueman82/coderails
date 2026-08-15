#!/bin/bash
# Routing resolution tests for hooks/scripts/lib/skill_route.sh (Unit 3,
# AC-2 through AC-5). AC-2/AC-3 resolve against the REAL skills/index.yaml
# at the repo root (not a fixture) — per plan.md, AC-3's whole point is that
# Unit 1 seeded a genuine `active` Codex sibling, not a fixture-only claim.
# AC-4/AC-5 need a synthetic fixture: no real index.yaml entry omits the
# `codex:` key entirely (confirmed on PR #388 review), so the "no provider
# mapping at all" case has no real-index target.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HELPER="$REPO_ROOT/hooks/scripts/lib/skill_route.sh"
REAL_INDEX="$REPO_ROOT/skills/index.yaml"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
run_check() { # desc, index_path, skill_id, provider, expected_exit, expect_substr
  local desc="$1" index="$2" id="$3" prov="$4" want_exit="$5" want_substr="$6"
  local out rc
  out=$(bash "$HELPER" "$index" "$id" "$prov"); rc=$?
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

# AC-2: a known Claude-active skill_id resolves to its real SKILL.md path.
run_check "AC-2: agentic-loop/claude resolves to real SKILL.md path" \
  "$REAL_INDEX" agentic-loop claude 0 "skills/agentic-loop/SKILL.md"

# AC-3: disposition-scout (Unit-1-seeded sibling) resolves under codex.
run_check "AC-3: disposition-scout/codex resolves to real Codex sibling path" \
  "$REAL_INDEX" disposition-scout codex 0 ".codex/skills/disposition-scout/SKILL.md"
[ -f "$REPO_ROOT/.codex/skills/disposition-scout/SKILL.md" ] || {
  printf 'FAIL - AC-3: resolved Codex sibling file does not exist on disk\n'
  fails=$((fails+1))
}

# Synthetic fixture for AC-4/AC-5: one entry with NO codex: key at all, one
# entry with codex: status: planned (mirrors the real index's shape for
# every non-seeded entry, isolated here so the assertion is exact and does
# not depend on which real entries happen to be planned).
cat > "$TMP/fixture_index.yaml" <<'YAML'
skills:
  no-codex-key-skill:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/fixture/SKILL.md
      status: active
    required_inputs: [x]
    output_contract: fixture entry with no codex key at all.
  planned-codex-skill:
    graph_role: null
    source_kind: skill
    claude:
      path: skills/fixture2/SKILL.md
      status: active
    codex:
      path: .codex/skills/fixture2/SKILL.md
      status: planned
    required_inputs: [x]
    output_contract: fixture entry with codex status planned.
YAML

# AC-4: a skill_id with no codex: key at all -> explicit fail-closed error,
# never proceeds to a dispatch call (asserted on exit code AND error text,
# not just "didn't crash").
run_check "AC-4: no codex key at all -> fail-closed NO_PROVIDER_MAPPING" \
  "$TMP/fixture_index.yaml" no-codex-key-skill codex 1 "NO_PROVIDER_MAPPING"

# AC-5: a skill_id with codex: status: planned -> same fail-closed behavior,
# never silently falls back to Claude.
run_check "AC-5: codex status:planned -> fail-closed NO_PROVIDER_MAPPING" \
  "$TMP/fixture_index.yaml" planned-codex-skill codex 1 "NO_PROVIDER_MAPPING"
# AC-5 continued: the SAME skill_id's claude path must still resolve --
# proves "planned" fails closed for codex specifically, not the whole entry.
run_check "AC-5: same skill_id's claude mapping still resolves independently" \
  "$TMP/fixture_index.yaml" planned-codex-skill claude 0 "skills/fixture2/SKILL.md"

# Additional fail-closed coverage: unknown skill_id entirely.
run_check "unknown skill_id -> fail-closed NO_PROVIDER_MAPPING" \
  "$REAL_INDEX" totally-unknown-skill-id claude 1 "NO_PROVIDER_MAPPING"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
