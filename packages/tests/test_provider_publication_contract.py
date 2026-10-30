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
from packages.tests.test_provider_add_unit_contract import assigned_checkout  # noqa: E402
from packages.tests.test_provider_controller_commands import Controller  # noqa: E402


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

    def test_worktree_is_registered_or_assigned_with_supported_commands(self) -> None:
        """A unit gets an absolute checkout at registration or through a later locked assignment."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name), tempfile.TemporaryDirectory() as scratch:
                c = Controller(Path(scratch), name)
                self.assertEqual(c.start().returncode, 0)
                checkout = Path(assigned_checkout(c.root))
                self.assertEqual(c.add("1", "--manifest", "README.md", "--worktree", str(checkout)).returncode, 0)
                self.assertEqual(c.read()["work_units"]["1"]["worktree"], str(checkout.resolve()))
                self.assertEqual(c.add("2").returncode, 0)
                assigned = c.run(
                    "assign-worktree",
                    "--session",
                    "sess-1",
                    "--loop-id",
                    "loop-a",
                    "--unit",
                    "2",
                    "--worktree",
                    str(checkout),
                )
                self.assertEqual(assigned.returncode, 0, assigned.stderr)
                self.assertEqual(c.read()["work_units"]["2"]["worktree"], str(checkout.resolve()))
                self.assertIn("worktree_assigned", c.codes("assign-worktree"))

    def test_existing_active_wave_keeps_its_revision_when_worktree_is_assigned(self) -> None:
        """Repair old unit metadata under the provider lock without replacing its active dispatch."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name), tempfile.TemporaryDirectory() as scratch:
                provider = Provider(Path(scratch), name)
                state = provider.read()
                state["work_units"]["1"] = {"status": "pending", "manifest": ["README.md"]}
                provider.write(state)
                provider.success("begin-wave")
                before = provider.read()
                checkout = assigned_checkout(provider.home)
                result = provider.call(
                    "assign-worktree",
                    "--session",
                    provider.session,
                    "--loop-id",
                    before["loop_id"],
                    "--unit",
                    "1",
                    "--worktree",
                    checkout,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                after = provider.read()
                self.assertEqual(after["revision"], before["revision"])
                self.assertEqual(after["graph"]["active_wave"], before["graph"]["active_wave"])
                self.assertEqual(after["graph"]["dispatches"], before["graph"]["dispatches"])
                self.assertEqual(after["work_units"]["1"]["worktree"], checkout)


if __name__ == "__main__":
    unittest.main()
