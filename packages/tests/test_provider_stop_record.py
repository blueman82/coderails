"""Exercise the recorded-stop intent row through both provider graph CLIs."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

from packages.tests.provider_fixture import Provider


class ProviderStopRecordTests(unittest.TestCase):
    """`graph.py stop` appends one typed, owner-checked, unconsumed row to progress.stops."""

    def setUp(self) -> None:
        """Prepare separate native provider states in one temporary home."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def stop(
        self,
        provider: Provider,
        category: str = "awaiting-input",
        code: str = "needs_human_input",
        reason: str = "need a decision",
        session: str | None = None,
    ) -> CompletedProcess[str]:
        """Invoke the stop subcommand with explicit enum fields."""
        return provider.call(
            "stop",
            "--session",
            session or provider.session,
            "--category",
            category,
            "--reason-code",
            code,
            "--reason",
            reason,
        )

    def test_records_typed_rows_and_keeps_the_revision(self) -> None:
        """An absent stops key is created; rows are sequenced, unconsumed, and bound to the revision."""
        for provider in self.providers:
            before = provider.read()
            self.assertNotIn("stops", before)
            self.assertEqual(self.stop(provider).returncode, 0)
            self.assertEqual(self.stop(provider, "hard-stop", "node_hard_stop", "boom").returncode, 0)
            after = provider.read()
            self.assertEqual(after["revision"], before["revision"])
            self.assertEqual(
                after["stops"],
                [
                    {
                        "seq": 1,
                        "category": "awaiting-input",
                        "reason_code": "needs_human_input",
                        "reason": "need a decision",
                        "revision": before["revision"],
                        "consumed": False,
                    },
                    {
                        "seq": 2,
                        "category": "hard-stop",
                        "reason_code": "node_hard_stop",
                        "reason": "boom",
                        "revision": before["revision"],
                        "consumed": False,
                    },
                ],
            )

    def test_refusals_leave_state_bytes_unchanged(self) -> None:
        """Bad enums, blank reason, foreign session, torn stops, and early complete all refuse."""
        for provider in self.providers:
            for args in (
                {"category": "paused"},
                {"code": "because"},
                {"reason": " "},
                {"session": "foreign-session"},
                {"category": "complete", "code": "work_complete"},  # graph still has a pending node
            ):
                before = provider.path.read_bytes()
                result = self.stop(provider, **args)
                self.assertNotEqual(result.returncode, 0, (provider.name, args, result.stdout))
                self.assertEqual(provider.path.read_bytes(), before)
            state = provider.read()
            state["stops"] = "torn"
            provider.write(state)
            before = provider.path.read_bytes()
            self.assertNotEqual(self.stop(provider).returncode, 0)
            self.assertEqual(provider.path.read_bytes(), before)
            self.assertFalse(list(provider.path.parent.glob("*.tmp*")))

    def test_complete_is_allowed_once_the_graph_is_resolved(self) -> None:
        """Category complete requires a resolved graph and then records normally."""
        for provider in self.providers:
            provider.finish_wave()
            result = self.stop(provider, "complete", "work_complete", "all nodes done")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(provider.read()["stops"][0]["category"], "complete")

    def test_unreadable_state_refuses_without_writing(self) -> None:
        """A truncated progress.json refuses; a leftover Claude lock directory refuses and keeps the file."""
        for provider in self.providers:
            provider.path.write_text('{"schema_version": 3,')
            before = provider.path.read_bytes()
            self.assertNotEqual(self.stop(provider).returncode, 0)
            self.assertEqual(provider.path.read_bytes(), before)
        claude = self.providers[0]
        claude.write(claude.state())
        Path(f"{claude.path}.lock").mkdir()
        before = claude.path.read_bytes()
        self.assertNotEqual(self.stop(claude).returncode, 0)
        self.assertEqual(claude.path.read_bytes(), before)

    @staticmethod
    def row(seq: int, category: str) -> dict[str, Any]:
        """A same-revision unconsumed row as `graph.py stop` would write it."""
        return {
            "seq": seq,
            "category": category,
            "reason_code": "other",
            "reason": "r",
            "revision": 1,
            "consumed": False,
        }

    def guard(self, provider: Provider, message: str = "stopping") -> str:
        """Run the Codex Stop guard and return its stdout."""
        payload = {"session_id": provider.session, "cwd": str(provider.home), "last_assistant_message": message}
        return provider.hook("graph_completion_guard", payload).stdout

    def test_codex_guard_releases_on_a_recorded_hard_stop_once(self) -> None:
        """A recorded hard-stop row on a typed hard-stopped graph releases without text, once; text is the fallback."""
        provider = self.providers[1]
        provider.success("hard-stop", "--node", "U3[1]", "--session", provider.session, "--reason", "owner decision")
        self.assertEqual(json.loads(self.guard(provider))["decision"], "block")
        self.assertEqual(self.stop(provider, "hard-stop", "node_hard_stop", "owner decision").returncode, 0)
        self.assertEqual(self.guard(provider), "")
        self.assertTrue(provider.read()["stops"][0]["consumed"])
        self.assertEqual(json.loads(self.guard(provider))["decision"], "block")  # consumed: no second free pass
        text = "LOOP-STOP: complete - x\nLOOP-STOP: stopped"
        self.assertEqual(json.loads(self.guard(provider, text))["decision"], "block")  # text alone never releases
        rows = self.trace_rows(provider)
        self.assertEqual(
            {(r["command"], r["reason_code"]) for r in rows}, {("graph_completion_guard", "stop_row_missing")}
        )
        self.assertNotIn("legacy_text_parse", json.dumps(rows))
        self.assertTrue(rows[0]["event_id"])

    def trace_rows(self, provider: Provider) -> list[dict[str, Any]]:
        """Rows the Codex guard appended to the session trace."""
        trace = provider.home / "state" / provider.session / "trace.jsonl"
        return [json.loads(line) for line in trace.read_text().splitlines()] if trace.is_file() else []

    def test_codex_guard_releases_approval_and_input_rows_once_without_a_hard_stop(self) -> None:
        """approval-gate and awaiting-input rows release a pending graph (no graph.hard_stop needed), once each."""
        provider = self.providers[1]
        for category, code in (("approval-gate", "needs_approval"), ("awaiting-input", "needs_human_input")):
            self.assertEqual(json.loads(self.guard(provider))["decision"], "block")
            self.assertEqual(self.stop(provider, category, code, "asking").returncode, 0)
            self.assertEqual(self.guard(provider), "", category)
            self.assertEqual(json.loads(self.guard(provider))["decision"], "block")  # consumed: one release only
        self.assertEqual([r["consumed"] for r in provider.read()["stops"]], [True, True])

    def test_complete_row_is_never_consumed_by_the_codex_guard(self) -> None:
        """`complete` goes through verify-completion; the guard leaves the row and still blocks without evidence."""
        provider = self.providers[1]
        provider.finish_wave()
        self.assertEqual(self.stop(provider, "complete", "work_complete", "all done").returncode, 0)
        self.assertEqual(json.loads(self.guard(provider, "LOOP-STOP: complete"))["decision"], "block")
        self.assertFalse(provider.read()["stops"][0]["consumed"])

    def test_both_providers_share_one_vocabulary_file(self) -> None:
        """Both stop modules import graph_vocab, define no local tuple, and the three copies are byte-identical."""
        root = Path(__file__).resolve().parents[2]
        modules = (
            root / "hooks/scripts/lib/graph_stops.py",
            root / "hooks/scripts/lib/loop_state_common.py",
            root / "packages/codex/skills/agentic-loop/scripts/graph_stops.py",
        )
        for module in modules:
            source = module.read_text()
            self.assertIn("from graph_vocab import", source, module.name)
            self.assertIsNone(re.search(r"^STOP_(CATEGORIES|REASON_CODES)\s*=", source, re.M), module.name)
        for name in ("graph_vocab", "graph_convert", "graph_semantics"):
            canonical = (root / f"packages/graph-semantics/{name}.py").read_bytes()
            for provider in ("skills/agentic-loop/scripts", "packages/codex/skills/agentic-loop/scripts"):
                self.assertEqual((root / provider / f"{name}.py").read_bytes(), canonical, (provider, name))

    def test_codex_guard_ignores_foreign_stale_and_complete_rows(self) -> None:
        """Stops for another revision or a `complete` category never release the guard."""
        provider = self.providers[1]
        state = provider.read()
        state["stops"] = [
            {"seq": 1, "category": "hard-stop", "reason_code": "other", "reason": "r", "revision": 0, "consumed": False}
        ]
        provider.write(state)
        provider.success("hard-stop", "--node", "U3[1]", "--session", provider.session, "--reason", "owner decision")
        self.assertEqual(json.loads(self.guard(provider))["decision"], "block")
        provider.write({**provider.read(), "stops": provider.read()["stops"] + [self.row(2, "complete")]})
        self.assertEqual(json.loads(self.guard(provider))["decision"], "block")


if __name__ == "__main__":
    unittest.main()
