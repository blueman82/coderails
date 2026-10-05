"""Contract test: the same scenario table runs against the REAL `muninn` and the sqlite fake, and they must agree.

Real muninn runs on a temp MUNINN_HOME / MUNINN_ROOTS / HOME with synthetic transcripts, so the live store is never
touched (a test also stats the live store before and after). Skipped, with a message, only when `muninn` is not on PATH
or lacks the Part A flags. A deliberately stale fake (wrong refusal code) must fail parity.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.tests.fake_muninn_case import LATER, LINES, PROMPT, PROPOSAL, SESSION  # noqa: E402

FAKE = REPO / "scripts/tests/fake_muninn.py"
PART_A = ("--scope-loop", "--confidence", "--valid-until", "--sensitivity", "--contradicts", "--tag", "lesson")
LIVE_HOME = Path.home() / ".local/share/muninn"
STALE = (
    "import sys\n"
    f"sys.path.insert(0, {str(REPO)!r})\n"
    "from scripts.tests import fake_muninn, fake_muninn_store as fs\n"
    "orig = fake_muninn.require_proposals\n"
    "def stale(events, cites):\n"
    "    try:\n"
    "        orig(events, cites)\n"
    "    except fs.RefusedError:\n"
    "        raise fs.RefusedError('approval_missing')  # the real code is approval_needs_reply\n"
    "fake_muninn.require_proposals = stale\n"
    "raise SystemExit(fake_muninn.main(sys.argv[1:]))\n"
)
EXPECTED_REFUSALS = {
    "uncited": "uncited",
    "not_found": "not_found",
    "quote_length": "quote_length",
    "quote_not_found": "quote_not_found",
    "approval": "approval_needs_reply",
    "preference": "preference_needs_user",
    "bad_supersedes": "bad_supersedes",
    "bad_valid_until": "bad_valid_until",
}


def real_muninn() -> str | None:
    """Path of the real muninn when it advertises the Part A flags, else None."""
    exe = shutil.which("muninn")
    if exe is None:
        return None
    p = subprocess.run([exe, "know", "add", "--help"], capture_output=True, text=True)
    text = p.stdout + p.stderr  # the live binary prints help on stderr with rc 2
    return exe if all(f in text for f in PART_A) else None


class Sandbox:
    """A temp MUNINN_HOME / MUNINN_ROOTS / HOME with synthetic transcripts, driven through one muninn executable."""

    def __init__(self, exe: str, root: Path) -> None:
        """Create the directories and the transcript."""
        self.exe, self.root = exe, root
        projects = root / "projects" / "p"
        projects.mkdir(parents=True)
        (projects / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(x) for x in LINES) + "\n")
        (root / "home").mkdir()
        (root / "h").mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root / "h"),
            "MUNINN_HOME": str(root / "home"),
            "MUNINN_ROOTS": json.dumps({"claude-projects": str(root / "projects")}),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def run(self, *args: str) -> tuple[int, dict[str, Any]]:
        """Run muninn; return (rc, stdout JSON or {})."""
        p = subprocess.run([self.exe, *args], capture_output=True, text=True, env=self.env, timeout=60)
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, {}

    def add(
        self, kind: str, text: str, *cites: tuple[str, str], extra: tuple[str, ...] = ()
    ) -> tuple[int, dict[str, Any]]:
        """`know add` for loop L1 with ordered cite/quote pairs."""
        flags = [x for ref, quote in cites for x in ("--cite", ref, "--quote", quote)]
        return self.run("know", "add", "--kind", kind, "--text", text, *flags, "--scope-loop", "L1", *extra)


def outcome(rc: int, out: dict[str, Any]) -> dict[str, Any]:
    """Normalise one `know add` answer: refusal code, or the entry's shape (never ts/actor/date)."""
    if "entry" not in out:
        return {"rc": rc, "error": out.get("error")}
    e = out["entry"]
    return {
        "rc": rc,
        "keys": sorted(e),
        "cite_keys": sorted(e["cites"][0]),
        "kid": bool(re.fullmatch(r"K\d+", e["id"])),
        "id": e["id"],
        "status": e["status"],
        "scope": e["scope"],
        "cites": len(e["cites"]),
        "expired": e["expired"],
        "has_valid_until": e["valid_until"] is not None,
    }


