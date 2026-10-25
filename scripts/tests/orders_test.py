"""Standing orders as typed records: decay/recurrence/idempotence, the hash chain, Muninn round trip, generated views.

The CLI is exercised as a subprocess (a real restart each call) against the hermetic fake `muninn`; nothing here touches
the live Muninn store. Each rule has a negative control that mutates the one thing it proves.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import memory_reasons  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.tests.fake_muninn_case import LATER, PROMPT, SESSION, StoreCase  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress  # noqa: E402

CLI = REPO / "scripts/lib/orders.py"
LEGACY = REPO / "scripts/tests/fixtures/standing-orders.legacy.md"
FM, LESSON = "flaky-tests-hidden", "Run the targeted tests before every commit."


def new_ledger(*ids: str, scope: str = "repo") -> dict[str, Any]:
    """A ledger with one order per id, each created at 2026-01-01 in session s1."""
    ledger = ol.empty()
    for i in ids:
        claim = f"lesson {i}"
        ledger = ol.record(ledger, i, claim, session_id="s1", loop_id="L0", now="2026-01-01", scope=scope)["ledger"]
    return ledger


def order(ledger: dict[str, Any], oid: str) -> dict[str, Any]:
    """The order with this id."""
    return next(o for o in ledger["orders"] if o["id"] == oid)


class Lifecycle(unittest.TestCase):
    """(a) K=5 decay, (b) recurrence, (c) idempotent tick, (d) predicate and candidates."""

    def test_decay_at_k5_and_never_deleted(self) -> None:
        """Four ticks keep it active at 4; the fifth decays it with decayed_at, and it stays in the ledger."""
        ledger = new_ledger("a")
        for n in range(1, 5):
            ledger = ol.tick(ledger, f"T{n}", f"2026-02-0{n}")["ledger"]
        self.assertEqual((order(ledger, "a")["status"], order(ledger, "a")["loops_since_recurrence"]), ("active", 4))
        out = ol.tick(ledger, "T5", "2026-02-05")
        self.assertEqual(out["decayed"], ["a"])
        got = order(out["ledger"], "a")
        self.assertEqual((got["status"], got["decayed_at"]), ("decayed", "2026-02-05"))
        self.assertEqual(len(out["ledger"]["orders"]), 1)
        self.assertIn("a", ol.view(out["ledger"], decayed=True))
        self.assertNotIn("## a\n", ol.view(out["ledger"], decayed=False))

    def test_control_k6_would_not_decay_on_the_fifth_tick(self) -> None:
        """Negative control: with K=6 the fifth tick leaves the order active."""
        ledger = new_ledger("a")
        with mock.patch.object(ol, "K", 6):
            for n in range(1, 6):
                ledger = ol.tick(ledger, f"T{n}", "2026-02-01")["ledger"]
        self.assertEqual(order(ledger, "a")["status"], "active")

    def test_recurrence_resets_survivors_increment_new_appends(self) -> None:
        """A match resets to 0, sets last_recurred and appends evidence; others increment; a new mode appends."""
        ledger = new_ledger("a", "b")
        ledger = ol.tick(ledger, "T1", "2026-02-01")["ledger"]
        self.assertEqual(order(ledger, "a")["loops_since_recurrence"], 1)
        out = ol.record(ledger, "a", "lesson a", session_id="s2", loop_id="T2", now="2026-02-02")
        self.assertFalse(out["created"])
        a = order(out["ledger"], "a")
        self.assertEqual(
            (a["loops_since_recurrence"], a["last_recurred"], a["created"]), (0, "2026-02-02", "2026-01-01")
        )
        self.assertEqual([e["session_id"] for e in a["evidence"]], ["s1", "s2"])
        ledger = ol.tick(out["ledger"], "T2", "2026-02-02")["ledger"]
        self.assertEqual(
            (order(ledger, "a")["loops_since_recurrence"], order(ledger, "b")["loops_since_recurrence"]), (0, 2)
        )
        added = ol.record(ledger, "c", "lesson c", session_id="s2", loop_id="T3", now="2026-02-03")
        self.assertTrue(added["created"])
        self.assertEqual([o["id"] for o in added["ledger"]["orders"]], ["a", "b", "c"])

    def test_tick_is_idempotent_per_loop_id(self) -> None:
        """The same loop id twice increments once."""
        once = ol.tick(new_ledger("a"), "T1", "2026-02-01")
        twice = ol.tick(once["ledger"], "T1", "2026-02-01")
        self.assertFalse(twice["ticked"])
        self.assertEqual(order(twice["ledger"], "a")["loops_since_recurrence"], 1)

    def test_control_without_the_ticked_guard_it_would_double_count(self) -> None:
        """Negative control: forgetting the ticked_loops set lets the same loop increment again."""
        once = ol.tick(new_ledger("a"), "T1", "2026-02-01")["ledger"]
        once["ticked_loops"] = []
        self.assertEqual(order(ol.tick(once, "T1", "2026-02-01")["ledger"], "a")["loops_since_recurrence"], 2)

    def test_predicate_needs_all_three_components(self) -> None:
        """10 retros + one recurred + one decayed is met; each missing component alone is unmet."""
        ledger = new_ledger("a", "b")
        for n in range(1, 6):
            ledger = ol.tick(ledger, f"T{n}", "2026-03-02")["ledger"]
        ledger = ol.record(ledger, "a", "x", session_id="s2", loop_id="L1", now="2026-03-09")["ledger"]  # revives a
        self.assertEqual((order(ledger, "a")["status"], order(ledger, "b")["status"]), ("active", "decayed"))
        met = ol.predicate(ledger, 10)
        self.assertEqual((met["met"], met["retro_count"], met["recurred"], met["decayed"]), (True, 10, 1, 1))
        self.assertFalse(ol.predicate(ledger, 9)["met"])
        self.assertFalse(ol.predicate(new_ledger("a", "b"), 10)["met"])  # nothing recurred, nothing decayed
        no_decay = copy.deepcopy(ledger)
        order(no_decay, "b")["status"] = "active"
        self.assertFalse(ol.predicate(no_decay, 10)["met"])
        no_recur = copy.deepcopy(ledger)
        order(no_recur, "a")["last_recurred"] = order(no_recur, "a")["created"]
        self.assertFalse(ol.predicate(no_recur, 10)["met"])

    def test_control_free_text_last_recurred_would_break_the_predicate(self) -> None:
        """Negative control: the predicate reads the typed field, so a lone free-text note does not count."""
        ledger = new_ledger("a")
        ledger["orders"][0]["notes"] = "last_recurred: yesterday"
        self.assertEqual([ol.predicate(ledger, 10)[key] for key in ("recurred", "met")], [0, False])

    def test_candidates_need_two_recurrences_two_sessions_and_agnostic(self) -> None:
        """Only an agnostic order recurred >= 2 times across >= 2 distinct sessions is a candidate."""
        ledger = new_ledger("g", "r", "one", "unc", scope="agnostic")
        order(ledger, "r")["scope"] = "repo"
        for oid in ("g", "r", "one"):  # cached write state does not establish current citation authority
            order(ledger, oid)["muninn"]["state"] = "written"
        for oid, sessions in (("g", ("s2", "s3")), ("r", ("s2", "s3")), ("one", ("s1", "s1")), ("unc", ("s2", "s3"))):
            fields = dict(now="2026-03-01", scope=order(ledger, oid)["scope"])
            for n, sid in enumerate(sessions):
                ledger = ol.record(ledger, oid, "x", session_id=sid, loop_id=f"{oid}{n}", **fields)["ledger"]
        self.assertEqual([o["id"] for o in ol.candidates(ledger)], ["g", "unc"])


class Chain(unittest.TestCase):
    """(3) the hash chain names a hand-edited order."""

    def test_clean_chain_verifies_and_hand_edit_names_the_order(self) -> None:
        """Editing loops_since_recurrence by hand is reported against that order."""
        ledger = ol.tick(new_ledger("a", "b", "c"), "T1", "2026-02-01")["ledger"]
        self.assertEqual(ol.verify(ledger), [])
        order(ledger, "b")["loops_since_recurrence"] = 0
        self.assertEqual([o["id"] for o in ol.verify(ledger)], ["b"])

    def test_dropped_order_is_reported(self) -> None:
        """Removing a middle order breaks the sequence at the next one."""
        ledger = new_ledger("a", "b", "c")
        del ledger["orders"][1]
        self.assertIn("c", [o["id"] for o in ol.verify(ledger)])


class Cli(StoreCase):
    """The orders.py CLI against the fake muninn."""

    with_store = True

    def setUp(self) -> None:
        """Name the caller session and make a repo-key dir."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.dir = self.tmp / "repo-key"
        self.dir.mkdir()

    def run_cli(
        self, *args: str, env: dict[str, str] | None = None, cwd: Path | None = None
    ) -> tuple[int, dict[str, Any]]:
        """Run orders.py in a fresh process; return (rc, stdout JSON)."""
        command = [sys.executable, str(CLI), "--dir", str(self.dir), *args]
        p = subprocess.run(command, capture_output=True, text=True, env={**os.environ, **(env or {})}, cwd=cwd)
        text = p.stdout.strip()
        return p.returncode, json.loads(text) if text.startswith(("{", "[")) else {"raw": text, "stderr": p.stderr}

    def rec(self, *extra: str, fm: str = FM, lesson: str = LESSON, loop: str = "L1") -> tuple[int, dict[str, Any]]:
        """orders.py record with a cite quote unless extra supplies none."""
        progress(self.dir, SESSION, loop)
        return self.run_cli("record", "--failure-mode", fm, "--lesson", lesson, "--loop", loop, *extra)

    def ledger(self) -> dict[str, Any]:
        """orders.json as on disk."""
        return json.loads((self.dir / "orders.json").read_text())  # type: ignore[no-any-return]

    def trace(self) -> list[dict[str, Any]]:
        """Trace rows of the caller session."""
        path = self.tmp / "loops" / SESSION / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def test_round_trip_survives_restart_and_muninn_status(self) -> None:
        """(f) record with a user quote; a fresh process returns the same text, K-id and cite; retract drops it."""
        rc, out = self.rec("--quote", PROMPT)
        self.assertEqual((rc, out["muninn"]["state"]), (0, "written"))
        kid = out["muninn"]["id"]
        rc, got = self.run_cli("lessons")
        self.assertEqual(rc, 0, got)
        row = got["lessons"][0]
        self.assertEqual((row["text"], row["muninn_id"], row["quote"]), (LESSON, kid, PROMPT))
        self.assertTrue(row["cite"])
        self.assertEqual(self.muninn("know", "retract", kid, "--reason", "test")[0], 0)
        rc, got = self.run_cli("lessons")
        self.assertEqual((rc, got["lessons"], got["excluded"][0]["order"]), (0, [], FM))
        self.assertIn("lesson_not_current", [r["reason_code"] for r in self.trace() if r["command"] == "lesson.query"])

    def test_expired_entry_is_excluded(self) -> None:
        """(f) a Muninn entry past valid_until drops out of `lessons`."""
        _, out = self.rec("--quote", PROMPT)
        self.sql("UPDATE knowledge SET valid_until = ? WHERE id = ?", 1.0, int(out["muninn"]["id"][1:]))
        rc, got = self.run_cli("lessons")
        self.assertEqual((rc, got["lessons"]), (0, []))

    def test_superseding_record_replaces_the_text(self) -> None:
        """(f) a record that supersedes the entry (same ord- tag) replaces it in `lessons`."""
        _, out = self.rec("--quote", PROMPT)
        tag = next(
            t for t in self.muninn("know", "show", out["muninn"]["id"])[1]["entry"]["tags"] if t.startswith("ord-")
        )
        rc, _ = self.muninn(
            "know", "add", "--kind", "lesson", "--text", "Replacement lesson text.", "--cite", "claude:s1:1.1",
            "--quote", PROMPT, "--tag", "order", "--tag", tag, "--supersedes", out["muninn"]["id"],
        )  # fmt: skip
        self.assertEqual(rc, 0)
        _, got = self.run_cli("lessons")
        self.assertEqual([r["text"] for r in got["lessons"]], ["Replacement lesson text."])

    def test_muninn_absent_lessons_prints_no_ledger_text_and_record_degrades(self) -> None:
        """(g) lessons exits 3 with muninn_absent and no lesson text; record still writes the ledger and exits 3."""
        self.rec("--quote", PROMPT)
        away = {"PATH": str(self.tmp / "nowhere")}
        p = subprocess.run(
            [sys.executable, str(CLI), "--dir", str(self.dir), "lessons"],
            capture_output=True, text=True, env={**os.environ, **away},
        )  # fmt: skip
        self.assertEqual(p.returncode, 3)
        self.assertEqual(json.loads(p.stdout), {"degraded": "muninn_absent"})
        self.assertNotIn(LESSON, p.stdout + p.stderr)
        progress(self.dir, SESSION, "L2")
        rc, out = self.run_cli(
            "record", "--failure-mode", "second-mode", "--lesson", "Second lesson.", "--loop", "L2",
            "--quote", PROMPT, env=away,
        )  # fmt: skip
        self.assertEqual((rc, out["muninn"]["state"], out["muninn"]["reason_code"]), (3, "degraded", "muninn_absent"))
        self.assertEqual(order(self.ledger(), "second-mode")["status"], "active")

    def test_backend_off_is_ledger_only_exit_0(self) -> None:
        """(h) memory.backend off: ledger written, exit 0, trace memory_backend_off, lessons served from the ledger."""
        repo = self.tmp / "offrepo"
        (repo / ".coderails").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".coderails/workflow.config.yaml").write_text("memory:\n  backend: off\n")
        progress(self.dir, SESSION, "L1")
        rc, out = self.run_cli(
            "record", "--failure-mode", FM, "--lesson", LESSON, "--loop", "L1", "--quote", PROMPT, cwd=repo
        )
        self.assertEqual(
            (rc, out["muninn"]["state"], out["muninn"]["reason_code"]), (0, "disabled", "memory_backend_off")
        )
        self.assertIn("memory_backend_off", [r["reason_code"] for r in self.trace() if r["command"] == "order.record"])
        rc, got = self.run_cli("lessons", cwd=repo)
        self.assertEqual((rc, [r["text"] for r in got["lessons"]]), (0, [LESSON]))

    def test_no_quote_stores_degraded_and_cite_attaches_later(self) -> None:
        """A record with no quote is active, degraded no_user_cite, exit 3; `cite` writes it to Muninn later."""
        rc, out = self.rec()
        self.assertEqual((rc, out["muninn"]["state"], out["muninn"]["reason_code"]), (3, "degraded", "no_user_cite"))
        self.assertEqual(order(self.ledger(), FM)["status"], "active")
        rc, got = self.run_cli("cite", FM, "--quote", LATER)
        self.assertEqual((rc, got["muninn"]["state"]), (0, "written"))
        self.assertTrue(order(self.ledger(), FM)["muninn"]["id"])
        self.assertEqual(self.run_cli("cite", "nope", "--quote", LATER)[0], 2)

    def test_hand_edited_ledger_is_refused_naming_the_order(self) -> None:
        """A mutating command on a ledger whose chain is broken exits 2, order_chain_broken, naming the order."""
        self.rec("--quote", PROMPT)
        data = self.ledger()
        data["orders"][0]["loops_since_recurrence"] = 3
        (self.dir / "orders.json").write_text(json.dumps(data))
        rc, out = self.run_cli("tick", "--loop", "L2")
        self.assertEqual((rc, out["reason_code"], out["offenders"][0]["id"]), (2, "order_chain_broken", FM))

    def test_tick_cli_decays_and_renders_views(self) -> None:
        """(a)(e) five ticks decay it; render writes both views with the marker, mode 0444, decayed only in its file."""
        self.rec("--quote", PROMPT)
        for n in range(5):
            progress(self.dir, SESSION, f"T{n}", "in-progress")
            self.assertEqual(self.run_cli("prepare", "--loop", f"T{n}")[0], 0)
            progress(self.dir, SESSION, f"T{n}")
            self.assertEqual(self.run_cli("tick", "--loop", f"T{n}")[0], 0)
        self.assertEqual(order(self.ledger(), FM)["status"], "decayed")
        rc, _ = self.run_cli("render")
        self.assertEqual(rc, 0)
        live, dead = self.dir / "standing-orders.md", self.dir / "standing-orders-decayed.md"
        for path in (live, dead):
            self.assertEqual(path.read_text().split("\n", 1)[0], ma.MARKER)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
        self.assertNotIn(FM, live.read_text())
        self.assertIn(FM, dead.read_text())
        self.assertEqual(self.run_cli("render")[0], 0)  # regenerating over a 0444 generated file works
        self.assertTrue({"order.record", "order.tick", "order.render"} <= {r["command"] for r in self.trace()})

    def test_render_refuses_a_hand_written_file(self) -> None:
        """(e) a standing-orders.md with no marker is never overwritten: handwritten_protected."""
        self.rec("--quote", PROMPT)
        hand = self.dir / "standing-orders.md"
        hand.write_text("# hand written\n")
        rc, out = self.run_cli("render")
        self.assertEqual((rc, out), (3, {"degraded": "handwritten_protected"}))
        self.assertEqual(hand.read_text(), "# hand written\n")

    def test_import_legacy_preserves_counters_and_archives_a_copy(self) -> None:
        """(e) 5 entries keep titles and counters; source and archive both remain."""
        shutil.copy(LEGACY, self.dir / "standing-orders.md")
        rc, out = self.run_cli("import-legacy")
        self.assertEqual((rc, out["imported"], out["source_retained"]), (0, 5, True))
        orders = self.ledger()["orders"]
        self.assertEqual(len(orders), 5)
        self.assertEqual(
            {o["id"]: o["loops_since_recurrence"] for o in orders if o["loops_since_recurrence"]},
            {
                "verification-ceiling-counter-shared-across-context-not-reset-by-delegation": 2,
                "dispatch-prompt-must-explicitly-instruct-worktree-isolation-even-for-audit-tasks": 4,
                "hardcoded-default-literal-can-have-more-than-one-stale-copy": 1,
            },
        )
        self.assertTrue(
            all(o["muninn"] == {"id": None, "state": "degraded", "reason_code": "legacy_uncited"} for o in orders)
        )
        self.assertEqual((self.dir / "standing-orders.legacy.md").read_bytes(), LEGACY.read_bytes())
        self.assertEqual((self.dir / "standing-orders.md").read_bytes(), LEGACY.read_bytes())
        (self.dir / "standing-orders.md").unlink()  # explicit retirement permits generated view rendering
        self.assertEqual(self.run_cli("render")[0], 0)
        self.assertEqual(ol.verify(self.ledger()), [])

    def test_import_legacy_fails_loudly_on_an_unparseable_counter(self) -> None:
        """(7) an unparseable counter is legacy_parse_error naming the entry; nothing is written or moved."""
        text = LEGACY.read_text().replace("loops_since_recurrence:** 4", "loops_since_recurrence:** four")
        (self.dir / "standing-orders.md").write_text(text)
        rc, out = self.run_cli("import-legacy")
        self.assertEqual((rc, out["reason_code"]), (2, "legacy_parse_error"))
        self.assertIn("dispatch-prompt", out["entry"])
        self.assertFalse((self.dir / "orders.json").exists())
        self.assertEqual((self.dir / "standing-orders.md").read_text(), text)

    def test_lessons_after_legacy_import_flags_uncited_entries(self) -> None:
        """With Muninn up, imported entries are served flagged cited=false (not silently dropped)."""
        shutil.copy(LEGACY, self.dir / "standing-orders.md")
        self.run_cli("import-legacy")
        rc, got = self.run_cli("lessons")
        self.assertEqual((rc, len(got["lessons"]), {r["cited"] for r in got["lessons"]}), (0, 5, {False}))


