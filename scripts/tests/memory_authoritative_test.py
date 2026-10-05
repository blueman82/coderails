"""Muninn-authoritative adapter: default-on backend, refusal mapping, user-anchored cites, mirrors and counters.

Runs the real adapter against the hermetic fake `muninn` (sqlite schema v2, temp MUNINN_HOME). Every acceptance test
has a negative control that mutates the one rule it proves. Nothing here touches the live Muninn store.
"""

from __future__ import annotations

import ast
import json
import os
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
from scripts.lib import memory_cite, memory_counters, memory_reasons, memory_schema  # noqa: E402
from scripts.tests import fake_muninn_store as fs  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT, PROPOSAL, SESSION, StoreCase  # noqa: E402

ADAPTER = str(REPO / "scripts/lib/memory_adapter.py")
APPROVAL = f"claude:{SESSION}:3.1"
REPLY = f"claude:{SESSION}:2.1"


class Base(StoreCase):
    """Fake muninn behind a logging wrapper, so a test can count how many times muninn was spawned."""

    with_store = True

    def setUp(self) -> None:
        """Put a call-logging wrapper first on PATH."""
        super().setUp()
        self.log = self.tmp / "calls.log"
        wrapper = self.tmp / "logbin" / "muninn"
        wrapper.parent.mkdir()
        wrapper.write_text(f'#!/bin/sh\necho "$@" >> "{self.log}"\nexec "{self.tmp}/bin/muninn" "$@"\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        os.environ["PATH"] = f"{wrapper.parent}{os.pathsep}{os.environ['PATH']}"

    def calls(self) -> list[str]:
        """Every muninn invocation so far."""
        return self.log.read_text().splitlines() if self.log.exists() else []

    def rows(self, session: str = "s1") -> list[dict[str, Any]]:
        """Trace rows for a session."""
        path = self.tmp / "loops" / session / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def approval(self) -> ma.Record:
        """A decision that cites only the short approval prompt."""
        return self.record("approved wording", type="decision", cite=APPROVAL, quote="yes")

    def reason(self, result: object) -> str:
        """The reason of a Degraded result."""
        self.assertIsInstance(result, ma.Degraded, result)
        assert isinstance(result, ma.Degraded)
        return result.reason

    def repo_with_config(self, name: str, text: str) -> None:
        """Chdir into a temp git repo (own directory per call) whose workflow config is `text`."""
        repo = self.tmp / name
        (repo / ".coderails").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".coderails/workflow.config.yaml").write_text(text)
        old = Path.cwd()
        os.chdir(repo)
        self.addCleanup(os.chdir, old)


class DefaultIsMuninn(Base):
    """(a) no config means Muninn is authoritative and a missing Muninn fails loudly, writing nothing."""

    def cli_add(self, env_path: str = "/nonexistent") -> tuple[subprocess.CompletedProcess[str], set[str]]:
        """Run `memory_adapter.py add` from an empty non-git dir; return the result and the files it created."""
        cwd = self.tmp / "cwd"
        cwd.mkdir(exist_ok=True)
        before = {str(p) for p in self.tmp.rglob("*")}
        env = {**os.environ, "PATH": env_path}
        cmd = [sys.executable, ADAPTER, "add", "--type", "lesson", "--loop", "L1", "--claim", "c", "--quote", PROMPT]
        p = subprocess.run([*cmd, "--session", "s1"], capture_output=True, text=True, env=env, cwd=cwd)
        return p, {str(x) for x in self.tmp.rglob("*")} - before

    def test_absent_muninn_exits_3_and_writes_no_markdown_or_ledger(self) -> None:
        """(a) exit 3 + muninn_absent + a trace row; the only new file is the trace."""
        p, created = self.cli_add()
        self.assertEqual((p.returncode, json.loads(p.stdout)), (3, {"degraded": "muninn_absent"}))
        (row,) = self.rows()
        self.assertEqual(
            (row["command"], row["outcome"], row["reason_code"]), ("memory.add", "degraded", "muninn_absent")
        )
        self.assertEqual({Path(c).name for c in created if Path(c).is_file()}, {"trace.jsonl"})
        self.assertEqual([c for c in created if c.endswith(".md")], [])

    def test_control_backend_off_changes_the_outcome(self) -> None:
        """Negative control 1: forcing the switch off no longer yields the default's loud muninn_absent."""
        with (
            mock.patch.object(ma, "backend", return_value="off"),
            mock.patch.dict(os.environ, {"PATH": "/nonexistent"}),
        ):
            self.assertEqual(self.reason(ma.add(self.record("x"), "s1")), "memory_backend_off")

    def test_backend_switch_from_config(self) -> None:
        """(f) off -> memory_backend_off, junk -> memory_backend_invalid (no muninn spawn); no key -> writes."""
        for name, text, want in (
            ("off", "memory:\n  backend: off\n", "memory_backend_off"),
            ("bad", "memory:\n  backend: nope\n", "memory_backend_invalid"),
        ):
            self.repo_with_config(name, text)
            self.assertEqual(self.reason(ma.add(self.record("x"), "s1")), want)
            self.assertEqual(self.calls(), [])
            self.assertEqual(self.rows()[-1]["reason_code"], want)
        self.repo_with_config("default", "project: x\n")  # no memory key: muninn is the backend
        self.written(ma.add(self.record("default is muninn"), "s1"))


