"""Procedure scripts ship in both providers, run from the Codex tree, and the Codex prose calls them."""

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Not importing scripts.*: that would bind the root `scripts` package; the Codex files run as subprocesses.
ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
MIRRORED = ("wiki_lint.py", "verify_merged.py", "memory_dir.py", "detect_test_command.py", "merge.py")
CODEX_ONLY_TEXT = {"merge.py"}  # differs by the provider's /coderails: vs $coderails-codex: command names
FENCE = re.compile(r"```.*?```", re.DOTALL)


def run(*argv: str, cwd: Path | None = None, **env: str) -> subprocess.CompletedProcess[str]:
    """Run a command with optional extra environment."""
    return subprocess.run(list(argv), cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True, check=False)


class MirrorTests(unittest.TestCase):
    """Both trees ship the scripts; only merge.py may differ, and only in provider command names."""

    def test_byte_identical_and_executable(self) -> None:
        """Four scripts are byte mirrors; every script is executable in both trees."""
        for name in MIRRORED:
            with self.subTest(name=name):
                claude, codex = ROOT / "scripts" / name, CODEX / "scripts" / name
                self.assertTrue(os.access(claude, os.X_OK) and os.access(codex, os.X_OK))
                if name not in CODEX_ONLY_TEXT:
                    self.assertEqual(claude.read_bytes(), codex.read_bytes())

    def test_merge_copies_keep_known_provider_differences_only(self) -> None:
        """The merge logic agrees after provider names and Codex config validation are removed."""
        claude = (ROOT / "scripts/merge.py").read_text().replace("/coderails:post-", "$coderails-codex:post-")
        codex = (CODEX / "scripts/merge.py").read_text()
        codex = codex.replace("from scripts.lib.config_strict import ConfigRejected, strict_settings\n", "")
        codex = codex.replace(
            "    if config:\n        try:\n            strict_settings(config)\n"
            "        except ConfigRejected as error:\n            raise git.WorkflowError(str(error)) from error\n"
            "        if integrity_enabled(config):\n"
            "            verify_integrity_status(sha, integrity_status_login(config))",
            "    if config and integrity_enabled(config):\n"
            "        verify_integrity_status(sha, integrity_status_login(config))",
        )
        self.assertEqual("".join(claude.split()), "".join(codex.split()))  # line wrapping may differ

    def test_schema_copies_agree_and_carry_the_key(self) -> None:
        """wiki_stale_days is typed (integer, default 30, enforced_by_code) in both schemas."""
        claude = (ROOT / "config.schema.json").read_bytes()
        self.assertEqual(claude, (CODEX / "config.schema.json").read_bytes())
        spec = json.loads(claude)["properties"]["wiki_stale_days"]
        self.assertEqual((spec["type"], spec["default"], spec["status"]), (["integer"], 30, "enforced_by_code"))

    def test_entrypoint_modes_list_every_new_script(self) -> None:
        """The exec-bit fixture names each new script in both trees as 100755."""
        modes = json.loads((ROOT / "hooks/scripts/tests/fixtures/python_entrypoint_modes.json").read_text())
        for name in MIRRORED + ("verify_merged.py",):
            for prefix in ("scripts/", "packages/codex/scripts/"):
                self.assertEqual(modes.get(prefix + name), "100755", prefix + name)


class CodexRunTests(unittest.TestCase):
    """The Codex copies run from the Codex tree."""

    def test_merge_describe_without_gh(self) -> None:
        """--describe exits 0 with the same gate names as the Claude copy, in a directory that is not a repo."""
        with tempfile.TemporaryDirectory() as directory:
            codex = run(sys.executable, str(CODEX / "scripts/merge.py"), "--describe", cwd=Path(directory))
            claude = run(sys.executable, str(ROOT / "scripts/merge.py"), "--describe", cwd=Path(directory))
        self.assertEqual((codex.returncode, claude.returncode), (0, 0), codex.stderr)

        def names(text: str) -> dict[str, list[str]]:
            return {k: [g["name"] for g in v] for k, v in json.loads(text).items()}

        self.assertEqual(names(codex.stdout), names(claude.stdout))
        self.assertEqual(len(names(codex.stdout)["verify_gates"]), 5)

    def test_memory_dir_and_detect_run(self) -> None:
        """memory_dir uses ~/.codex for the codex provider; detect_test_command reads the project."""
        with tempfile.TemporaryDirectory() as home:
            out = run(
                sys.executable, str(CODEX / "scripts/memory_dir.py"), "--cwd", "/a/b", "--provider", "codex", HOME=home
            )
            self.assertEqual(out.stdout.strip(), f"{home}/.codex/projects/-a-b/memory")
            Path(home, "go.mod").write_text("")
            found = run(sys.executable, str(CODEX / "scripts/detect_test_command.py"), "--dir", home)
            self.assertEqual(json.loads(found.stdout), {"command": "go test ./...", "candidates": ["go test ./..."]})

    def test_wiki_lint_runs_from_the_codex_tree(self) -> None:
        """An empty vault reports the default threshold."""
        with tempfile.TemporaryDirectory() as directory:
            result = run(
                sys.executable, str(CODEX / "scripts/wiki_lint.py"), "stale", "--repo", directory, "--vault", directory
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["stale_days"], 30)


