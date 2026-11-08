"""Complete current Note rows remain authoritative through provider dispatch contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_contract  # noqa: E402
import graph_lessons  # noqa: E402

from packages.tests.provider_fixture import Provider  # noqa: E402


class CurrentNoteContractTests(unittest.TestCase):
    """Exercise real current readers and the separate stored-contract authority boundary."""

    def setUp(self) -> None:
        """Use a canonical temporary project path for current-request binding."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.count = 0

    def fresh(self, name: str) -> Provider:
        """Create one isolated provider and mapped repository."""
        self.count += 1
        base = self.root / str(self.count)
        base.mkdir()
        return Provider(base, name)

    def verdict(self, provider: Provider, request: dict[str, Any]) -> bool:
        """Run the real native dispatch guard without starting a worker."""
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return bool(result.stdout) and json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def refuse(self, provider: Provider, request: dict[str, Any], code: str) -> None:
        """Require the exact refusal and preserve the issued graph bytes."""
        before = provider.path.read_bytes()
        self.assertTrue(self.verdict(provider, request))
        self.assertEqual(provider.path.read_bytes(), before)
        trace = provider.path.with_name("recovery-trace.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(trace[-1])["reason_code"], code)

    def test_full_current_note_survives_native_and_driver_contracts(self) -> None:
        """Dropping nested metadata or refusing modern rows breaks actual begin-wave and authorization."""
        for name in ("claude", "codex"):
            for operation in ("begin-wave", "begin-driver-wave"):
                with self.subTest(provider=name, operation=operation):
                    provider = self.fresh(name)
                    _, row = provider.current_note()
                    if operation == "begin-driver-wave":
                        provider.success("cutover-driver", "--session", provider.session)
                    wave = provider.success(operation)
                    contract = next(iter(provider.read()["graph"]["dispatches"].values()))["contract"]
                    self.assertEqual(contract["lessons"], ["Authored local guidance.", row])
                    self.assertEqual(
                        contract["lessons_sha256"],
                        hashlib.sha256(json.dumps([row], sort_keys=True).encode()).hexdigest(),
                    )
                    self.assertEqual(graph_contract.validate_contract(contract), contract)
                    self.assertIn(
                        "lessons: " + json.dumps(contract["lessons"], sort_keys=True),
                        wave["dispatches"][0]["prompt_sections"],
                    )
                    if operation == "begin-wave":
                        self.assertFalse(self.verdict(provider, provider.request()))
                    calls = [json.loads(line) for line in (provider.home / "calls.jsonl").read_text().splitlines()]
                    self.assertTrue(all(call["cwd"] == str(provider.checkout) for call in calls))
                    self.assertTrue(
                        all(call["args"][:2] != ["learn", "request"] or "--help" in call["args"] for call in calls)
                    )

    def test_malformed_current_rows_refuse_reader_and_stored_contract(self) -> None:
        """A recomputed digest must not certify malformed or ineligible Note metadata."""
        provider = self.fresh("claude")
        _, row = provider.current_note()
        base = graph_contract.build_contract(provider.read(), "U3[1]", "main")
        mutations: list[tuple[str, Any]] = [
            ("revision", True),
            ("revision", 0),
            ("request_id", ""),
            ("request_id", 4),
            ("body", []),
            ("expiry", []),
            ("supports", []),
            ("supports", ["bad"]),
            ("privacy_classification", "normal"),
            ("privacy_checks", []),
            ("cited", False),
            ("use_allowed", False),
            ("use_allowed", "unknown"),
            ("use_reason", "unknown"),
            ("quote", ""),
            ("muninn_id", None),
            ("extra", "unknown top level"),
        ]
        rows = [{**row, key: value} for key, value in mutations]
        rows += [{k: v for k, v in row.items() if k != missing} for missing in row]
        body_changes: list[tuple[str, Any]] = [
            ("conditions", ["Only with approval"]),
            ("kind", "decision"),
            ("scope", {}),
            ("scope", {"project_id": row["body"]["scope"]["project_id"]}),
            ("evidence_refs", []),
            ("content", 1),
        ]
        for key, value in body_changes:
            rows.append({**row, "body": {**row["body"], key: value}})
        rows += [
            {**row, "expiry": {**row["expiry"], "condition": "Until approved"}},
            {**row, "supports": [{**row["supports"][0], "quote": ""}, row["supports"][1]]},
            {**row, "supports": [{**row["supports"][0], "id": 4}, row["supports"][1]]},
            {k: row[k] for k in ("id", "text", "cited", "cite", "quote", "muninn_id", "scope")},
        ]
        rows += [
            {**row, "supports": [{k: v for k, v in row["supports"][0].items() if k != missing}, row["supports"][1]]}
            for missing in row["supports"][0]
            if missing != "extra"
        ]
        for index, invalid in enumerate(rows):
            digest = hashlib.sha256(json.dumps([invalid], sort_keys=True).encode()).hexdigest()
            payload = {"lessons": [invalid], "sha256": digest}
            with (
                self.subTest(case=index),
                mock.patch.object(
                    subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, json.dumps(payload)),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "invalid lesson row"):
                    graph_lessons.query(provider.path, provider.plugin / "scripts/push.py", provider.session)
                with self.assertRaisesRegex(ValueError, "lesson"):
                    graph_contract.validate_contract(
                        {**base, "lessons": ["Authored guidance", invalid], "lessons_sha256": digest}
                    )

    def test_null_expiry_and_complete_row_order_share_the_snapshot_contract(self) -> None:
        """A null expiry is eligible; row reordering requires a new digest, excluding authored strings."""
        provider = self.fresh("claude")
        _, row = provider.current_note()
        rows = [{**row, "id": "first", "expiry": None}, {**row, "id": "second"}]
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        contract = graph_contract.build_contract(provider.read(), "U3[1]", "main")
        contract.update(lessons=["Authored guidance", *rows], lessons_sha256=digest)
        self.assertEqual(graph_contract.validate_contract(contract), contract)
        for changed in ({**contract, "lessons": [*reversed(rows)]}, {**contract, "lessons_sha256": None}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "digest"):
                graph_contract.validate_contract(changed)

    def test_nested_support_bindings_refuse_with_a_correct_snapshot_digest(self) -> None:
        """Neither boundary may certify missing locator/selection facts or contradictory scope/ref."""
        provider = self.fresh("claude")
        _, row = provider.current_note()
        base = graph_contract.build_contract(provider.read(), "U3[1]", "main")
        support = row["supports"][0]
        mutations: list[tuple[str, Any]] = [
            ("scope", {}),
            ("scope", {"project_id": "foreign", "task": None}),
            ("scope", {"project_id": row["body"]["scope"]["project_id"], "task": "foreign"}),
            ("thread_id", "foreign-thread"),
            ("provider", "foreign-provider"),
            ("line", 2),
            ("part", 2),
            ("session_root", "missing required key"),
            ("source_version", " "),
            ("projection_version", " "),
            ("original_locator", {}),
            ("original_locator", {"kind": "unknown"}),
            ("original_locator", {"kind": "cursor_db", "database": "db", "conversation_id": "c"}),
            ("original_locator", {"kind": "cursor_db", "database": "db", "conversation_id": "c", "record_key": 1}),
            ("selector", {}),
            ("selector", {"json_pointer": "bad", "start": None, "end": None}),
            ("selector", {"json_pointer": "/bad~2escape", "start": None, "end": None}),
            ("selector", {"json_pointer": "", "start": True, "end": 2}),
            ("selector", {"json_pointer": "", "start": 3, "end": 2}),
            ("selector", {"json_pointer": "", "start": None, "end": 2}),
            ("selector_digest", "0" * 64),
        ]
        mutations += [
            ("original_locator", {**support["original_locator"], key: value})
            for key, value in (("path", ""), ("byte_offset", True), ("byte_offset", -1), ("byte_length", 0))
        ]
        mutations += [
            ("selector", {k: v for k, v in support["selector"].items() if k != missing})
            for missing in support["selector"]
        ]
        mutations += [
            (field, refs)
            for field in ("body", "expiry")
            for refs in (["bad"], row["body"]["evidence_refs"] * 2, [f"E_{i:032x}" for i in range(101)])
        ]
        for index, (key, value) in enumerate(mutations):
            changed = copy.deepcopy(row)
            if key in ("body", "expiry"):
                changed[key]["evidence_refs"] = value
                if len(value) > 100:
                    changed["body"]["evidence_refs"] = value
                    changed["expiry"]["evidence_refs"] = value
                    changed["supports"] = [{**support, "id": ref} for ref in value]
            else:
                changed["supports"][0][key] = value
            if key == "session_root":
                del changed["supports"][0][key]
            if key == "selector":
                changed["supports"][0]["selector_digest"] = hashlib.sha256(
                    json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
                ).hexdigest()
            digest = hashlib.sha256(json.dumps([changed], sort_keys=True).encode()).hexdigest()
            with self.subTest(case=index, boundary="stored"), self.assertRaisesRegex(ValueError, "lesson"):
                graph_contract.validate_contract({**base, "lessons": [changed], "lessons_sha256": digest})
            with (
                self.subTest(case=index, boundary="query"),
                mock.patch.object(
                    subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps({"lessons": [changed], "sha256": digest})
                    ),
                ),
                self.assertRaisesRegex(ValueError, "invalid lesson row"),
            ):
                graph_lessons.query(provider.path, provider.plugin / "scripts/push.py", provider.session)

    def test_supported_locator_variants_keep_nested_extra_fields(self) -> None:
        """Pure binding checks retain extras for JSONL and cursor locators and valid selected spans."""
        provider = self.fresh("claude")
        _, row = provider.current_note()
        base = graph_contract.build_contract(provider.read(), "U3[1]", "main")
        for variant in ("jsonl", "cursor_db", "missing_task", "null_session_root"):
            kind = "cursor_db" if variant == "cursor_db" else "jsonl"
            changed = copy.deepcopy(row)
            support = changed["supports"][0]
            if kind == "cursor_db":
                support["original_locator"] = {
                    "kind": kind,
                    "database": " ",
                    "conversation_id": " ",
                    "record_key": " ",
                }
            else:
                support["original_locator"]["path"] = " "
            support["original_locator"]["extra"] = {"retained": [kind]}
            support["scope"].update(task=changed["body"]["scope"]["task"], extra="retained")
            if variant == "missing_task":
                del support["scope"]["task"]
            if variant == "null_session_root":
                support["session_root"] = None
            support["selector"].update(json_pointer="/escaped~0key/~1field", start=0, end=3, extra="retained")
            support["selector_digest"] = hashlib.sha256(
                json.dumps(support["selector"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
            digest = hashlib.sha256(json.dumps([changed], sort_keys=True).encode()).hexdigest()
            with self.subTest(variant=variant, boundary="stored"):
                self.assertEqual(
                    graph_contract.validate_contract({**base, "lessons": [changed], "lessons_sha256": digest})[
                        "lessons"
                    ],
                    [changed],
                )
            with (
                self.subTest(variant=variant, boundary="query"),
                mock.patch.object(
                    subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps({"lessons": [changed], "sha256": digest})
                    ),
                ),
            ):
                self.assertEqual(
                    graph_lessons.query(provider.path, provider.plugin / "scripts/push.py", provider.session)[
                        "lessons"
                    ],
                    [changed],
                )

    def test_changed_metadata_invalidates_digest_and_issued_authorization(self) -> None:
        """Revision, body, expiry and second-support changes cannot reuse a snapshot or issued contract."""
        for name in ("claude", "codex"):
            for field in ("revision", "body", "expiry", "supports"):
                with self.subTest(provider=name, field=field):
                    provider = self.fresh(name)
                    data, row = provider.current_note()
                    provider.success("begin-wave")
                    contract = next(iter(provider.read()["graph"]["dispatches"].values()))["contract"]
                    changed = copy.deepcopy(row)
                    if field == "revision":
                        changed[field] = 4
                        data["notes"][0][field] = 4
                        data["receipt"]["applied"][0][field] = 4
                    elif field == "supports":
                        changed[field][1]["extra"] = {"retained": ["changed second support"]}
                        data["evidence"][1]["extra"] = changed[field][1]["extra"]
                    else:
                        changed[field]["extra"] = "changed metadata"
                        data["notes"][0][field]["extra"] = "changed metadata"
                    with self.assertRaisesRegex(ValueError, "digest"):
                        graph_contract.validate_contract({**contract, "lessons": [changed]})
                    fresh_digest = hashlib.sha256(json.dumps([changed], sort_keys=True).encode()).hexdigest()
                    self.assertEqual(
                        graph_contract.validate_contract(
                            {**contract, "lessons": [changed], "lessons_sha256": fresh_digest}
                        )["lessons"],
                        [changed],
                    )
                    with (
                        mock.patch.object(
                            subprocess,
                            "run",
                            return_value=subprocess.CompletedProcess(
                                [], 0, json.dumps({"lessons": [changed], "sha256": contract["lessons_sha256"]})
                            ),
                        ),
                        self.assertRaisesRegex(ValueError, "wrong digest"),
                    ):
                        graph_lessons.query(provider.path, provider.plugin / "scripts/push.py", provider.session)
                    (provider.home / "data.json").write_text(json.dumps(data))
                    self.refuse(provider, provider.request(), "dispatch_lessons_stale")

    def test_conditional_unknown_and_malformed_readers_refuse_before_dispatch(self) -> None:
        """A conditional, pending or unknown current read cannot become successful dispatch guidance."""
        for name in ("claude", "codex"):
            for defect in ("condition", "conditional_expiry", "pending", "unknown", "malformed"):
                with self.subTest(provider=name, defect=defect):
                    provider = self.fresh(name)
                    data, _ = provider.current_note()
                    if defect == "condition":
                        data["notes"][0]["body"]["conditions"] = ["Only after approval"]
                    elif defect == "conditional_expiry":
                        data["notes"][0]["expiry"]["condition"] = "Until approved"
                    elif defect in ("pending", "unknown"):
                        data["request"]["state"] = defect
                        data["receipt"] = None
                    else:
                        data["notes"][0]["body"]["conditions"] = True
                    (provider.home / "data.json").write_text(json.dumps(data))
                    before = provider.path.read_bytes()
                    result = provider.call("begin-wave")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("dispatch_lessons_unavailable", result.stderr)
                    self.assertEqual(provider.path.read_bytes(), before)

    def test_explicit_backend_off_keeps_only_uncited_diagnostic_form(self) -> None:
        """The documented off switch retains ledger text without certifying a current Note."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                provider.current_note()
                (provider.home / ".coderails/workflow.config.yaml").write_text(
                    "memory:\n  backend: off\nsandbox_workers: false\n"
                )
                provider.success("begin-wave")
                contract = next(iter(provider.read()["graph"]["dispatches"].values()))["contract"]
                expected = {
                    "id": "both",
                    "text": "Use both supports.",
                    "cited": False,
                    "cite": "",
                    "quote": "",
                    "muninn_id": None,
                    "scope": "repo",
                }
                self.assertEqual(contract["lessons"], ["Authored local guidance.", expected])
                self.assertEqual(graph_contract.validate_contract(contract), contract)
                self.assertFalse((provider.home / "calls.jsonl").exists())

    def test_bad_reader_transport_has_a_typed_pre_dispatch_refusal(self) -> None:
        """Malformed JSON, nonobjects, invalid contracts and nonzero conditional/unknown responses refuse."""
        provider = self.fresh("claude")
        for code, output in (
            (0, "{bad"),
            (0, "[]"),
            (0, '{"lessons":[],"sha256":"bad"}'),
            (3, '{"degraded":"learning_conditional_use_unsupported"}'),
            (3, '{"degraded":"learning_request_unknown"}'),
        ):
            with (
                self.subTest(code=code, output=output),
                mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], code, output)),
                self.assertRaises(graph_contract.DispatchDeniedError) as error,
            ):
                graph_contract.current_lessons(provider.path, provider.plugin / "scripts/push.py", provider.session)
            self.assertEqual(error.exception.code, "dispatch_lessons_unavailable")


if __name__ == "__main__":
    unittest.main()
