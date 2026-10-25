"""Keep owner review and launchd root-domain boundaries under local test control."""

from __future__ import annotations

import builtins
import io
import runpy
import subprocess
import sys
import unittest
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_http import IntegrityError
from integrity_install import LABEL, activate, sudo


class InstallBoundaryTests(unittest.TestCase):
    """Intercept every privileged operation; never mutate installed paths or launchd."""

    def test_retired_entrypoint_exits_before_legacy_installer_import(self) -> None:
        """The public command cannot reach legacy preflight, promotion, or sudo."""
        original_import = builtins.__import__

        def reject_legacy_import(
            name: str,
            globals: Mapping[str, object] | None = None,
            locals: Mapping[str, object] | None = None,
            fromlist: Sequence[str] | None = (),
            level: int = 0,
        ) -> ModuleType:
            if name in {"integrity_install", "integrity_http"}:
                raise AssertionError(f"legacy installer imported: {name}")
            return original_import(name, globals, locals, fromlist or (), level)

        output = io.StringIO()
        with (
            patch("builtins.__import__", side_effect=reject_legacy_import),
            redirect_stdout(output),
            redirect_stderr(output),
            self.assertRaises(SystemExit) as exit_status,
        ):
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "install.py"), run_name="__main__")
        self.assertEqual(exit_status.exception.code, 1)
        self.assertIn("GitHub Actions", output.getvalue())

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
