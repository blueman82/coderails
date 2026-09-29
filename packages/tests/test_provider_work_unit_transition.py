"""Exercise native work-unit decisions through both provider graph CLIs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from packages.tests.provider_fixture import Provider


class ProviderWorkUnitTransitionTests(unittest.TestCase):
    """A work unit is decided explicitly after its deliverable is checked."""

    def setUp(self) -> None:
        """Prepare separate native provider states in one temporary home."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def request(
        self, provider: Provider, unit: str, status: str, detail: str, *, session: str | None = None
    ) -> CompletedProcess[str]:
        """Invoke a provider work unit transition with its matching detail flag."""
        option = "--evidence" if status == "done" else "--reason"
        return provider.call(
            "record-unit",
            "--session",
            session or provider.session,
            "--unit",
            unit,
            "--status",
            status,
            option,
            detail,
        )

    def test_done_records_verified_evidence_without_inference_from_node(self) -> None:
        """Store the supplied work unit evidence independently of graph nodes."""
        for provider in self.providers:
            state = provider.read()
            state["work_units"] = {"1": {"status": "pending"}}
            state["graph"]["nodes"]["U3[1]"].update(status="done", outcome="done")
            provider.write(state)
            result = self.request(provider, "1", "done", "reviewed fixture diff and tests")
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = provider.read()
            self.assertEqual(
                updated["work_units"]["1"], {"status": "done", "evidence": "reviewed fixture diff and tests"}
            )
            self.assertEqual(updated["revision"], state["revision"])

    def test_dropped_records_reason(self) -> None:
        """Store the explicit reason for dropping a work unit."""
        for provider in self.providers:
            state = provider.read()
            state["work_units"] = {"1": {"status": "pending"}}
            provider.write(state)
            result = self.request(provider, "1", "dropped", "deliverable withdrawn by owner")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                provider.read()["work_units"]["1"],
                {"status": "dropped", "dropped_reason": "deliverable withdrawn by owner"},
            )

    def test_recording_unit_preserves_completed_wave_evidence(self) -> None:
        """Deciding a work unit retains evidence from the completed wave."""
        for provider in self.providers:
            state = provider.read()
            state["work_units"] = {"1": {"status": "pending"}}
            provider.write(state)
            provider.finish_wave()
            result = self.request(provider, "1", "done", "verified completed wave")
            self.assertEqual(result.returncode, 0, result.stderr)
            provider.artifacts()
            completion = provider.complete()
            self.assertEqual(completion.returncode, 0, completion.stderr)

    def test_refusals_leave_state_bytes_unchanged(self) -> None:
        """Invalid requests must leave both providers' state bytes unchanged."""
        for provider in self.providers:
            state = provider.read()
            state["work_units"] = {"1": {"status": "pending"}}
            provider.write(state)
            for unit, status, detail, session in (
                ("1", "done", " ", None),
                ("1", "dropped", " ", None),
                ("unknown", "done", "checked", None),
                (" ", "done", "checked", None),
                ("1", "done", "checked", "foreign-session"),
            ):
                before = provider.path.read_bytes()
                result = self.request(provider, unit, status, detail, session=session)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(provider.path.read_bytes(), before)
            state["work_units"]["1"] = {"status": "done", "evidence": "checked"}
            provider.write(state)
            before = provider.path.read_bytes()
            self.assertNotEqual(self.request(provider, "1", "dropped", "changed mind").returncode, 0)
            self.assertEqual(provider.path.read_bytes(), before)
            state["work_units"]["1"] = {"status": "pending"}
            provider.write(state)
            provider.success("begin-wave")
            before = provider.path.read_bytes()
            self.assertNotEqual(self.request(provider, "1", "done", "checked").returncode, 0)
            self.assertEqual(provider.path.read_bytes(), before)
            state["graph"] = provider.state()["graph"]
            state["status"] = "complete"
            provider.write(state)
            before = provider.path.read_bytes()
            self.assertNotEqual(self.request(provider, "1", "done", "checked").returncode, 0)
            self.assertEqual(provider.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
