"""Evidence-side dispatch checks for both provider graph runtimes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from packages.tests.provider_fixture import Provider

SECTIONS = 'model_role: "default"'


class DispatchEvidenceTests(unittest.TestCase):
    """Exercise native spawn binding after the pre-dispatch hook."""

    def setUp(self) -> None:
        """Create an isolated provider home."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.count = 0

    def opened(self, name: str) -> Provider:
        """Open one active wave in a unique provider home."""
        self.count += 1
        base = self.root / str(self.count)
        base.mkdir()
        provider = Provider(base, name)
        provider.write(provider.state(("U3[1]",)))
        provider.success("begin-wave")
        return provider

    def launched(self) -> tuple[Provider, dict[str, Any]]:
        """Return an active Claude wave and its native spawn result."""
        provider = self.opened("claude")
        return provider, provider.launch()

    def test_codex_evidence_rejects_unconsumed_native_dispatch(self) -> None:
        """A task-name-matched child cannot replace missing hook authorization."""
        provider = self.opened("codex")
        report = provider.launch()
        state = provider.read()
        next(iter(state["graph"]["dispatches"].values()))["authorized"] = None
        provider.write(state)
        before = provider.path.read_bytes()
        failed = provider.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_unauthorized", failed.stderr)
        self.assertEqual(provider.path.read_bytes(), before)

    def test_codex_evidence_rejects_changed_stored_contract(self) -> None:
        """A native task name cannot rescue a stored v2 contract whose digest no longer matches."""
        provider = self.opened("codex")
        report = provider.launch()
        state = provider.read()
        record = next(iter(state["graph"]["dispatches"].values()))
        record["contract"]["scope"] = "changed after begin-wave"
        provider.write(state)
        before = provider.path.read_bytes()
        failed = provider.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_contract_altered", failed.stderr)
        self.assertEqual(provider.path.read_bytes(), before)

    def test_codex_evidence_rejects_native_message_and_role_changes(self) -> None:
        """Binding checks the actual native spawn arguments after the hook's decision."""
        for change, reason in (("sections", "dispatch_sections_missing"), ("role", "role_mismatch")):
            with self.subTest(change=change):
                provider = self.opened("codex")
                report = provider.launch()
                lines = provider.parent.read_text().splitlines()
                native = json.loads(lines[1])
                arguments = json.loads(native["payload"]["arguments"])
                if change == "sections":
                    arguments["message"] = arguments["message"].replace(SECTIONS, "model_role: removed")
                else:
                    arguments["agent_type"] = "explorer"
                native["payload"]["arguments"] = json.dumps(arguments)
                lines[1] = json.dumps(native)
                provider.parent.write_text("\n".join(lines) + "\n")
                before = provider.path.read_bytes()
                failed = provider.call("record-wave", json.dumps(report))
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(reason, failed.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_codex_completion_rechecks_consumed_dispatch(self) -> None:
        """Later deletion of authorization cannot preserve an already-bound done node."""
        provider = self.opened("codex")
        provider.success("record-wave", json.dumps(provider.launch()))
        provider.artifacts()
        state = provider.read()
        next(iter(state["graph"]["dispatches"].values()))["authorized"] = None
        provider.write(state)
        before = provider.path.read_bytes()
        failed = provider.complete()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_unauthorized", failed.stderr)
        self.assertEqual(provider.path.read_bytes(), before)

    def test_codex_off_records_only_a_v2_owned_native_wave(self) -> None:
        """Off bypasses consumption but still binds the current native v2 request to the wave."""
        provider = self.opened("codex")
        provider.environment = {**provider.environment, "CODERAILS_GRAPH_DISPATCH": "off"}
        report = provider.launch()
        state = provider.read()
        next(iter(state["graph"]["dispatches"].values()))["authorized"] = None
        provider.write(state)
        provider.success("record-wave", json.dumps(report))

        missing = self.opened("codex")
        missing.environment = {**missing.environment, "CODERAILS_GRAPH_DISPATCH": "off"}
        report = missing.launch()
        lines = missing.parent.read_text().splitlines()
        native = json.loads(lines[1])
        arguments = json.loads(native["payload"]["arguments"])
        arguments["message"] = "No graph envelope"
        native["payload"]["arguments"] = json.dumps(arguments)
        lines[1] = json.dumps(native)
        missing.parent.write_text("\n".join(lines) + "\n")
        before = missing.path.read_bytes()
        failed = missing.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_missing_envelope", failed.stderr)
        self.assertEqual(missing.path.read_bytes(), before)

    def test_claude_evidence_rejects_foreign_hook_tool_identity(self) -> None:
        """A consumed dispatch id must name the actual native Agent tool call when the hook supplied an id."""
        provider, report = self.launched()
        state = provider.read()
        next(iter(state["graph"]["dispatches"].values()))["authorized"] = {"tool_use_id": "toolu_foreign"}
        provider.write(state)
        before = provider.path.read_bytes()
        failed = provider.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_unauthorized", failed.stderr)
        self.assertEqual(provider.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
