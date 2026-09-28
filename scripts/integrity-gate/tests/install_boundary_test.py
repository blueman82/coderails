"""Keep owner review and launchd root-domain boundaries under local test control."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_http import IntegrityError
from integrity_install import LABEL, activate, sudo

import install as installer


class InstallBoundaryTests(unittest.TestCase):
    """Intercept every privileged operation; never mutate installed paths or launchd."""

    def test_promotion_requires_review_of_changed_or_shared_install(self) -> None:
        """Declining changed/shared runtime promotion prevents all privileged mutations."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for clean, others in ((False, []), (True, ["other-daemon"])):
                output = io.StringIO()
                with (
                    patch(
                        "install.preflight",
                        return_value=(root, root / "daemon.plist", root / "credentials", "owner/repo"),
                    ),
                    patch("install.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]")),
                    patch("install.diff_before_promote", return_value=clean),
                    patch("install.other_instance_labels", return_value=others),
                    patch("builtins.input", return_value="n"),
                    patch("install.promote") as promote,
                    redirect_stdout(output),
                    redirect_stderr(output),
                ):
                    self.assertEqual(installer.main(), 1)
                promote.assert_not_called()
                self.assertIn("installed copy left unchanged", output.getvalue())
                if others:
                    self.assertIn("other-daemon", output.getvalue())
            with (
                patch(
                    "install.preflight", return_value=(root, root / "daemon.plist", root / "credentials", "owner/repo")
                ),
                patch("install.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]")),
                patch("install.diff_before_promote", return_value=True),
                patch("install.other_instance_labels", return_value=[]),
                patch("builtins.input") as ask,
                patch("install.promote") as promote,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(installer.main(), 0)
            ask.assert_not_called()
            promote.assert_called_once()
            self.assertEqual(list(root.iterdir()), [])

    def test_privileged_failures_are_required_unless_explicitly_optional(self) -> None:
        """A failed install operation cannot masquerade as a successful launchd change."""
        with patch("integrity_install.subprocess.run", return_value=subprocess.CompletedProcess([], 1)) as run:
            self.assertFalse(sudo(["launchctl", "print", "system/test"], required=False))
            with self.assertRaisesRegex(IntegrityError, "privileged operation failed"):
                sudo(["install", "source", "destination"])
            self.assertTrue(all(call.args[0][0] == "sudo" for call in run.call_args_list))

    def test_activation_verifies_system_and_reaps_user_ghosts(self) -> None:
        """Bootstrap must be system-owned and surviving per-user instances refuse completion."""
        destination = Path("/fixture/daemon.plist")
        with (
            patch("integrity_install.Path.stat", side_effect=OSError("no console")),
            patch("integrity_install.sudo", side_effect=[False, True, False]),
            self.assertRaisesRegex(IntegrityError, "not registered after bootstrap"),
        ):
            activate(destination)
        with (
            patch("integrity_install.Path.stat") as stat,
            patch("integrity_install.sudo", return_value=True) as command,
            redirect_stdout(io.StringIO()),
        ):
            stat.return_value.st_uid = 501
            with self.assertRaisesRegex(IntegrityError, "per-user ghost"):
                activate(destination)
            calls = [call.args[0] for call in command.call_args_list]
            for domain in ("gui/501", "user/501"):
                self.assertIn(["launchctl", "bootout", f"{domain}/{LABEL}"], calls)
            self.assertIn(["launchctl", "bootstrap", "system", str(destination)], calls)


if __name__ == "__main__":
    unittest.main()
