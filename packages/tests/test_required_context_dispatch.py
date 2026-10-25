"""Native refusals for missing or changed required graph context in both providers."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
from graph_contract import sections_sha256

from packages.tests.provider_fixture import Provider


class RequiredContextDispatchTests(unittest.TestCase):
    """Use provider hooks and state files, without changing a live graph."""

    def open(self, name: str) -> Provider:
        """Create one isolated active wave."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        provider = Provider(Path(temporary.name), name)
        provider.success("begin-wave")
        return provider

    def refuse(self, provider: Provider, request: dict[str, Any], code: str) -> None:
        """Require a typed refusal and no state write."""
        before = provider.path.read_bytes()
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(provider.path.read_bytes(), before)
        trace = provider.path.with_name("recovery-trace.jsonl")
        self.assertEqual(json.loads(trace.read_text().splitlines()[-1])["reason_code"], code)

    def test_missing_or_changed_required_context_refuses(self) -> None:
        """A new hash cannot make a missing or false typed route valid."""
        for name in ("claude", "codex"):
            for change, code in (("missing", "dispatch_contract_altered"), ("changed", "dispatch_context_mismatch")):
                with self.subTest(provider=name, change=change):
                    provider = self.open(name)
                    request = provider.request()
                    state = provider.read()
                    record = next(iter(state["graph"]["dispatches"].values()))
                    if change == "missing":
                        del record["contract"]["required_context"]
                    else:
                        record["contract"]["required_context"]["skills"] = ["agentic-loop", "task-evals"]
                    record["prompt_sections_sha256"] = sections_sha256(record["contract"])
                    provider.write(state)
                    self.refuse(provider, request, code)

    def test_context_cutoff_must_be_bounded(self) -> None:
        """A missing or advanced cutoff cannot downgrade a new dispatch to old evidence."""
        for name in ("claude", "codex"):
            for stamp in (None, "2", 0, 10**9):
                with self.subTest(provider=name, stamp=stamp):
                    provider = self.open(name)
                    state = provider.read()
                    if stamp is None:
                        del state["graph"]["context_from_revision"]
                    else:
                        state["graph"]["context_from_revision"] = stamp
                    provider.write(state)
                    result = provider.call("inspect")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("dispatch_state_unconverted", result.stderr)


if __name__ == "__main__":
    unittest.main()