def scenarios(sb: Sandbox) -> dict[str, Any]:
    """The scenario table: refusals, K-id format, approved reply, supersession and expiry."""
    ok = (f"claude:{SESSION}:1.1", PROMPT)
    future = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400 * 400))
    got: dict[str, Any] = {}
    rows: dict[str, Callable[[], tuple[int, dict[str, Any]]]] = {
        "uncited": lambda: sb.add("lesson", "x"),
        "not_found": lambda: sb.add("lesson", "x", (f"claude:{SESSION}:99.1", PROMPT)),
        "quote_length": lambda: sb.add("lesson", "x", (ok[0], "Always run")),
        "quote_not_found": lambda: sb.add("lesson", "x", (ok[0], "this sentence is not in the prompt")),
        "approval": lambda: sb.add("decision", "x", (f"claude:{SESSION}:3.1", "yes")),
        "preference": lambda: sb.add("preference", "x", (f"claude:{SESSION}:2.1", "record the lesson that targeted")),
        "bad_supersedes": lambda: sb.add("lesson", "x", ok, extra=("--supersedes", "K77")),
        "bad_valid_until": lambda: sb.add("lesson", "x", ok, extra=("--valid-until", "2020-01-01")),
    }
    for name, call in rows.items():
        got[name] = outcome(*call())
    got["k1"] = outcome(*sb.add("lesson", "first wording", ok, extra=("--tag", "run-a")))
    got["approved_reply"] = outcome(
        *sb.add("decision", "approved", (f"claude:{SESSION}:2.1", PROPOSAL), (f"claude:{SESSION}:3.1", "yes"))
    )
    got["k3_supersedes_k1"] = outcome(*sb.add("lesson", "second wording", ok, extra=("--supersedes", "K1")))
    got["fresh"] = outcome(
        *sb.add("lesson", "dated", (f"claude:{SESSION}:4.1", LATER), extra=("--valid-until", future))
    )
    show = sb.run("know", "show", "K1")[1].get("entry", {})
    got["show_k1"] = {"status": show.get("status"), "superseded_by": show.get("superseded_by")}
    for status in ("current", "superseded", "expired", "all"):
        listed = sb.run("know", "list", "--scope-loop", "L1", "--status", status)[1]
        got[f"list_{status}"] = [e["id"] for e in listed["entries"]]
    return got


