#!/usr/bin/env bash
# Functions are passed by name to check().
# shellcheck disable=SC2329
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGE="$ROOT/packages/codex"
QUICK_VALIDATE="${QUICK_VALIDATE:-${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py}"
FAILS=0

pass() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n' "$1"; FAILS=$((FAILS + 1)); }

check() {
  local label="$1" output
  shift
  if output=$("$@" 2>&1); then
    pass "$label"
    return
  fi
  fail "$label"
  [[ -z "$output" ]] || printf '       %s\n' "$output"
}

manifest_is_native() {
  python3 - "$PACKAGE/.codex-plugin/plugin.json" "$PACKAGE" <<'PY'
import json
import pathlib
import sys

manifest = pathlib.Path(sys.argv[1])
package = pathlib.Path(sys.argv[2]).resolve()
data = json.loads(manifest.read_text())
assert manifest.parent.parent.resolve() == package, "plugin root is not packages/codex"
assert set(data) == {"name", "version", "description", "skills"}, "unsupported manifest keys"
assert data["name"] == "coderails-codex", "wrong plugin name"
assert data["skills"] == "./skills/", "wrong skills path"
assert all(isinstance(data[key], str) and data[key] for key in data), "blank manifest value"
PY
}

skills_have_frontmatter() {
  python3 - "$PACKAGE/skills" <<'PY'
import pathlib
import re
import sys

skills = pathlib.Path(sys.argv[1])
directories = sorted(path for path in skills.iterdir() if path.is_dir())
assert len(directories) == 37, f"expected 37 skill directories, found {len(directories)}"
for directory in directories:
    skill = directory / "SKILL.md"
    assert skill.is_file(), f"missing {skill}"
    text = skill.read_text()
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
    assert match, f"invalid frontmatter: {skill}"
    frontmatter = match.group(1)
    name = re.search(r"^name:\s*([a-z0-9-]+)\s*$", frontmatter, re.MULTILINE)
    description = re.search(r"^description:\s*(\S.*)\s*$", frontmatter, re.MULTILINE)
    assert name and name.group(1) == directory.name, f"invalid name: {skill}"
    assert description and description.group(1) not in {'""', "''"}, f"invalid description: {skill}"
PY
}

skills_pass_quick_validate() {
  local skill failed=0
  [[ -f "$QUICK_VALIDATE" ]] || {
    printf 'quick_validate.py not found: %s\n' "$QUICK_VALIDATE" >&2
    return 1
  }
  while IFS= read -r skill; do
    if ! python3 "$QUICK_VALIDATE" "$skill" >/dev/null; then
      printf 'quick_validate failed: %s\n' "${skill#"$ROOT"/}" >&2
      failed=1
    fi
  done < <(find "$PACKAGE/skills" -mindepth 1 -maxdepth 1 -type d | sort)
  return "$failed"
}

migrated_commands_exist() {
  local name
  for name in assumptions disconfirm init merge notchecked post-evals post-review prep push test-gate-setup workflow; do
    [[ -f "$PACKAGE/skills/$name/SKILL.md" ]] || {
      printf 'missing migrated skill: %s\n' "$name" >&2
      return 1
    }
  done
}

prep_uses_nearest_project_config() {
  grep -Fq 'walking from the current directory upward to the Git root' "$PACKAGE/skills/prep/SKILL.md"
}

prep_bootstraps_local_projects() {
  local prep="$PACKAGE/skills/prep/SKILL.md"
  grep -Fq 'git init -b main' "$prep" || return 1
  grep -Fq 'git add -A' "$prep" || return 1
  grep -Fq 'git commit --allow-empty -m "Initial project"' "$prep" || return 1
  grep -Fq 'Do not add a remote' "$prep"
}

agents_are_native() {
  python3 - "$PACKAGE/agents" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
expected = {
    "deploy-safety-reviewer", "design-scout", "disposition-scout", "docs-auditor",
    "loop-worker", "preflight-scout", "proof-author", "source-auditor",
    "spec-reviewer", "wiki-writer",
}
read_only = {
    "deploy-safety-reviewer", "design-scout", "disposition-scout",
    "preflight-scout", "source-auditor", "spec-reviewer",
}
files = sorted(root.glob("*.toml"))
assert {path.stem for path in files} == expected, "custom-agent TOML set differs"
for path in files:
    text = path.read_text()
    header, separator, instructions_body = text.partition('developer_instructions = """')
    assert separator and instructions_body.endswith('"""\n'), f"invalid TOML body: {path}"
    name = re.search(r'^name = "([^"]+)"$', text, re.MULTILINE)
    description = re.search(r'^description = "(.+)"$', text, re.MULTILINE)
    instructions = re.search(r'^developer_instructions = """(?:\n|.)+?^"""$', text, re.MULTILINE)
    assert name and name.group(1) == path.stem, f"invalid name: {path}"
    assert description, f"missing description: {path}"
    assert instructions, f"missing developer_instructions: {path}"
    sandbox_modes = re.findall(r'^sandbox_mode = "([^"]+)"$', header, re.MULTILINE)
    if path.stem in read_only:
        assert sandbox_modes == ["read-only"], f"read-only sandbox missing: {path}"
    else:
        assert not sandbox_modes, f"write-capable agent is read-only: {path}"
    assert not re.search(r'claude|pr-review-toolkit|/security-review', text, re.IGNORECASE), f"provider-specific agent text: {path}"
PY
}

hooks_are_native() {
  python3 - "$PACKAGE/hooks/hooks.json" "$PACKAGE" <<'PY'
import json
import os
import pathlib
import re
import sys

hooks_file = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2]).resolve()
data = json.loads(hooks_file.read_text())
commands = []
for groups in data["hooks"].values():
    for group in groups:
        for hook in group["hooks"]:
            commands.append(hook["command"])
