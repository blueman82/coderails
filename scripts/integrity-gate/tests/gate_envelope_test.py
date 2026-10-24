"""Keep the trusted attestor boundary narrow and the diff size finite."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import integrity_policy
from gate_policy_test import EvidenceFixture  # type: ignore[import-not-found]
from integrity_http import Client
from integrity_policy import gate_pr


class GateEnvelopeTests(unittest.TestCase):
    """Check both sides of the protected source and input size boundaries."""

    def gate(self, client: EvidenceFixture, maximum: int = 786432) -> int:
        """Run the real policy with a local evidence fixture."""
        with redirect_stdout(io.StringIO()):
            return gate_pr(client, 7, maximum, 0)

    def test_unrelated_plugin_paths_can_attest(self) -> None:
        """An ordinary plugin change must remain eligible for review."""
        for filename in (
            "skills/dashboard/page.ts",
            "launchd/job.plist",
            "scripts/merge.py",
            "scripts/lib/eval_artifact.py",
            "hooks/scripts/lib/pr_merge_gate.py",
            "packages/codex/scripts/merge.py",
            "config.schema.json",
        ):
            with self.subTest(filename=filename):
                client = EvidenceFixture()
                client.files = [{"filename": filename}]
                self.assertEqual(self.gate(client), 0)
                self.assertEqual(client.posts[-1][1], "success")

    def test_import_overrides_remain_protected(self) -> None:
        """A package or compiled module can replace a trusted Python import."""
        for filename in (
            "argparse.py",
            "argparse/__init__.py",
            "json.py",
            "scripts/lib/eval_integrity/__init__.py",
            "scripts/lib/eval_signing.cpython-312-x86_64-linux-gnu.so",
            "scripts/lib/config/__init__.py",
            "scripts/lib/artifact_io/__init__.py",
        ):
            with self.subTest(filename=filename):
                client = EvidenceFixture()
                client.files = [{"filename": filename}]
                self.assertEqual(self.gate(client), 0)
                self.assertEqual(client.posts[-1][1], "failure")
                self.assertNotIn("diff", client.calls)

    def test_diff_boundary_is_inclusive_and_bounded(self) -> None:
        """The gate admits the limit and refuses the next byte."""
        limit = 786432
        prefix = "diff --git a/docs/safe.txt b/docs/safe.txt\n"
        for size, state in ((566762, "success"), (limit, "success"), (limit + 1, "failure")):
            with self.subTest(size=size):
                client = EvidenceFixture()
                client.diff = prefix + "x" * (size - len(prefix) - 1) + "\n"
                self.assertEqual(self.gate(client, maximum=limit), 0)
                self.assertEqual(client.posts[-1][1], state)

    def test_raw_crlf_diff_boundary_through_transport(self) -> None:
        """Curl output keeps CRLF bytes through HTTP parsing and the gate."""
        limit = 786432
        prefix = b"diff --git a/docs/safe.txt b/docs/safe.txt\r\n"
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "response"
            curl = Path(directory) / "curl"
            curl.write_text(
                f"#!{sys.executable}\nimport sys\n" f"sys.stdout.buffer.write(open({str(payload)!r}, 'rb').read())\n"
            )
            curl.chmod(0o700)
            transport = Client("owner/repo", "fixture-token")
            transport.curl = str(curl)
            for size, state in ((limit, "success"), (limit + 1, "failure")):
                with self.subTest(size=size):
                    diff = prefix + b"x" * (size - len(prefix) - 2) + b"\r\n"
                    payload.write_bytes(diff + b"\n200")
                    client = EvidenceFixture()
                    client.diff = transport.get("pulls/7", "application/vnd.github.v3.diff")
                    self.assertEqual(len(client.diff.encode()), size)
                    self.assertTrue(client.diff.endswith("\r\n"))
                    self.assertEqual(self.gate(client, maximum=limit), 0)
                    self.assertEqual(client.posts[-1][1], state)

    def test_missing_stdlib_names_refuses_attestation(self) -> None:
        """An older runtime cannot silently weaken the import boundary."""
        client = EvidenceFixture()
        client.files = [{"filename": "config.schema.json"}]
        with patch.object(integrity_policy, "STDLIB_MODULES", None):
            self.assertEqual(self.gate(client), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("reason=unsupported_python_runtime", client.posts[-1][2])
        self.assertNotIn("diff", client.calls)


if __name__ == "__main__":
    unittest.main()
