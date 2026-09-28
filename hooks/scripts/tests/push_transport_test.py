"""Verify local push outcomes, lease flags and remote rejection diagnostics."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.workflow_push_fixture import PushFixture


class PushTransportTests(unittest.TestCase):
    """Use actual local Git pushes and inert protocol-output controls, never GitHub."""

    def test_lease_flag_and_success_with_only_remote_lines(self) -> None:
        """Only the explicit lease flag changes argv; filtered display cannot fail success."""
        for arguments, mode in (((), ""), (("--force-with-lease",), ""), ((), "remote-only")):
            with self.subTest(arguments=arguments, mode=mode), tempfile.TemporaryDirectory() as directory:
                fixture = PushFixture(Path(directory))
                fixture.record_pushes()
                (fixture.repo / "base.txt").write_text("modified")
                result = fixture.push(*arguments, mode=mode)
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertIn("✓ Pushed", output)
                self.assertEqual("--force-with-lease" in fixture.push_arguments()[-1], bool(arguments))
                self.assertEqual(
                    fixture.git(fixture.repo, "rev-parse", "origin/feature"),
                    fixture.git(fixture.repo, "rev-parse", "HEAD"),
                )

    def test_nonfastforward_and_stale_lease_are_failures(self) -> None:
        """A competing clone's update rejects the push while retaining the local commit."""
        for arguments in ((), ("--force-with-lease",)):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                fixture = PushFixture(Path(directory))
                fixture.git(fixture.repo, "push", "-u", "origin", "feature")
                fixture.advance_remote()
                before = fixture.git(fixture.repo, "rev-parse", "HEAD")
                (fixture.repo / "base.txt").write_text("local change")
                result = fixture.push(*arguments)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertNotIn("✓ Pushed", output)
                self.assertIn("stale" if arguments else "rejected", output)
                self.assertIn("Push failed", output)
                self.assertNotEqual(before, fixture.git(fixture.repo, "rev-parse", "HEAD"))

    def test_server_reason_survives_and_deceptive_success_fails(self) -> None:
        """Preserve server remote lines on rejection and require the remote tracking SHA."""
        for mode in ("server-reject", "deceptive"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                fixture = PushFixture(Path(directory))
                fixture.git(fixture.repo, "push", "-u", "origin", "feature")
                if mode == "server-reject":
                    hook = fixture.origin / "hooks/pre-receive"
                    hook.write_text(
                        f"#!{sys.executable}\nimport sys\n"
                        'print("GH006: changes must be made through a pull request", file=sys.stderr)\n'
                        "raise SystemExit(1)\n"
                    )
                    hook.chmod(0o755)
                else:
                    fixture.record_pushes()
                (fixture.repo / "base.txt").write_text("local change")
                result = fixture.push(mode=mode)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertNotIn("✓ Pushed", output)
                if mode == "server-reject":
                    self.assertIn("GH006", output)
                    self.assertIn("through a pull request", output)
                else:
                    self.assertIn("does not match local HEAD", output)


if __name__ == "__main__":
    unittest.main()