class CodexQualityTests(unittest.TestCase):
    """quality_feedback consumes --json: a path that spells the clean summary no longer hides a finding."""

    def test_bad_json_external_failure_and_nonzero_clean_claim_are_disclosed(self) -> None:
        """The maintained consumer validates its input and reports checker failures."""
        reader = runpy.run_path(str(CODEX / "hooks/scripts/quality_feedback.py"))["finding_lines"]
        for stdout, code in (
            ("", 0),
            ("not-json", 0),
            ('{"findings": {}}', 0),
            ('{"scanned": 1, "findings": [], "external_ok": true}', 1),
            ('{"scanned": 1, "findings": [], "external_ok": false}', 0),
        ):
            with self.subTest(stdout=stdout, code=code):
                self.assertTrue(reader(subprocess.CompletedProcess([], code, stdout, "diagnostic")))

    def test_json_and_crafted_filename(self) -> None:
        """The checker's --json names the finding; the hook still emits feedback for `a 0 finding(s).py`."""
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            run("git", "init", "-q", cwd=repo)
            bad = repo / "a 0 finding(s).py"
            bad.write_text("x = 1 \n")
            checker = CODEX / "hooks/scripts/lib/quality_check.py"
            plain = run(sys.executable, str(checker), "--root", str(repo), "--paths", str(bad))
            self.assertIn("0 finding(s)", plain.stdout + plain.stderr)  # the old substring test would have gone silent
            data = json.loads(
                run(sys.executable, str(checker), "--json", "--root", str(repo), "--paths", str(bad)).stdout
            )
            self.assertEqual(
                (data["scanned"], data["external_ok"], [(f["line"], f["message"]) for f in data["findings"]]),
                (1, True, [(1, "trailing whitespace")]),
            )
            payload = json.dumps({"cwd": str(repo), "tool_input": {"command": f"*** Add File: {bad}\n"}})
            hook = subprocess.run(
                [sys.executable, str(CODEX / "hooks/scripts/quality_feedback.py")],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(hook.returncode, 0, hook.stderr)
            self.assertIn("trailing whitespace", hook.stdout)
            bad.write_text('"""ok."""\n')
            quiet = subprocess.run(
                [sys.executable, str(CODEX / "hooks/scripts/quality_feedback.py")],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual((quiet.returncode, quiet.stdout), (0, ""))


class CodexProseTests(unittest.TestCase):
    """The Codex skills point at the scripts and keep $ARGUMENTS out of code fences."""

    def test_skills_call_the_scripts(self) -> None:
        """Each skill names its script."""
        for relative, needle in (
            ("wiki-lint", "scripts/wiki_lint.py"),
            ("verify-merged-pr", "scripts/verify_merged.py"),
            ("merge", "--describe"),
            ("test-gate-setup", "scripts/detect_test_command.py"),
            ("memory-consolidation", "scripts/memory_dir.py"),
        ):
            with self.subTest(skill=relative):
                self.assertIn(needle, (CODEX / f"skills/{relative}/SKILL.md").read_text())

    def test_wiki_lint_skill_dropped_the_inline_staleness_procedure(self) -> None:
        """Both wiki-lint skills call wiki_lint.py and no longer carry the hand-run date comparison."""
        for path in (ROOT / "skills/wiki-lint/SKILL.md", CODEX / "skills/wiki-lint/SKILL.md"):
            with self.subTest(path=str(path.relative_to(ROOT))):
                text = path.read_text()
                self.assertIn("wiki_lint.py", text)
                self.assertNotIn("%cI", text)
                for block in FENCE.findall(text):
                    self.assertNotIn("$ARGUMENTS", block)


if __name__ == "__main__":
    unittest.main()