class Sources(unittest.TestCase):
    """(j)(k) prose calls code, mirrors are byte copies, files stay small."""

    def test_mirrors_and_size(self) -> None:
        """Codex copies are byte-identical and every new module is under 400 lines."""
        for name in ("orders_ledger", "orders", "lessons", "memory_adapter", "memory_reasons"):
            rel = f"scripts/lib/{name}.py"
            self.assertEqual((REPO / rel).read_bytes(), (REPO / "packages/codex" / rel).read_bytes(), rel)
            self.assertLess(len((REPO / rel).read_text().splitlines()), 400, rel)

    def test_prose_names_the_scripts_and_no_longer_hand_edits(self) -> None:
        """(j) retro-promotion SKILL.md files and teardown.md name orders.py/lessons.py, not hand-editing."""
        files = (
            "skills/loop-retro-promotion/SKILL.md",
            "packages/codex/skills/loop-retro-promotion/SKILL.md",
            "skills/agentic-loop/teardown.md",
        )
        for rel in files:
            text = (REPO / rel).read_text()
            self.assertRegex(text, r"orders\.py|lessons\.py", rel)
            self.assertNotIn("--standing-orders", text, rel)
            self.assertNotRegex(text, r"(?i)hand-edit(?:ing)? `?standing-orders", rel)
        self.assertNotIn("Count `<repo-key-dir>/*/retro.json`", (REPO / files[0]).read_text())
        self.assertNotIn("--standing-orders", (REPO / "scripts/lib/memory_adapter.py").read_text())

    def test_new_reason_codes_are_documented(self) -> None:
        """Each order/lesson/legacy reason is a REASONS key and named in the runbook."""
        runbook = (REPO / "docs/RUNBOOK.md").read_text()
        for code in (
            "order_chain_broken", "order_blank_field", "order_not_found", "order_state_error", "order_already_ticked",
            "no_user_cite", "legacy_uncited", "legacy_parse_error", "legacy_missing", "lesson_not_current",
        ):  # fmt: skip
            self.assertIn(code, memory_reasons.REASONS)
            self.assertIn(f"`{code}`", runbook)

    def test_slug_is_stable(self) -> None:
        """Ids derive deterministically from the failure mode."""
        self.assertEqual(ol.slug("Flaky  tests: hidden!"), "flaky-tests-hidden-70e14f0c6a2f")
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+", ol.slug("Ünï cödé 123")))


if __name__ == "__main__":
    unittest.main()
