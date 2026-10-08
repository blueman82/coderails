"""Real owned callers, receipt publication faults and shared staged order identity."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.lib.loop_state_common import atomic_progress_update  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests import fake_muninn_store as fs  # noqa: E402
from scripts.tests.fake_muninn_case import LINES, PROMPT, StoreCase  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress  # noqa: E402

SESSION_KEYS = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID")
PRIOR = b'{"step":"other_publisher","fixture":"preserve these bytes"}\n'
PROBE = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders
mode, canonical, command = sys.argv[2:5]
real_write, real_replace = os.write, os.replace
target, calls, published = None, 0, 0
def write(fd, data):
    global target, calls
    raw = bytes(data)
    stat = os.fstat(fd)
    inode = (stat.st_dev, stat.st_ino)
    marker = ('"step": "orders_' + ('prepared' if command == 'prepare' else 'ticked') + '"').encode()
    if target is None and marker in raw:
        target = inode
    if inode != target or mode == 'published':
        return real_write(fd, data)
    calls += 1
    if mode == 'partial_exception':
        real_write(fd, raw[:max(1, len(raw) // 2)])
        raise OSError('exception after partial unpublished write')
    if mode == 'zero' and calls > 1:
        return 0
    limit = len(raw) - 1 if mode == 'newline' and calls == 1 else max(1, len(raw) // 2)
    return real_write(fd, raw[:limit])
def replace(src, dst):
    global published
    real_replace(src, dst)
    if mode == 'published' and str(dst) == canonical:
        published += 1
        raise OSError('ambiguous reply after publication')
os.write, os.replace = write, replace
rc = orders.main(sys.argv[5:])
print(json.dumps({'calls': calls, 'published': published, 'rc': rc}))
raise SystemExit(rc)
"""


