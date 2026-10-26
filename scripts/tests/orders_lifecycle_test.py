"""Owned preparation and durable-completion application of standing-order lifecycle effects."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.lib.loop_state_common import atomic_progress_update as progress_update  # noqa: E402
from scripts.lib import orders  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT, SESSION, StoreCase  # noqa: E402

STAMP = "2026-10-06T10:00:00+00:00"


def progress(repo: Path, session: str, loop: str, status: str = "complete") -> Path:
    """Independent minimal schema-3 graph with distinct directory/session/loop identities."""
    directory = repo / session
    directory.mkdir(exist_ok=True)
    state: dict[str, Any] = {
        "schema_version": 3,
        "session_id": session,
        "loop_id": loop,
        "revision": 1,
        "status": status,
        "created": STAMP,
        "updated_at": STAMP,
        "authorising_prompt_raw": "Run this bounded loop.",
        "completed_marker": 0,
        "work_units": {},
        "graph": {"nodes": {}, "edges": [], "joins": {}, "active_wave": None, "hard_stop": None},
    }
    path = directory / "progress.json"
    path.write_text(json.dumps(state))
    return path


def retrospective(repo: Path, session: str, loop: str) -> Path:
    """A completed source-bound retrospective with the original schema-2 required fields."""
    state_path = progress(repo, session, loop)
    state = json.loads(state_path.read_text())
    retro: dict[str, Any] = {
        "schema_version": 2,
        "session_id": session,
        "loop_id": loop,
        "status": "complete",
        "created": STAMP,
        "summary": "Completed bounded loop.",
        "artifacts": [],
        "review_themes": [],
        "decisions_absorbed": [],
        "loop_stop_counts": {},
        "models_used": [],
        "cost": {},
        "source_hashes": {"progress.json": hashlib.sha256(state_path.read_bytes()).hexdigest()},
        "revision": state["revision"],
    }
    path = state_path.with_name("retro.json")
    path.write_text(json.dumps(retro))
    return path


class OwnedCli(StoreCase):
    """Real subprocesses use only private progress, orders and fake-store files."""

    with_store = True

    def setUp(self) -> None:
        """Create a running owned graph and a private source directory."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.repo = self.tmp / "repo-key"
        self.repo.mkdir()
        self.path = progress(self.repo, SESSION, "logical-loop", "in-progress")

    def cli(self, *args: str, env: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        """Call the real CLI with a bounded subprocess and inspect its JSON payload."""
        got = subprocess.run(
            [sys.executable, str(REPO / "scripts/lib/orders.py"), "--dir", str(self.repo), "--session", SESSION, *args],
            capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=15,
        )  # fmt: skip
        self.assertEqual(got.stderr, "", got.stderr)
        return got.returncode, json.loads(got.stdout)

    def stage_record(self, *extra: str) -> tuple[int, dict[str, Any]]:
        """Stage one source-bound order."""
        return self.cli(
            "record",
            "--failure-mode",
            "stable-mode",
            "--lesson",
            "Keep the whole cited lesson.",
            "--loop",
            "logical-loop",
            "--quote",
            PROMPT,
            *extra,
        )

    def ledger(self) -> dict[str, Any]:
        """Read actual durable ledger contents, including absent-ledger empty state."""
        return ol.open_ledger(self.repo)

    def rows(self) -> list[dict[str, Any]]:
        """Read the actual observations without inferring command invocation from field presence."""
        path = self.path.with_name("teardown.jsonl")
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def complete(self) -> None:
        """Use the existing atomic progress writer for the successful durable commit boundary."""
        self.assertTrue(progress_update(self.path, lambda s: {**s, "status": "complete"}, preserve_updated_at=True))

    def test_running_record_only_prepares_without_recurrence(self) -> None:
        """A prospective completion may synchronize a claim but cannot create lifecycle evidence or ages."""
        rc, out = self.stage_record()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ledger()["orders"], [])
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)
        self.assertEqual([r["step"] for r in self.rows()], ["orders_prepared"])
        self.assertEqual(self.cli("tick", "--loop", "logical-loop")[0], 2)
        self.assertEqual(self.ledger()["ticked_loops"], [])

    def test_failed_progress_save_ages_nothing_then_apply_is_idempotent(self) -> None:
        """A failed atomic completion write leaves counts untouched; a durable one authorizes exactly one apply."""
        self.stage_record()
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)
        with mock.patch("hooks.scripts.lib.loop_state_common.os.replace", side_effect=OSError("disk-full")):
            self.assertFalse(progress_update(self.path, lambda s: {**s, "status": "complete"}))
        self.assertEqual(self.cli("tick", "--loop", "logical-loop")[0], 2)
        self.assertEqual(self.ledger()["orders"], [])
        self.assertNotIn("orders_ticked", [r["step"] for r in self.rows()])
        self.complete()
        rc, out = self.cli("tick", "--loop", "logical-loop")
        self.assertEqual((rc, out["ticked"]), (0, True))
        self.assertEqual(len(self.ledger()["orders"][0]["evidence"]), 1)
        self.assertEqual(self.cli("tick", "--loop", "logical-loop")[1]["ticked"], False)
        self.assertEqual(len(self.ledger()["orders"][0]["evidence"]), 1)
        self.assertEqual([r["step"] for r in self.rows()], ["orders_prepared", "orders_ticked"])

    def test_foreign_malformed_and_ineligible_sources_are_refused(self) -> None:
        """Only the genuine directory owner and a finished valid graph authorize preparing or ticking."""
        self.stage_record()
        original = json.loads(self.path.read_text())
        mutations = [
            {},
            {**original, "session_id": "foreign"},
            {**original, "loop_id": "invented"},
            {**original, "revision": True},
            {**original, "work_units": {"1": {"status": "pending"}}},
            {**original, "graph": {**original["graph"], "hard_stop": {"reason": "blocked"}}},
        ]
        for state in mutations:
            with self.subTest(state=state):
                self.path.write_text(json.dumps(state))
                self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 2)
                self.assertEqual(self.cli("tick", "--loop", "logical-loop")[0], 2)
                self.assertEqual(self.ledger()["orders"], [])
        self.path.write_text(json.dumps(original))
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)

    def test_changed_source_and_invented_receipt_cannot_apply(self) -> None:
        """A claimed observation cannot replace genuine preparation, and stale prepared progress is rejected."""
        self.path.with_name("teardown.jsonl").write_text(json.dumps({"step": "orders_prepared"}) + "\n")
        self.complete()
        self.assertEqual(self.cli("tick", "--loop", "logical-loop")[0], 2)
        self.path = progress(self.repo, SESSION, "logical-loop", "in-progress")
        self.stage_record()
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)
        self.complete()
        state = json.loads(self.path.read_text())
        state["authorising_prompt_raw"] = "changed source"
        self.path.write_text(json.dumps(state))
        self.assertEqual(self.cli("tick", "--loop", "logical-loop")[0], 2)
        self.assertEqual(self.ledger()["orders"], [])

    def test_receipt_failure_recovers_after_saved_ledger(self) -> None:
        """A ledger saved before a failed receipt remains pending, then retries without another lifecycle effect."""
        self.stage_record()
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)
        self.complete()
        receipts = self.path.with_name("teardown.jsonl")
        original = receipts.read_text()
        output = io.StringIO()
        argv = ["--dir", str(self.repo), "--session", SESSION, "tick", "--loop", "logical-loop"]
        with (
            mock.patch.object(lifecycle, "write_bytes", side_effect=OSError("receipt-publication")),
            contextlib.redirect_stdout(output),
        ):
            rc = orders.main(argv)
        out = json.loads(output.getvalue())
        self.assertEqual((rc, out.get("pending_teardown")), (3, True))
        self.assertEqual(len(self.ledger()["orders"][0]["evidence"]), 1)
        self.assertEqual(receipts.read_text(), original)
        rc, out = self.cli("tick", "--loop", "logical-loop")
        self.assertEqual((rc, out["ticked"]), (0, False))
        self.assertEqual(len(self.ledger()["orders"][0]["evidence"]), 1)
        self.assertEqual([r["step"] for r in self.rows()], ["orders_prepared", "orders_ticked"])

    def test_failed_ledger_save_emits_no_tick_receipt(self) -> None:
        """An actual ledger-save exception must not emit orders_ticked or claim a successful lifecycle effect."""
        self.stage_record()
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)
        self.complete()
        argv = ["--dir", str(self.repo), "--session", SESSION, "tick", "--loop", "logical-loop"]
        with mock.patch.object(ol, "save", side_effect=OSError("disk-full")), contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(orders.main(argv), 0)
        self.assertEqual(self.ledger()["orders"], [])
        self.assertNotIn("orders_ticked", [r["step"] for r in self.rows()])

    def test_same_logical_loop_in_different_sessions_is_not_a_tick_collision(self) -> None:
        """Completed session+loop identities must age a survivor independently."""
        self.stage_record()
        self.assertEqual(self.cli("prepare", "--loop", "logical-loop")[0], 0)
        self.complete()
        self.assertEqual(self.cli("tick", "--loop", "logical-loop")[0], 0)
        for session in ("other-session", "third-session"):
            progress(self.repo, session, "logical-loop", "in-progress")
            prefix = [
                sys.executable,
                str(REPO / "scripts/lib/orders.py"),
                "--dir",
                str(self.repo),
                "--session",
                session,
            ]
            for command in (["prepare", "--loop", "logical-loop"],):
                got = subprocess.run([*prefix, *command], capture_output=True, text=True, timeout=15)
                self.assertEqual(got.returncode, 0, got.stdout)
            path = self.repo / session / "progress.json"
            self.assertTrue(progress_update(path, lambda s: {**s, "status": "complete"}, preserve_updated_at=True))
            got = subprocess.run(
                [*prefix, "tick", "--loop", "logical-loop"], capture_output=True, text=True, timeout=15
            )
            self.assertEqual(got.returncode, 0, got.stdout)
        self.assertEqual(self.ledger()["orders"][0]["loops_since_recurrence"], 2)

    def test_codex_apply_uses_the_real_provider_revision_contract(self) -> None:
        """The Codex package CLI accepts its completion increment and rejects arbitrary revisions."""
        self.stage_record()
        script = REPO / "packages/codex/scripts/lib/orders.py"
        prefix = [sys.executable, str(script), "--dir", str(self.repo), "--session", SESSION]
        prepared = subprocess.run(
            [*prefix, "prepare", "--loop", "logical-loop"], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        state = json.loads(self.path.read_text())
        for revision in (4, True):
            self.path.write_text(
                json.dumps({**state, "status": "complete", "revision": revision, "completion": {"revision": 1}})
            )
            got = subprocess.run(
                [*prefix, "tick", "--loop", "logical-loop"], capture_output=True, text=True, timeout=15
            )
            self.assertEqual(got.returncode, 2, got.stdout)
            self.assertEqual(self.ledger()["orders"], [])
        self.path.write_text(json.dumps({**state, "status": "complete", "revision": 2, "completion": {"revision": 1}}))
        for expected in (True, False):
            got = subprocess.run(
                [*prefix, "tick", "--loop", "logical-loop"], capture_output=True, text=True, timeout=15
            )
            self.assertEqual((got.returncode, json.loads(got.stdout).get("ticked")), (0, expected), got.stderr)
        self.assertEqual(len(self.ledger()["orders"][0]["evidence"]), 1)


class TypedInputs(StoreCase):
    """Typed models reject lossy identifiers, counters and ambiguous legacy conversion."""

    with_store = True

    def test_sealed_malformed_counter_and_duplicate_evidence_are_rejected(self) -> None:
        """Recomputing integrity hashes cannot turn booleans, negatives or invented evidence into valid counters."""
        ledger = ol.record(ol.empty(), "valid", "lesson", session_id="s1", loop_id="L1", now=STAMP)["ledger"]
        for value in (True, -1, 1.5, "2"):
            damaged = copy.deepcopy(ledger)
            damaged["orders"][0]["loops_since_recurrence"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                ol.verify(ol.seal(damaged))
        damaged = copy.deepcopy(ledger)
        damaged["orders"][0]["evidence"] *= 2
        with self.assertRaises(ValueError):
            ol.verify(ol.seal(damaged))

    def test_owned_creation_and_sealed_order_fields_remain_typed(self) -> None:
        """Truthy metadata and recomputed hashes cannot make invented source fields eligible."""
        repo = self.tmp / "repo"
        repo.mkdir()
        path = progress(repo, "s1", "L1")
        original = json.loads(path.read_text())
        for value in (True, ["made-up"], "not a timestamp"):
            path.write_text(json.dumps({**original, "created": value}))
            with self.subTest(value=value), self.assertRaises(ValueError):
                lifecycle.owned(repo, "s1", "L1", complete=True)
        ledger = ol.record(ol.empty(), "valid", "lesson", session_id="s1", loop_id="L1", now=STAMP)["ledger"]
        changes: list[dict[str, Any]] = [
            {"lesson": []},
            {"failure_mode": ""},
            {"last_recurred": True},
            {"muninn": {"state": "written", "id": None}},
        ]
        for fields in changes:
            damaged = copy.deepcopy(ledger)
            damaged["orders"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ol.verify(ol.seal(damaged))

    def test_lossy_ids_are_nonempty_distinct_and_explicit_collision_is_refused(self) -> None:
        """Unicode, punctuation and long prefixes must not silently merge different failure modes."""
        texts = ["失败", "A/B thing", "a b thing", "a" * 130 + "x", "a" * 130 + "y"]
        ids = [ol.slug(text) for text in texts]
        self.assertEqual(len(set(ids)), len(texts))
        self.assertTrue(all(ids))
        ledger = ol.record(
            ol.empty(), "same-id", "lesson", session_id="s1", loop_id="L1", now=STAMP, failure_mode="first mode"
        )["ledger"]
        with self.assertRaisesRegex(ValueError, "order_id_collision"):
            ol.record(
                ledger, "same-id", "lesson", session_id="s1", loop_id="L2", now=STAMP, failure_mode="another mode"
            )

    def test_legacy_conversion_preserves_decayed_and_rejects_ambiguous_fields(self) -> None:
        """Imported counters at K=5 remain tombstones; duplicate/missing fields and empty lessons are refused."""
        body = "### lossless\n**loops_since_recurrence:** 5\n**First seen:** session old\nLesson text.\n"
        parsed = ol.parse_legacy(body, STAMP)
        self.assertEqual((parsed[0]["status"], parsed[0]["loops_since_recurrence"]), ("decayed", 5))
        for text in [
            body + body,
            body.replace("Lesson text.", ""),
            body + "**loops_since_recurrence:** 1\n",
            body.replace("**First seen:** session old\n", ""),
        ]:
            with self.subTest(text=text), self.assertRaises(ol.LegacyParseError):
                ol.parse_legacy(text, STAMP)

    def test_invalid_and_incomplete_retros_do_not_count(self) -> None:
        """Graduation counts distinct valid completed source-bound retros; incomplete or stale ones add nothing."""
        repo = self.tmp / "repo"
        repo.mkdir()
        for n in range(10):
            path = retrospective(repo, f"s{n}", f"L{n}")
            self.assertTrue(path.is_file())
        self.assertEqual(ol.retro_count(repo), 10)
        for n in range(10):
            path = repo / f"s{n}" / "retro.json"
            data = json.loads(path.read_text())
            mutations = [
                {"schema_version": 2, "loop_id": "invented"},
                {**data, "schema_version": True},
                {**data, "status": "incomplete"},
                {**data, "session_id": "foreign"},
                {**data, "source_hashes": {"progress.json": "0" * 64}},
            ]
            path.write_text(json.dumps(mutations[n % len(mutations)]))
        self.assertEqual(ol.retro_count(repo), 0)

    def test_incomplete_schema2_and_unsupported_schema3_are_not_known_counts(self) -> None:
        """Missing complete fields are invalid; an unavailable schema3 validator is an explicit refusal."""
        repo = self.tmp / "repo"
        repo.mkdir()
        path = retrospective(repo, "s1", "L1")
        original = json.loads(path.read_text())
        for field in (
            "summary",
            "artifacts",
            "review_themes",
            "decisions_absorbed",
            "loop_stop_counts",
            "models_used",
            "cost",
        ):
            path.write_text(json.dumps({k: v for k, v in original.items() if k != field}))
            with self.subTest(field=field):
                self.assertEqual(ol.retro_count(repo), 0)
        path.write_text(json.dumps({**original, "schema_version": 3}))
        with self.assertRaisesRegex(ValueError, "order_retro_validator_unavailable"):
            ol.retro_count(repo)

    def test_duplicate_record_cannot_rejuvenate_an_aged_order(self) -> None:
        """The same completed source cannot reset a counter or revive its later tombstone."""
        ledger = ol.record(ol.empty(), "valid", "lesson", session_id="s1", loop_id="L1", now=STAMP)["ledger"]
        for n in range(5):
            ledger = ol.tick(ledger, f"T{n}", STAMP)["ledger"]
        out = ol.record(ledger, "valid", "lesson", session_id="s1", loop_id="L1", now=STAMP)["ledger"]
        self.assertEqual((out["orders"][0]["status"], out["orders"][0]["loops_since_recurrence"]), ("decayed", 5))


if __name__ == "__main__":
    unittest.main()
