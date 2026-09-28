"""Map original installer preflight predicates without privileged or network calls."""

from __future__ import annotations

import io
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_http import IntegrityError, credentials
from integrity_install import (
    check_machine_user_collaborator,
    check_tools,
    classify_mode,
    diff_before_promote,
    other_instance_labels,
    preflight,
    render_plist,
    resolve_repo_slug,
    same_file,
)


class InstallPreflightTests(unittest.TestCase):
    """Use real local files for every credential, link, plist and promotion comparison."""

    def setUp(self) -> None:
        """Allocate an isolated fixture directory."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_required_tools_name_only_missing_runtime_dependencies(self) -> None:
        """Python replaces jq; gh, curl and absolute system Python remain mandatory."""
        with patch("integrity_install.shutil.which", return_value="present"):
            check_tools()

        def locate(name: str) -> str | None:
            """Hide only curl from the isolated tool lookup."""
            return None if name == "curl" else "present"

        with patch("integrity_install.shutil.which", side_effect=locate):
            with self.assertRaises(IntegrityError) as caught:
                check_tools()
            self.assertIn("curl", str(caught.exception))
            self.assertNotIn("gh", str(caught.exception).split("tools:")[-1])
        with patch("integrity_install.shutil.which", return_value=None):
            with self.assertRaises(IntegrityError) as caught:
                check_tools()
            for name in ("gh", "curl"):
                self.assertIn(name, str(caught.exception))
        with (
            patch("integrity_install.shutil.which", return_value="present"),
            patch("integrity_install.Path.is_file", return_value=False),
            self.assertRaisesRegex(IntegrityError, "/usr/bin/python3"),
        ):
            check_tools()

    def test_credentials_absent_empty_missing_and_literal_values(self) -> None:
        """Missing and blank required keys refuse; unrelated OAuth is unnecessary."""
        path = self.root / "credentials"
        with self.assertRaisesRegex(IntegrityError, "credentials file not found at"):
            credentials(path)
        for text in ("", "GH_TOKEN=fixture\n", "GH_TOKEN=\nMACHINE_USER=machine\n"):
            path.write_text(text)
            with self.assertRaises(IntegrityError):
                credentials(path)
        path.write_text("GH_TOKEN=fixture\n")
        with self.assertRaises(IntegrityError) as caught:
            credentials(path)
        self.assertIn("missing a non-empty MACHINE_USER=", str(caught.exception))
        self.assertNotIn("missing a non-empty GH_TOKEN=", str(caught.exception))
        for tail in ("", "CLAUDE_CODE_OAUTH_TOKEN=ignored\n"):
            path.write_text("GH_TOKEN=literal=$(do-not-execute)\nMACHINE_USER=machine\n" + tail)
            self.assertEqual(credentials(path), {"GH_TOKEN": "literal=$(do-not-execute)", "MACHINE_USER": "machine"})
        path.write_text("GH_TOKEN=first\nGH_TOKEN=second\nMACHINE_USER=machine\n")
        self.assertEqual(credentials(path)["GH_TOKEN"], "first")

    def test_collaborator_slug_and_default_stored_machine_identity(self) -> None:
        """Preflight honors stored login, with explicit override and safe argv boundaries."""
        with patch("integrity_install.subprocess.run") as run:
            with self.assertRaisesRegex(IntegrityError, "no machine-user"):
                check_machine_user_collaborator("")
            run.assert_not_called()
            run.return_value = subprocess.CompletedProcess([], 0, "owner/repo\n")
            check_machine_user_collaborator("machine", "fixture-gh")
            self.assertEqual(run.call_args.args[0][-1], "repos/{owner}/{repo}/collaborators/machine")
            self.assertEqual(resolve_repo_slug("fixture-gh"), "owner/repo")
            for code, body in ((1, ""), (0, ""), (0, "malformed")):
                run.return_value = subprocess.CompletedProcess([], code, body)
                with self.assertRaises(IntegrityError):
                    resolve_repo_slug()
            with self.assertRaisesRegex(IntegrityError, 'machine user "machine"'):
                run.return_value = subprocess.CompletedProcess([], 1, "")
                check_machine_user_collaborator("machine")
        path = self.root / "credentials"
        path.write_text("GH_TOKEN=fixture\nMACHINE_USER=stored\n")
        with (
            patch.dict(os.environ, {"TGI_CREDS_SRC": str(path)}, clear=True),
            patch("integrity_install.check_tools"),
            patch("integrity_install.check_machine_user_collaborator") as collaborator,
            patch("integrity_install.resolve_repo_slug", return_value="owner/repo"),
        ):
            self.assertEqual(preflight()[2:], (path, "owner/repo"))
            collaborator.assert_called_once_with("stored")
            with patch.dict(os.environ, {"TGI_MACHINE_USER": "override"}):
                preflight()
            collaborator.assert_called_with("override")

    def test_diff_links_and_other_plists_preserve_root_review(self) -> None:
        """Show real changed bytes and handle inode-equivalent paths without copying."""
        source, target = self.root / "source", self.root / "target"
        source.write_text("original\n")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(diff_before_promote(source, target, "runner"))
            target.write_text("original\n")
            self.assertTrue(diff_before_promote(source, target, "runner"))
            target.write_text("TAMPERED\n")
            self.assertFalse(diff_before_promote(source, target, "runner"))
        for phrase in ("no installed copy yet", "no change", "DIFFERS", "TAMPERED"):
            self.assertIn(phrase, output.getvalue())
        self.assertTrue(same_file(source, source))
        self.assertFalse(same_file(source, target))
        self.assertFalse(same_file(source, self.root / "absent"))
        link = self.root / "link"
        link.symlink_to(source)
        hard = self.root / "hard"
        os.link(source, hard)
        (self.root / "subdir").mkdir()
        for alias in (link, hard, self.root / "subdir/../source"):
            self.assertTrue(same_file(source, alias))
        own, other = self.root / "own.plist", self.root / "other.plist"
        own.write_bytes(plistlib.dumps({"Label": "own"}))
        other.write_bytes(plistlib.dumps({"Label": "other"}))
        self.assertEqual(other_instance_labels(own, str(self.root / "*.plist")), ["other"])
        self.assertEqual(other_instance_labels(own, str(own)), [])
        self.assertEqual(other_instance_labels(own, str(self.root / "missing*.plist")), [])

    def test_plist_and_honest_mode(self) -> None:
        """Bind all runtime paths literally and never overclaim unreadable server policy."""
        template = Path(__file__).resolve().parents[1] / "com.coderails.integrity-gate.plist.template"
        rendered = render_plist(template, Path("/etc/a&b/runner.py"), Path("/etc/c<d/credentials"), "owner/repo")
        self.assertNotIn(b"__INTEGRITY_GATE_", rendered)
        parsed = plistlib.loads(rendered)
        self.assertEqual(parsed["Label"], "com.coderails.integrity-gate")
        self.assertEqual(parsed["ProgramArguments"][:2], ["/usr/bin/python3", "/etc/a&b/runner.py"])
        self.assertEqual(parsed["EnvironmentVariables"]["INTEGRITY_GATE_CREDS"], "/etc/c<d/credentials")
        self.assertEqual(parsed["EnvironmentVariables"]["INTEGRITY_GATE_REPO"], "owner/repo")
        for value in ("[]", "", "not json", "{}"):
            self.assertIn("MODE: audit", classify_mode(value))
        self.assertEqual(classify_mode('[{"type":"pull_request"}]'), "MODE: enforced")


if __name__ == "__main__":
    unittest.main()
