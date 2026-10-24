"""Current cited authority, chronology and owned artifact paths through both native CLIs."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, cast

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests import lessons_test as lesson_cases  # noqa: E402
from scripts.tests import orders_recovery_test as recovery  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress  # noqa: E402

PATH_PROBE = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders, orders_lifecycle as lifecycle
canonical = sys.argv[2]
reads, opens = 0, 0
real_object, real_open = lifecycle.object_file, Path.open
def object_file(path):
    global reads
    if str(path) == canonical:
        reads += 1
    return real_object(path)
def opened(path, *args, **kwargs):
    global opens
    if str(path) == canonical:
        opens += 1
    return real_open(path, *args, **kwargs)
lifecycle.object_file, Path.open = object_file, opened
rc = orders.main(sys.argv[3:])
print(json.dumps({'reads': reads, 'opens': opens, 'rc': rc}))
raise SystemExit(rc)
"""


class CitationChronology(recovery.RecoveryCase):
    """Store currentness is separate from a sealed lifecycle snapshot and cached write metadata."""

    def record_text(self, session: str, text: str, quote: str = PROMPT) -> tuple[int, dict[str, Any]]:
        """Use a genuine eligible source and the explicit lesson-authoring frontdoor."""
        if not (self.repo / session / "progress.json").exists():
            self.owner(session)
        return self.cli(
            "record",
            "--id",
            "stable-mode",
            "--failure-mode",
            "stable-mode",
            "--lesson",
            text,
            "--scope",
            "agnostic",
            "--loop",
            "logical-" + session,
            "--quote",
            quote,
            session=session,
        )

    def apply(self, session: str) -> dict[str, Any]:
        """Durably complete before actual local application; no test invents a precompletion tick."""
        self.complete(session)
        rc, out = self.cli("tick", "--loop", "logical-" + session, session=session)
        self.assertIn(rc, (0, 3), out)
        return cast("dict[str, Any]", ol.open_ledger(self.repo)["orders"][0])

    def test_cite_reconciles_newer_staged_claim_without_authoring_old_ledger_text(self) -> None:
        """Cite of applied A never supersedes a legitimate later current B; explicit record may author C."""
        for codex in (False, True):
            self.configure(codex, "chronology")
            self.assertEqual(self.record_text("s1", "Lesson A")[0], 0)
            first = self.apply("s1")
            self.assertEqual(self.record_text("s2", "Lesson B")[0], 0)
            self.assertEqual(ol.open_ledger(self.repo)["orders"][0]["lesson"], "Lesson A")
            prior = self.store_rows()
            rc, out = self.cli("cite", "stable-mode", "--quote", PROMPT)
            with self.subTest(codex=codex, boundary="cite"):
                self.assertEqual(rc, 0, out)
                self.assertNotEqual(out["muninn"]["id"], first["muninn"]["id"])
                self.assertEqual(self.store_rows(), prior)
            with self.subTest(codex=codex, boundary="current-query"):
                current = self.cli("query", script="lessons.py")[1]["lessons"]
                self.assertEqual([r["text"] for r in current], ["Lesson B"])
            self.apply("s2")
            with self.subTest(codex=codex, boundary="after-apply"):
                self.assertEqual(self.cli("query", script="lessons.py")[1]["lessons"][0]["text"], "Lesson B")
            self.assertEqual(self.record_text("s3", "Lesson C")[0], 0)
            self.assertEqual(self.cli("query", script="lessons.py")[1]["lessons"][0]["text"], "Lesson C")

    def test_completed_tick_preserves_later_good_citation_over_old_prepared_metadata(self) -> None:
        """No-id and old-id preparations cannot erase a later saved current citation, including read failure."""
        exe = self.tmp / "bin/muninn"
        original = exe.read_bytes()
        for codex in (False, True):
            for old_id in (False, True):
                for unavailable in (False, True):
                    exe.write_bytes(original)
                    self.configure(codex, f"provenance{old_id}{unavailable}")
                    self.assertIn(self.record_text("s1", "Stable lesson", PROMPT if old_id else "")[0], (0, 3))
                    self.apply("s1")
                    if old_id:
                        lesson_cases.SessionAttribution.unavailable_list(self)
                    self.assertEqual(self.record_text("s2", "Stable lesson", "")[0], 3)
                    exe.write_bytes(original)
                    if old_id:
                        self.sql("UPDATE knowledge SET status = 'retracted'")
                        self.assertEqual(self.record_text("s3", "Stable lesson")[0], 0)
                    rc, cited = self.cli("cite", "stable-mode", "--quote", PROMPT)
                    self.assertEqual(rc, 0, cited)
                    known = cited["muninn"]["id"]
                    if unavailable:
                        lesson_cases.SessionAttribution.unavailable_list(self)
                    self.complete("s2")
                    reads = sum(r["command"] == "memory.list" for r in self.trace_rows())
                    store = self.store_rows()
                    rc, applied = self.cli("tick", "--loop", "logical-s2", session="s2")
                    order = ol.open_ledger(self.repo)["orders"][0]
                    with self.subTest(codex=codex, old_id=old_id, unavailable=unavailable, boundary="provenance"):
                        self.assertEqual(order["muninn"]["id"], known, applied)
                    with self.subTest(codex=codex, old_id=old_id, unavailable=unavailable, boundary="state"):
                        self.assertEqual(order["muninn"]["state"], "degraded" if unavailable else "written")
                    with self.subTest(codex=codex, old_id=old_id, unavailable=unavailable, boundary="exit"):
                        self.assertEqual(rc, 3 if unavailable else 0, applied)
                    if unavailable:
                        with self.subTest(codex=codex, old_id=old_id, boundary="fresh-read-counter"):
                            self.assertGreater(sum(r["command"] == "memory.list" for r in self.trace_rows()), reads)
                    self.assertEqual(self.store_rows(), store)
                    exe.write_bytes(original)
                    saved = ol.open_ledger(self.repo)
                    rc, retry = self.cli("tick", "--loop", "logical-s2", session="s2")
                    after = ol.open_ledger(self.repo)
                    with self.subTest(codex=codex, old_id=old_id, unavailable=unavailable, boundary="retry"):
                        self.assertEqual((rc, retry["ticked"]), (0, False), retry)
                        self.assertEqual(after["orders"][0]["muninn"]["id"], known)
                        self.assertEqual(after["orders"][0]["muninn"]["state"], "written")
                        self.assertEqual(after["ticked_loops"], saved["ticked_loops"])
                        self.assertEqual(after["orders"][0]["evidence"], saved["orders"][0]["evidence"])

    def test_promotion_uses_current_join_despite_cached_degraded_or_pending(self) -> None:
        """Recovered current citations authorize promotion without an extra write to fix cached state."""
        exe = self.tmp / "bin/muninn"
        original = exe.read_bytes()
        for codex in (False, True):
            exe.write_bytes(original)
            self.configure(codex, "promotion")
            for sid in ("s1", "s2", "s3"):
                self.assertEqual(self.record_text(sid, "Current promotion lesson")[0], 0)
                self.apply(sid)
            lesson_cases.SessionAttribution.unavailable_list(self)
            self.assertEqual(self.cli("cite", "stable-mode", "--quote", PROMPT)[0], 3)
            exe.write_bytes(original)
            for state in ("degraded", "pending"):
                if state == "pending":
                    ledger = ol.open_ledger(self.repo)
                    order = ledger["orders"][0]
                    ledger = ol.set_muninn(ledger, order["id"], {**order["muninn"], "state": "pending"})
                    ol.save(self.repo / "orders.json", ledger)
                self.assertEqual(ol.open_ledger(self.repo)["orders"][0]["muninn"]["state"], state)
                before = self.store_rows()
                with self.subTest(codex=codex, state=state):
                    self.assertEqual(self.cli("query", script="lessons.py")[1]["lessons"][0]["cited"], True)
                    rc, out = self.cli("predicate", script="lessons.py")
                    self.assertEqual(rc, 0, out)
                    self.assertEqual([r["lesson"] for r in out["candidates"]], ["Current promotion lesson"])
                    self.assertEqual(self.store_rows(), before)

    def test_different_valid_current_claims_refuse_instead_of_numeric_or_cached_choice(self) -> None:
        """The actual store allows tagged adds without supersession; differing current claims are ambiguous."""
        for codex in (False, True):
            self.configure(codex, "ambiguous")
            self.assertEqual(self.record_text("s1", "First valid claim")[0], 0)
            self.apply("s1")
            self.owner("s2")
            rc, added = self.muninn(
                "know",
                "add",
                "--kind",
                "lesson",
                "--text",
                "Different valid claim",
                "--cite",
                "claude:s2:1.1",
                "--quote",
                PROMPT,
                "--tag",
                "order",
                "--tag",
                "ord-stable-mode",
                extra_env=self.native_env,
            )
            self.assertEqual(rc, 0, added)
            prior = self.store_rows()
            for script, command in (
                ("lessons.py", ("query",)),
                ("orders.py", ("cite", "stable-mode", "--quote", PROMPT)),
            ):
                with self.subTest(codex=codex, script=script):
                    rc, out = self.cli(*command, script=script)
                    self.assertIn(rc, (2, 3), out)
                    reason = out.get("reason_code") or out.get("degraded") or out.get("muninn", {}).get("reason_code")
                    self.assertEqual(reason, "lesson_not_current", out)
                    self.assertEqual(self.store_rows(), prior)

    def test_uncited_first_attachment_ignores_divergent_advanced_historical_text(self) -> None:
        """Historical rows bind immutable identity; they cannot permanently veto the active ledger's first cite."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex, "historical-text")
                for sid, text in (("s1", "Historical A"), ("s2", "Active B")):
                    self.assertEqual(self.record_text(sid, text, "")[0], 3)
                    self.apply(sid)
                progress(self.repo, "s1", "next-logical-loop", "in-progress")
                self.assertEqual(self.store_rows(), [])
                rc, out = self.cli("cite", "stable-mode", "--quote", PROMPT)
                self.assertEqual(rc, 0, out)
                self.assertEqual([row[1] for row in self.store_rows()], ["Active B"])
                self.assertEqual(self.cli("query", script="lessons.py")[1]["lessons"][0]["text"], "Active B")

    def test_cite_with_former_cited_id_and_no_current_replacement_refuses_implicit_reauthoring(self) -> None:
        """A retracted formerly cited claim is absent authority; cite cannot recreate it as a new lesson."""
        for codex in (False, True):
            self.configure(codex, "absent-current")
            self.assertEqual(self.record_text("s1", "Former claim")[0], 0)
            known = self.apply("s1")["muninn"]["id"]
            self.sql("UPDATE knowledge SET status = 'retracted'")
            before = self.store_rows()
            rc, out = self.cli("cite", "stable-mode", "--quote", PROMPT)
            with self.subTest(codex=codex, boundary="refusal"):
                self.assertIn(rc, (2, 3), out)
                self.assertEqual(out.get("reason_code", out.get("muninn", {}).get("reason_code")), "lesson_not_current")
            with self.subTest(codex=codex, boundary="no-knowledge-write"):
                self.assertEqual(self.store_rows(), before)
                self.assertEqual(ol.open_ledger(self.repo)["orders"][0]["muninn"]["id"], known)


class OwnedArtifacts(recovery.RecoveryCase):
    """Linked canonical artifacts refuse before their read/open rather than relying on later binding checks."""

    def probe(self, canonical: Path, *args: str) -> tuple[int, dict[str, Any], dict[str, Any]]:
        """Instrument the real reader/open boundary, without replacing its outcome or disk operations."""
        got = subprocess.run(
            [
                sys.executable,
                "-c",
                PATH_PROBE,
                str(self.root),
                str(canonical),
                *self.argv("orders.py", "s1", *args)[2:],
            ],
            capture_output=True,
            text=True,
            env=self.native_env,
            timeout=15,
        )
        self.assertEqual(got.stderr, "")
        out, probe = map(json.loads, got.stdout.splitlines())
        return got.returncode, out, probe

    def test_active_preparation_frontdoors_refuse_links_before_external_read(self) -> None:
        """Prepare, CAS refresh, record and empty completed tick share the owned canonical-path rule."""
        for codex in (False, True):
            for command in ("prepare", "refresh", "record", "tick"):
                self.configure(codex, command)
                if command == "tick":
                    self.assertEqual(self.stage("s0")[0], 0)
                    self.complete("s0")
                    self.assertEqual(self.cli("tick", "--loop", "logical-s0", session="s0")[0], 0)
                self.owner("s1")
                rc, prepared = self.cli("prepare", "--loop", "logical-s1")
                self.assertEqual(rc, 0, prepared)
                if command == "tick":
                    self.complete("s1")
                path = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
                foreign = self.tmp / f"foreign-preparation-{codex}-{command}.json"
                path.rename(foreign)
                path.symlink_to(foreign)
                raw = foreign.read_bytes()
                before = ol.open_ledger(self.repo)
                receipt = (path.parent / "teardown.jsonl").read_bytes()
                args = ["tick" if command == "tick" else "prepare", "--loop", "logical-s1"]
                if command == "refresh":
                    args += ["--refresh-from-sha256", prepared["evidence_sha256"]]
                if command == "record":
                    args = [
                        "record",
                        "--id",
                        "new-id",
                        "--failure-mode",
                        "new-mode",
                        "--lesson",
                        "New lesson",
                        "--loop",
                        "logical-s1",
                        "--quote",
                        PROMPT,
                    ]
                rc, out, probe = self.probe(path, *args)
                with self.subTest(codex=codex, command=command, boundary="refusal"):
                    self.assertEqual(rc, 2, out)
                with self.subTest(codex=codex, command=command, boundary="before-read"):
                    self.assertEqual(probe["reads"], 0, probe)
                if command == "tick":
                    with self.subTest(codex=codex, command=command, boundary="no-aging"):
                        self.assertEqual(ol.open_ledger(self.repo)["orders"][0]["loops_since_recurrence"], 0)
                with self.subTest(codex=codex, command=command, boundary="no-mutation"):
                    self.assertTrue(path.is_symlink())
                    self.assertEqual(foreign.read_bytes(), raw)
                    self.assertEqual(ol.open_ledger(self.repo), before)
                    self.assertEqual((path.parent / "teardown.jsonl").read_bytes(), receipt)

    def test_receipt_and_persistent_sidecar_links_refuse_before_read_open_or_create(self) -> None:
        """A dangling lock sidecar must not create an external target; linked evidence remains untouched."""
        for codex in (False, True):
            for kind in ("receipt", "sidecar", "dangling-sidecar"):
                self.configure(codex, kind)
                self.owner("s1")
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 0)
                receipt = self.repo / "s1/teardown.jsonl"
                path = receipt if kind == "receipt" else receipt.with_name("teardown.jsonl.lock")
                foreign = self.tmp / f"foreign-{codex}-{kind}"
                if kind == "dangling-sidecar":
                    path.rename(self.tmp / f"retained-lock-{codex}")
                    raw = None
                else:
                    path.rename(foreign)
                    raw = foreign.read_bytes()
                path.symlink_to(foreign)
                rc, out, probe = self.probe(path, "prepare", "--loop", "logical-s1")
                with self.subTest(codex=codex, kind=kind, boundary="refusal"):
                    self.assertEqual(rc, 2, out)
                with self.subTest(codex=codex, kind=kind, boundary="before-open"):
                    self.assertEqual(probe["opens"], 0, probe)
                with self.subTest(codex=codex, kind=kind, boundary="untouched"):
                    self.assertTrue(path.is_symlink())
                    self.assertEqual(foreign.read_bytes() if foreign.exists() else None, raw)

    def test_unicode_inside_a_json_string_is_not_a_record_separator(self) -> None:
        """Physical LF framing still permits legitimate Unicode in a complete JSON object's string."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex, "unicode-string")
                self.owner("s1")
                path = self.repo / "s1/teardown.jsonl"
                raw = (
                    json.dumps({"step": "other", "text": "inside\u0085and\u2028string"}, ensure_ascii=False) + "\n"
                ).encode()
                path.write_bytes(raw)
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 0)
                self.assertTrue(path.read_bytes().startswith(raw))

    def test_nonfinite_extra_value_refuses_even_when_receipt_would_dedupe(self) -> None:
        """Matching evidence cannot waive strict finite validation of its complete prior row."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex, "nonfinite-match")
                self.owner("s1")
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 0)
                path = self.repo / "s1/teardown.jsonl"
                row = json.loads(path.read_bytes())
                row["extra"] = "overflow"
                raw = (json.dumps(row).replace('"overflow"', "1e999") + "\n").encode()
                path.write_bytes(raw)
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 2)
                self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
