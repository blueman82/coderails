"""Exercise scripts/installed_parity.py end to end through its command line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "installed_parity.py"
REPO = SCRIPT.parent.parent


def write(root: Path, relative: str, content: bytes = b"same\n") -> None:
    """Create one file, and any parent directories, under a root."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def parity(*arguments: str, home: str = "/nonexistent-home") -> subprocess.CompletedProcess[str]:
    """Run the tool with a fake HOME so default-location lookup never sees real installs."""
    environment = {**os.environ, "HOME": home}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, check=False, env=environment
    )


class InstalledParityTests(unittest.TestCase):
    """Cover identical, drifted, extra, missing, ignored and packages/codex cases."""

    def setUp(self) -> None:
        """Build a source tree with a Claude file and a packages/codex file."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.source, self.claude, self.codex = base / "src", base / "claude", base / "codex"
        write(self.source, "skills/x/a.py", b"claude-body\n")
        write(self.source, "packages/codex/skills/x/a.py", b"codex-body\n")
        write(self.claude, "skills/x/a.py", b"claude-body\n")
        write(self.codex, "skills/x/a.py", b"codex-body\n")
        for root, relative in (
            (self.source, ".claude-plugin/plugin.json"),
            (self.source, "hooks/hooks.json"),
            (self.source, "packages/codex/.codex-plugin/plugin.json"),
            (self.source, "packages/codex/hooks/hooks.json"),
            (self.claude, ".claude-plugin/plugin.json"),
            (self.claude, "hooks/hooks.json"),
            (self.codex, ".codex-plugin/plugin.json"),
            (self.codex, "hooks/hooks.json"),
        ):
            write(root, relative, b"{}\n")
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        subprocess.run(["git", "-C", str(self.source), "add", "-A"], check=True)

    def run_parity(self) -> subprocess.CompletedProcess[str]:
        """Compare the fixture installs against the fixture source."""
        return parity(
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )

    def test_identical_trees_pass_and_codex_maps_to_packages_codex(self) -> None:
        """Codex content differs from the Claude path yet matches packages/codex, so this passes."""
        result = self.run_parity()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_byte_drift_fails_and_names_file(self) -> None:
        """A single changed byte in the Claude bundle exits 1 and names bundle and path."""
        write(self.claude, "skills/x/a.py", b"claude-bodY\n")
        result = self.run_parity()
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude", result.stdout)
        self.assertIn("skills/x/a.py", result.stdout)

    def test_codex_drift_is_judged_against_packages_codex(self) -> None:
        """A Codex file equal to the root copy but not the packages/codex copy is drift."""
        write(self.codex, "skills/x/a.py", b"claude-body\n")
        result = self.run_parity()
        self.assertEqual(result.returncode, 1)
        self.assertIn("codex", result.stdout)

    def test_extra_installed_file_fails(self) -> None:
        """A file only in the installed tree is a difference."""
        write(self.codex, "skills/x/extra.py")
        result = self.run_parity()
        self.assertEqual(result.returncode, 1)
        self.assertIn("skills/x/extra.py", result.stdout)

    def test_ignored_files_do_not_count(self) -> None:
        """__pycache__, .pyc and .DS_Store never count as differences."""
        write(self.claude, "skills/x/__pycache__/a.cpython-39.pyc")
        write(self.claude, "skills/x/b.pyc")
        write(self.claude, ".DS_Store")
        write(self.codex, "skills/.DS_Store")
        result = self.run_parity()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_directory_exits_two(self) -> None:
        """A given installed directory that does not exist is a usage error, not a pass."""
        result = parity("--source-root", str(self.source), "--claude-installed", str(self.claude / "nope"))
        self.assertEqual(result.returncode, 2)

    def test_not_installed_defaults_skip_with_exit_zero(self) -> None:
        """With no flags and no installed copies the tool says so and exits 0."""
        result = parity("--source-root", str(self.source), home=self.temporary.name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("not installed, skipped"), 2)

    def test_strict_refuses_when_both_installs_are_absent(self) -> None:
        """A release check cannot pass without either provider."""
        result = parity("--require-both", "--source-root", str(self.source), home=self.temporary.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude: not installed", result.stdout)
        self.assertIn("codex: not installed", result.stdout)
        self.assertNotIn("skipped", result.stdout)

    def test_strict_refuses_when_one_install_is_absent(self) -> None:
        """One present provider does not hide a missing second provider."""
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            home=self.temporary.name,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude: 0 difference(s)", result.stdout)
        self.assertIn("codex: not installed", result.stdout)

    def test_strict_accepts_both_matching_installs(self) -> None:
        """Both matching provider installs satisfy strict presence."""
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_explicit_missing_directory_is_usage_error(self) -> None:
        """A bad explicit path remains a usage error in strict mode."""
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude / "missing"),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 2)

    def test_strict_refuses_symlink_installed_root(self) -> None:
        """A link to the source tree is not evidence of an installed copy."""
        linked = Path(self.temporary.name) / "linked-claude"
        linked.symlink_to(self.source, target_is_directory=True)
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(linked),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

    def test_strict_refuses_nested_symlink_file_or_directory(self) -> None:
        """An installed tree cannot hide a linked file or directory."""
        linked_file = self.claude / "skills/x/linked.py"
        linked_file.symlink_to(self.source / "skills/x/a.py")
        linked_dir = self.codex / "linked-skills"
        linked_dir.symlink_to(self.source / "packages/codex/skills", target_is_directory=True)
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

    def test_strict_refuses_ignored_runtime_source_even_if_installed(self) -> None:
        """An ignored hook cannot become part of a release by matching the install."""
        write(self.source, ".gitignore", b"hooks/extra.py\n")
        write(self.source, "hooks/extra.py", b"print('hidden')\n")
        write(self.claude, "hooks/extra.py", b"print('hidden')\n")
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("untracked runtime source", result.stderr)

    def test_strict_refuses_extra_installed_runtime_file(self) -> None:
        """A hook absent from the tracked source cannot pass strict parity."""
        write(self.claude, "hooks/extra.py", b"print('extra')\n")
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not tracked", result.stderr)

    def test_strict_refuses_source_without_git_inventory(self) -> None:
        """A release needs a source tree whose file list Git can verify."""
        other = Path(self.temporary.name) / "not-a-repo"
        write(other, "skills/x/a.py", b"claude-body\n")
        write(other, "packages/codex/skills/x/a.py", b"codex-body\n")
        result = parity(
            "--require-both",
            "--source-root",
            str(other),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Git source", result.stderr)

    def test_strict_refuses_empty_installed_directories(self) -> None:
        """Directory presence alone does not prove either plugin is installed."""
        empty_claude = Path(self.temporary.name) / "empty-claude"
        empty_codex = Path(self.temporary.name) / "empty-codex"
        empty_claude.mkdir()
        empty_codex.mkdir()
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(empty_claude),
            "--codex-installed",
            str(empty_codex),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required installed file missing", result.stderr)

    def test_strict_refuses_source_checkout_as_installed_plugin(self) -> None:
        """Matching source bytes cannot stand in for an installed provider."""
        for claude, codex in (
            (self.source, self.codex),
            (self.claude, self.source / "packages/codex"),
        ):
            result = parity(
                "--require-both",
                "--source-root",
                str(self.source),
                "--claude-installed",
                str(claude),
                "--codex-installed",
                str(codex),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("source checkout", result.stderr)

    def test_strict_keeps_cache_file_exclusions(self) -> None:
        """Python caches and Finder files do not become release source files."""
        for root in (self.source, self.claude):
            write(root, "hooks/__pycache__/gate.cpython-39.pyc")
            write(root, "hooks/.DS_Store")
        result = parity(
            "--require-both",
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_refuses_missing_runtime_files_in_either_provider(self) -> None:
        """Matching registration files cannot hide a missing skill or control data file."""
        for bundle, installed, prefix in (
            ("claude", self.claude, ""),
            ("codex", self.codex, "packages/codex/"),
        ):
            for relative in ("policy/review_policy.json", "capabilities/profiles.json", "routines/docs-sync.json"):
                write(self.source, prefix + relative, b"{}\n")
                write(installed, relative, b"{}\n")
            subprocess.run(["git", "-C", str(self.source), "add", "-A"], check=True)
            for relative in (
                "skills/x/a.py",
                "policy/review_policy.json",
                "capabilities/profiles.json",
                "routines/docs-sync.json",
            ):
                with self.subTest(bundle=bundle, relative=relative):
                    target = installed / relative
                    original = target.read_bytes()
                    target.unlink()
                    result = parity(
                        "--require-both",
                        "--source-root",
                        str(self.source),
                        "--claude-installed",
                        str(self.claude),
                        "--codex-installed",
                        str(self.codex),
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(relative, result.stderr)
                    target.write_bytes(original)

    def test_default_locations_are_discovered(self) -> None:
        """Defaults resolve the Claude installPath and the Codex plugin cache under HOME."""
        home = Path(self.temporary.name) / "home"
        write(
            home,
            ".claude/plugins/installed_plugins.json",
            json.dumps({"plugins": {"coderails@coderails": [{"installPath": str(self.claude)}]}}).encode(),
        )
        write(home, ".codex/plugins/cache/coderails/coderails-codex/0.2.0/skills/x/a.py", b"codex-DRIFT\n")
        result = parity("--source-root", str(self.source), home=str(home))
        self.assertEqual(result.returncode, 1)
        self.assertIn("codex", result.stdout)
        self.assertNotIn("DIFF claude", result.stdout)


class Mirrors(unittest.TestCase):
    """(j) Codex mirrors are byte copies and every new file stays under 400 lines."""

    FILES = (
        "teardown_steps",
        "retro",
        "retro_check",
        "handoff_derive",
        "proof",
        "orders",
        "decision_record",
        "memory_reasons",
    )

    def test_mirrors_identical_and_short(self) -> None:
        """Each shared lib equals its packages/codex copy; the new ones are under 400 lines."""
        for name in self.FILES:
            body = (REPO / f"scripts/lib/{name}.py").read_bytes()
            self.assertEqual(body, (REPO / f"packages/codex/scripts/lib/{name}.py").read_bytes(), name)
            self.assertLess(len(body.splitlines()), 400, name)

    def test_stale_hand_written_lessons_prose_is_gone(self) -> None:
        """teardown.md no longer tells the model to assemble the retro by hand or to hand-write lessons."""
        text = (REPO / "skills/agentic-loop/teardown.md").read_text()
        for stale in (
            "hand-written lessons",
            "Written at `schema_version` 2",
            "| `review_themes`, `raw_notes` | Free-form. |",
        ):
            self.assertNotIn(stale, text)
        self.assertIn("retro.py assemble", text)
        self.assertIn("Schema 3 field spec", text)
        skill = (REPO / "skills/agentic-loop/SKILL.md").read_text()
        self.assertIn("scripts/lib/retro.py", skill)
        self.assertNotIn("Assemble `retro.json` (`schema_version` 2)", skill)


if __name__ == "__main__":
    unittest.main()
