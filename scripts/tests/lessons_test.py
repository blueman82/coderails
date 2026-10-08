"""lessons.py: the promotion-routine selection and the verbatim dispatch contract list, against the fake muninn."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import lessons, memory_read  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests import orders_recovery_test as recovery  # noqa: E402
from scripts.tests.fake_muninn_case import FAKE, LINES, PROMPT, SESSION, StoreCase  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress, retrospective  # noqa: E402

LESSONS = REPO / "scripts/lib/lessons.py"
ORDERS = REPO / "scripts/lib/orders.py"


class LessonsCli(StoreCase):
    """query --format contract and predicate over a repo-key dir."""

    with_store = True

    def setUp(self) -> None:
        """Name the caller session and make a repo-key dir."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.dir = self.tmp / "repo-key"
        self.dir.mkdir()

    def call(self, script: Path, *args: str) -> tuple[int, dict[str, Any]]:
        """Run a script with --dir in a fresh process; return (rc, stdout JSON)."""
        p = subprocess.run([sys.executable, str(script), "--dir", str(self.dir), *args], capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout) if p.stdout.strip() else {}

    def add(self, mode: str, scope: str = "repo", sessions: tuple[str, ...] = ("s1",)) -> None:
        """Record an order, once per session (so a later session is a recurrence)."""
        for n, sid in enumerate(sessions):
            (self.tmp / "projects" / "p" / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in LINES) + "\n")
            args = ["--session", sid, "record", "--failure-mode", mode, "--lesson", f"Lesson for {mode}.", "--loop"]
            args += [f"{mode}{n}", "--scope", scope, "--quote", PROMPT]
            progress(self.dir, sid, f"{mode}{n}")
            self.assertIn(self.call(ORDERS, *args)[0], (0, 3))

    def test_contract_list_is_stable_sorted_and_verbatim(self) -> None:
        """(i) two runs give the same bytes and hash; entries are sorted by order id; text is Muninn's."""
        for mode in ("zeta-mode", "alpha-mode", "mid-mode"):
            self.add(mode)
        first = subprocess.run(
            [sys.executable, str(LESSONS), "--dir", str(self.dir), "query", "--format", "contract"],
            capture_output=True, text=True,
        )  # fmt: skip
        second = subprocess.run(
            [sys.executable, str(LESSONS), "--dir", str(self.dir), "query", "--format", "contract"],
            capture_output=True, text=True,
        )  # fmt: skip
        self.assertEqual((first.returncode, first.stdout), (0, second.stdout))
        got = json.loads(first.stdout)
        self.assertEqual([x["id"] for x in got["lessons"]], ["alpha-mode", "mid-mode", "zeta-mode"])
        self.assertEqual(got["lessons"][0]["text"], "Lesson for alpha-mode.")
        digest = hashlib.sha256(json.dumps(got["lessons"], sort_keys=True).encode()).hexdigest()
        self.assertEqual(got["sha256"], digest)

    def test_query_with_muninn_absent_degrades_without_text(self) -> None:
        """No ledger text leaks when Muninn is absent: exit 3, muninn_absent."""
        self.add("alpha-mode")
        p = subprocess.run(
            [sys.executable, str(LESSONS), "--dir", str(self.dir), "query", "--format", "contract"],
            capture_output=True, text=True, env={**os.environ, "PATH": str(self.tmp / "nowhere")},
        )  # fmt: skip
        self.assertEqual((p.returncode, json.loads(p.stdout)), (3, {"degraded": "muninn_absent"}))
        self.assertNotIn("Lesson for", p.stdout)

    def test_predicate_reports_graduation_and_candidates(self) -> None:
        """Only an agnostic order recurred twice across sessions is a candidate; graduation is unmet at 0 retros."""
        self.add("agnostic-mode", scope="agnostic", sessions=("s1", "s2", "s3"))
        self.add("repo-mode", scope="repo", sessions=("s1", "s2", "s3"))
        rc, out = self.call(LESSONS, "predicate")
        self.assertEqual(rc, 0)
        self.assertEqual([c["id"] for c in out["candidates"]], ["agnostic-mode"])
        self.assertEqual((out["graduation"]["met"], out["graduation"]["retro_count"]), (False, 0))
        self.assertEqual(out["graduation"]["recurred"], 2)
        for n in range(10):
            retrospective(self.dir, f"sess{n}", f"L{n}")
        self.assertEqual(self.call(LESSONS, "predicate")[1]["graduation"]["retro_count"], 10)

    def test_retracted_or_non_user_citation_is_never_authoritative(self) -> None:
        """Non-user anchors and no-longer-current citations cannot supply dispatch text."""
        self.add("alpha-mode")
        self.sql("UPDATE citation SET role = 'assistant'")
        self.assertEqual(self.call(LESSONS, "query")[1]["lessons"], [])
        self.sql("UPDATE citation SET role = 'user', state = 'erased'")
        self.assertEqual(self.call(LESSONS, "query")[1]["lessons"], [])

    def test_current_selection_excludes_uncited_lifecycle_eligible_orders(self) -> None:
        """Lifecycle candidates g/unc become only g at the real current cited CLI intersection."""
        self.add("g", scope="agnostic", sessions=("s1", "s2", "s3"))
        for n, sid in enumerate(("s1", "s2", "s3")):
            progress(self.dir, sid, f"unc{n}")
            rc, out = self.call(
                ORDERS, "--session", sid, "record", "--failure-mode", "unc", "--lesson", "Uncited lesson.",
                "--loop", f"unc{n}", "--scope", "agnostic",
            )  # fmt: skip
            self.assertEqual(rc, 3, out)
        self.assertEqual([o["id"] for o in ol.candidates(ol.open_ledger(self.dir))], ["g", "unc"])
        rc, out = self.call(LESSONS, "predicate")
        self.assertEqual(rc, 0, out)
        self.assertEqual([o["id"] for o in out["candidates"]], ["g"])

    def test_predicate_with_unavailable_currentness_is_degraded(self) -> None:
        """Missing store reads must not be reported as an ordinary empty successful promotion result."""
        self.add("alpha-mode")
        p = subprocess.run(
            [sys.executable, str(LESSONS), "--dir", str(self.dir), "predicate"],
            capture_output=True, text=True, env={**os.environ, "PATH": str(self.tmp / "nowhere")},
        )  # fmt: skip
        self.assertEqual((p.returncode, json.loads(p.stdout).get("degraded")), (3, "muninn_absent"))


