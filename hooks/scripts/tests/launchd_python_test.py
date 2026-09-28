"""Verify launchd copy persistence and asynchronous unload using inert mocks."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from launchd import launch_agents

ROOT = Path(__file__).resolve().parents[3]


class LaunchAgentsTests(unittest.TestCase):
    """Exercise changes only inside temporary homes with mocked launchctl."""

    def test_install_copies_before_bootstrap_and_reinstall(self) -> None:
        """Bootstrap persistent identical copies and preserve restrictive log modes."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = ROOT / "launchd/com.coderails.routine-sweeper.calendar.plist"
            with patch("launchd.launch_agents.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, "", "")
                for _ in range(2):
                    launch_agents.install_agent(source, home)
                destination = home / "Library/LaunchAgents" / source.name
                self.assertEqual(source.read_bytes(), destination.read_bytes())
                self.assertEqual(destination.stat().st_mode & 0o777, 0o644)
                self.assertEqual(run.call_args_list[-1].args[0][-1], str(destination))
                self.assertEqual(run.call_args_list[-2].args[0][1], "bootout")
                launch_agents.uninstall_agent(source.stem, home)
                launch_agents.uninstall_agent(source.stem, home)
                self.assertFalse(destination.exists())

    def test_failed_bootstrap_and_missing_plists_fail(self) -> None:
        """Refuse missing inputs and surface bootstrap failures."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with self.assertRaisesRegex(ValueError, "no com.coderails.routine-sweeper"):
                launch_agents.routine_plists(home)
            with patch("launchd.launch_agents.subprocess.run") as run:
                run.side_effect = [subprocess.CompletedProcess([], 1), subprocess.CalledProcessError(1, "launchctl")]
                with self.assertRaises(subprocess.CalledProcessError):
                    launch_agents.install_agent(ROOT / "launchd/com.coderails.dashboard.plist", home)

    def test_unload_poll_and_still_loaded_retains_copy(self) -> None:
        """Only delete a dashboard plist once launchctl confirms it unloaded."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            destination = home / "Library/LaunchAgents/com.coderails.dashboard.plist"
            destination.parent.mkdir(parents=True)
            destination.write_text("fixture")
            with patch("launchd.launch_agents.subprocess.run") as run, patch("launchd.launch_agents.time.sleep"):
                run.return_value = subprocess.CompletedProcess([], 0, "", "denied")
                with self.assertRaisesRegex(ValueError, "still loaded after bootout"):
                    launch_agents.uninstall_agent("com.coderails.dashboard", home, wait=True)
                self.assertTrue(destination.exists())
                run.side_effect = [
                    subprocess.CompletedProcess([], 0, "", ""),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 1),
                ]
                launch_agents.uninstall_agent("com.coderails.dashboard", home, wait=True)
                self.assertFalse(destination.exists())

    def test_port_holder_blocks(self) -> None:
        """An occupied dashboard port refuses activation, a missing lsof stands aside."""
        with patch("launchd.launch_agents.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "listener", "")
            with self.assertRaisesRegex(ValueError, "Port 4173"):
                launch_agents.require_dashboard_port()
            run.side_effect = FileNotFoundError()
            launch_agents.require_dashboard_port()


if __name__ == "__main__":
    unittest.main()
