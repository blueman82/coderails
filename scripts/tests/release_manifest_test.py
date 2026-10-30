"""Check a release candidate against Git, configuration, and two fake installed bundles."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

SCRIPT = Path(__file__).resolve().parents[1] / "release_manifest.py"


class ReleaseManifestTests(unittest.TestCase):
    """Use a small Git repository and private install roots."""

    def setUp(self) -> None:
        """Create a clean fixture commit, config, and two fake installed bundles."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "source"
        self.root.mkdir()
        self.claude = Path(temporary.name) / "claude"
        self.codex = Path(temporary.name) / "codex"
        self.config = Path(temporary.name) / "workflow.config.yaml"
        self.config.write_text("action_authority: advisory\n")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.git("remote", "add", "origin", "git@github.com:blueman82/coderails.git")
        self.branch = self.git("branch", "--show-current")
        self.write(".claude-plugin/plugin.json", b"{}\n")
        self.write("hooks/hooks.json", b'{"hooks":{}}\n')
        self.write("packages/codex/.codex-plugin/plugin.json", b"{}\n")
        self.write("packages/codex/hooks/hooks.json", b'{"hooks":{}}\n')
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        for relative in (".claude-plugin/plugin.json", "hooks/hooks.json"):
            self.copy(relative, self.claude / relative)
        for relative in (".codex-plugin/plugin.json", "hooks/hooks.json"):
            self.copy(f"packages/codex/{relative}", self.codex / relative)

    def git(self, *arguments: str) -> str:
        """Run Git only in the private source repository."""
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], text=True).strip()

    def write(self, relative: str, data: bytes) -> None:
        """Write a tracked source fixture."""
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def copy(self, relative: str, target: Path) -> None:
        """Copy one source byte string into a private installed bundle."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((self.root / relative).read_bytes())

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the CLI with no real user home or installed plugin path."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "HOME": str(self.root.parent / "empty-home")},
        )

    def snapshot(self) -> dict[str, object]:
        """Create one candidate from the exact clean fixture commit."""
        result = self.run_cli("snapshot", "--source-root", str(self.root), "--config", str(self.config))
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(json.loads(result.stdout))

    def verify(self, manifest: dict[str, object]) -> subprocess.CompletedProcess[str]:
        """Check a candidate against the source and both private installs."""
        path = self.root.parent / "candidate.json"
        path.write_text(json.dumps(manifest))
        return self.run_cli(
            "verify",
            str(path),
            "--source-root",
            str(self.root),
            "--config",
            str(self.config),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )

    def test_clean_candidate_binds_repository_ref_commit_tree_and_both_bundles(self) -> None:
        """An exact candidate passes while remaining labelled as a candidate."""
        manifest = self.snapshot()
        self.assertEqual(manifest["status"], "candidate")
        self.assertEqual(manifest["repository"], "github.com/blueman82/coderails")
        self.assertEqual(manifest["commit"], self.git("rev-parse", "HEAD"))
        self.assertNotIn(str(self.config), json.dumps(manifest))
        self.assertEqual(self.verify(manifest).returncode, 0)

    def test_missing_or_changed_installed_file_refuses(self) -> None:
        """A required installed file cannot be omitted or changed."""
        manifest = self.snapshot()
        (self.codex / "hooks/hooks.json").unlink()
        self.assertIn("installed_file_missing", self.verify(manifest).stderr)
        self.copy("packages/codex/hooks/hooks.json", self.codex / "hooks/hooks.json")
        (self.claude / "hooks/hooks.json").write_bytes(b"changed")
        self.assertIn("installed_file_changed", self.verify(manifest).stderr)

    def test_complete_claude_root_keeps_nested_codex_provider_separate(self) -> None:
        """A root bundle includes Codex without weakening either provider's runtime checks."""
        self.write("packages/codex/agents/security-reviewer.toml", b"name = 'codex-only'\n")
        self.git("add", ".")
        self.git("commit", "-qm", "independent nested distribution")
        for relative in self.git("ls-files").splitlines():
            self.copy(relative, self.claude / relative)
        self.copy("packages/codex/agents/security-reviewer.toml", self.codex / "agents/security-reviewer.toml")
        manifest = self.snapshot()
        accepted = self.verify(manifest)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        for installed in (self.claude, self.codex):
            with self.subTest(provider=installed.name):
                target = installed / "hooks/hooks.json"
                content = target.read_bytes()
                target.unlink()
                self.assertIn("installed_file_missing", self.verify(manifest).stderr)
                target.write_bytes(b"changed\n")
                self.assertIn("installed_file_changed", self.verify(manifest).stderr)
                target.write_bytes(content)
                extra = installed / "capabilities/extra.json"
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b"{}\n")
                self.assertIn("installed_file_extra", self.verify(manifest).stderr)
                extra.unlink()
                target.unlink()
                target.symlink_to(self.root / "hooks/hooks.json")
                self.assertIn("installed_path_symlink", self.verify(manifest).stderr)
                target.unlink()
                target.write_bytes(content)
        self.assertEqual(self.verify(manifest).returncode, 0)

    def test_manifest_file_or_hash_cannot_be_removed_or_changed(self) -> None:
        """The verifier recomputes the complete tracked runtime file list and hashes."""
        manifest = self.snapshot()
        files = manifest["files"]
        assert isinstance(files, dict)
        claude = cast("dict[str, object]", files["claude"])
        assert isinstance(claude, dict)
        del claude["hooks/hooks.json"]
        self.assertIn("manifest_files_changed", self.verify(manifest).stderr)
        claude["hooks/hooks.json"] = "0" * 64
        self.assertIn("source_file_changed", self.verify(manifest).stderr)

    def test_dirty_source_or_changed_config_refuses(self) -> None:
        """Git state and effective gate configuration stay bound to the candidate."""
        manifest = self.snapshot()
        self.config.write_text("action_authority: off\n")
        self.assertIn("config_changed", self.verify(manifest).stderr)
        self.config.write_text("action_authority: advisory\n")
        self.write("hooks/hooks.json", b"dirty\n")
        self.assertIn("source_dirty", self.verify(manifest).stderr)

    def test_changed_commit_or_repository_refuses(self) -> None:
        """A different Git identity cannot reuse a candidate."""
        manifest = self.snapshot()
        manifest["repository"] = "github.com/other/repo"
        self.assertIn("repository_changed", self.verify(manifest).stderr)
        manifest = self.snapshot()
        self.write("hooks/new.py", b"pass\n")
        self.git("add", ".")
        self.git("commit", "-qm", "next")
        self.assertIn("commit_changed", self.verify(manifest).stderr)

    def test_changed_ref_or_absent_install_refuses(self) -> None:
        """A new branch at the same commit and a missing provider install both refuse."""
        manifest = self.snapshot()
        self.git("checkout", "-qb", "different")
        self.assertIn("ref_changed", self.verify(manifest).stderr)
        self.git("checkout", "-q", self.branch)
        for path in self.codex.rglob("*"):
            if path.is_file():
                path.unlink()
        self.assertIn("installed_file_missing", self.verify(manifest).stderr)

    def test_missing_config_or_malformed_manifest_refuses(self) -> None:
        """Neither an absent configuration nor a torn manifest can pass."""
        manifest = self.snapshot()
        self.config.unlink()
        self.assertIn("config_missing", self.verify(manifest).stderr)
        self.config.write_text("action_authority: advisory\n")
        manifest["schema_version"] = 2
        self.assertIn("manifest_invalid", self.verify(manifest).stderr)

    def test_lookalike_remote_host_refuses(self) -> None:
        """A URL that only contains github.com as a suffix is not that host."""
        self.git("remote", "set-url", "origin", "https://evilgithub.com/blueman82/coderails.git")
        result = self.run_cli("snapshot", "--source-root", str(self.root), "--config", str(self.config))
        self.assertIn("repository_invalid", result.stderr)

    def test_nested_source_root_and_symlinked_install_directory_refuse(self) -> None:
        """Git identity must bind the file root, and installed bytes cannot come through a link."""
        nested = self.run_cli("snapshot", "--source-root", str(self.root / "hooks"), "--config", str(self.config))
        self.assertIn("source_root_mismatch", nested.stderr)
        manifest = self.snapshot()
        (self.claude / "hooks").rename(self.claude / "hooks-old")
        (self.claude / "hooks").symlink_to(self.root / "hooks", target_is_directory=True)
        self.assertIn("installed_path_symlink", self.verify(manifest).stderr)

    def test_ignored_source_runtime_file_and_extra_installed_file_refuse(self) -> None:
        """An executable file outside Git cannot become unverified plugin code."""
        manifest = self.snapshot()
        (self.claude / "hooks/extra.py").write_bytes(b"pass\n")
        self.assertIn("installed_file_extra", self.verify(manifest).stderr)
        (self.claude / "hooks/extra.py").unlink()
        self.write(".gitignore", b"hooks/extra.py\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore a hook")
        self.write("hooks/extra.py", b"pass\n")
        result = self.run_cli("snapshot", "--source-root", str(self.root), "--config", str(self.config))
        self.assertIn("source_runtime_untracked", result.stderr)

    def test_source_checkout_cannot_be_an_installed_bundle(self) -> None:
        """Matching source bytes do not prove that a provider was installed."""
        manifest = self.snapshot()
        path = self.root.parent / "candidate.json"
        path.write_text(json.dumps(manifest))
        result = self.run_cli(
            "verify",
            str(path),
            "--source-root",
            str(self.root),
            "--config",
            str(self.config),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.root / "packages/codex"),
        )
        self.assertIn("installed_is_source", result.stderr)

    def test_python_cache_files_do_not_change_runtime_inventory(self) -> None:
        """Python cache files made by read-only tools are outside the release file list."""
        self.write(".gitignore", b"__pycache__/\n*.pyc\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore caches")
        cache = self.root / "scripts/__pycache__/reader.cpython-312.pyc"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"cache")
        result = self.run_cli("snapshot", "--source-root", str(self.root), "--config", str(self.config))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_retained_control_files_are_required_and_hashed(self) -> None:
        """Missing or changed policy, capability and routine data cannot pass a release check."""
        paths = (
            "policy/review_policy.json",
            "capabilities/profiles.json",
            "capabilities/mcp.json",
            "routines/docs-sync.json",
        )
        for relative in paths:
            self.write(relative, b"{}\n")
            self.copy(relative, self.claude / relative)
        self.git("add", ".")
        self.git("commit", "-qm", "retained control data")
        manifest = self.snapshot()
        self.assertEqual(self.verify(manifest).returncode, 0)
        for relative in paths:
            with self.subTest(relative=relative):
                target = self.claude / relative
                target.unlink()
                self.assertIn("installed_file_missing", self.verify(manifest).stderr)
                target.write_bytes(b"changed\n")
                self.assertIn("installed_file_changed", self.verify(manifest).stderr)
                self.copy(relative, target)

    def test_ignored_retained_control_data_refuses(self) -> None:
        """Ignored files beside retained policy, capability and routine data remain runtime inputs."""
        self.write(".gitignore", b"policy/extra.json\ncapabilities/extra.json\nroutines/extra.json\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore retained control data")
        for directory in ("policy", "capabilities", "routines"):
            with self.subTest(directory=directory):
                relative = f"{directory}/extra.json"
                self.write(relative, b"{}\n")
                result = self.run_cli("snapshot", "--source-root", str(self.root), "--config", str(self.config))
                self.assertIn("source_runtime_untracked", result.stderr)
                (self.root / relative).unlink()


if __name__ == "__main__":
    unittest.main()
