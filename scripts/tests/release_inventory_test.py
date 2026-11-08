"""Exercise release inventory edge cases against private Git and install fixtures."""

from __future__ import annotations

import ast
import os
import socket
import subprocess
import unittest
from pathlib import Path
from typing import cast

from scripts.tests import installed_parity_test, release_manifest_test


class ReleaseInventoryTests(unittest.TestCase):
    """Check modes, complete assets, entry types, exclusions and schema types."""

    def setUp(self) -> None:
        """Use the existing private fixture builders without duplicating their tests."""
        self.manifest = release_manifest_test.ReleaseManifestTests()
        self.manifest.setUp()
        self.addCleanup(self.manifest.doCleanups)
        self.parity = installed_parity_test.InstalledParityTests()
        self.parity.setUp()
        self.addCleanup(self.parity.doCleanups)

    def strict(self) -> subprocess.CompletedProcess[str]:
        """Run strict parity only on the private fixture roots."""
        case = self.parity
        return installed_parity_test.parity(
            "--require-both",
            "--source-root",
            str(case.source),
            "--claude-installed",
            str(case.claude),
            "--codex-installed",
            str(case.codex),
        )

    def test_manifest_refuses_installed_execute_bit_drift(self) -> None:
        """Identical bytes cannot hide a lost executable hook permission."""
        case = self.manifest
        case.write("hooks/run.py", b"pass\n")
        (case.root / "hooks/run.py").chmod(0o755)
        case.git("add", ".")
        case.git("commit", "-qm", "executable hook")
        case.copy("hooks/run.py", case.claude / "hooks/run.py")
        (case.claude / "hooks/run.py").chmod(0o755)
        snapshot = case.snapshot()
        self.assertEqual(case.verify(snapshot).returncode, 0)
        (case.claude / "hooks/run.py").chmod(0o644)
        self.assertIn("installed_file_mode", case.verify(snapshot).stderr)

    def test_parity_refuses_installed_execute_bit_drift(self) -> None:
        """Parity must compare permissions as well as identical hook bytes."""
        source = self.parity.source / "skills/x/a.py"
        source.chmod(0o755)
        subprocess.run(["git", "-C", str(self.parity.source), "add", "skills/x/a.py"], check=True)
        (self.parity.claude / "skills/x/a.py").chmod(0o755)
        self.assertEqual(self.strict().returncode, 0)
        (self.parity.claude / "skills/x/a.py").chmod(0o644)
        self.assertNotEqual(self.strict().returncode, 0)

    def test_candidate_refuses_execute_drift_hidden_from_git_status(self) -> None:
        """Disabling Git's mode detection cannot remove approved executable intent."""
        case = self.manifest
        selections = (("hooks/run.py", case.claude), ("packages/codex/hooks/run.py", case.codex))
        for relative, installed in selections:
            case.write(relative, b"pass\n")
            (case.root / relative).chmod(0o755)
            case.copy(relative, installed / "hooks/run.py")
            (installed / "hooks/run.py").chmod(0o755)
        case.git("add", ".")
        case.git("commit", "-qm", "executable hook")
        snapshot = case.snapshot()
        case.git("config", "core.filemode", "false")
        self.assertEqual(case.verify(snapshot).returncode, 0)
        for relative, installed in selections:
            with self.subTest(relative=relative):
                (case.root / relative).chmod(0o644)
                (installed / "hooks/run.py").chmod(0o644)
                self.assertEqual(case.git("status", "--porcelain"), "")
                self.assertIn("source_file_mode", case.verify(snapshot).stderr)
                (case.root / relative).chmod(0o755)
                (installed / "hooks/run.py").chmod(0o755)
        self.assertEqual(case.verify(snapshot).returncode, 0)

    def test_index_inventory_preserves_tabs_and_newlines_in_paths(self) -> None:
        """NUL-delimited Git entries keep path delimiters separate from mode metadata."""
        case = self.manifest
        paths = ("hooks/tab\tname.py", "packages/codex/hooks/line\nname.py")
        for relative, installed in zip(paths, (case.claude, case.codex)):
            case.write(relative, b"pass\n")
            case.copy(relative, installed / "hooks" / Path(relative).name)
        case.git("add", ".")
        case.git("commit", "-qm", "delimited paths")
        snapshot = case.snapshot()
        self.assertEqual(case.verify(snapshot).returncode, 0)
        (case.codex / "hooks/line\nname.py").unlink()
        self.assertIn("installed_file_missing", case.verify(snapshot).stderr)

    def test_hidden_index_flags_cannot_bind_uncommitted_runtime_bytes(self) -> None:
        """A clean status with index suppression is not proof of committed source bytes."""
        case = self.manifest
        relative = "hooks/hooks.json"
        original = (case.root / relative).read_bytes()
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                case.git("update-index", f"--{flag}", relative)
                try:
                    preserved = case.run_cli("snapshot", "--source-root", str(case.root), "--config", str(case.config))
                    self.assertEqual(preserved.returncode, 0, preserved.stderr)
                    (case.root / relative).write_bytes(b"changed\n")
                    (case.claude / relative).write_bytes(b"changed\n")
                    self.assertEqual(case.git("status", "--porcelain"), "")
                    result = case.run_cli("snapshot", "--source-root", str(case.root), "--config", str(case.config))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("source_file_uncommitted", result.stderr)
                finally:
                    (case.root / relative).write_bytes(original)
                    (case.claude / relative).write_bytes(original)
                    case.git("update-index", f"--no-{flag}", relative)

    def test_importable_modules_outside_known_directories_are_runtime(self) -> None:
        """Root modules, packages and extension modules cannot bypass extra-file checks."""
        snapshot = self.manifest.snapshot()
        for relative in ("argparse.py", "argparse/__init__.py", "argparse.so"):
            with self.subTest(relative=relative):
                target = self.manifest.claude / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"unverified module\n")
                try:
                    self.assertIn("installed_file_extra", self.manifest.verify(snapshot).stderr)
                finally:
                    target.unlink()

    def test_untracked_root_modules_refuse_strict_parity(self) -> None:
        """Source selection must also reject untracked root import-shadow modules."""
        installed_parity_test.write(self.parity.source, "argparse.py", b"unverified module\n")
        result = self.strict()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("untracked runtime source", result.stderr)

    def test_source_binding_accepts_git_sha256_object_format(self) -> None:
        """Object verification uses the selected repository's native object hash."""
        case = self.manifest
        (case.root / ".git").rename(case.root.parent / "original-git")
        case.git("init", "-q", "--object-format=sha256")
        case.git("config", "user.email", "test@example.com")
        case.git("config", "user.name", "Test")
        case.git("remote", "add", "origin", "git@github.com:blueman82/coderails.git")
        case.git("add", ".")
        case.git("commit", "-qm", "SHA256 fixture")
        snapshot = case.snapshot()
        self.assertEqual(len(str(snapshot["commit"])), 64)
        result = case.verify(snapshot)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extra_symlinked_import_package_refuses_manifest(self) -> None:
        """Package directories must not escape link checks through file filtering."""
        case = self.manifest
        snapshot = case.snapshot()
        package = case.root.parent / "external-package"
        package.mkdir()
        (package / "__init__.py").write_bytes(b"unused package\n")
        (case.claude / "argparse").symlink_to(package, target_is_directory=True)
        self.assertIn("installed_path_symlink", case.verify(snapshot).stderr)

    def test_ignored_local_tool_modules_are_not_bundle_inputs(self) -> None:
        """Ignored private tooling cannot shadow ordinary root module imports."""
        case = self.manifest
        case.write(".gitignore", b".local-tools/\n")
        case.git("add", ".gitignore")
        case.git("commit", "-qm", "private tooling state")
        case.write(".local-tools/tool.py", b"local tooling\n")
        self.assertEqual(case.verify(case.snapshot()).returncode, 0)
        installed_parity_test.write(self.parity.source, ".gitignore", b".local-tools/\n")
        installed_parity_test.write(self.parity.source, ".local-tools/tool.py")
        result = self.strict()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_strict_requires_tracked_nonruntime_assets(self) -> None:
        """A tracked document must exist even when all runtime files remain."""
        case = self.parity
        installed_parity_test.write(case.source, "docs/guide.md")
        installed_parity_test.write(case.claude, "docs/guide.md")
        case_source = str(case.source)
        subprocess.run(["git", "-C", case_source, "add", "-A"], check=True)
        self.assertEqual(self.strict().returncode, 0)
        (case.claude / "docs/guide.md").unlink()
        self.assertNotEqual(self.strict().returncode, 0)
        self.assertIn("docs/guide.md", self.strict().stderr)

    def test_special_installed_entries_refuse_without_reading_them(self) -> None:
        """Extra FIFOs and sockets cannot silently disappear from inventory checks."""
        for kind in ("fifo", "socket"):
            with self.subTest(kind=kind):
                case = self.manifest
                snapshot = case.snapshot()
                first = case.claude / "hooks/special"
                second = self.parity.claude / "hooks/special"
                sockets: list[socket.socket] = []
                try:
                    for target in (first, second):
                        if kind == "fifo":
                            os.mkfifo(target)
                        else:
                            endpoint = socket.socket(socket.AF_UNIX)
                            sockets.append(endpoint)
                            endpoint.bind(str(target))
                    with self.subTest(check="manifest"):
                        self.assertIn("installed_path_type", case.verify(snapshot).stderr)
                    with self.subTest(check="parity"):
                        self.assertNotEqual(self.strict().returncode, 0)
                finally:
                    for endpoint in sockets:
                        endpoint.close()
                    for target in (first, second):
                        target.unlink(missing_ok=True)

    def test_excluded_cache_links_do_not_fail_either_check(self) -> None:
        """Unconditional cache exclusions precede link and entry-type validation."""
        snapshot = self.manifest.snapshot()
        for root in (self.manifest.claude, self.parity.claude):
            for relative in ("unused.pyc", ".DS_Store", "__pycache__/ignored"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(root / "not-present")
        result = self.manifest.verify(snapshot)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.strict()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_schema_requires_integer_one(self) -> None:
        """JSON booleans and floats are not integer schema versions."""
        snapshot = self.manifest.snapshot()
        for version in (True, 1.0):
            with self.subTest(version=version):
                snapshot["schema_version"] = version
                self.assertIn("manifest_invalid", self.manifest.verify(snapshot).stderr)

    def test_manifest_requires_shared_graph_dependencies(self) -> None:
        """Canonical graph modules used by installed scripts are runtime files."""
        case = self.manifest
        module = ast.parse((Path(__file__).resolve().parents[1] / "installer/files.py").read_text())
        declaration = next(
            node
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "SHARED_MODULES" for target in node.targets)
        )
        values: object = ast.literal_eval(declaration.value)
        assert isinstance(values, tuple)
        names = cast("tuple[object, ...]", values)
        assert all(isinstance(name, str) for name in names)
        paths = [f"packages/graph-semantics/{name}" for name in names]
        for relative in paths:
            case.write(relative, b"value = 1\n")
            case.copy(relative, case.claude / relative)
        case.git("add", ".")
        case.git("commit", "-qm", "canonical graph module")
        snapshot = case.snapshot()
        self.assertEqual(case.verify(snapshot).returncode, 0)
        for relative in paths:
            with self.subTest(relative=relative):
                target = case.claude / relative
                target.unlink()
                self.assertIn("installed_file_missing", case.verify(snapshot).stderr)
                target.write_bytes(b"changed\n")
                self.assertIn("installed_file_changed", case.verify(snapshot).stderr)
                case.copy(relative, target)

    def test_parity_excludes_cache_only_untracked_directories(self) -> None:
        """Directory collapsing cannot turn excluded cache files into runtime inputs."""
        case = self.parity
        installed_parity_test.write(case.source, ".gitignore", b"*.pyc\n")
        installed_parity_test.write(case.source, "scripts/orphan/module.pyc")
        result = self.strict()
        self.assertEqual(result.returncode, 0, result.stderr)
        installed_parity_test.write(case.source, "scripts/orphan/module.py")
        result = self.strict()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("untracked runtime source", result.stderr)

    def test_manifest_requires_lifecycle_scripts_and_memory_seeds(self) -> None:
        """Installed setup, cleanup and seed inputs must be present and unchanged."""
        case = self.manifest
        paths = (
            "launchd/install_dashboard_agent.py",
            "starter-memory/feedback_example.md",
            "uninstall.py",
            "examples/dashboard-config.json",
            ".agents/plugins/marketplace.json",
            "pyproject.toml",
        )
        for relative in paths:
            case.write(relative, b"lifecycle input\n")
            case.copy(relative, case.claude / relative)
        case.git("add", ".")
        case.git("commit", "-qm", "lifecycle inputs")
        snapshot = case.snapshot()
        self.assertEqual(case.verify(snapshot).returncode, 0)
        for relative in paths:
            with self.subTest(relative=relative):
                target = case.claude / relative
                target.unlink()
                self.assertIn("installed_file_missing", case.verify(snapshot).stderr)
                target.write_bytes(b"changed\n")
                self.assertIn("installed_file_changed", case.verify(snapshot).stderr)
                case.copy(relative, target)

    def test_parity_refuses_untracked_lifecycle_inputs(self) -> None:
        """Source inventory must cover setup assets as well as ordinary hook files."""
        case = self.parity
        for relative in (
            "launchd/new.py",
            "starter-memory/feedback_new.md",
            "uninstall.py",
            "examples/dashboard-config.json",
            ".agents/plugins/marketplace.json",
            "pyproject.toml",
        ):
            with self.subTest(relative=relative):
                installed_parity_test.write(case.source, relative)
                try:
                    result = self.strict()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("untracked runtime source", result.stderr)
                finally:
                    (case.source / relative).unlink()


if __name__ == "__main__":
    unittest.main()
