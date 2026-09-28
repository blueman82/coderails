"""Verify credential-safe transport and reviewed ruleset setup using local mocks."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_http import Client, IntegrityError, credentials
from integrity_setup import configure_ruleset, ruleset_matches, ruleset_payload


class TransportTests(unittest.TestCase):
    """No fixture performs a network request or privileged operation."""

    def test_http_failure_and_transport_diagnostics_hide_credentials(self) -> None:
        """Transport and HTTP failures cannot masquerade as valid evidence."""
        client = Client("owner/repo", "private-fixture-token", "machine")
        with patch("integrity_http.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "{}\n403")
            with self.assertRaises(IntegrityError) as caught:
                client.get("pulls/7")
            self.assertNotIn(client.token, str(caught.exception))
            run.return_value = subprocess.CompletedProcess([], 1, "")
            with self.assertRaises(IntegrityError) as caught:
                client.get("pulls/7")
            self.assertNotIn(client.token, str(caught.exception))
            run.return_value = subprocess.CompletedProcess([], 0, "{}\n200")
            self.assertEqual(client.get_object("pulls/7"), {})

    def test_live_identity_before_every_status(self) -> None:
        """Refuse all status mutations for a token belonging to another account."""
        client = Client("owner/repo", "fixture-token", "machine")
        with (
            patch.object(client, "get_object", return_value={"login": "other"}),
            patch.object(client, "request") as request,
        ):
            with self.assertRaisesRegex(IntegrityError, "identity mismatch"):
                client.post_status("a" * 40, "success", "description")
            request.assert_not_called()
        with (
            patch.object(client, "get_object", return_value={"login": "machine"}) as identity,
            patch.object(client, "request", return_value="201") as request,
        ):
            client.post_status("a" * 40, "pending", "pending")
            client.post_status("a" * 40, "success", "success")
            self.assertEqual(identity.call_count, 2)
            self.assertEqual(request.call_count, 2)

    def test_credentials_first_line_and_required_keys(self) -> None:
        """Credentials are literal data with first matching keys winning."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "creds"
            path.write_text("GH_TOKEN=literal=$(no-execution)\nGH_TOKEN=later\nMACHINE_USER=machine\n")
            self.assertEqual(credentials(path)["GH_TOKEN"], "literal=$(no-execution)")
            path.write_text("GH_TOKEN=\nMACHINE_USER=machine\n")
            with self.assertRaises(IntegrityError):
                credentials(path)

    def test_review_before_create_and_verify_after(self) -> None:
        """Only affirmative owner approval permits the exact printed ruleset creation."""
        expected = ruleset_payload()
        self.assertTrue(ruleset_matches(expected))
        self.assertFalse(ruleset_matches(dict(expected, bypass_actors=[{"actor_id": 1}])))
        with (
            patch("integrity_setup.gh_array", return_value=[]),
            patch("builtins.input", return_value="n"),
            patch("integrity_setup.subprocess.run") as run,
        ):
            with self.assertRaisesRegex(IntegrityError, "cancelled"):
                configure_ruleset("owner/repo")
            run.assert_not_called()
        with (
            patch("integrity_setup.gh_array", side_effect=[[], [expected]]),
            patch("builtins.input", return_value="y"),
            patch("integrity_setup.subprocess.run") as run,
        ):
            run.return_value = subprocess.CompletedProcess([], 0)
            configure_ruleset("owner/repo")
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), expected)
            self.assertIn("POST", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