class TypedRecordRoundTrip(Base):
    """(b) gap 5: typed records round-trip; untyped ones are rejected before any muninn spawn."""

    def test_round_trip_with_restart(self) -> None:
        """Add returns the K-id; a fresh process lists the same id and cite."""
        kid = self.written(ma.add(self.record("typed claim"))).id
        ma.PROBE_CACHE.clear()
        p = subprocess.run(
            [sys.executable, ADAPTER, "list", "--scope", "loop", "--loop", "L1"], capture_output=True, text=True
        )
        (got,) = json.loads(p.stdout)
        self.assertEqual((kid, got["id"], got["cite"]), ("K1", "K1", f"claude:{SESSION}:1.1"))
        self.assertEqual([r.id for r in self.listed()], [kid])  # (e)

    def test_untyped_records_rejected_before_spawn(self) -> None:
        """Bad kind, no scope, no loop id, empty claim -> bad_record and zero muninn invocations."""
        for bad in (
            self.record("x", type="nonsense"),
            self.record("x", scope=""),
            self.record("x", loop_id=None),
            self.record("   "),
        ):
            self.assertEqual(self.reason(ma.add(bad, "s1")), "bad_record")
        self.assertEqual(self.calls(), [])

    def test_search_path_is_scoped_to_the_loop(self) -> None:
        """list(query) goes through `search --all-projects` and keeps only loop:<id> hits."""
        self.written(ma.add(self.record("zebrafish alpha")))
        self.written(ma.add(self.record("zebrafish beta", loop_id="L2")))
        self.written(ma.add(self.record("unrelated")))
        got = ma.list_records("loop", "L1", query="zebrafish")
        assert isinstance(got, list)
        self.assertEqual([r.claim for r in got], ["zebrafish alpha"])
        self.assertTrue(any(c.startswith("search zebrafish --all-projects") for c in self.calls()))


