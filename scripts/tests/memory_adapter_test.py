"""Verify scripts/lib/memory_adapter.py against a fake `muninn` executable (no real ledger is touched)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import memory_adapter as ma  # noqa: E402

ADAPTER = str(REPO / "scripts/lib/memory_adapter.py")
NEW_FLAGS = "--scope-loop --confidence --valid-until --sensitivity --contradicts --tag"
FAKE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "new")
if os.environ.get("FAKE_SLEEP"):
    import time; time.sleep(5)
if "--help" in sys.argv:
    sys.stdout.write("usage: kinds {decision,fact,preference,procedure}" if mode == "old"
                     else "usage: kinds lesson constraint @FLAGS@")
    sys.exit(int(os.environ.get("FAKE_HELP_RC", "0")))
if sys.argv[2] == "list":
    sys.stdout.write(open(os.environ["FAKE_LIST"]).read()); sys.exit(0)
sys.stdout.write("{}")
""".replace(
    "@FLAGS@", NEW_FLAGS
)

ENTRIES: dict[str, Any] = {
    "entries": [
        {
            "id": "K1",
            "kind": "lesson",
            "text": "Always cite",
            "tags": ["run-a", "x"],
            "sensitivity": "normal",
            "expired": False,
            "confidence": "observed",
            "valid_until": None,
            "date": "2026-10-01",
            "cites": [{"ref": "claude:t:1.1", "quote": "cite it"}],
        },
        {"id": "K2", "kind": "lesson", "text": "secret", "sensitivity": "restricted", "expired": False},
        {"id": "K3", "kind": "lesson", "text": "stale", "sensitivity": "normal", "expired": True},
    ]
}


