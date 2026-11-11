"""Lock docs-sync normative instructions and exercise the real dashboard loader."""

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATTERNS = (
    r"do not make a branch .* for a no-drift run",
    r"do not .*open a PR for a no-drift run",
    r"before you make a branch or PR",
    r"routine_run\.py",
    r"RR begin",
    r"RR finish no_drift",
    r"RR stage manifest_check",
    r"RR run-gate push --",
    r"RR run-gate merge --",
    r"RR finish ok",
    r"diff_manifest\.py --policy policy/docs-sync\.policy\.json",
    r"The runner ends with `run_abort` and cleans up\. Do not continue after a violation",
    r"Correct only tracked `\.md` files that the policy permits",
    r"exits nonzero",
    r"Do not invent a marker",
    r"Do not wait, poll, or retry",
    r"For example, `integrity-review` can be `pending`",
    r"writes its cause to the run note",
    r"does not give a dashboard alert or PR comment for an error",
    r"self-governance deny-list",
    r"Changes to `skills/\*\*/SKILL.md`.*abort before push",
    r"hooks do not run",
    r"reduces the risk of",
)
STAGES = [
    *("fetch_branch", "evals_frozen", "edit_made", "manifest_check", "push"),
    *("review", "post_review", "post_evals", "merge"),
]
NODE_CHECK = r"""
import {loadConfig} from './skills/dashboard/lib/src/config.ts';
import {checkForeignSkillExists} from './skills/dashboard/runner/src/escalate.ts';
import assert from 'node:assert/strict';
const cfg = loadConfig('./examples/dashboard-config.json');
const routine = cfg.routines.find(r => /(docs.?sync|sync.?docs)/i.test(r.name));
assert.ok(routine);
assert.equal(routine.cadence, 'nightly');
assert.equal(routine.foreignSkillPath, undefined);
assert.ok(routine.expectedArtifact.maxAgeSeconds < 691200);
const button = cfg.buttons.find(b => b.name === (routine.buttonRef || routine.name));
assert.ok(button);
assert.equal(button.profile, 'bypass');
assert.equal(cfg.routines.filter(r => /sync-docs/.test(r.name)).map(r => r.cadence).join('\n'), 'nightly');
assert.equal(cfg.buttons.filter(b => /sync-docs/.test(b.name)).map(b => b.profile).join('\n'), 'bypass');
assert.equal(checkForeignSkillExists('/Users/harrison/.claude/skills/sync-docs/SKILL.md'), false);
"""


class DocsSyncTests(unittest.TestCase):
    """The normative sentence must exist and removing it must defeat its assertion."""

    def test_normative_instructions_and_removal_controls(self) -> None:
        """Pin the script calls and the surviving prohibitions, each with a removal control."""
        text = (ROOT / "skills/docs-sync/SKILL.md").read_text()
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                expression = re.compile(pattern, re.I | re.M)
                self.assertIsNotNone(expression.search(text))
                stripped = "\n".join(line for line in text.splitlines() if not expression.search(line))
                self.assertIsNone(expression.search(stripped))

    def test_chain_is_in_the_spec_not_repeated_in_prose(self) -> None:
        """Both specs carry the ordered stages and policy; each SKILL spells the gate chain once."""
        for routine, policy in (("docs-sync", "docs-sync"), ("loop-retro-promotion", "retro-promotion")):
            with self.subTest(routine=routine):
                spec = json.loads((ROOT / f"routines/{routine}.json").read_text())
                self.assertEqual(spec["stages"], STAGES)
                self.assertEqual(spec["policy"], f"policy/{policy}.policy.json")
                self.assertTrue((ROOT / spec["policy"]).is_file())
                self.assertEqual(spec["cleanup"], ["close_pr", "delete_local_branch"])
                text = (ROOT / f"skills/{routine}/SKILL.md").read_text()
                self.assertEqual(text.count("RR run-gate merge --"), 1, "the chain appears once")
                self.assertNotIn("/coderails:post-evals", text, "the old prose chain is gone")
                self.assertNotRegex(text, r"append (a|an) .?(abort|delivery)=")

    def test_deny_list_is_policy_data(self) -> None:
        """The self-governance deny-list the SKILL names is the docs-sync policy's, including its own file."""
        deny = json.loads((ROOT / "policy/docs-sync.policy.json").read_text())["docs_sync"]["deny"]
        for entry in ("skills/**/SKILL.md", "AGENTS.md", "CLAUDE.md", "docs/routines.md", ".claude/**"):
            self.assertIn(entry, deny)

    def test_actual_loader_and_missing_foreign_skill(self) -> None:
        """Run the production TypeScript loader and existence predicate when dependencies exist."""
        self.assertIsNotNone(shutil.which("node"), "node is required")
        if missing_dependencies():
            self.skipTest("dashboard lib/runner node_modules missing; runtime validation unavailable")
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", NODE_CHECK],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def missing_dependencies() -> bool:
    """Keep the documented cold-clone outcome distinct from a failed assertion."""
    return any(not (ROOT / f"skills/dashboard/{name}/node_modules").is_dir() for name in ("lib", "runner"))


if __name__ == "__main__":
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(DocsSyncTests))
    if not result.wasSuccessful():
        sys.exit(1)
    if result.skipped:
        print("SKIP: dashboard lib/runner node_modules missing; run npm install in both")
        sys.exit(3)