class RefusalMapping(Base):
    """(c) a short approval alone is refused and written nowhere; with its reply it writes."""

    def short_alone(self) -> str:
        """Reason the adapter gives for the approval cited alone."""
        return self.reason(ma.add(self.approval(), "s1"))

    def test_short_approval_alone_then_with_reply(self) -> None:
        """refused_approval_needs_reply keeps muninn's code as detail and writes nothing; approved_reply writes."""
        self.assertEqual(self.short_alone(), "refused_approval_needs_reply")
        self.assertEqual(self.reason(ma.add(self.approval())), "refused_approval_needs_reply")
        self.assertEqual(self.muninn("know", "list", "--scope-loop", "L1", "--status", "all")[1]["count"], 0)
        refused = ma.add(self.approval())
        assert isinstance(refused, ma.Degraded)
        self.assertEqual(refused.detail, "approval_needs_reply")
        self.assertIn("muninn_error", dict(self.rows()[-1]["inputs"]))
        both = self.record(
            "approved wording", type="decision", cite=APPROVAL, quote="yes", reply_cite=REPLY, reply_quote=PROPOSAL
        )
        self.written(ma.add(both))
        (got,) = self.listed()
        self.assertEqual((got.id, got.type), ("K1", "decision"))

    def test_control_old_collapse_hides_the_refusal(self) -> None:
        """Negative control 2: with the old muninn_error collapse the refusal code is lost."""

        def collapse(_stdout: str) -> None:
            return None

        with mock.patch.object(ma, "_refusal", collapse):
            self.assertEqual(self.short_alone(), "muninn_error")

    def test_other_nonzero_exit_stays_muninn_error(self) -> None:
        """Only rc 2 JSON refusals map; the rc 1 store constraint of a pre-v2 kind CHECK stays muninn_error."""
        self.assertEqual(self.reason(ma.add(self.record("x", valid_until="2020-01-01"))), "refused_bad_valid_until")
        fs.create(self.tmp / "oldkind", old_kind=True)
        with mock.patch.dict(os.environ, {"MUNINN_HOME": str(self.tmp / "oldkind")}):
            self.assertEqual(self.reason(ma.add(self.record("lesson on a pre-v2 CHECK"))), "muninn_error")

    def test_cli_approval_resolves_reply_from_session(self) -> None:
        """`--approval REF` finds the preceding reply via `muninn session`; a reply as the anchor is cite_not_user."""
        base = [
            sys.executable,
            ADAPTER,
            "add",
            "--type",
            "decision",
            "--loop",
            "L1",
            "--claim",
            "ok",
            "--session",
            "s1",
        ]
        p = subprocess.run([*base, "--approval", APPROVAL], capture_output=True, text=True)
        self.assertEqual((p.returncode, json.loads(p.stdout)), (0, {"ok": True, "id": "K1"}))
        p = subprocess.run([*base, "--cite", REPLY, "--quote", PROPOSAL], capture_output=True, text=True)
        self.assertEqual((p.returncode, json.loads(p.stdout)), (3, {"degraded": "cite_not_user"}))
        p = subprocess.run([*base, "--cite", "claude:nope:1.1", "--quote", PROMPT], capture_output=True, text=True)
        self.assertEqual(json.loads(p.stdout), {"degraded": "cite_not_user"})  # unknown session: no verified anchor


class UserAnchoredCites(Base):
    """(d) a cite set with no user-prompt anchor never reaches muninn."""

    def assistant_only(self) -> ma.Record:
        """A lesson that cites only the assistant's reply."""
        return self.record("self cite", cite=REPLY, quote=PROPOSAL, cite_role="assistant", cite_kind="reply")

    def test_assistant_only_is_cite_not_user_with_zero_spawns(self) -> None:
        """cite_not_user and the wrapper log shows ZERO muninn invocations."""
        self.assertEqual(self.reason(ma.add(self.assistant_only(), "s1")), "cite_not_user")
        self.assertEqual(self.calls(), [])

    def test_control_without_the_precheck_muninn_is_called(self) -> None:
        """Negative control 3: drop the pre-check and muninn is spawned (and, being lenient on replies, writes)."""
        with mock.patch.object(memory_cite, "check", return_value=None):
            ma.add(self.assistant_only(), "s1")
        self.assertTrue(self.calls())

    def test_quote_forms(self) -> None:
        """quote_only needs 12-300 chars without a ref; with a ref muninn arbitrates; roles and halves are checked."""
        short = self.record("x", cite="", quote="eleven char")
        self.assertEqual(self.reason(ma.add(short)), "cite_too_short")
        self.assertIsNone(memory_cite.check(self.record("x", cite="", quote="twelve chars")))
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.written(ma.add(self.record("quote only", cite="", quote="targeted tests before committing")))
        half = self.record("x", reply_cite=REPLY, reply_quote="")
        self.assertEqual(memory_cite.check(half), "cite_unresolved")
        payload = {"events": [{"ref": REPLY, "role": "assistant", "kind": "reply", "preview": PROPOSAL + "..."}]}
        self.assertEqual(memory_cite.approved_reply(payload, REPLY), "cite_not_user")
        self.assertEqual(memory_cite.approved_reply(payload, "claude:s:9.1"), "cite_unresolved")


