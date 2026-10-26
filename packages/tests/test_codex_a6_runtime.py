"""A6 invalid and encrypted native dispatch behavior through the real Codex graph adapter."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))

import graph  # noqa: E402
import graph_semantics  # noqa: E402
from graph_evidence import validate_worker_evidence  # noqa: E402
from graph_identity import GraphError, task_name  # noqa: E402

from packages.tests.codex_fixture import read_json, spawn, write_json  # noqa: E402
from packages.tests.provider_fixture import Provider  # noqa: E402
from packages.tests.test_codex_graph_runtime import RuntimeFixture  # noqa: E402


class A6RuntimeTests(RuntimeFixture):
    """Recover missing envelopes and verify opaque native evidence."""

    def test_authorization_binds_call_id_after_rollout(self) -> None:
        """The enabled reader records the exact native call ID."""
        with tempfile.TemporaryDirectory() as temporary:
            provider = Provider(Path(temporary), "codex")
            provider.write(provider.state(("U3[1]",)))
            provider.success("begin-wave")
            request = provider.request()
            provider.environment["CODERAILS_A6_EVIDENCE_WRITE"] = "on"
            result = provider.hook("loop_dispatch_guard", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            record = next(iter(provider.read()["graph"]["dispatches"].values()))
            self.assertEqual(record["authorized"], {"tool_use_id": request["tool_use_id"]})

    def test_child_cwd_must_match_assigned_worktree(self) -> None:
        """A completed native child in another checkout cannot satisfy the issued unit."""
        current = read_json(self.path)
        current["work_units"] = {"1": {"status": "pending", "worktree": str(self.directory)}}
        write_json(self.path, current)
        graph.begin_wave(self.path)
        child = spawn(self.parent, read_json(self.path))
        rows = child.read_text(encoding="utf-8").splitlines()
        first = json.loads(rows[0])
        first["payload"]["cwd"] = "/tmp/foreign-worktree"
        rows[0] = json.dumps(first)
        child.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.assert_unchanged(self.record)
        first["payload"]["cwd"] = str(self.directory)
        rows[0] = json.dumps(first)
        child.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.record()
        validate_worker_evidence(read_json(self.path))
        first["payload"]["cwd"] = "/tmp/foreign-worktree"
        rows[0] = json.dumps(first)
        child.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GraphError, "worktree"):
            validate_worker_evidence(read_json(self.path))

    def test_record_wave_denied_dispatch_is_coded_without_traceback(self) -> None:
        """Authorization, ciphertext and role refusals are coded and atomic."""
        for scenario, code in (
            ("authorization", "dispatch_unauthorized"),
            ("ciphertext", "dispatch_missing_envelope"),
            ("role", "role_mismatch"),
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                provider = Provider(Path(temporary), "codex")
                provider.success("begin-wave")
                report = provider.launch()
                current = provider.read()
                dispatch = next(iter(current["graph"]["dispatches"].values()))
                if scenario == "authorization":
                    dispatch["authorized"] = None
                else:
                    rows = provider.parent.read_text(encoding="utf-8").splitlines()
                    call = json.loads(rows[1])
                    arguments = json.loads(call["payload"]["arguments"])
                    if scenario == "ciphertext":
                        arguments["message"] = base64.urlsafe_b64encode(b"\x80" + b"\x00" * 72).decode("ascii")
                    else:
                        arguments["agent_type"] = "design-scout"
                    call["payload"]["arguments"] = json.dumps(arguments)
                    rows[1] = json.dumps(call)
                    provider.parent.write_text("\n".join(rows) + "\n", encoding="utf-8")
                provider.write(current)
                before = provider.path.read_bytes()
                result = provider.call("record-wave", json.dumps(report))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"reason_code={code}", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_reject_invalid_native_dispatch_and_retry(self) -> None:
        """A finished spawn with no envelope is a failed attempt, never accepted worker work."""
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        self.assert_unchanged(graph.reject_invalid_dispatch, self.path, "parent", "U3[1]", "wave-2")
        lines = self.parent.read_text(encoding="utf-8").splitlines()
        call = json.loads(lines[1])
        arguments = json.loads(call["payload"]["arguments"])
        arguments["message"] = "encrypted_content"
        call["payload"]["arguments"] = json.dumps(arguments)
        lines[1] = json.dumps(call)
        self.parent.write_text("\n".join(lines) + "\n", encoding="utf-8")
        current = read_json(self.path)
        for record in current["graph"]["dispatches"].values():
            record["authorized"] = None
        write_json(self.path, current)
        self.assert_unchanged(graph.reject_invalid_dispatch, self.path, "foreign", "U3[1]", "wave-2")
        self.assert_unchanged(graph.reject_invalid_dispatch, self.path, "parent", "U3[2]", "wave-2")
        before = self.path.read_bytes()
        self.assertFalse(graph.reject_invalid_dispatch(self.path, "parent", "U3[1]", "wave-2", apply=False)["applied"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assert_unchanged(graph.reject_invalid_dispatch, self.path, "parent", "U3[1]", "wave-2")
        with patch.dict("os.environ", {"CODERAILS_A6_EVIDENCE_WRITE": "on"}):
            report = graph.reject_invalid_dispatch(self.path, "parent", "U3[1]", "wave-2")
        self.assertEqual(report["reason_code"], "dispatch_missing_envelope")
        self.assertEqual(read_json(self.path)["graph"]["nodes"]["U3[1]"]["retry"]["attempts"], 1)
        recovered = read_json(self.path)
        for status in ("done", "skipped"):
            with self.subTest(status=status):
                forged = copy.deepcopy(recovered)
                node = forged["graph"]["nodes"]["U3[1]"]
                node["status"] = status
                node["outcome"] = status
                node["retry"]["attempts"] = 0
                graph_semantics.validate(forged)
                with self.assertRaisesRegex(GraphError, "completed attempt cannot rest on an invalid dispatch"):
                    validate_worker_evidence(forged)
        wave = graph.begin_wave(self.path)
        self.assertEqual(wave["task_names"]["U3[1]"], task_name("loop", "U3[1]", 2))
        spawn(self.parent, read_json(self.path))
        self.record()
        validate_worker_evidence(read_json(self.path))

    def test_old_encrypted_receipt_cannot_bind_native_dispatch(self) -> None:
        """An old ciphertext receipt cannot complete an unverifiable worker."""
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        lines = self.parent.read_text(encoding="utf-8").splitlines()
        call = json.loads(lines[1])
        arguments = json.loads(call["payload"]["arguments"])
        arguments["message"] = base64.urlsafe_b64encode(b"\x80" + b"\x00" * 72).decode("ascii")
        ciphertext = arguments["message"]
        call["payload"]["arguments"] = json.dumps(arguments)
        lines[1] = json.dumps(call)
        self.parent.write_text("\n".join(lines) + "\n", encoding="utf-8")
        current = read_json(self.path)
        dispatch = next(iter(current["graph"]["dispatches"].values()))
        dispatch["authorized"] = None
        write_json(self.path, current)
        self.assert_unchanged(self.record)
        dispatch["authorized"] = {"tool_use_id": "wrong-call"}
        write_json(self.path, current)
        self.assert_unchanged(self.record)
        dispatch["authorized"] = {
            "tool_use_id": call["payload"]["call_id"],
            "ciphertext_sha256": hashlib.sha256(ciphertext.encode()).hexdigest(),
        }
        write_json(self.path, current)
        self.assert_unchanged(self.record)
        with (
            patch.dict("os.environ", {"CODERAILS_A6_EVIDENCE_WRITE": "on"}),
            self.assertRaisesRegex(GraphError, "dispatch_prompt_unverifiable"),
        ):
            self.record()

    def test_encrypted_dispatch_refuses_off_switch_receipt(self) -> None:
        """An off-mode receipt cannot bind an opaque native prompt to an approved call."""
        opened = graph.begin_wave(self.path)["dispatches"][0]
        message = self.path.with_name("message.txt")
        message.write_text(opened["prompt_prefix"] + "\n" + opened["prompt_sections"], encoding="utf-8")
        with patch.dict("os.environ", {"CODERAILS_GRAPH_DISPATCH": "off", "CODERAILS_A6_EVIDENCE_WRITE": "on"}):
            graph.authorize_dispatch(
                self.path,
                "parent",
                opened["dispatch_id"],
                message,
                "",
                opened["task_name"],
                self.path.with_name("evals.json"),
            )
            off_receipt = next(iter(read_json(self.path)["graph"]["dispatches"].values()))["authorized"]
            self.assertEqual(off_receipt, {"tool_use_id": None, "mode": "off"})
            spawn(self.parent, read_json(self.path))
            current = read_json(self.path)
            next(iter(current["graph"]["dispatches"].values()))["authorized"] = off_receipt
            write_json(self.path, current)
            lines = self.parent.read_text(encoding="utf-8").splitlines()
            call = json.loads(lines[1])
            arguments = json.loads(call["payload"]["arguments"])
            arguments["message"] = base64.urlsafe_b64encode(b"\x80" + b"\x00" * 72).decode("ascii")
            call["payload"]["arguments"] = json.dumps(arguments)
            lines[1] = json.dumps(call)
            self.parent.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assert_unchanged(self.record)

    def test_plaintext_dispatch_survives_off_switch_rescue(self) -> None:
        """A v2-only plaintext rescue stays valid after normal policy resumes."""
        opened = graph.begin_wave(self.path)["dispatches"][0]
        message = self.path.with_name("message.txt")
        message.write_text(opened["prompt_prefix"], encoding="utf-8")
        with patch.dict("os.environ", {"CODERAILS_GRAPH_DISPATCH": "off", "CODERAILS_A6_EVIDENCE_WRITE": "on"}):
            graph.authorize_dispatch(
                self.path,
                "parent",
                opened["dispatch_id"],
                message,
                "",
                opened["task_name"],
                self.path.with_name("evals.json"),
            )
            off_receipt = next(iter(read_json(self.path)["graph"]["dispatches"].values()))["authorized"]
            spawn(self.parent, read_json(self.path))
            current = read_json(self.path)
            next(iter(current["graph"]["dispatches"].values()))["authorized"] = off_receipt
            write_json(self.path, current)
            lines = self.parent.read_text(encoding="utf-8").splitlines()
            call = json.loads(lines[1])
            arguments = json.loads(call["payload"]["arguments"])
            arguments["message"] = opened["prompt_prefix"]
            call["payload"]["arguments"] = json.dumps(arguments)
            lines[1] = json.dumps(call)
            self.parent.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.record()
        validate_worker_evidence(read_json(self.path))

    def test_off_switch_keeps_old_receipt_shape_while_new_writer_is_off(self) -> None:
        """A reader-first install does not persist the new off-mode receipt."""
        opened = graph.begin_wave(self.path)["dispatches"][0]
        message = self.path.with_name("message.txt")
        message.write_text(opened["prompt_prefix"], encoding="utf-8")
        with patch.dict("os.environ", {"CODERAILS_GRAPH_DISPATCH": "off", "CODERAILS_A6_EVIDENCE_WRITE": ""}):
            graph.authorize_dispatch(
                self.path,
                "parent",
                opened["dispatch_id"],
                message,
                "",
                opened["task_name"],
                self.path.with_name("evals.json"),
            )
        self.assertIsNone(next(iter(read_json(self.path)["graph"]["dispatches"].values()))["authorized"])
