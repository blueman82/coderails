"""Exercise release inventory edge cases against private Git and install fixtures."""

from __future__ import annotations

import os
import socket
import subprocess
import unittest

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
        (self.parity.claude / "skills/x/a.py").chmod(0o755)
        self.assertEqual(self.strict().returncode, 0)
        (self.parity.claude / "skills/x/a.py").chmod(0o644)
        self.assertNotEqual(self.strict().returncode, 0)

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
        relative = "packages/graph-semantics/graph_contract.py"
        case.write(relative, b"value = 1\n")
        case.git("add", ".")
        case.git("commit", "-qm", "canonical graph module")
        target = case.claude / relative
        case.copy(relative, target)
        snapshot = case.snapshot()
        self.assertEqual(case.verify(snapshot).returncode, 0)
        target.unlink()
        self.assertIn("installed_file_missing", case.verify(snapshot).stderr)
        target.write_bytes(b"changed\n")
        self.assertIn("installed_file_changed", case.verify(snapshot).stderr)

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


if __name__ == "__main__":
    unittest.main()