class ProbeSchema(Base):
    """(g) probe() reads the schema, not the version string."""

    def test_v1_store_is_caught_even_when_version_looks_new(self) -> None:
        """muninn_schema_old with --version 9.9.9; the control without the schema check lets the v1 store through."""
        fs.create(self.tmp / "v1", user_version=1)
        env = {"MUNINN_HOME": str(self.tmp / "v1"), "FAKE_MUNINN_VERSION": "9.9.9"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(ma.probe(), ma.Degraded("muninn_schema_old"))
            self.assertEqual(self.reason(ma.add(self.record("x"))), "muninn_schema_old")
            with mock.patch.object(memory_schema, "check", return_value=None):  # negative control 4
                self.assertIsNone(ma.probe())

    def test_missing_store_and_smoke_failure_are_reason_coded(self) -> None:
        """No store -> muninn_store_missing; a failing read smoke -> its reason (here muninn_error)."""
        with mock.patch.dict(os.environ, {"MUNINN_HOME": str(self.tmp / "none")}):
            self.assertEqual(ma.probe(), ma.Degraded("muninn_store_missing"))
        ma.PROBE_CACHE.clear()

        def run(args: list[str], help_probe: bool = False) -> str | ma.Degraded:
            return "usage " + " ".join((*ma.ADD_FLAGS, *ma.KINDS)) if help_probe else ma.Degraded("muninn_error")

        with mock.patch.object(ma, "_run", run):
            self.assertEqual(ma.probe(), ma.Degraded("muninn_error"))


class MirrorsCountersReasons(Base):
    """(i) mirrors, (j) counters, (k) reasons, (6) no Markdown writes outside write_view."""

    def test_codex_mirrors_byte_identical(self) -> None:
        """Adapter, cite, reasons, schema and config schema are byte copies."""
        for rel in (
            "scripts/lib/memory_adapter.py",
            "scripts/lib/memory_cite.py",
            "scripts/lib/memory_reasons.py",
            "scripts/lib/memory_schema.py",
            "config.schema.json",
        ):
            mirror = REPO / "packages/codex" / rel
            self.assertEqual((REPO / rel).read_bytes(), mirror.read_bytes(), rel)

    def test_counts_dedupe_by_event_id_and_group_by_command(self) -> None:
        """All typed-record prefixes count once per event_id; other commands are ignored."""
        d = self.tmp / "loops" / "x"
        d.mkdir(parents=True)
        rows = [
            ("e1", "memory.add", "muninn_absent"),
            ("e2", "decision.record", "ok"),
            ("e3", "proof.run", "ok"),
            ("e4", "other/x", "no"),
        ]
        lines = [json.dumps({"event_id": e, "command": c, "reason_code": r}) for e, c, r in rows]
        (d / "trace.jsonl").write_text("\n".join([*lines, lines[0]]) + "\n")
        got = memory_counters.memory_counts([self.tmp / "loops"])
        self.assertEqual(got["rows"], 3)
        self.assertEqual(got["by_command"], {"decision.record": 1, "memory.add": 1, "proof.run": 1})
        self.assertEqual(got["by_reason_code"], {"muninn_absent": 1, "ok": 2})

    def test_every_emitted_reason_is_documented(self) -> None:
        """Every reason literal in the adapter and cite sources is a REASONS key (SSOT)."""
        pattern = (
            r'"((?:muninn|memory|cite)_[a-z_]+|uncited_write|bad_record|restricted_refused|handwritten_protected)"'
        )
        import re

        used = set(re.findall(pattern, (REPO / "scripts/lib/memory_adapter.py").read_text()))
        used |= set(re.findall(pattern, (REPO / "scripts/lib/memory_cite.py").read_text()))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(memory_reasons.REASONS) - {"muninn", "memory_cite"}), [])

    def test_markdown_is_written_only_through_write_view(self) -> None:
        """No memory module opens/writes a file outside write_view; the scanner does catch a violator."""
        for name in ("adapter", "cite", "reasons", "counters", "schema"):
            self.assertEqual(writers((REPO / f"scripts/lib/memory_{name}.py").read_text()), set(), name)
        self.assertEqual(writers("def sneaky(p):\n    open(p, 'w')\n"), {"sneaky"})

    def test_module_sizes(self) -> None:
        """New modules stay under 400 lines."""
        for name in ("adapter", "cite", "reasons", "counters"):
            self.assertLess(len((REPO / f"scripts/lib/memory_{name}.py").read_text().splitlines()), 400, name)


def writers(source: str) -> set[str]:
    """Names of functions (other than write_view) that call a file-writing primitive."""
    primitives = {"open", "write_text", "write_bytes", "mkstemp", "fdopen"}
    found: set[str] = set()
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, ast.FunctionDef) and fn.name != "write_view":
            for call in ast.walk(fn):
                if (
                    isinstance(call, ast.Call)
                    and getattr(call.func, "attr", getattr(call.func, "id", "")) in primitives
                ):
                    found.add(fn.name)
    return found


if __name__ == "__main__":
    unittest.main()
