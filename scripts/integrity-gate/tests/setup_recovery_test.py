"""Exercise real Python setup CLI recovery with inert local command fixtures."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SetupRecoveryTests(unittest.TestCase):
    """No fixture can reach GitHub, sudo, credential collection or installed paths."""

    def run_setup(
        self, scenario: str, dry_run: bool
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]], dict[str, str]]:
        """Execute the setup CLI against a private PATH with an exact argv recorder."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            source = Path(__file__).with_name("setup_command_fixture.py").read_text()
            (binary / "gh").write_text(f"#!{sys.executable}\n" + source)
            for name in ("curl", "git", "sudo"):
                (binary / name).write_text(f"#!{sys.executable}\nraise SystemExit(98)\n")
            for path in binary.iterdir():
                path.chmod(0o755)
            args = [sys.executable, str(Path(__file__).resolve().parents[1] / "setup.py")]
            if dry_run:
                args.append("--dry-run")
            result = subprocess.run(
                args,
                input="\n\n",
                capture_output=True,
                text=True,
                check=False,
                env={
                    **os.environ,
                    "HOME": str(root),
                    "PATH": str(binary),
                    "INTEGRITY_SETUP_FIXTURE": str(root),
                    "INTEGRITY_SETUP_SCENARIO": scenario,
                },
            )
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            counts = {path.name: path.read_text() for path in root.glob("*-count")}
            return result, calls, counts

    def test_failed_retry_names_access_failure_without_auth_mutation(self) -> None:
        """Exactly one Enter-triggered retry fails without invoking auth login."""
        result, calls, counts = self.run_setup("repo-fail", True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("gh retry failed; check GitHub connectivity and repository access", result.stderr)
        self.assertEqual(counts["repo-count"], "2")
        self.assertTrue(all(call[:2] == ["repo", "view"] for call in calls))

    def test_enter_recovery_reaches_read_only_dry_run(self) -> None:
        """A successful single retry resolves the repo and never collects credentials."""
        result, calls, counts = self.run_setup("repo-recover", True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Would configure the product-neutral integrity gate for octo/coderails", result.stdout)
        self.assertEqual(counts["repo-count"], "2")
        self.assertTrue(all(call[:2] == ["repo", "view"] for call in calls))

    def test_malformed_rules_json_recovers_then_cancellation_prevents_post(self) -> None:
        """Malformed JSON is retried once; cancelling the reviewed proposal stops setup."""
        result, calls, counts = self.run_setup("rules-recover", False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Could not read valid JSON from GitHub", result.stderr)
        self.assertIn("ruleset creation cancelled; validator installation not started", result.stderr)
        self.assertEqual(counts["rules-count"], "2")
        self.assertTrue(all("POST" not in call and call[:2] != ["auth", "login"] for call in calls))


if __name__ == "__main__":
    unittest.main()