class ReadBoundary(unittest.TestCase):
    """Malformed currentness/provenance is excluded, and timestamp expiry keeps its full precision."""

    def test_missing_currentness_or_typed_provenance_is_not_served(self) -> None:
        """A successful CLI response alone cannot establish currentness or a user citation."""
        cite = {
            "ref": "claude:s1:1.1",
            "quote": "The owner said this.",
            "role": "user",
            "kind": "prompt",
            "state": "live",
            "verify": "ok",
        }
        entry = {
            "id": "K1",
            "kind": "lesson",
            "text": "Cited lesson",
            "status": "current",
            "scope": "repo:p",
            "sensitivity": "normal",
            "expired": False,
            "tags": ["order"],
            "cites": [cite],
        }
        changes: list[dict[str, Any]] = [
            {"status": None},
            {"id": "invented"},
            {"text": []},
            {"tags": "order"},
            {"expired": "false"},
            {"scope": None},
            {"cites": [{**cite, "verify": "unknown"}]},
            {"cites": [{**cite, "kind": "reply"}]},
            {"cites": [{**cite, "state": "erased"}]},
        ]
        with mock.patch.object(ma, "probe", return_value=None):
            for change in changes:
                with (
                    self.subTest(change=change),
                    mock.patch.object(ma, "_run", return_value=json.dumps({"entries": [{**entry, **change}]})),
                ):
                    self.assertEqual(ma.list_records("repository", type="lesson", tags=["order"]), [])
            with mock.patch.object(ma, "_run", return_value=json.dumps({"entries": [entry]})):
                records = ma.list_records("repository", type="lesson", tags=["order"])
                self.assertIsInstance(records, list)
                assert not isinstance(records, ma.Degraded)
                self.assertEqual([r.id for r in records], ["K1"])

    def test_expiry_timestamp_before_at_and_after_boundary(self) -> None:
        """A future time on the same day stays current; at the expiry instant it is excluded."""
        self.assertIs(ma.__dict__["_expired"], memory_read.expired)
        with mock.patch("scripts.lib.memory_read.time.time", return_value=1780315200):  # 2026-06-01T12:00:00Z
            self.assertFalse(memory_read.expired("2026-06-01T12:00:01+00:00"))
            self.assertTrue(memory_read.expired("2026-06-01T12:00:00+00:00"))
            self.assertTrue(memory_read.expired("2026-06-01T11:59:59+00:00"))
            self.assertTrue(memory_read.expired(True))

    def test_native_terminal_work_units_are_reused(self) -> None:
        """Reasoned drops and absent rosters remain terminal; malformed drops still fail native validation."""
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            path = progress(repo, "s1", "L1")
            state = json.loads(path.read_text())
            for units in (
                {"1": {"status": "done"}},
                {"1": {"status": "dropped", "dropped_reason": "Out of scope."}},
                None,
            ):
                path.write_text(json.dumps({**state, "work_units": units}))
                with self.subTest(units=units):
                    self.assertEqual(lifecycle.owned(repo, "s1", "L1", complete=True)[1]["status"], "complete")
            reasons: list[Any] = [None, "", " ", True, 4, [], {}]
            for reason in reasons:
                path.write_text(
                    json.dumps({**state, "work_units": {"1": {"status": "dropped", "dropped_reason": reason}}})
                )
                with self.subTest(reason=reason), self.assertRaises(ValueError):
                    lifecycle.owned(repo, "s1", "L1", complete=True)