class Contract(unittest.TestCase):
    """Real muninn vs the fake over one scenario table."""

    tmp: Path
    exe: str
    wrapper: str
    real_results: dict[str, Any]
    fake_results: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        """Locate real muninn (skip when absent/old) and build the fake wrapper; both get their own temp tree."""
        exe = real_muninn()
        if exe is None:
            raise unittest.SkipTest("muninn is not on PATH or lacks the Part A flags: contract test skipped")
        cls.tmp = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.exe = exe
        cls.wrapper = cls.make_wrapper("fake", f'exec "{sys.executable}" "{FAKE}" "$@"')
        cls.real_results = cls.table(exe, "real")
        cls.fake_results = cls.table(cls.wrapper, "fake")

    @classmethod
    def make_wrapper(cls, name: str, body: str) -> str:
        """A `muninn` shell wrapper script."""
        path = cls.tmp / f"{name}-bin" / "muninn"
        path.parent.mkdir()
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    @classmethod
    def table(cls, exe: str, name: str) -> dict[str, Any]:
        """Run the scenario table on a fresh sandbox (real muninn must ingest the transcripts first)."""
        sb = Sandbox(exe, cls.tmp / name)
        if exe == cls.exe:
            rc, _ = sb.run("ingest")
            assert rc == 0, "real muninn could not ingest the synthetic transcripts"
        return scenarios(sb)

    def test_real_refusal_codes_and_shapes(self) -> None:
        """The real binary gives the documented refusal codes (rc 2), K-ids, supersession and expiry."""
        for name, code in EXPECTED_REFUSALS.items():
            self.assertEqual(self.real_results[name], {"rc": 2, "error": code}, name)
        k1 = self.real_results["k1"]
        self.assertEqual(
            (k1["rc"], k1["kid"], k1["id"], k1["status"], k1["scope"]), (0, True, "K1", "current", "loop:L1")
        )
        self.assertEqual(self.real_results["approved_reply"]["cites"], 2)
        self.assertEqual(self.real_results["show_k1"], {"status": "superseded", "superseded_by": "K3"})
        self.assertEqual(self.real_results["list_current"], ["K4", "K3", "K2"])
        self.assertEqual(self.real_results["list_superseded"], ["K1"])
        self.assertEqual(self.real_results["list_expired"], [])
        fresh = self.real_results["fresh"]
        self.assertEqual((fresh["has_valid_until"], fresh["expired"]), (True, False))

    def test_fake_agrees_with_real(self) -> None:
        """Refusal codes, JSON keys, K-id format, supersession and expiry are identical in the fake."""
        self.assertEqual(self.fake_results, self.real_results)

    def test_control_stale_fake_fails_parity(self) -> None:
        """Negative control 5: a fake with a wrong refusal code is detected by the same comparison."""
        script = self.tmp / "stale_fake.py"
        script.write_text(STALE)
        stale = self.make_wrapper("stale", f'exec "{sys.executable}" "{script}" "$@"')
        results = self.table(stale, "stale")
        self.assertNotEqual(results, self.real_results)
        self.assertEqual(results["approval"]["error"], "approval_missing")

    def test_adapter_works_against_the_real_binary(self) -> None:
        """Probe (real help shape and schema), add -> K-id, list round trip, refusal mapping, all on the temp store."""
        from unittest import mock

        from scripts.lib import memory_adapter as ma

        sb = Sandbox(self.exe, self.tmp / "adapter")
        self.assertEqual(sb.run("ingest")[0], 0)
        env = {**sb.env, "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp / "loops")}
        with mock.patch.dict(os.environ, env):
            ma.PROBE_CACHE.clear()
            self.addCleanup(ma.PROBE_CACHE.clear)
            self.assertIsNone(ma.probe())
            rec = ma.Record("loop", "lesson", "adapter on real", f"claude:{SESSION}:1.1", PROMPT, loop_id="L1")
            self.assertEqual(ma.add(rec, "s1"), ma.Written("K1"))
            got = ma.list_records("loop", "L1")
            assert isinstance(got, list)
            self.assertEqual([(r.id, r.cite) for r in got], [("K1", f"claude:{SESSION}:1.1")])
            short = ma.Record("loop", "decision", "x", f"claude:{SESSION}:3.1", "yes", loop_id="L1")
            self.assertEqual(ma.add(short, "s1"), ma.Degraded("refused_approval_needs_reply"))
            self.assertEqual([r.id for r in ma.list_records("loop", "L1", query="adapter")], ["K1"])  # type: ignore[union-attr]

    def test_sandbox_never_points_at_the_live_store(self) -> None:
        """Every path handed to muninn is under the temp tree, never ~/.local/share/muninn or the real HOME."""
        sb = Sandbox(self.exe, self.tmp / "iso")
        for key in ("HOME", "MUNINN_HOME"):
            path = Path(sb.env[key]).resolve()
            self.assertTrue(path.is_relative_to(self.tmp.resolve()), key)
            self.assertFalse(path.is_relative_to(LIVE_HOME), key)
        self.assertNotEqual(sb.env["HOME"], str(Path.home()))


if __name__ == "__main__":
    unittest.main()