class Base(unittest.TestCase):
    """Put a fake muninn first on PATH and isolate the trace directory."""

    def setUp(self) -> None:
        """Create the fake executable, list fixture, env patch and clear the probe cache."""
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        exe = self.tmp / "bin" / "muninn"
        exe.parent.mkdir()
        exe.write_text(FAKE)
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        (self.tmp / "list.json").write_text(json.dumps(ENTRIES))
        self.log = self.tmp / "argv.log"
        env = {
            "PATH": f"{exe.parent}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_LIST": str(self.tmp / "list.json"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
        }
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        ma.PROBE_CACHE.clear()

    def argv(self) -> list[list[str]]:
        """Return every argv the fake muninn recorded."""
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def rows(self, session: str = "s1") -> list[dict[str, Any]]:
        """Return the trace rows written for a session."""
        path = self.tmp / "loops" / session / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def rec(
    scope: str = "loop",
    type: str = "lesson",
    cite: str = "claude:t:1.1",
    quote: str = "q",
    tags: list[str] | None = None,
    loop_id: str | None = "L1",
    valid_until: str | None = None,
) -> ma.Record:
    """Build a record, defaulting to a valid cited loop lesson."""
    return ma.Record(scope, type, "c", cite, quote, ["run-ab"] if tags is None else tags, loop_id, None, valid_until)


class WriteTests(Base):
    """The write path."""

    def test_add_maps_flags(self) -> None:
        """Every typed field becomes its exact muninn flag."""
        r = rec(valid_until="2027-01-01")
        r.confidence, r.supersedes, r.contradicts = "observed", "K1", "K2"
        self.assertIsNone(ma.add(r, "s1"))
        call = self.argv()[-1]
        self.assertEqual(call[:2], ["know", "add"])
        pairs = [("--kind", "lesson"), ("--scope-loop", "L1"), ("--tag", "run-ab"), ("--cite", "claude:t:1.1")]
        pairs += [("--quote", "q"), ("--valid-until", "2027-01-01"), ("--confidence", "observed")]
        pairs += [("--supersedes", "K1"), ("--contradicts", "K2")]
        for flag, value in pairs:
            self.assertEqual(call[call.index(flag) + 1], value)

    def test_user_scope_is_global(self) -> None:
        """User scope maps to --global."""
        ma.add(rec(scope="user", loop_id=None), "s1")
        self.assertIn("--global", self.argv()[-1])

    def test_uncited_write_refused_before_spawn(self) -> None:
        """No cite or no quote refuses before any add process starts, and traces it."""
        for bad in (rec(cite=""), rec(quote="")):
            degraded = ma.add(bad, "s1")
            assert degraded is not None
            self.assertEqual(degraded.reason, "uncited_write")
        self.assertEqual([c for c in self.argv() if c[:2] == ["know", "add"]], [])
        self.assertEqual([x["reason_code"] for x in self.rows()], ["uncited_write"] * 2)

    def test_uncited_negative_control(self) -> None:
        """With the guard removed the uncited write spawns muninn, so the guard test above is not vacuous."""
        with mock.patch.object(ma, "validate", return_value=None):
            ma.add(rec(cite=""), "s1")
        self.assertTrue([c for c in self.argv() if c[:2] == ["know", "add"]])

    def test_bad_record(self) -> None:
        """Bad type, tag, date or a loop scope without an id is refused."""
        for bad in (rec(type="nope"), rec(tags=["Bad Tag"]), rec(valid_until="12345.0"), rec(loop_id=None)):
            degraded = ma.add(bad, "s1")
            assert degraded is not None
            self.assertEqual(degraded.reason, "bad_record")


class DegradeTests(Base):
    """Every degrade is a value, never an exception."""

    def reason(self, result: object) -> str:
        """Return the degrade reason of a result."""
        assert isinstance(result, ma.Degraded)
        return str(result.reason)

    def test_old_ledger(self) -> None:
        """A 0.1.0-style help degrades writes and reads without any add/list spawn."""
        os.environ["FAKE_MODE"] = "old"
        self.assertEqual(self.reason(ma.add(rec(), "s1")), "muninn_old_ledger")
        self.assertEqual(self.reason(ma.list_records("loop", "L1", session_id="s1")), "muninn_old_ledger")
        self.assertEqual([c for c in self.argv() if "--help" not in c], [])
        self.assertIn("muninn_old_ledger", [x["reason_code"] for x in self.rows()])

    def test_absent(self) -> None:
        """No muninn on PATH degrades."""
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertEqual(self.reason(ma.add(rec(), "s1")), "muninn_absent")

    def test_timeout(self) -> None:
        """A hung muninn degrades."""
        os.environ["FAKE_SLEEP"] = "1"
        with mock.patch.object(ma, "TIMEOUT", 0.2):
            self.assertEqual(self.reason(ma.add(rec(), "s1")), "muninn_timeout")

    def test_unsafe_session_no_row_no_raise(self) -> None:
        """A foreign or unsafe session id degrades normally but writes no trace row."""
        os.environ["FAKE_MODE"] = "old"
        for sid in ("../x", "a/b", "?"):
            self.assertEqual(self.reason(ma.add(rec(), sid)), "muninn_old_ledger")
        self.assertEqual(list((self.tmp / "loops").glob("**/trace.jsonl")), [])


class ReadTests(Base):
    """The read path."""

    def test_filters_and_provenance(self) -> None:
        """Restricted and expired rows are dropped; id, cite and quote are attached."""
        out = ma.list_records("loop", "L1", session_id="s1")
        assert isinstance(out, list)
        self.assertEqual([r.id for r in out], ["K1"])
        self.assertEqual((out[0].cite, out[0].quote), ("claude:t:1.1", "cite it"))
        call = self.argv()[-1]
        self.assertEqual(call[:4], ["know", "list", "--status", "current"])
        self.assertIn("--scope-loop", call)

    def test_loop_scope_without_loop_id_refused(self) -> None:
        """A loop-scope read with no loop id would list every scope mislabeled as loop; it degrades instead."""
        out = ma.list_records("loop", None, session_id="s1")
        assert isinstance(out, ma.Degraded)
        self.assertEqual(out.reason, "bad_record")
        self.assertEqual([c for c in self.argv() if c[:2] == ["know", "list"]], [])

    def test_tag_and_query_filter(self) -> None:
        """Tags and query filter client-side."""
        self.assertEqual(len(ma.list_records("loop", "L1", tags=["run-a"], session_id="s1")), 1)  # type: ignore[arg-type]
        self.assertEqual(ma.list_records("loop", "L1", tags=["zzz"], session_id="s1"), [])
        self.assertEqual(ma.list_records("loop", "L1", query="nomatch", session_id="s1"), [])

    def test_unparseable_output_degrades(self) -> None:
        """Output that is not the pinned JSON shape degrades instead of guessing."""
        (self.tmp / "list.json").write_text("not json")
        out = ma.list_records("loop", "L1", session_id="s1")
        assert isinstance(out, ma.Degraded)
        self.assertEqual(out.reason, "muninn_error")


class HardeningTests(Base):
    """Read-path fail-closed filters, probe code stability and default-session tracing."""

    def listed(self, entry: dict[str, Any]) -> list[str]:
        """Return the ids a single fake entry yields through list_records."""
        (self.tmp / "list.json").write_text(json.dumps({"entries": [entry]}))
        out = ma.list_records("loop", "L1", session_id="s1")
        assert isinstance(out, list)
        return [r.id or "" for r in out]

    def test_uncited_current_record_not_returned(self) -> None:
        """A record with no cites is never current, even when muninn returns it."""
        base = {"id": "a", "kind": "lesson", "text": "nocite", "sensitivity": "normal"}
        self.assertEqual(self.listed({**base, "cites": []}), [])
        self.assertEqual(self.listed({**base, "cites": [{"ref": "", "quote": ""}]}), [])
        self.assertEqual(self.listed({**base, "cites": [{"ref": "r", "quote": "q"}]}), ["a"])  # negative control

    def test_filters_fail_closed(self) -> None:
        """Missing sensitivity, non-current status and a past valid_until are all dropped."""
        ok = {"id": "b", "kind": "fact", "text": "t", "cites": [{"ref": "r", "quote": "q"}], "sensitivity": "normal"}
        self.assertEqual(self.listed(ok), ["b"])
        self.assertEqual(self.listed({k: v for k, v in ok.items() if k != "sensitivity"}), [])
        self.assertEqual(self.listed({**ok, "status": "superseded"}), [])
        self.assertEqual(self.listed({**ok, "status": "current"}), ["b"])
        self.assertEqual(self.listed({**ok, "valid_until": "2000-01-01"}), [])
        self.assertEqual(self.listed({**ok, "valid_until": 946684800.0}), [])
        self.assertEqual(self.listed({**ok, "valid_until": "2999-01-01"}), ["b"])

    def test_help_nonzero_is_old_ledger(self) -> None:
        """A help that exits nonzero (muninn 0.1.0 exits 2) is an old ledger, not muninn_error."""
        os.environ["FAKE_HELP_RC"] = "2"
        self.assertEqual(ma.probe(), ma.Degraded("muninn_old_ledger"))

    def test_default_session_still_traces(self) -> None:
        """With no session id the degrade still lands a trace row under a fixed fallback id."""
        os.environ["FAKE_MODE"] = "old"
        ma.add(rec(), "")
        self.assertIn("muninn_old_ledger", [x["reason_code"] for x in self.rows(ma.NO_SESSION)])

    def test_runbook_covers_every_reason_code(self) -> None:
        """Each code the adapter emits has a remediation line in the runbook."""
        text = (REPO / "docs/RUNBOOK.md").read_text()
        remediation = text.split("## Memory silently using Markdown", 1)[1].split("- Remediation:", 1)[1]
        for code in ("muninn_absent", "muninn_old_ledger", "muninn_timeout", "muninn_error", "bad_record"):
            self.assertIn(f"`{code}`", remediation, code)
        self.assertIn("unset", text)

    def test_codex_handoff_resolves_paths(self) -> None:
        """The Codex handoff names resolvable paths and where state and session come from."""
        text = (REPO / "packages/codex/skills/handoff/SKILL.md").read_text()
        self.assertIn("$SKILL_DIR/../../scripts/lib/memory_adapter.py", text)
        self.assertIn("$SKILL_DIR/../agentic-loop/scripts/graph.py", text)
        self.assertIn("bootstrap", text)


class RenderTests(Base):
    """The generated Markdown view."""

    def view(self) -> str:
        """Render the fixture records."""
        found = ma.list_records("loop", "L1", session_id="s1")
        assert isinstance(found, list)
        return ma.render(found)

    def reason(self, result: ma.Degraded | None) -> str:
        """Return a degrade reason."""
        assert result is not None
        return result.reason

    def test_render_and_marker_guard(self) -> None:
        """Hand-written files are protected; absent or marker-stamped files are writable."""
        text = self.view()
        self.assertEqual(text.splitlines()[0], ma.MARKER)
        self.assertIn("K1", text)
        target = self.tmp / "MEMORY.md"
        target.write_text("hand written\n")
        self.assertEqual(self.reason(ma.write_view(target, text, "s1")), "handwritten_protected")
        self.assertEqual(target.read_text(), "hand written\n")
        self.assertIsNone(ma.write_view(self.tmp / "new.md", text, "s1"))
        self.assertIsNone(ma.write_view(self.tmp / "new.md", text + "x", "s1"))

    def test_torn_write_keeps_old_file(self) -> None:
        """A failure before os.replace leaves the old file and no temp file."""
        target = self.tmp / "m.md"
        target.write_text(ma.MARKER + "\nold\n")
        with mock.patch("os.replace", side_effect=OSError("boom")):
            self.assertEqual(self.reason(ma.write_view(target, ma.MARKER + "\nnew\n", "s1")), "muninn_error")
        self.assertEqual(target.read_text(), ma.MARKER + "\nold\n")
        self.assertEqual([p.name for p in self.tmp.glob("*.tmp*")], [])

    def test_cli_dry_run_does_not_write(self) -> None:
        """Render without --write only prints."""
        cmd = [sys.executable, ADAPTER, "render", "--memory-md", "--loop", "L1", "--session", "s1"]
        out = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith(ma.MARKER))

    def test_starter_memory_is_handwritten(self) -> None:
        """The shipped starter MEMORY.md carries no marker, so --write refuses it."""
        starter = REPO / "starter-memory/coderails/MEMORY.md"
        self.assertNotEqual(starter.read_text().splitlines()[0], ma.MARKER)


