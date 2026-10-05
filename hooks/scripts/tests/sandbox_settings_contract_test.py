"""Pin every sandbox policy key, path substitution and input refusal."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ROOT, ArtifactCase
from scripts.lib.artifact_io import array_value, read_object
from scripts.sandbox.render_settings import main, render_settings


class SettingsContractTests(ArtifactCase):
    """Retain allow-only writes and explicit executable-surface denies."""

    def test_full_rendered_policy(self) -> None:
        """All required srt fields and narrow provider paths survive literal substitution."""
        home = self.directory / "home"
        scratch = self.directory / "scratch"
        shared_tmp = self.directory / "shared-tmp"
        primary = self.directory / "primary/.git"
        for path in (home, scratch, shared_tmp, primary):
            path.mkdir(parents=True)
        for name in ("clone", "pipe|clone", 'quoted"clone'):
            workdir = scratch / name
            workdir.mkdir()
            project_state = Path(f"/private/tmp/claude-{os.getuid()}") / str(workdir).replace("/", "-")
            self.addCleanup(project_state.rmdir)
            output = self.directory / f"{name}.json"
            with patch.dict(os.environ, {"HOME": str(home), "TMPDIR": str(shared_tmp) + "/"}):
                render_settings(str(workdir), str(scratch), str(output))
            data = read_object(output)
            for section, keys in (
                ("network", ("allowedDomains", "deniedDomains")),
                ("filesystem", ("denyRead", "allowWrite", "denyWrite")),
            ):
                for key in keys:
                    self.assertIsInstance(data[section][key], list, f"{section}.{key}")
            filesystem = data["filesystem"]
            self.assertEqual(filesystem["allowWrite"], [str(scratch), str(project_state)])
            self.assertNotIn(str(project_state.parent), filesystem["allowWrite"])
            for path in (home / ".claude.json", home / ".claude", home, primary, shared_tmp, workdir):
                self.assertNotIn(str(path), filesystem["allowWrite"])
            self.assertFalse(filesystem.get("allowGitConfig", False))
            for domain in ("api.anthropic.com", "github.com"):
                self.assertIn(domain, data["network"]["allowedDomains"])
            self.assertNotIn("%%", output.read_text())
            self.assertFalse(any(line.lstrip().startswith("//") for line in output.read_text().splitlines()))
            self.assertFalse(
                any(
                    str(value).startswith("~")
                    for key in ("denyRead", "allowWrite", "denyWrite")
                    for value in array_value(filesystem[key])
                )
            )

    def test_preconditions_and_missing_arguments(self) -> None:
        """Name invalid paths and reject missing CLI arguments without producing output."""
        output = self.directory / "settings.json"
        for path, reason in (("relative/path", "absolute"), (str(self.directory / "missing"), "missing")):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, reason):
                render_settings(path, str(self.directory), str(output))
            self.assertFalse(output.exists())
        self.assertEqual(main([str(self.directory)]), 1)

    def test_launcher_preconditions_name_failed_boundary(self) -> None:
        """Missing arguments and non-repository directories fail before credentials or sandboxing."""
        launcher = ROOT / "scripts/sandbox/spawn_sandboxed_worker.py"
        environment = {key: value for key, value in os.environ.items() if key != "CLAUDE_CODE_SESSION_ID"}
        for arguments, reason in (
            ([], "worktree"),
            ([str(self.directory), str(self.path), "fixture"], "git-common-dir"),
        ):
            result = subprocess.run(
                [sys.executable, str(launcher), *arguments],
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn(reason, result.stderr)


if __name__ == "__main__":
    unittest.main()
