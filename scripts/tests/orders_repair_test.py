"""Second-pass repairs for orders.py / lessons.py.

Recovery after a retract, no ledger text on a down render, uncited orders kept out of dispatch and promotion,
forgeable ticks, tail drops and fake retro files.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.tests.fake_muninn_case import LATER, LINES, PROMPT, SESSION, StoreCase  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress, retrospective  # noqa: E402

ORDERS, LESSONS = REPO / "scripts/lib/orders.py", REPO / "scripts/lib/lessons.py"
FM, LESSON = "flaky-tests-hidden", "Run the targeted tests before every commit."


def ledger_of(*ids: str) -> dict[str, Any]:
    """A sealed ledger with one order per id."""
    ledger = ol.empty()
    for i in ids:
        ledger = ol.record(ledger, i, f"lesson {i}", session_id="s1", loop_id="L0", now="2026-01-01")["ledger"]
    return ledger


class LedgerIntegrity(unittest.TestCase):
    """Head anchor, ticks inside the integrity check, missing-file refusal, real retro files only."""

    def test_dropping_the_last_order_is_named(self) -> None:
        """A popped tail used to verify clean; the head count/hash now names it. Control: the intact ledger is clean."""
        ledger = ledger_of("a", "b", "c")
        self.assertEqual(ol.verify(ledger), [])
        ledger["orders"].pop()
        self.assertEqual(ol.verify(ledger), [{"id": "#ledger", "reason": "bad_head"}])

    def test_edited_ticked_loops_are_named(self) -> None:
        """ticked_loops is covered by the head, so un-ticking a loop is reported. Control: untouched is clean."""
        ledger = ol.tick(ledger_of("a"), "T1", "2026-02-01")["ledger"]
        self.assertEqual(ol.verify(ledger), [])
        ledger["ticked_loops"] = []
        self.assertEqual([o["reason"] for o in ol.verify(ledger)], ["bad_head"])

    def test_missing_ledger_beside_a_generated_view_is_an_error(self) -> None:
        """Deleting orders.json no longer loads as an empty ledger once a generated view exists. Control: no view."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertEqual(ol.open_ledger(d)["orders"], [])
            (d / "standing-orders.md").write_text(ma.MARKER + "\n# Standing Orders\n")
            with self.assertRaises(ValueError):
                ol.open_ledger(d)

    def test_retro_count_ignores_empty_and_duplicate_files(self) -> None:
        """Incomplete files do not count; genuine completed sources count each logical loop once."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for n in range(3):
                (d / f"s{n}").mkdir()
                (d / f"s{n}" / "retro.json").write_text("{}")
            (d / "bad").mkdir()
            (d / "bad" / "retro.json").write_text("not json")
            self.assertEqual(ol.retro_count(d), 0)
            for n in range(3):
                (d / f"s{n}" / "retro.json").write_text(json.dumps({"schema_version": 2, "loop_id": f"L{n % 2}"}))
            self.assertEqual(ol.retro_count(d), 0)
            for n in range(3):
                retrospective(d, f"s{n}", f"L{n % 2}")
            self.assertEqual(ol.retro_count(d), 2)  # L0 twice counts once


class Cli(StoreCase):
    """The CLI repairs against the fake muninn."""

    with_store = True

    def setUp(self) -> None:
        """Name the caller session and make a repo-key dir."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.dir = self.tmp / "repo-key"
        self.dir.mkdir()

    def run_cli(self, script: Path, *args: str, env: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        """Run a script with --dir in a fresh process; return (rc, stdout JSON)."""
        p = subprocess.run(
            [sys.executable, str(script), "--dir", str(self.dir), *args],
            capture_output=True, text=True, env={**os.environ, **(env or {})},
        )  # fmt: skip
        text = p.stdout.strip()
        return p.returncode, json.loads(text) if text.startswith("{") else {"raw": text, "stderr": p.stderr}

    def rec(self, *extra: str, fm: str = FM, session: str = SESSION, loop: str = "L1") -> tuple[int, dict[str, Any]]:
        """Queue a real scratch request; a quoted fixture explicitly completes its controlled review."""
        (self.tmp / "projects/p" / f"{session}.jsonl").write_text("\n".join(map(json.dumps, LINES)) + "\n")
        progress(self.dir, session, loop)
        args = ["--session", session, "record", "--failure-mode", fm, "--lesson", LESSON, "--loop", loop, *extra]
        code, result = self.run_cli(ORDERS, *args)
        if "--quote" in extra and code == 3 and result.get("muninn", {}).get("state") == "pending":
            self.muninn("learn", "complete", result["muninn"]["request_id"], "--kind", "lesson", "--content", LESSON)
            return self.run_cli(ORDERS, *args)
        return code, result

    def test_retract_requires_new_authored_source_before_recovery(self) -> None:
        """A quote cannot recreate a retracted receipt; a new authored source gets a separate request."""
        _, first = self.rec("--quote", PROMPT)
        kid = first["muninn"]["id"]
        self.assertEqual(self.muninn("know", "retract", kid, "--reason", "test")[0], 0)
        self.assertEqual(self.run_cli(ORDERS, "lessons")[1]["lessons"], [])
        rc, unchanged = self.rec("--quote", LATER)
        self.assertEqual((rc, unchanged["muninn"]["id"]), (3, kid))
        rc, again = self.rec("--quote", PROMPT, session="s2", loop="L2")
        self.assertEqual((rc, again["muninn"]["state"]), (0, "written"))
        self.assertNotEqual(again["muninn"]["id"], kid)
        rc, got = self.run_cli(ORDERS, "lessons")
        self.assertEqual((rc, [r["muninn_id"] for r in got["lessons"]]), (0, [again["muninn"]["id"]]))

    def test_render_with_muninn_down_writes_nothing(self) -> None:
        """A down Muninn gives exit 3 and no view (no ledger text). Control: with Muninn up the view is written."""
        self.rec("--quote", PROMPT)
        away = {"PATH": str(self.tmp / "nowhere")}
        rc, out = self.run_cli(ORDERS, "render", env=away)
        self.assertEqual((rc, out), (3, {"degraded": "muninn_absent"}))
        self.assertFalse((self.dir / "standing-orders.md").exists())
        self.assertEqual(self.run_cli(ORDERS, "render")[0], 0)
        self.assertIn(FM, (self.dir / "standing-orders.md").read_text())

    def test_contract_serves_cited_orders_only(self) -> None:
        """An order with no quote is not in the dispatch contract. Control: `lessons` still shows it flagged."""
        self.rec()  # no quote -> degraded no_user_cite
        rc, contract = self.run_cli(LESSONS, "query", "--format", "contract")
        self.assertEqual((rc, contract["lessons"]), (0, []))
        rows = self.run_cli(ORDERS, "lessons")[1]["lessons"]
        self.assertEqual([(r["id"], r["cited"]) for r in rows], [(FM, False)])

    def sessions(self, *names: str) -> None:
        """Give each session id a synthetic transcript so its quote can be cited."""
        for n in names:
            (self.tmp / "projects" / "p" / f"{n}.jsonl").write_text("\n".join(json.dumps(x) for x in LINES) + "\n")

    def test_uncited_recurrences_are_not_promotion_candidates(self) -> None:
        """Three sessions recording with no quote yield no candidate; with quotes they do, with Muninn's text."""
        self.sessions("s2", "s3")
        for s in ("s1", "s2", "s3"):
            self.rec("--scope", "agnostic", fm="uncited-mode", session=s, loop="uncited")
        self.assertEqual(self.run_cli(LESSONS, "predicate")[1]["candidates"], [])
        for s in ("s1", "s2", "s3"):
            self.rec("--scope", "agnostic", "--quote", PROMPT, fm="cited-mode", session=s, loop="cited")
        got = self.run_cli(LESSONS, "predicate")[1]["candidates"]
        self.assertEqual([(c["id"], c["lesson"], len(c["sessions"])) for c in got], [("cited-mode", LESSON, 3)])

    def test_evidence_session_flag_is_gone(self) -> None:
        """The free-text --evidence-session flag is refused by the parser (argparse exit 2)."""
        rc, _ = self.rec("--evidence-session", "fake-1")
        self.assertEqual(rc, 2)

    def test_tick_needs_a_real_loop(self) -> None:
        """Unknown logical loops and empty progress are refused; owned preparation plus completion authorizes tick."""
        self.rec("--quote", PROMPT)
        rc, out = self.run_cli(ORDERS, "tick", "--loop", "fake-a")
        self.assertEqual((rc, out["reason_code"]), (2, "order_wrong_session"))
        path = self.dir / SESSION / "progress.json"
        path.write_text("{}")
        self.assertEqual(self.run_cli(ORDERS, "tick", "--loop", "real")[0], 2)
        progress(self.dir, SESSION, "real", "in-progress")
        self.assertEqual(self.run_cli(ORDERS, "prepare", "--loop", "real")[0], 0)
        progress(self.dir, SESSION, "real")
        rc, out = self.run_cli(ORDERS, "tick", "--loop", "real")
        self.assertEqual((rc, out["ticked"]), (0, True))


class Reconciliation(StoreCase):
    """Recovery and contention exercise currentness through actual fake-store subprocesses."""

    def setUp(self) -> None:
        """Create genuine completed progress for record calls."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.dir = self.tmp / "repo-key"
        self.dir.mkdir()
        progress(self.dir, SESSION, "L1")

    with_store = True
    run_cli = cast("Callable[..., tuple[int, dict[str, Any]]]", Cli.run_cli)
    rec = cast("Callable[..., tuple[int, dict[str, Any]]]", Cli.rec)

    def count(self) -> int:
        """Count durable current requests instead of retired numeric-K adds."""
        path = self.home / "requests.json"
        return len(json.loads(path.read_text())["requests"]) if path.exists() else 0

    def test_degraded_or_pending_record_recovers_exact_retained_request(self) -> None:
        """Mutable cached status cannot erase the retained request's committed identity."""
        _, first = self.rec("--quote", PROMPT)
        path = self.dir / "orders.json"
        for state in ("degraded", "pending"):
            data = json.loads(path.read_text())
            data["orders"][0]["muninn"].update(id=None, state=state, reason_code="muninn_error")
            path.write_text(json.dumps(data))
            rc, out = self.run_cli(ORDERS, "cite", FM)
            self.assertEqual((rc, out["muninn"]["id"], self.count()), (0, first["muninn"]["id"], 1))

    def test_failed_currentness_read_retains_prior_kid_and_request(self) -> None:
        """A failed exact current-list read retains prior observations without claiming a save."""
        _, first = self.rec("--quote", PROMPT)
        exe = self.tmp / "bin/muninn"
        delegate = exe.read_text().split("exec ", 1)[1].split(' "$@"', 1)[0]
        exe.write_text(
            '#!/bin/sh\nif [ "$1 $2" = "know list" ] && [ "$3" != "--help" ]; then exit 1; fi\n'
            f'exec {delegate} "$@"\n'
        )
        rc, out = self.run_cli(ORDERS, "cite", FM)
        self.assertEqual((rc, out["muninn"]["state"], out["muninn"]["reason_code"]), (3, "unknown", "muninn_error"))
        for key in ("id", "request_id", "request_window", "project_id"):
            self.assertEqual(out["muninn"][key], first["muninn"][key])

    def test_unknown_submission_and_failed_local_save_do_not_duplicate_requests(self) -> None:
        """A lost submission answer stays fenced; a retained journal survives final local-save failure."""
        exe = self.tmp / "bin/muninn"
        original = exe.read_text()
        delegate = original.split("exec ", 1)[1].split(' "$@"', 1)[0]
        exe.write_text(
            '#!/bin/sh\nif [ "$1 $2" = "learn request" ] && [ "$3" != "--help" ]; then\n'
            f'  {delegate} "$@" >/dev/null\n  exit 1\nfi\nexec {delegate} "$@"\n'
        )
        rc, first = self.rec("--quote", PROMPT)
        self.assertEqual((rc, first["muninn"]["state"], self.count()), (3, "unknown", 1))
        exe.write_text(original)
        self.assertEqual((self.rec("--quote", PROMPT)[1]["muninn"]["state"], self.count()), ("unknown", 1))
        save = ol.save

        def fail_ledger(path: Path, value: ol.Ledger) -> None:
            if path.name == "orders.json":
                raise OSError("disk-full")
            save(path, value)

        (self.tmp / "projects/p/s2.jsonl").write_text("\n".join(map(json.dumps, LINES)) + "\n")
        progress(self.dir, "s2", "L2")
        argv = [
            "--dir",
            str(self.dir),
            "--session",
            "s2",
            "record",
            "--failure-mode",
            "new-mode",
            "--lesson",
            "A new cited lesson.",
            "--loop",
            "L2",
        ]
        with (
            mock.patch.object(ol, "save", side_effect=fail_ledger),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(orders.main(argv), 3)
        failed = json.loads(output.getvalue())
        self.assertTrue(failed["pending_teardown"])
        self.assertEqual(self.count(), 2)
        journal = next(
            json.loads(path.read_text())
            for path in self.dir.glob("order-request-*.json")
            if json.loads(path.read_text())["session"] == "s2"
        )
        self.muninn("learn", "complete", journal["request_id"], "--kind", "lesson", "--content", "A new cited lesson.")
        self.assertEqual(self.run_cli(ORDERS, *argv[2:])[0], 0)
        self.assertEqual(self.count(), 2)

    def test_parallel_record_and_cite_reconcile_one_retained_request(self) -> None:
        """Concurrent callbacks over the non-reentrant order lock finish with one request and current Note."""
        _, first = self.rec("--quote", PROMPT)
        prefix = [sys.executable, str(ORDERS), "--dir", str(self.dir), "--session", SESSION]
        argv = [[*prefix, "record", "--failure-mode", FM, "--lesson", LESSON, "--loop", "L1"], [*prefix, "cite", FM]]
        with (
            subprocess.Popen(argv[0], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as one,
            subprocess.Popen(argv[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as two,
        ):
            outs = [one.communicate(timeout=15), two.communicate(timeout=15)]
            self.assertEqual((one.returncode, two.returncode), (0, 0), outs)
        self.assertEqual(self.count(), 1)
        self.assertEqual([json.loads(out)["muninn"]["id"] for out, _ in outs], [first["muninn"]["id"]] * 2)

    def test_long_claim_is_refused_without_silent_truncation(self) -> None:
        """The 500-character store limit cannot silently alter an authoritative lesson."""
        rc, out = self.run_cli(
            ORDERS, "record", "--failure-mode", FM, "--lesson", "x" * 501, "--loop", "L1", "--quote", PROMPT
        )
        self.assertEqual((rc, out.get("reason_code"), self.count()), (2, "order_lesson_too_long", 0))

    def test_render_uses_request_bound_claim_and_excludes_pending_text(self) -> None:
        """A different request cannot replace an active order, and pending text cannot enter its view."""
        self.rec("--quote", PROMPT)
        (self.tmp / "projects/p/s2.jsonl").write_text("\n".join(map(json.dumps, LINES)) + "\n")
        progress(self.dir, "s2", "L2")
        args = [
            "--session",
            "s2",
            "record",
            "--failure-mode",
            "diagnostic-only",
            "--lesson",
            "Unreviewed diagnostic.",
            "--loop",
            "L2",
        ]
        self.assertEqual(self.run_cli(ORDERS, *args)[0], 3)
        self.assertEqual(self.run_cli(ORDERS, "render")[0], 0)
        view = (self.dir / "standing-orders.md").read_text()
        self.assertIn(LESSON, view)
        self.assertNotIn("Unreviewed diagnostic.", view)
        self.assertNotIn("diagnostic-only", view)

    def test_legacy_collision_and_external_source_refusal_preserve_inputs(self) -> None:
        """Import cannot drop a colliding entry or move an arbitrary source outside the repo-key directory."""
        self.rec()
        body = f"### {FM}\n**loops_since_recurrence:** 2\n**First seen:** legacy\nOriginal lesson.\n"
        source = self.dir / "standing-orders.md"
        source.write_text(body)
        self.assertEqual(self.run_cli(ORDERS, "import-legacy")[0], 2)
        self.assertEqual(source.read_text(), body)
        external = self.tmp / "elsewhere.md"
        external.write_text(body)
        self.assertEqual(self.run_cli(ORDERS, "import-legacy", "--file", str(external))[0], 2)
        self.assertEqual(external.read_text(), body)


class Callers(unittest.TestCase):
    """Both providers' teardown prose runs record, tick and render through orders.py."""

    def test_codex_and_claude_teardown_call_the_code(self) -> None:
        """Codex agentic-loop SKILL.md carries the step (it did not); each names record, tick and render."""
        for rel in ("skills/agentic-loop/teardown.md", "packages/codex/skills/agentic-loop/SKILL.md"):
            text = (REPO / rel).read_text()
            for needle in ("orders.py", "record --failure-mode", "tick --loop", "render"):
                self.assertIn(needle, text, f"{rel}: {needle}")

    def test_mirrors_match(self) -> None:
        """The Codex copies of the changed modules are byte-identical."""
        for name in ("orders_ledger", "orders", "lessons", "memory_reasons"):
            rel = f"scripts/lib/{name}.py"
            self.assertEqual((REPO / rel).read_bytes(), (REPO / "packages/codex" / rel).read_bytes(), rel)


if __name__ == "__main__":
    unittest.main()
