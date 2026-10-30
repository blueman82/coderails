"""Current-hash recovery of an owned, incomplete standing-order preparation."""

from __future__ import annotations

import contextlib
import copy
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
from hooks.scripts.lib.loop_state_common import atomic_progress_update  # noqa: E402
from scripts.lib import orders  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests import orders_recovery_test as recovery  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT, SESSION, StoreCase  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress  # noqa: E402

LOOP = "separate-logical-loop"


class PreparationRefresh(StoreCase):
    """Real eligible sources, durable preparations and ledger files; no live store or completion gate."""

    with_store = True

    def setUp(self) -> None:
        """Stage a genuine cited observation while progress remains incomplete."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.repo = self.tmp / "repo-key"
        self.repo.mkdir()
        self.path = progress(self.repo, SESSION, LOOP, "in-progress")
        self.prep = lifecycle.preparation_path(self.path.parent, LOOP)
        rc, out = self.cli(
            "record", "--failure-mode", "stable-mode", "--lesson", "Keep this complete lesson.",
            "--loop", LOOP, "--quote", PROMPT,
        )  # fmt: skip
        self.assertEqual(rc, 0, out)
        self.original = json.loads(self.prep.read_text())
        self.current_hash = lifecycle.sha(self.original)

    def argv(self, *args: str, codex: bool = False) -> list[str]:
        """Bind the actual provider package CLI explicitly, never a caller-selected revision flag."""
        root = REPO / "packages/codex" if codex else REPO
        return [
            sys.executable,
            str(root / "scripts/lib/orders.py"),
            "--dir",
            str(self.repo),
            "--session",
            SESSION,
            *args,
        ]

    def cli(self, *args: str, codex: bool = False) -> tuple[int, dict[str, Any]]:
        """Run the native entrypoint; retain parser refusal as a real RED failure of the missing interface."""
        got = subprocess.run(self.argv(*args, codex=codex), capture_output=True, text=True, timeout=15)
        return got.returncode, json.loads(got.stdout) if got.stdout.strip() else {"stderr": got.stderr}

    def revise(self, **fields: Any) -> None:  # noqa: ANN401
        """Use the real atomic writer to save a new owned source without declaring completion."""
        self.assertTrue(
            atomic_progress_update(
                self.path, lambda state: {**state, **fields}, preserve_updated_at=fields.get("status") == "complete"
            )
        )

    def refresh(self, evidence: str | None = None) -> tuple[int, dict[str, Any]]:
        """Supply the current preparation's canonical evidence hash as the compare-and-swap input."""
        return self.cli("prepare", "--loop", LOOP, "--refresh-from-sha256", evidence or self.current_hash)

    def observations(self) -> list[dict[str, Any]]:
        """Read durable observations; invocation alone proves nothing."""
        return [json.loads(line) for line in self.path.with_name("teardown.jsonl").read_text().splitlines()]

    def assert_no_effects(self) -> None:
        """Prospective recovery must never age orders or manufacture recurrence evidence."""
        ledger = ol.open_ledger(self.repo)
        self.assertEqual((ledger["orders"], ledger["ticked_loops"]), ([], []))
        self.assertEqual(json.loads(self.path.read_text())["status"], "in-progress")
        self.assertNotIn("orders_ticked", [row["step"] for row in self.observations()])

    def test_refresh_current_hash_preserves_records_and_is_effect_free(self) -> None:
        """Same-revision source changes and later eligible revisions need an explicit current-hash refresh."""
        self.revise(last_updated="2026-10-07T10:00:00+00:00")
        self.assertEqual(self.cli("prepare", "--loop", LOOP)[0], 2)
        rc, out = self.refresh()
        self.assertEqual(rc, 0, out)
        saved = json.loads(self.prep.read_text())
        self.assertEqual(saved["records"], self.original["records"])
        self.assertEqual(out["evidence_sha256"], lifecycle.sha(saved))
        self.assertNotEqual(out["evidence_sha256"], self.current_hash)
        self.current_hash = out["evidence_sha256"]
        self.revise(revision=2)
        rc, out = self.refresh()
        self.assertEqual(rc, 0, out)
        saved = json.loads(self.prep.read_text())
        self.assertEqual((saved["binding"]["revision"], saved["records"]), (2, self.original["records"]))
        self.assertEqual(out["evidence_sha256"], lifecycle.sha(saved))
        self.assert_no_effects()

    def test_wrong_or_historical_hash_refuses_unchanged(self) -> None:
        """A historical receipt cannot authorize refresh of the current canonical preparation."""
        self.revise(revision=2)
        before = self.prep.read_bytes()
        for bad in ("0" * 64, "not-a-hash"):
            rc, out = self.refresh(bad)
            self.assertEqual((rc, out.get("reason_code")), (2, "order_source_mismatch"), out)
            self.assertEqual(self.prep.read_bytes(), before)
        self.assertEqual(self.refresh()[0], 0)
        saved = self.prep.read_bytes()
        self.revise(revision=3)
        rc, out = self.refresh()
        self.assertEqual((rc, out.get("reason_code")), (2, "order_source_mismatch"), out)
        self.assertEqual(self.prep.read_bytes(), saved)
        self.assert_no_effects()

    def test_invalid_foreign_complete_and_rollback_sources_refuse_unchanged(self) -> None:
        """CAS is no bypass for genuine source ownership, graph eligibility, revision or completion checks."""
        state = json.loads(self.path.read_text())
        before = self.prep.read_bytes()
        mutations = [
            {**state, "session_id": "foreign"},
            {**state, "loop_id": "foreign-loop"},
            {**state, "revision": True},
            {**state, "status": "complete"},
            {**state, "work_units": {"u": {"status": "pending"}}},
            {**state, "graph": {**state["graph"], "hard_stop": {"reason": "blocked"}}},
        ]
        for changed in mutations:
            with self.subTest(changed=changed):
                self.path.write_text(json.dumps(changed))
                self.assertEqual(self.refresh()[0], 2)
                self.assertEqual(self.prep.read_bytes(), before)
        self.path.write_text(json.dumps(state))
        self.revise(revision=2)
        rc, out = self.refresh()
        self.assertEqual(rc, 0, out)
        self.current_hash = out["evidence_sha256"]
        before = self.prep.read_bytes()
        self.revise(revision=1)
        self.assertEqual(self.refresh()[0], 2)
        self.assertEqual(self.prep.read_bytes(), before)

    def test_foreign_preparation_binding_cannot_be_rebound(self) -> None:
        """Even the current hash cannot change immutable resolved directory, session or logical-loop identities."""
        self.revise(revision=2)
        for field in ("repo_dir", "state_dir", "session_id", "loop_id"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.original)
                changed["binding"][field] = "foreign"
                self.prep.write_text(json.dumps(changed))
                self.current_hash = lifecycle.sha(changed)
                before = self.prep.read_bytes()
                self.assertEqual(self.refresh()[0], 2)
                self.assertEqual(self.prep.read_bytes(), before)
        self.assert_no_effects()

    def test_applied_tick_or_recurrence_forbids_refresh(self) -> None:
        """An incomplete-looking source cannot replay an identity whose local lifecycle effect already applied."""
        self.revise(revision=2)
        before = self.prep.read_bytes()
        ticked = ol.seal({**ol.empty(), "ticked_loops": [lifecycle.loop_key(SESSION, LOOP)]})
        recurrent = ol.record(
            ol.empty(), "older-mode", "Keep prior evidence.", session_id=SESSION, loop_id=LOOP, now="2026-10-06"
        )["ledger"]
        for ledger in (ticked, recurrent):
            with self.subTest(ledger=ledger):
                ol.save(self.repo / "orders.json", ledger)
                before_ledger = (self.repo / "orders.json").read_bytes()
                self.assertEqual(self.refresh()[0], 2)
                self.assertEqual(self.prep.read_bytes(), before)
                self.assertEqual((self.repo / "orders.json").read_bytes(), before_ledger)

    def test_concurrent_refresh_compares_current_hash_under_the_one_lock(self) -> None:
        """Two real processes racing one old hash produce one replacement and one stale refusal."""
        self.revise(revision=2)
        argv = self.argv("prepare", "--loop", LOOP, "--refresh-from-sha256", self.current_hash)
        with (
            subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as one,
            subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as two,
        ):
            output = [one.communicate(timeout=15), two.communicate(timeout=15)]
            self.assertEqual(sorted([one.returncode, two.returncode]), [0, 2], output)
        rows = self.observations()
        evidence = lifecycle.sha(json.loads(self.prep.read_text()))
        self.assertEqual(sum(row["evidence_sha256"] == evidence for row in rows), 1)
        self.assertEqual(len(rows), 2)
        self.assert_no_effects()

    def test_failed_receipt_after_replacement_repairs_by_ordinary_prepare(self) -> None:
        """A saved replacement needs only an unchanged prepare retry to produce its truthful receipt."""
        self.revise(revision=2)
        argv = self.argv("prepare", "--loop", LOOP, "--refresh-from-sha256", self.current_hash)[2:]
        with (
            mock.patch.object(lifecycle, "write_bytes", side_effect=OSError("disk-full")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            rc = orders.main(argv)
        self.assertEqual(rc, 2)
        saved = json.loads(self.prep.read_text())
        self.assertEqual(saved["binding"]["revision"], 2)
        self.assertEqual(len(self.observations()), 1)
        self.assertEqual(self.refresh()[0], 2)
        rc, out = self.cli("prepare", "--loop", LOOP)
        self.assertEqual((rc, out["evidence_sha256"]), (0, lifecycle.sha(saved)))
        self.assertEqual(self.cli("prepare", "--loop", LOOP)[0], 0)
        self.assertEqual(len(self.observations()), 2)
        self.assert_no_effects()

    def test_failed_replacement_save_keeps_prior_preparation_and_observation(self) -> None:
        """A failed atomic save cannot emit a new preparation observation or apply lifecycle effects."""
        self.revise(revision=2)
        before = self.prep.read_bytes()
        argv = self.argv("prepare", "--loop", LOOP, "--refresh-from-sha256", self.current_hash)[2:]
        with (
            mock.patch.object(ol, "save", side_effect=OSError("disk-full")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(orders.main(argv), 2)
        self.assertEqual(self.prep.read_bytes(), before)
        self.assertEqual(len(self.observations()), 1)
        self.assert_no_effects()

    def test_codex_refresh_then_durable_complete_applies_once(self) -> None:
        """The mirrored package uses the actual Codex one-increment completion contract after refresh."""
        self.revise(revision=2)
        rc, out = self.cli("prepare", "--loop", LOOP, "--refresh-from-sha256", self.current_hash, codex=True)
        self.assertEqual(rc, 0, out)
        self.revise(status="complete", revision=3, completion={"revision": 2})
        rc, applied = self.cli("tick", "--loop", LOOP, codex=True)
        self.assertEqual((rc, applied["ticked"]), (0, True))
        self.assertEqual(self.cli("tick", "--loop", LOOP, codex=True)[1]["ticked"], False)
        self.assertEqual(len(ol.open_ledger(self.repo)["orders"][0]["evidence"]), 1)
        self.assertEqual(
            self.cli("prepare", "--loop", LOOP, "--refresh-from-sha256", out["evidence_sha256"], codex=True)[0], 2
        )


class IdentityHistory(recovery.RecoveryCase):
    """Historical preparations constrain identity without asserting present source eligibility or store currentness."""

    def test_shared_record_rejects_scope_and_mode_without_mutating_input(self) -> None:
        """All application callers reuse the identity boundary, including direct ledger clients."""
        ledger = ol.record(
            ol.empty(),
            "stable-mode",
            "Original",
            session_id="s1",
            loop_id="L1",
            now="2026-10-07",
            scope="agnostic",
            failure_mode="stable-mode",
        )["ledger"]
        before = copy.deepcopy(ledger)
        for scope, mode in (("repo", "stable-mode"), ("agnostic", "foreign")):
            with self.subTest(scope=scope, mode=mode), self.assertRaisesRegex(ValueError, "order_id_collision"):
                ol.record(
                    ledger,
                    "stable-mode",
                    "Replacement",
                    session_id="s2",
                    loop_id="L2",
                    now="2026-10-08",
                    scope=scope,
                    failure_mode=mode,
                )
        self.assertEqual(ledger, before)

    def test_foreign_history_path_refuses_before_content_read(self) -> None:
        """Historical identity validation cannot read a linked file outside its bound state directory."""
        self.configure(False, "symlink")
        self.assertEqual(self.stage("s1")[0], 0)
        path = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
        foreign = self.tmp / "foreign-preparation.json"
        path.rename(foreign)
        path.symlink_to(foreign)
        with mock.patch.object(lifecycle, "object_file", wraps=lifecycle.object_file) as reader:
            with self.assertRaisesRegex(ValueError, "order_wrong_session"):
                lifecycle.staged(self.repo)
            reader.assert_not_called()

    def test_advanced_source_retains_same_identity_and_rejects_conflict(self) -> None:
        """A later logical loop/revision does not erase an earlier prepared id/mode/scope binding."""
        for codex in (False, True):
            self.configure(codex, "advanced")
            self.assertEqual(self.stage("s1")[0], 0)
            path = self.repo / "s1/progress.json"
            self.assertTrue(
                atomic_progress_update(path, lambda state: {**state, "revision": 2, "loop_id": "later-loop"})
            )
            with self.subTest(codex=codex, identity="same"):
                self.assertEqual(self.stage("s2")[0], 0)
                self.assertEqual(ol.open_ledger(self.repo)["orders"], [])
            before = self.store_rows()
            with self.subTest(codex=codex, identity="conflicting"):
                rc, out = self.stage("s3", scope="repo")
                self.assertEqual((rc, out.get("reason_code")), (2, "order_id_collision"), out)
                self.assertEqual(self.store_rows(), before)

    def test_foreign_or_malformed_history_refuses_before_store_write(self) -> None:
        """Other sessions are expected; foreign directories, invented filenames and malformed fields are not."""
        changes: list[dict[str, Any]] = [
            {"repo_dir": "foreign"},
            {"state_dir": "foreign"},
            {"session_id": "foreign"},
            {"revision": True},
            {"progress_sha256": "unknown"},
            {"loop_id": "invented"},
        ]
        for codex in (False, True):
            for n, fields in enumerate(changes):
                with self.subTest(codex=codex, fields=fields):
                    self.configure(codex, "invalid" + str(n))
                    self.assertEqual(self.stage("s1")[0], 0)
                    path = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
                    value = json.loads(path.read_text())
                    value["binding"].update(fields)
                    path.write_text(json.dumps(value))
                    before = self.store_rows()
                    self.assertEqual(self.stage("s2")[0], 2)
                    self.assertEqual(self.store_rows(), before)

    def test_cite_checks_shared_history_before_external_sync(self) -> None:
        """The cite front door cannot supersede a claim when staged history conflicts with its ledger identity."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex, "cite")
                self.assertEqual(self.stage("s1")[0], 0)
                self.complete("s1")
                self.assertEqual(self.cli("tick", "--loop", "logical-s1")[0], 0)
                self.assertEqual(self.stage("s2")[0], 0)
                path = lifecycle.preparation_path(self.repo / "s2", "logical-s2")
                value = json.loads(path.read_text())
                value["records"][0]["scope"] = "repo"
                path.write_text(json.dumps(value))
                before = self.store_rows()
                rc, out = self.cli("cite", "stable-mode", "--quote", PROMPT)
                self.assertEqual((rc, out.get("reason_code")), (2, "order_id_collision"), out)
                self.assertEqual(self.store_rows(), before)

    def test_object_publisher_preserves_existing_utf8_json_bytes(self) -> None:
        """The shared publisher preserves every write_object caller's serialization contract."""
        data = {"unicode": "\u00e9\u2603", "rows": [{"flag": True, "nullable": None}], "float": 1.25}
        expected = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        code = (
            "import sys,json;sys.path.insert(0,sys.argv[1]);"
            "from scripts.lib.artifact_io import write_object;write_object(sys.argv[2],json.loads(sys.argv[3]))"
        )
        for codex in (False, True):
            self.configure(codex, "objects")
            path = self.repo / "artifact.json"
            got = subprocess.run(
                [sys.executable, "-c", code, str(self.root), str(path), json.dumps(data)],
                capture_output=True,
                env=self.native_env,
                timeout=15,
            )
            self.assertEqual((got.returncode, got.stdout, got.stderr), (0, b"", b""))
            self.assertEqual(path.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