class RecoveryCase(StoreCase):
    """Shared genuine fixtures; no test methods are inherited by consumers."""

    with_store = True

    def configure(self, codex: bool, label: str = "") -> None:
        """Give each provider/case its own store, source and trace directories."""
        self.codex = codex
        self.root = REPO / "packages/codex" if codex else REPO
        key = ("codex" if codex else "claude") + label
        self.repo = self.tmp / ("repo-" + key)
        self.repo.mkdir()
        self.home = self.tmp / ("home-" + key)
        fs.create(self.home)
        self.trace_base = self.tmp / ("trace-" + key)
        self.native_env = {k: v for k, v in os.environ.items() if k not in SESSION_KEYS}
        self.native_env.update(MUNINN_HOME=str(self.home), CLAUDE_AGENTIC_LOOP_DIR=str(self.trace_base))
        self.native_env["CODEX_THREAD_ID" if codex else "CLAUDE_CODE_SESSION_ID"] = "s1"

    def argv(self, script: str, session: str, *args: str, explicit: bool = True) -> list[str]:
        """Use the actual provider package and a separately bound caller session."""
        return [
            sys.executable,
            str(self.root / "scripts/lib" / script),
            "--dir",
            str(self.repo),
            *(["--session", session] if explicit else []),
            *args,
        ]

    def cli(
        self,
        *args: str,
        session: str = "s1",
        script: str = "orders.py",
        explicit: bool = True,
        env: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Run native CLI code in a fresh process, keeping its real exit and JSON response."""
        got = subprocess.run(
            self.argv(script, session, *args, explicit=explicit),
            capture_output=True,
            text=True,
            env=env or self.native_env,
            timeout=15,
        )
        self.assertEqual(got.stderr, "", got.stderr)
        return got.returncode, json.loads(got.stdout)

    def owner(self, session: str) -> Path:
        """Create genuine owned eligible progress and a synthetic user transcript."""
        (self.tmp / "projects/p" / f"{session}.jsonl").write_text("\n".join(map(json.dumps, LINES)) + "\n")
        return progress(self.repo, session, "logical-" + session, "in-progress")

    def stage(self, session: str, scope: str = "agnostic", mode: str = "stable-mode") -> tuple[int, dict[str, Any]]:
        """Stage the same shared id while independently owning session, loop and source."""
        if not (self.repo / session / "progress.json").exists():
            self.owner(session)
        env = {**self.native_env, "CODEX_THREAD_ID" if self.codex else "CLAUDE_CODE_SESSION_ID": session}
        return self.cli(
            "record",
            "--id",
            "stable-mode",
            "--failure-mode",
            mode,
            "--lesson",
            "Lesson for " + session,
            "--scope",
            scope,
            "--loop",
            "logical-" + session,
            "--quote",
            PROMPT,
            session=session,
            env=env,
        )

    def complete(self, session: str) -> None:
        """Save the fields changed by the actual provider's completion contract."""

        def change(state: dict[str, Any]) -> dict[str, Any]:
            if self.codex:
                state.update(completion={"revision": state["revision"]}, revision=state["revision"] + 1)
            state["status"] = "complete"
            return state

        self.assertTrue(atomic_progress_update(self.repo / session / "progress.json", change))

    def trace_rows(self) -> list[dict[str, Any]]:
        """Read actual per-session trace files from this fixture's private boundary."""
        return [
            json.loads(line) for path in self.trace_base.glob("*/trace.jsonl") for line in path.read_text().splitlines()
        ]

    def store_rows(self) -> list[tuple[Any, ...]]:
        """Inspect only this test's SQLite store to detect premature supersession."""
        with sqlite3.connect(fs.db_path(self.home)) as db:
            return db.execute("SELECT id, text, status FROM knowledge ORDER BY id").fetchall()


class ReceiptRecovery(RecoveryCase):
    """Boundary faults affect this call's publication, never unrelated trace writes or live evidence."""

    def setup_receipt(self, codex: bool, command: str, label: str) -> tuple[Path, bytes]:
        """Prepare/tick through owned native callers while preserving a foreign publisher's prior row."""
        self.configure(codex, label)
        self.owner("s1")
        path = self.repo / "s1/teardown.jsonl"
        path.write_bytes(PRIOR)
        if command == "tick":
            self.assertEqual(self.stage("s1")[0], 0)
            self.complete("s1")
        return path, path.read_bytes()

    def fault(self, mode: str, command: str, path: Path) -> tuple[int, dict[str, Any], dict[str, Any]]:
        """Inject real short/partial writes or an ambiguous os.replace reply in each provider subprocess."""
        args = self.argv("orders.py", "s1", command, "--loop", "logical-s1")[2:]
        got = subprocess.run(
            [sys.executable, "-c", PROBE, str(self.root), mode, str(path), command, *args],
            capture_output=True,
            text=True,
            env=self.native_env,
            timeout=15,
        )
        self.assertEqual(got.stderr, "", got.stderr)
        rows = [json.loads(line) for line in got.stdout.splitlines()]
        return got.returncode, rows[0], rows[1]

    def retry_once(self, command: str, path: Path) -> None:
        """Ordinary retry dedupes receipts and cannot duplicate recurrence or aging."""
        self.assertEqual(self.cli(command, "--loop", "logical-s1")[0], 0)
        saved = path.read_bytes()
        ledger = (self.repo / "orders.json").read_bytes() if command == "tick" else None
        self.assertEqual(self.cli(command, "--loop", "logical-s1")[0], 0)
        self.assertEqual(path.read_bytes(), saved)
        if ledger is not None:
            self.assertEqual((self.repo / "orders.json").read_bytes(), ledger)
            self.assertEqual(len(ol.open_ledger(self.repo)["orders"][0]["evidence"]), 1)

    def test_positive_short_writes_and_last_newline_finish_before_publication(self) -> None:
        """Repeated short progress and a separately written last newline form one complete canonical event."""
        for codex in (False, True):
            for command in ("prepare", "tick"):
                for mode in ("short", "newline"):
                    with self.subTest(codex=codex, command=command, mode=mode):
                        path, before = self.setup_receipt(codex, command, command + mode)
                        rc, out, probe = self.fault(mode, command, path)
                        self.assertEqual(rc, 0, (out, probe))
                        self.assertGreater(probe["calls"], 1)
                        self.assertTrue(path.read_bytes().startswith(before))
                        self.assertTrue(path.read_bytes().endswith(b"\n"))
                        self.assertEqual(
                            len([json.loads(line) for line in path.read_bytes().splitlines()]),
                            len(before.splitlines()) + 1,
                        )
                        self.assertTrue(path.with_name("teardown.jsonl.lock").is_file())
                        self.retry_once(command, path)

    def test_zero_progress_and_exception_after_partial_leave_canonical_unchanged(self) -> None:
        """Failed unpublished writes preserve prior bytes and permit an ordinary receipt retry."""
        for codex in (False, True):
            for command in ("prepare", "tick"):
                for mode in ("zero", "partial_exception"):
                    path, before = self.setup_receipt(codex, command, command + mode)
                    rc, out, probe = self.fault(mode, command, path)
                    with self.subTest(codex=codex, command=command, mode=mode, boundary="failure"):
                        self.assertEqual(rc, 3 if command == "tick" else 2, (out, probe))
                        self.assertGreater(probe["calls"], 0)
                        self.assertEqual(path.read_bytes(), before)
                        self.assertEqual(
                            list(path.parent.glob("teardown.jsonl.*")), [path.with_name("teardown.jsonl.lock")]
                        )
                    with self.subTest(codex=codex, command=command, mode=mode, boundary="retry"):
                        self.retry_once(command, path)

    def test_ambiguous_error_after_publication_dedupes_on_retry(self) -> None:
        """Canonical publication may succeed before an error reply; retry never appends or applies twice."""
        for codex in (False, True):
            for command in ("prepare", "tick"):
                with self.subTest(codex=codex, command=command):
                    path, before = self.setup_receipt(codex, command, command + "published")
                    rc, out, probe = self.fault("published", command, path)
                    self.assertEqual((rc, probe["published"]), (3 if command == "tick" else 2, 1), out)
                    self.assertTrue(path.read_bytes().startswith(before))
                    self.assertTrue(path.read_bytes().endswith(b"\n"))
                    saved = path.read_bytes()
                    self.retry_once(command, path)
                    self.assertEqual(path.read_bytes(), saved)

    def test_arbitrary_corruption_and_missing_terminal_newline_refuse_untouched(self) -> None:
        """No attempt identity authorizes changing a pre-existing malformed or unframed canonical tail."""
        for codex in (False, True):
            for n, raw in enumerate(
                (PRIOR + b'{"partial":', PRIOR + b"[]\n", PRIOR.rstrip(b"\n"), PRIOR + b'{"value":NaN}\n')
            ):
                with self.subTest(codex=codex, raw=raw):
                    path, _ = self.setup_receipt(codex, "prepare", "corrupt" + str(n))
                    path.write_bytes(raw)
                    self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 2)
                    self.assertEqual(path.read_bytes(), raw)

    def test_concurrent_cooperating_events_preserve_bytes_and_any_matching_dedupe(self) -> None:
        """Two real publishers share the persistent sidecar without combining provider dedupe policies."""
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; "
            "from scripts.lib import orders_lifecycle as l; "
            'b={"session_id":"s1","loop_id":"logical-s1","revision":1}; '
            '[l.observe(Path(sys.argv[2]), "fixture-"+sys.argv[3]+str(n), b, "0"*64) for n in range(3)]; '
            'l.observe(Path(sys.argv[2]), "fixture-shared", b, "1"*64)'
        )
        for codex in (False, True):
            with self.subTest(codex=codex):
                path, before = self.setup_receipt(codex, "prepare", "publishers")
                argv = [sys.executable, "-c", code, str(self.root), str(path.parent)]
                with (
                    subprocess.Popen(
                        [*argv, "a"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.native_env
                    ) as one,
                    subprocess.Popen(
                        [*argv, "b"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.native_env
                    ) as two,
                ):
                    output = [one.communicate(timeout=15), two.communicate(timeout=15)]
                    self.assertEqual((one.returncode, two.returncode, output), (0, 0, [(b"", b""), (b"", b"")]))
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(before))
                self.assertTrue(raw.endswith(b"\n"))
                self.assertEqual(len([json.loads(line) for line in raw.splitlines()]), 8)
                self.assertTrue(path.with_name("teardown.jsonl.lock").is_file())

    def test_missing_newline_refuses_even_when_prior_row_would_dedupe(self) -> None:
        """A complete JSON fragment is still unframed evidence, even if its fields match this request."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                path, _ = self.setup_receipt(codex, "prepare", "dedupe")
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 0)
                raw = path.read_bytes().rstrip(b"\n")
                path.write_bytes(raw)
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 2)
                self.assertEqual(path.read_bytes(), raw)

    def test_unacquired_sidecar_lock_refuses_without_publication(self) -> None:
        """A lock context must actually yield ownership, not merely be invoked."""
        path, before = self.setup_receipt(False, "prepare", "busy-lock")
        binding = {"session_id": "s1", "loop_id": "logical-s1", "revision": 1}
        with (
            mock.patch.object(lifecycle, "file_lock", return_value=contextlib.nullcontext(False), create=True),
            self.assertRaisesRegex(ValueError, "order_state_error"),
        ):
            lifecycle.observe(path.parent, "orders_prepared", binding, "0" * 64)
        self.assertEqual(path.read_bytes(), before)


class SharedIdentity(RecoveryCase):
    """An id binds failure mode and scope across staged sessions and committed local application."""

    def test_staged_collision_refuses_before_store_supersession(self) -> None:
        """The ledger is still empty when a conflicting other session must be rejected."""
        for codex in (False, True):
            for field in ("scope", "failure_mode"):
                self.configure(codex, field)
                self.assertEqual(self.stage("s1")[0], 0)
                self.owner("s2")
                prior = self.store_rows()
                rc, out = self.stage(
                    "s2",
                    scope="repo" if field == "scope" else "agnostic",
                    mode="foreign-mode" if field == "failure_mode" else "stable-mode",
                )
                with self.subTest(codex=codex, field=field, boundary="refusal"):
                    self.assertEqual((rc, out.get("reason_code")), (2, "order_id_collision"), out)
                with self.subTest(codex=codex, field=field, boundary="store"):
                    self.assertEqual(self.store_rows(), prior)
                    self.assertEqual(list((self.repo / "s2").glob("orders-prepared-*.json")), [])
                self.assertEqual(ol.open_ledger(self.repo)["orders"], [])

    def test_existing_conflicting_preparation_cannot_replace_applied_scope(self) -> None:
        """A typed pre-existing conflicting staged row cannot preserve agnostic scope while replacing repo text."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex)
                for sid in ("s1", "s2"):
                    self.assertEqual(self.stage(sid)[0], 0)
                self.complete("s1")
                self.assertEqual(self.cli("tick", "--loop", "logical-s1")[0], 0)
                path = lifecycle.preparation_path(self.repo / "s2", "logical-s2")
                prepared = json.loads(path.read_text())
                prepared["records"][0]["scope"] = "repo"
                path.write_text(json.dumps(prepared))
                self.complete("s2")
                before = (self.repo / "orders.json").read_bytes()
                rc, out = self.cli("tick", "--loop", "logical-s2", session="s2")
                self.assertEqual((rc, out.get("reason_code")), (2, "order_id_collision"), out)
                self.assertEqual((self.repo / "orders.json").read_bytes(), before)

    def test_same_identity_stages_across_sessions_and_recurrence_applies_once(self) -> None:
        """Three owned sessions may stage one id/mode/scope before any completion, then apply accepted recurrence."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                self.configure(codex)
                for sid in ("s1", "s2", "s3"):
                    self.assertEqual(self.stage(sid)[0], 0)
                self.assertEqual(ol.open_ledger(self.repo)["orders"], [])
                for sid in ("s1", "s2", "s3"):
                    self.complete(sid)
                    self.assertEqual(self.cli("tick", "--loop", "logical-" + sid, session=sid)[0], 0)
                    self.assertEqual(self.cli("tick", "--loop", "logical-" + sid, session=sid)[1]["ticked"], False)
                order = ol.open_ledger(self.repo)["orders"][0]
                self.assertEqual(
                    (order["scope"], len(order["evidence"]), order["loops_since_recurrence"]), ("agnostic", 3, 0)
                )
                self.assertEqual(len(ol.candidates(ol.open_ledger(self.repo))), 1)


if __name__ == "__main__":
    unittest.main()