class SessionAttribution(recovery.RecoveryCase):
    """Real provider callers bind default/explicit sessions to successful and degraded read observations."""

    def unavailable_list(self: recovery.RecoveryCase) -> None:
        """Fail only the actual typed read; the separate capability/schema probe genuinely succeeds."""
        exe = self.tmp / "bin/muninn"
        exe.write_text(
            f"#!{sys.executable}\nimport runpy, sys\n"
            "if sys.argv[1:3] == ['know', 'list'] and '--kind' in sys.argv: raise SystemExit(1)\n"
            f"sys.argv[0] = {str(FAKE)!r}\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
        )

    def test_actual_provider_session_environment_defaults(self) -> None:
        """Explicit synthetic environment contracts cover both Codex identifiers with Claude variables absent."""
        for codex in (False, True):
            for key in recovery.SESSION_KEYS:
                for command in ("query", "predicate"):
                    with self.subTest(codex=codex, key=key, command=command):
                        self.configure(codex, key + command)
                        env = {k: v for k, v in self.native_env.items() if k not in recovery.SESSION_KEYS}
                        env[key] = "current-caller"
                        self.assertEqual(self.cli(command, script="lessons.py", explicit=False, env=env)[0], 0)
                        rows = self.trace_rows()
                        self.assertTrue(rows)
                        self.assertEqual({r["session_id"] for r in rows}, {"current-caller"})
                        self.assertIn("lesson." + command, [r["command"] for r in rows])

    def test_explicit_session_reaches_actual_degraded_list_in_all_join_callers(self) -> None:
        """An explicit session overrides environment attribution down to the adapter's genuine failed read."""
        self.unavailable_list()
        for codex in (False, True):
            for script, command in (
                ("lessons.py", "query"),
                ("lessons.py", "predicate"),
                ("orders.py", "lessons"),
                ("orders.py", "render"),
            ):
                with self.subTest(codex=codex, script=script, command=command):
                    self.configure(codex, script + command)
                    rc, out = self.cli(command, script=script, session="explicit-caller")
                    self.assertEqual((rc, out.get("degraded")), (3, "muninn_error"), out)
                    rows = self.trace_rows()
                    self.assertIn("memory.list", [r["command"] for r in rows])
                    self.assertEqual({r["session_id"] for r in rows}, {"explicit-caller"})
                    self.assertTrue(all(r["outcome"] == "degraded" for r in rows))

    def test_codex_default_session_reaches_genuine_degraded_query_and_predicate(self) -> None:
        """The omitted --session callers still bind adapter and lesson observations to the current Codex fixture."""
        self.unavailable_list()
        for codex in (False, True):
            for command in ("query", "predicate"):
                with self.subTest(codex=codex, command=command):
                    self.configure(codex, command)
                    env = {k: v for k, v in self.native_env.items() if k not in recovery.SESSION_KEYS}
                    env["CODEX_THREAD_ID"] = "codex-current"
                    self.assertEqual(self.cli(command, script="lessons.py", explicit=False, env=env)[0], 3)
                    rows = self.trace_rows()
                    self.assertIn("memory.list", [r["command"] for r in rows])
                    self.assertEqual({r["session_id"] for r in rows}, {"codex-current"})

    def test_function_serve_propagates_session_to_real_failure_trace(self) -> None:
        """A library caller's supplied session survives the joined/list boundary without a mocked trace."""
        with (
            mock.patch.object(ma, "probe", return_value=None),
            mock.patch.object(ma, "_run", return_value=ma.Degraded("muninn_error")),
            mock.patch.object(ma, "list_records", wraps=ma.list_records) as listed,
        ):
            payload, rc = lessons.serve(ol.empty(), "library-caller")
        self.assertEqual((rc, payload), (3, {"degraded": "muninn_error"}))
        self.assertEqual(listed.call_args.kwargs.get("session_id"), "library-caller")
        rows = [
            json.loads(line)
            for path in (self.tmp / "loops").glob("*/trace.jsonl")
            for line in path.read_text().splitlines()
        ]
        self.assertEqual({r["session_id"] for r in rows}, {"library-caller"})

    def test_early_probe_failure_is_counted_by_the_actual_session_bound_read(self) -> None:
        """Binary absence uses the underlying list trace as well as the high-level caller observation."""
        for codex in (False, True):
            for script, command in (
                ("lessons.py", "query"),
                ("lessons.py", "predicate"),
                ("orders.py", "lessons"),
                ("orders.py", "render"),
            ):
                with self.subTest(codex=codex, script=script, command=command):
                    self.configure(codex, "absent" + script + command)
                    env = {**self.native_env, "PATH": str(self.tmp / "absent-binary")}
                    rc, out = self.cli(command, script=script, session="early-caller", env=env)
                    self.assertEqual((rc, out.get("degraded")), (3, "muninn_absent"), out)
                    rows = self.trace_rows()
                    self.assertIn("memory.list", [r["command"] for r in rows])
                    self.assertEqual({r["session_id"] for r in rows}, {"early-caller"})


