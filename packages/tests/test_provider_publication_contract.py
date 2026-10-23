"""A worker publication command is concrete, prompt-bound, and checked by both provider guards."""

from __future__ import annotations

import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_contract  # noqa: E402

from packages.tests.provider_fixture import Provider  # noqa: E402


class PublicationContractTests(unittest.TestCase):
    """Exercise issued contract records and native guard decisions."""

    def test_worker_contract_requires_exact_publication_command(self) -> None:
        """A correctly hashed but wrong command cannot authorize a worker."""
        for name in ("claude", "codex"):
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                provider = Provider(Path(scratch), name)
                provider.success("begin-wave")
                state = provider.read()
                record = next(iter(state["graph"]["dispatches"].values()))
                expected = shlex.join(
                    [
                        "python3",
                        str(provider.plugin / "scripts/push.py"),
                        "--unit",
                        "1",
                        "--progress",
                        str(provider.path.resolve()),
                    ]
                )
                self.assertEqual(record["contract"]["publication_command"], expected)
                request = provider.request()
                key = "prompt" if name == "claude" else "message"
                self.assertIn(expected, request["tool_input"][key])
                record["contract"]["publication_command"] = "python3 scripts/push.py --unit 2 --progress /tmp/wrong"
                record["prompt_sections_sha256"] = graph_contract.sections_sha256(record["contract"])
                provider.write(state)
                request["tool_input"][key] = request["tool_input"][key].replace(
                    expected, record["contract"]["publication_command"]
                )
                denied = provider.hook("loop_dispatch_guard", request)
                self.assertIn("deny", denied.stdout)
                rows = provider.path.with_name("recovery-trace.jsonl").read_text().splitlines()
                self.assertEqual(json.loads(rows[-1])["reason_code"], "dispatch_publication_mismatch")


if __name__ == "__main__":
    unittest.main()