class CounterTests(Base):
    """Counters in scripts/measure_graph_alignment.py."""

    def test_counts_by_reason_deduped_and_measure_wired(self) -> None:
        """Memory rows are counted once per event_id, by reason code; other commands are ignored."""
        os.environ["FAKE_MODE"] = "old"
        ma.add(rec(), "s1")
        ma.add(rec(cite=""), "s1")
        path = self.tmp / "loops" / "s1" / "trace.jsonl"
        path.write_text(path.read_text() * 2 + '{"command": "other/x", "event_id": "z", "reason_code": "no"}\n')
        cmd = [sys.executable, str(REPO / "scripts/measure_graph_alignment.py"), "--root", str(REPO), "--json"]
        env = {**os.environ, "HOME": str(self.tmp), "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp / "loops")}
        out = subprocess.run(cmd, capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        expected = {"rows": 2, "by_reason_code": {"muninn_old_ledger": 1, "uncited_write": 1}}
        self.assertEqual(json.loads(out.stdout)["memory"], expected)

    def test_measure_stays_within_line_limit(self) -> None:
        """The repo 400-line limit holds for the measurement script."""
        self.assertLessEqual(len((REPO / "scripts/measure_graph_alignment.py").read_text().splitlines()), 400)


class ProbeAndParity(Base):
    """CLI probe, Codex mirror and docs."""

    def test_cli_probe_degraded_exit_code(self) -> None:
        """An old ledger exits 3 with the reason on stdout."""
        os.environ["FAKE_MODE"] = "old"
        out = subprocess.run([sys.executable, ADAPTER, "probe", "--session", "s1"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 3)
        self.assertEqual(json.loads(out.stdout)["degraded"], "muninn_old_ledger")

    def test_codex_mirror_byte_equal(self) -> None:
        """The Codex copy is byte-identical."""
        mirror = REPO / "packages/codex/scripts/lib/memory_adapter.py"
        self.assertEqual(Path(ADAPTER).read_bytes(), mirror.read_bytes())

    def test_docs_carry_helper(self) -> None:
        """Teardown and both handoff skills name the helper command."""
        docs = ("skills/agentic-loop/teardown.md", "skills/handoff/SKILL.md", "packages/codex/skills/handoff/SKILL.md")
        for rel in docs:
            self.assertIn("memory_adapter.py", (REPO / rel).read_text(), rel)


if __name__ == "__main__":
    unittest.main()