class NativeReadBoundary(recovery.RecoveryCase):
    """Modify an actual typed-list response from a private store rather than inventing citation authority."""

    def modify_list(self, field: str, value: object, raw: bool = False) -> None:
        """The schema/capability smoke stays real; only the served row's tested field changes on the wire."""
        (self.tmp / "bin/muninn").write_text(
            f"#!{sys.executable}\nimport contextlib, io, json, runpy, sys\n"
            f"sys.argv[0] = {str(FAKE)!r}\n"
            "if sys.argv[1:3] == ['know', 'list'] and '--kind' in sys.argv:\n"
            "    buf = io.StringIO()\n"
            "    try:\n"
            "        with contextlib.redirect_stdout(buf): runpy.run_path(sys.argv[0], run_name='__main__')\n"
            "    except SystemExit as done:\n"
            "        if done.code not in (None, 0): print(buf.getvalue(), end=''); raise\n"
            "    data = json.loads(buf.getvalue())\n"
            f"    for row in data['entries']: row[{field!r}] = {value!r}\n"
            "    text = json.dumps(data)\n"
            + (f"    text = text.replace(json.dumps({value!r}), {value!r})\n" if raw else "")
            + "    print(text)\nelse: runpy.run_path(sys.argv[0], run_name='__main__')\n"
        )

    def current_candidate(self, codex: bool, label: str) -> None:
        """Three genuinely owned completed sessions create a cited current promotion candidate."""
        self.configure(codex, label)
        for sid in ("s1", "s2", "s3"):
            self.assertEqual(self.stage(sid)[0], 0)
            self.complete(sid)
            self.assertEqual(self.cli("tick", "--loop", "logical-" + sid, session=sid)[0], 0)
        self.assertEqual(len(self.cli("predicate", script="lessons.py")[1]["candidates"]), 1)

    def test_nonfinite_and_overflow_expiry_never_serves_renders_or_promotes(self) -> None:
        """Malformed rows are excluded from a successful list; unavailable reads retain their separate failure API."""
        exe = self.tmp / "bin/muninn"
        original = exe.read_bytes()
        for codex in (False, True):
            exe.write_bytes(original)
            self.current_candidate(codex, "expiry")
            for token in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999", "9" * 400):
                self.modify_list("valid_until", token, raw=True)
                for command, key in (("query", "lessons"), ("predicate", "candidates")):
                    with self.subTest(codex=codex, token=token[:20], command=command):
                        rc, out = self.cli(command, script="lessons.py")
                        self.assertEqual(rc, 0, out)
                        self.assertEqual(out[key], [])
                with self.subTest(codex=codex, token=token[:20], command="render"):
                    self.assertEqual(self.cli("render")[0], 0)
                    self.assertNotIn("Lesson for", (self.repo / "standing-orders.md").read_text())

    def test_opaque_scope_labels_and_finite_supported_expiry_remain_current(self) -> None:
        """Muninn labels are display text; its cwd scope-id query supplies repository ownership."""
        exe = self.tmp / "bin/muninn"
        original = exe.read_bytes()
        for codex in (False, True):
            exe.write_bytes(original)
            self.current_candidate(codex, "supported")
            for field, values in (
                ("scope", ("not-a-scope", "/private/repository", "repo:p", "repo:", "global:ordinary-label")),
                ("valid_until", (None, "", 4102444800.5, "2099-01-01", "2099-01-01T12:00:00+00:00")),
            ):
                for value in values:
                    self.modify_list(field, value)
                    with self.subTest(codex=codex, field=field, value=value):
                        self.assertEqual(len(self.cli("query", script="lessons.py")[1]["lessons"]), 1)
                        self.assertEqual(len(self.cli("predicate", script="lessons.py")[1]["candidates"]), 1)
            bad_scopes: tuple[object, ...] = (None, 4, {}, "", " \t", "global", "loop:L1", "loop:", "loop:bad/id")
            for bad_scope in bad_scopes:
                self.modify_list("scope", bad_scope)
                with self.subTest(codex=codex, excluded=bad_scope):
                    self.assertEqual(self.cli("query", script="lessons.py")[1]["lessons"], [])
                    self.assertEqual(self.cli("predicate", script="lessons.py")[1]["candidates"], [])


if __name__ == "__main__":
    unittest.main()
