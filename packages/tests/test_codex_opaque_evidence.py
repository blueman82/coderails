"""Recheck opaque native evidence against its exact consumed call and ciphertext."""

from __future__ import annotations

import base64
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
import graph_contract
from graph_evidence import _verify_dispatch  # pyright: ignore[reportPrivateUsage]

from packages.tests.test_codex_native_dispatch_cli import TASK, seeded_state


class OpaqueEvidenceTests(unittest.TestCase):
    """Read actual native request arguments and compare consumed receipts."""

    def test_opaque_evidence_rechecks_actual_call_and_ciphertext(self) -> None:
        """A consumed receipt binds exactly one native call and its observed ciphertext."""
        with tempfile.TemporaryDirectory() as scratch:
            state = seeded_state(Path(scratch) / "progress.json")
            record = next(iter(state["graph"]["dispatches"].values()))
            token = base64.urlsafe_b64encode(bytes([128]) + bytes(8 + 16 + 16 + 32)).decode()
            receipt = {"tool_use_id": "call_native_1", "ciphertext_sha256": hashlib.sha256(token.encode()).hexdigest()}
            record["authorized"] = receipt
            requests: dict[str, list[dict[str, Any] | None]] = {
                "call_native_1": [{"task_name": TASK, "message": token}]
            }
            _verify_dispatch(state, "U3[7]", 1, "wave-2", "call_native_1", requests)
            for altered in (
                {"tool_use_id": None, "ciphertext_sha256": receipt["ciphertext_sha256"]},
                {"tool_use_id": "other", "ciphertext_sha256": receipt["ciphertext_sha256"]},
                {"tool_use_id": "call_native_1", "ciphertext_sha256": "0" * 64},
                {"tool_use_id": "call_native_1"},
            ):
                with self.subTest(receipt=altered):
                    record["authorized"] = altered
                    with self.assertRaises(graph_contract.DispatchDeniedError):
                        _verify_dispatch(state, "U3[7]", 1, "wave-2", "call_native_1", requests)
            record["authorized"] = receipt
            with self.assertRaises(graph_contract.DispatchDeniedError):
                _verify_dispatch(
                    state,
                    "U3[7]",
                    1,
                    "wave-2",
                    "call_native_1",
                    {"call_native_1": [requests["call_native_1"][0], requests["call_native_1"][0]]},
                )
            changed = base64.urlsafe_b64encode(bytes([128, 1]) + bytes(7 + 16 + 16 + 32)).decode()
            with self.assertRaises(graph_contract.DispatchDeniedError):
                _verify_dispatch(
                    state,
                    "U3[7]",
                    1,
                    "wave-2",
                    "call_native_1",
                    {"call_native_1": [{"task_name": TASK, "message": changed}]},
                )
            with self.assertRaises(graph_contract.DispatchDeniedError):
                _verify_dispatch(
                    state,
                    "U3[7]",
                    1,
                    "wave-2",
                    "call_native_1",
                    {"call_native_1": [{"task_name": "foreign", "message": token}]},
                )
