"""Verify privileged installer predicates with no privileged operations."""

import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/integrity-gate"))
from integrity_install import (
    RUNTIME_FILES,
    classify_mode,
    diff_before_promote,
    other_instance_labels,
    promote,
    render_plist,
    same_file,
)

ROOT = Path(__file__).resolve().parents[3]


class IntegrityInstallTests(unittest.TestCase):
    """Check first installs, promotion diffs, inode identity and XML escaping."""

    def test_plist_roundtrip_with_literal_special_paths(self) -> None:
        """Render executable and credential paths as data without XML injection."""
        template = ROOT / "scripts/integrity-gate/com.coderails.integrity-gate.plist.template"
        rendered = render_plist(template, Path("/etc/a&b/runner.py"), Path("/etc/c<d/creds"), "owner/repo")
        parsed = plistlib.loads(rendered)
        self.assertIn("/etc/a&b/runner.py", parsed["ProgramArguments"])
        self.assertEqual(parsed["EnvironmentVariables"]["INTEGRITY_GATE_CREDS"], "/etc/c<d/creds")
        self.assertEqual(parsed["EnvironmentVariables"]["INTEGRITY_GATE_REPO"], "owner/repo")
        with self.assertRaises(ValueError):
            render_plist(template, Path("/runner"), Path("/creds"), "")

    def test_diff_same_file_and_other_instances(self) -> None:
        """Compare root-owned copies before promotion and detect hardlinked destinations."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, target = base / "source", base / "target"
            source.write_text("old\n")
            self.assertTrue(diff_before_promote(source, target, "runner"))
            target.write_text("new\n")
            self.assertFalse(diff_before_promote(source, target, "runner"))
            self.assertFalse(same_file(source, target))
            target.unlink()
            os.link(source, target)
            self.assertTrue(same_file(source, target))
            own, other = base / "own.plist", base / "other.plist"
            own.write_bytes(plistlib.dumps({"Label": "own"}))
            other.write_bytes(plistlib.dumps({"Label": "other"}))
            self.assertEqual(other_instance_labels(own, str(base / "*.plist")), ["other"])

    def test_promotes_complete_protected_runtime_and_same_file_credentials(self) -> None:
        """Install every helper locally and preserve same-inode credentials without copying."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            creds = root / "credentials"
            creds.write_text("fixture")
            destination = root / "daemon.plist"
            with (
                patch("integrity_install.sudo", return_value=True) as privileged,
                patch("integrity_install.activate") as activate,
            ):
                promote(ROOT / "scripts/integrity-gate", root, creds, destination, b"fixture plist")
            calls = [call.args[0] for call in privileged.call_args_list]
            installed = [call[-1] for call in calls if call[0] == "install"]
            for filename in RUNTIME_FILES:
                self.assertIn(str(root / filename), installed)
            self.assertNotIn(str(creds), installed)
            self.assertIn(["chmod", "0600", str(creds)], calls)
            self.assertIn(["chown", "root:wheel", str(creds)], calls)
            activate.assert_called_once_with(destination)

    def test_mode_is_honest_on_invalid_visibility(self) -> None:
        """Claim enforcement only for a nonempty rules array."""
        for text in ("", "[]", "{}", '{"error": "denied"}', "invalid"):
            self.assertIn("audit", classify_mode(text))
        self.assertEqual(classify_mode("[{}]"), "MODE: enforced")


if __name__ == "__main__":
    unittest.main()
