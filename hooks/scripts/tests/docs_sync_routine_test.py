"""Lock docs-sync normative instructions and exercise the real dashboard loader."""

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATTERNS = (
    r"do \*\*not\*\* create a branch",
    r"do \*\*not\*\* open a pull request",
    r"BEFORE any branch or PR is created",
    r"--name-status",
    r"never .{0,5}--name-only",
    r"no line has status .R. or .C. \(rename/copy\) unless its SOURCE path",
    r"no line has status .D. \(deletion\) for an in-scope doc",
    r"ABORT, never warn-and-continue",
    r"git-tracked `\.md` files only",
    r"refused=<gate>",
    r"abort=<reason>",
    r"exits non-zero",
    r"never invent a new marker",
    r"never wait, poll, or retry",
    r"worked example is a .pending. .integrity-review. status",
    r"writes its reason into the run-note",
    r"There is no dashboard alert and no PR comment",
    r"self-governance deny-list",
    r"skills/\*\*/SKILL.md.*including this skill.s own file",
    r"^ *- .AGENTS\.md.$",
    r"^ *- .docs/routines\.md.$",
    r"documents that define",
    r"do not fire.*it reduces the risk of self-governance drift",
)
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
        """Cover every original prose assertion and strengthen each with a removal control."""
        text = (ROOT / "skills/docs-sync/SKILL.md").read_text()
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                expression = re.compile(pattern, re.I | re.M)
                self.assertIsNotNone(expression.search(text))
                stripped = "\n".join(line for line in text.splitlines() if not expression.search(line))
                self.assertIsNone(expression.search(stripped))

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
