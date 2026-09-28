"""Verify the independently installed Codex package and its native delivery contract."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages/codex"


class NativePackageTests(unittest.TestCase):
    """Inspect shipped native assets without installing or changing user settings."""

    def test_manifest_and_skills(self) -> None:
        """Keep minimal native manifest and complete named skill frontmatter."""
        manifest = json.loads((PACKAGE / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), {"name", "version", "description", "skills"})
        self.assertEqual(manifest["name"], "coderails-codex")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertTrue(all(isinstance(value, str) and value for value in manifest.values()))
        directories = sorted(path for path in (PACKAGE / "skills").iterdir() if path.is_dir())
        self.assertEqual(len(directories), 37)
        for directory in directories:
            text = (directory / "SKILL.md").read_text(encoding="utf-8")
            match = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
            self.assertIsNotNone(match)
            if match is None:
                continue
            self.assertRegex(match.group(1), rf"(?m)^name:\s*{directory.name}\s*$")
            self.assertRegex(match.group(1), r"(?m)^description:\s*\S.+$")
        for name in (
            "assumptions",
            "disconfirm",
            "init",
            "merge",
            "notchecked",
            "post-evals",
            "post-review",
            "prep",
            "push",
            "test-gate-setup",
            "workflow",
        ):
            self.assertTrue((PACKAGE / "skills" / name / "SKILL.md").is_file())

    def test_skill_validation(self) -> None:
        """Run the existing system skill validator on each package skill."""
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        validator = Path(
            os.environ.get("QUICK_VALIDATE", str(codex_home / "skills/.system/skill-creator/scripts/quick_validate.py"))
        )
        self.assertTrue(validator.is_file(), str(validator))
        for skill in sorted((PACKAGE / "skills").iterdir()):
            if skill.is_dir():
                result = subprocess.run(
                    [sys.executable, str(validator), str(skill)], capture_output=True, text=True, check=False
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_agents(self) -> None:
        """Retain ten native instruction files and read-only reviewer boundaries."""
        expected = {
            "deploy-safety-reviewer",
            "design-scout",
            "disposition-scout",
            "docs-auditor",
            "loop-worker",
            "preflight-scout",
            "proof-author",
            "source-auditor",
            "spec-reviewer",
            "wiki-writer",
        }
        readonly = {
            "deploy-safety-reviewer",
            "design-scout",
            "disposition-scout",
            "preflight-scout",
            "source-auditor",
            "spec-reviewer",
        }
        files = sorted((PACKAGE / "agents").glob("*.toml"))
        self.assertEqual({path.stem for path in files}, expected)
        for path in files:
            text = path.read_text(encoding="utf-8")
            header, separator, body = text.partition('developer_instructions = """')
            self.assertTrue(separator and body.endswith('"""\n'))
            self.assertRegex(header, rf'(?m)^name = "{path.stem}"$')
            self.assertRegex(header, r'(?m)^description = ".+"$')
            modes = re.findall(r'^sandbox_mode = "([^"]+)"$', header, re.MULTILINE)
            self.assertEqual(modes, ["read-only"] if path.stem in readonly else [])
            self.assertNotRegex(text.lower(), r"claude|pr-review-toolkit|/security-review")

    def test_local_prep_and_graph_guidance(self) -> None:
        """Keep local bootstrap, provider-native orchestration, and graph authority guidance."""
        prep = (PACKAGE / "skills/prep/SKILL.md").read_text(encoding="utf-8")
        for text in (
            "walking from the current directory upward to the Git root",
            "git init -b main",
            "git add -A",
            'git commit --allow-empty -m "Initial project"',
            "Do not add a remote",
        ):
            self.assertIn(text, prep)
        guidance = (PACKAGE / "skills/agentic-loop/SKILL.md").read_text(encoding="utf-8")
        for text in (
            "spawn_agent",
            "begin-wave",
            "superpowers:dispatching-parallel-agents",
            "superpowers:brainstorming",
            "superpowers:writing-plans",
            "superpowers:using-git-worktrees",
            "superpowers:test-driven-development",
            "superpowers:subagent-driven-development",
            "superpowers:verification-before-completion",
            "superpowers:systematic-debugging",
            "superpowers:finishing-a-development-branch",
            "three or more work units, or any cross-unit dependency",
        ):
            self.assertIn(text, guidance)
        self.assertRegex(guidance, r"update_plan.*display only")
        self.assertRegex(guidance, r"spec.md.*beside.*progress.json")
        self.assertRegex(guidance, r"reread.*spec.md.*plan.md.*resume")
        self.assertNotRegex(guidance, r"claude -p|codex exec|pr-review-toolkit|background scheduler")
        result = subprocess.run(
            [sys.executable, str(PACKAGE / "skills/agentic-loop/scripts/graph.py"), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        for command in ("authorize-dispatch", "verify-completion", "respawn-stale", "hard-stop"):
            self.assertIn(command, result.stdout)
        for command in ("cancel-unspawned-wave", "acknowledge-cancelled-wave", "add-remediation-node"):
            self.assertNotIn(command, result.stdout)

    def test_workflow_delivery_and_grading(self) -> None:
        """Workflow entry points are executable, local modules private, and stamps current."""
        for name in ("merge", "post_evals", "post_review", "push"):
            path = PACKAGE / "scripts" / f"{name}.py"
            self.assertTrue(path.is_file() and os.access(path, os.X_OK), str(path))
        for name in ("config", "eval_artifact", "git_common", "review_artifact"):
            path = PACKAGE / "scripts/lib" / f"{name}.py"
            self.assertTrue(path.is_file() and not os.access(path, os.X_OK), str(path))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "scope": "loop",
                        "task_ref": "loop-package",
                        "verification_level": 0,
                        "verification_justification": "package fixture",
                        "frozen_sha": sha,
                        "head_sha": sha,
                        "session_id": "session-package",
                        "loop_id": "loop-package",
                        "revision": 1,
                        "evals": [],
                        "amendments": [],
                        "result": None,
                        "graded_at": None,
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(PACKAGE / "scripts/post_evals.py"), "grade-loop", str(path)],
                check=True,
                capture_output=True,
            )
            graded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(graded["result"], "GO")
            self.assertEqual(graded["grading"]["by"], "post_evals.py grade-loop")
            self.assertRegex(graded["grading"]["checksum"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
