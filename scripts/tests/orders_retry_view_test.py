"""Late completed-record retry and physical ownership of both fixed generated views."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT  # noqa: E402
from scripts.tests.orders_boundary_test import NO_OPENS, BoundaryCase  # noqa: E402

FINAL_SAVE_FAULT = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders, orders_ledger as ol
canonical = Path(sys.argv[2])
real_save, saved, refused = ol.save, [], []
def save(path, value):
    if path == canonical:
        refused.append(str(path))
        raise OSError('injected final ledger save only')
    real_save(path, value)
    saved.append(str(path))
ol.save = save
rc = orders.main(sys.argv[3:])
print(json.dumps({'saved': saved, 'refused': refused, 'rc': rc}))
raise SystemExit(rc)
"""
VIEWS = ("standing-orders.md", "standing-orders-decayed.md")
SEALS = ("seq", "prev_sha256", "row_sha256")


class ConsumerCase(BoundaryCase):
    """Reuse real provider CLI/store/owned-progress probes with genuine repository configuration."""

    def configured(self, codex: bool, backend: str, label: str) -> None:
        """A containing private Git repository makes this backend choice effective for each actual CLI."""
        self.configure(codex, label + backend)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        path = self.repo / ".coderails/workflow.config.yaml"
        path.parent.mkdir()
        path.write_text("memory:\n  backend: " + backend + "\n")

    def record_order(self, session: str, order_id: str, lesson: str) -> tuple[int, dict[str, Any]]:
        """Record the exact stable identity through the supported native frontdoor."""
        if not (self.repo / session / "progress.json").exists():
            self.owner(session)
        return self.cli(
            "record",
            "--id",
            order_id,
            "--failure-mode",
            order_id,
            "--lesson",
            lesson,
            "--scope",
            "agnostic",
            "--quote",
            PROMPT,
            "--loop",
            "logical-" + session,
            session=session,
        )

    def apply(self, session: str) -> None:
        """Save genuine completion, then apply exactly once with the provider's real CLI."""
        self.complete(session)
        rc, out = self.cli("tick", "--loop", "logical-" + session, session=session)
        self.assertEqual((rc, out.get("ticked")), (0, True), out)

    def assert_backend(self, backend: str) -> None:
        """Observe the actual selected read state rather than assume an ignored off configuration."""
        rc, out = self.cli("lessons")
        self.assertEqual((rc, out["state"]), (0, "memory_backend_off" if backend == "off" else "muninn"), out)

    def views(self) -> dict[str, Any]:
        """Do not dereference a linked view while capturing its complete physical state."""
        result: dict[str, Any] = {}
        for name in VIEWS:
            path = self.repo / name
            result[name] = (
                ("link", str(path.readlink()))
                if path.is_symlink()
                else ("file", path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else ("absent",)
            )
        return result


class LateCompletedRecord(ConsumerCase):
    """A loop tick does not establish that every later accepted order observation has been saved."""

    def interrupted_record(
        self, ledger_path: Path, prepared_path: Path, receipts: Path, prior: tuple[bytes, bytes, bytes]
    ) -> dict[str, Any]:
        """Accept preparation, fail only the final ledger save, and preserve the prior canonical evidence."""
        before, preparation_before, receipt_before = prior
        args = self.argv(
            "orders.py",
            "s1",
            "record",
            "--id",
            "late-mode",
            "--failure-mode",
            "late-mode",
            "--lesson",
            "Keep the complete late lesson.",
            "--scope",
            "agnostic",
            "--quote",
            PROMPT,
            "--loop",
            "logical-s1",
        )[2:]
        got = subprocess.run(
            [sys.executable, "-c", FINAL_SAVE_FAULT, str(self.root), str(ledger_path), *args],
            cwd=self.repo,
            env=self.native_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(got.stderr, "")
        out, seen = map(json.loads, got.stdout.splitlines())
        self.assertEqual((got.returncode, seen["rc"], out.get("pending_teardown")), (3, 3, True), out)
        self.assertEqual((seen["saved"], seen["refused"]), ([str(prepared_path)], [str(ledger_path)]))
        self.assertEqual(ledger_path.read_bytes(), before)
        self.assertNotEqual(prepared_path.read_bytes(), preparation_before)
        prepared: dict[str, Any] = json.loads(prepared_path.read_bytes())
        self.assertEqual([r["id"] for r in prepared["records"]], ["stable-mode", "late-mode"])
        self.assertTrue(receipts.read_bytes().startswith(receipt_before))
        rows = [json.loads(line) for line in receipts.read_bytes().split(b"\n") if line]
        self.assertEqual((rows[-1]["step"], rows[-1]["evidence_sha256"]), ("orders_prepared", lifecycle.sha(prepared)))
        return prepared

    def test_same_bound_tick_recovers_only_missing_observations_after_final_save_failure(self) -> None:
        """New and existing missing observations recover, preserving later text, aging and repeated-retry bytes."""
        for codex in (False, True):
            for backend in ("off", "muninn"):
                for existing in (False, True):
                    self.configured(codex, backend, "late" + str(existing))
                    self.assertEqual(self.record_order("s0", "aged-mode", "Keep aging intact.")[0], 0)
                    if existing:
                        self.assertEqual(self.record_order("s0", "late-mode", "Earlier late lesson.")[0], 0)
                    self.apply("s0")
                    self.assertEqual(self.stage("s1")[0], 0)
                    self.apply("s1")
                    self.assertEqual(self.stage("s2")[0], 0)
                    self.apply("s2")
                    self.assert_backend(backend)
                    ledger_path = self.repo / "orders.json"
                    prepared_path = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
                    receipts = self.repo / "s1/teardown.jsonl"
                    before, previous = ledger_path.read_bytes(), ol.open_ledger(self.repo)
                    preparation_before, receipt_before = prepared_path.read_bytes(), receipts.read_bytes()
                    saved = {
                        k: v
                        for k, v in cast("dict[str, Any]", ol.find(previous, "stable-mode")).items()
                        if k not in SEALS
                    }
                    aged = {
                        k: v
                        for k, v in cast("dict[str, Any]", ol.find(previous, "aged-mode")).items()
                        if k not in SEALS
                    }
                    self.assertEqual((saved["lesson"], aged["loops_since_recurrence"]), ("Lesson for s2", 2))
                    prepared = self.interrupted_record(
                        ledger_path, prepared_path, receipts, (before, preparation_before, receipt_before)
                    )
                    rc, retry, recovered = self.probe(ledger_path, "tick", "--loop", "logical-s1")
                    current = ol.open_ledger(self.repo)
                    late = ol.find(current, "late-mode") or {}
                    for boundary, actual, expected in (
                        ("retry", (rc, retry.get("ticked"), retry.get("pending_teardown", False)), (0, False, False)),
                        ("lesson", late.get("lesson"), "Keep the complete late lesson."),
                        ("counter", late.get("loops_since_recurrence"), 0),
                        (
                            "evidence",
                            [(e["session_id"], e["loop_id"]) for e in late.get("evidence", [])],
                            [("s0", "logical-s0"), ("s1", "logical-s1")] if existing else [("s1", "logical-s1")],
                        ),
                        (
                            "saved-observation",
                            {
                                k: v
                                for k, v in cast("dict[str, Any]", ol.find(current, "stable-mode")).items()
                                if k not in SEALS
                            },
                            saved,
                        ),
                        (
                            "aging",
                            {
                                k: v
                                for k, v in cast("dict[str, Any]", ol.find(current, "aged-mode")).items()
                                if k not in SEALS
                            },
                            aged,
                        ),
                        ("tick-keys", current["ticked_loops"], previous["ticked_loops"]),
                        (
                            "save-before-receipt",
                            [
                                e["destination"]
                                for e in recovered["events"]
                                if e["event"] == "replace" and e["destination"] in (str(ledger_path), str(receipts))
                            ],
                            [str(ledger_path), str(receipts)],
                        ),
                    ):
                        with self.subTest(codex=codex, backend=backend, existing=existing, boundary=boundary):
                            self.assertEqual(actual, expected, retry)
                    complete = [json.loads(line) for line in receipts.read_bytes().split(b"\n") if line]
                    with self.subTest(codex=codex, backend=backend, existing=existing, boundary="truthful-receipt"):
                        self.assertEqual(
                            (complete[-1]["step"], complete[-1]["evidence_sha256"]),
                            ("orders_ticked", lifecycle.sha(prepared)),
                        )
                    canonical, receipt_saved = self.canonical(), receipts.read_bytes()
                    rc, repeated = self.cli("tick", "--loop", "logical-s1")
                    with self.subTest(codex=codex, backend=backend, existing=existing, boundary="repeated-retry"):
                        self.assertEqual(
                            (rc, repeated.get("ticked"), repeated.get("pending_teardown", False)),
                            (0, False, False),
                            repeated,
                        )
                    self.assertTrue(self.canonical() == canonical)
                    self.assertEqual(receipts.read_bytes(), receipt_saved)
                    self.assertEqual(
                        prepared_path.read_bytes(), json.dumps(prepared, indent=1, sort_keys=True).encode() + b"\n"
                    )


class OwnedGeneratedViews(ConsumerCase):
    """The two fixed owned destinations reject physical links independently of marker contents."""

    def rendered_source(self, codex: bool, backend: str, label: str) -> None:
        """Keep a genuine normal canonical ledger and verify the actual current/backend-off path."""
        self.configured(codex, backend, label)
        self.assertEqual(self.stage("s1")[0], 0)
        self.apply("s1")
        self.assert_backend(backend)
        for name in VIEWS:
            (self.repo / name).write_text(ma.MARKER + "\nOriginal generated " + name + "\n")

    def test_both_owned_views_refuse_links_before_target_read_or_initialization(self) -> None:
        """Marked/unmarked outside files and dangling links remain untouched on both real render frontdoors."""
        for codex in (False, True):
            for backend in ("off", "muninn"):
                for name in VIEWS:
                    for kind in ("marked", "handwritten", "dangling"):
                        self.rendered_source(codex, backend, name + kind)
                        path = self.repo / name
                        outside = self.tmp / ("outside-" + str(codex) + backend + name + kind)
                        if kind != "dangling":
                            outside.write_text((ma.MARKER + "\n" if kind == "marked" else "") + "Outside text.\n")
                        raw = outside.read_bytes() if outside.exists() else None
                        path.unlink()
                        path.symlink_to(outside)
                        canonical, views = self.canonical(), self.views()
                        rc, out, seen = self.probe(path, "render")
                        for boundary, actual, expected in (
                            ("refusal", (rc, out.get("reason_code")), (2, "order_wrong_session")),
                            ("before-read", seen["opens"], NO_OPENS),
                            ("linked-path", path.is_symlink(), True),
                            ("outside-bytes", outside.read_bytes() if outside.exists() else None, raw),
                            ("fixed-view-state", self.views(), views),
                        ):
                            with self.subTest(codex=codex, backend=backend, name=name, kind=kind, boundary=boundary):
                                self.assertEqual(actual, expected, out)
                        self.assertTrue(self.canonical() == canonical, out)

    def test_regular_generated_views_and_handwritten_refusal_keep_existing_contract(self) -> None:
        """Ordinary marker-stamped views regenerate; regular handwritten sources still refuse unchanged."""
        for codex in (False, True):
            for backend in ("off", "muninn"):
                self.rendered_source(codex, backend, "regular")
                canonical = self.canonical()
                self.assertEqual(self.cli("render")[0], 0)
                generated = self.views()
                self.assertEqual(self.cli("render")[0], 0)
                self.assertEqual(self.views(), generated)
                for name in VIEWS:
                    path = self.repo / name
                    path.chmod(0o600)
                    path.write_text("Handwritten source remains here.\n")
                    rc, out = self.cli("render")
                    self.assertEqual((rc, out.get("degraded")), (3, "handwritten_protected"), out)
                    self.assertEqual(path.read_text(), "Handwritten source remains here.\n")
                    path.write_bytes(generated[name][1])
                self.assertTrue(self.canonical() == canonical)


if __name__ == "__main__":
    unittest.main()