assert commands, "no hook commands registered"
for command in commands:
    match = re.fullmatch(r'"\$\{PLUGIN_ROOT\}/([^" ]+)"', command)
    assert match, f"non-native hook command: {command}"
    target = (root / match.group(1)).resolve()
    target.relative_to(root)
    assert target.is_file(), f"missing hook command: {target}"
    assert os.access(target, os.X_OK), f"hook command is not executable: {target}"
PY
}

helpers_have_modes() {
  local path
  for path in merge.sh post_evals.sh post_review.sh push.sh; do
    [[ -f "$PACKAGE/scripts/$path" && -x "$PACKAGE/scripts/$path" ]] || {
      printf 'missing executable helper: %s\n' "$path" >&2
      return 1
    }
  done
  for path in config.sh eval-artifact.sh git-common.sh review-artifact.sh; do
    [[ -f "$PACKAGE/scripts/lib/$path" && ! -x "$PACKAGE/scripts/lib/$path" ]] || {
      printf 'invalid library mode: %s\n' "$path" >&2
      return 1
    }
  done
}

native_graph_contract_exists() {
  local graph="$PACKAGE/skills/agentic-loop/scripts/graph.py"
  [[ -x "$graph" ]] || return 1
  python3 "$graph" --help | grep -q 'authorize-dispatch' || return 1
  python3 "$graph" --help | grep -q 'verify-completion' || return 1
  grep -q 'spawn_agent' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:dispatching-parallel-agents' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'begin-wave' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'update_plan.*display only' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:brainstorming' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:writing-plans' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'three or more work units, or any cross-unit dependency' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'spec.md.*beside.*progress.json' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'reread.*spec.md.*plan.md.*resume' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:using-git-worktrees' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:test-driven-development' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:subagent-driven-development' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:verification-before-completion' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:systematic-debugging' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  grep -q 'superpowers:finishing-a-development-branch' "$PACKAGE/skills/agentic-loop/SKILL.md" || return 1
  ! grep -Eiq 'claude -p|codex exec|pr-review-toolkit|background scheduler' "$PACKAGE/skills/agentic-loop/SKILL.md"
}

package_grades_loop_evals() {
  local tmp evals sha rc
  tmp=$(mktemp -d)
  evals="$tmp/evals.json"
  sha=$(git -C "$ROOT" rev-parse HEAD)
  jq -n --arg sha "$sha" '{
    schema_version:1,scope:"loop",task_ref:"loop-package",verification_level:0,
    verification_justification:"package fixture",frozen_sha:$sha,head_sha:$sha,
    session_id:"session-package",loop_id:"loop-package",revision:1,
    evals:[],amendments:[],result:null,graded_at:null
  }' >"$evals"
  if ! "$PACKAGE/scripts/post_evals.sh" grade-loop "$evals" >/dev/null; then
    rm -r "$tmp"
    return 1
  fi
  jq -e '.result == "GO" and .grading.by == "post_evals.sh grade-loop" and (.grading.checksum | test("^[0-9a-f]{64}$"))' "$evals" >/dev/null
  rc=$?
  rm -r "$tmp"
  return "$rc"
}

provider_split_is_clean() {
  local path
  for path in \
    .codex-plugin .codex codex \
    packages/codex/runtime packages/codex/catalog.py packages/codex/catalog.json \
    packages/codex/hooks/lifecycle.py packages/codex/install.json packages/codex/manifest.json \
    packages/claude packages/fixtures skills/index.yaml scripts/validate-skills-index.sh \
    hooks/scripts/lib/skill_route.sh hooks/scripts/lib/codex_dispatch.sh \
    hooks/scripts/lib/parallel_review.sh hooks/scripts/lib/parallel_review_harness.sh \
    hooks/scripts/lib/parallel_review_join.sh docs/DESIGN-MIXED-PROVIDER-REVIEW.md \
    docs/parallel-review-handoff.md docs/evals/live-graph-wiring.evals.json \
    docs/evals/mixed-provider-review.evals.json \
    docs/evals/neutral-integration-parallel-review-fix.evals.json \
    .github/prompts/agentic-loop.prompt.md .github/prompts/disposition-scout.prompt.md; do
    [[ ! -e "$ROOT/$path" ]] || {
      printf 'forbidden path remains: %s\n' "$path" >&2
      return 1
    }
  done
  [[ -f "$ROOT/.claude-plugin/plugin.json" ]] || return 1
  [[ -d "$ROOT/commands" && -d "$ROOT/skills" && -d "$ROOT/agents" ]] || return 1
  [[ -f "$ROOT/hooks/hooks.json" ]] || return 1
}

check "minimal native plugin manifest" manifest_is_native
check "37 native skills have name and description" skills_have_frontmatter
check "all native skills pass quick_validate" skills_pass_quick_validate
check "11 migrated commands exist as skills" migrated_commands_exist
check "prep resolves the nearest project config" prep_uses_nearest_project_config
check "prep bootstraps a local-only project" prep_bootstraps_local_projects
check "exactly 10 native custom agents" agents_are_native
check "native hook commands resolve under PLUGIN_ROOT" hooks_are_native
check "package helper modes" helpers_have_modes
check "native Codex graph contract" native_graph_contract_exists
check "package-local helper grades loop evals" package_grades_loop_evals
check "provider split and cleanup" provider_split_is_clean

if [[ "$FAILS" -eq 0 ]]; then
  printf 'PASS\n'
  exit 0
fi
printf 'FAILED (%s)\n' "$FAILS"
exit 1
