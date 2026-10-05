"""Shared sandbox for the memory-store tests: temp MUNINN_HOME, synthetic transcripts, a fake `muninn` on PATH."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from scripts.lib import memory_adapter as ma
from scripts.tests import fake_muninn_store as fs

FAKE = Path(__file__).resolve().parent / "fake_muninn.py"
SESSION = "s1"
PROMPT = "Always run the targeted tests before committing any change to the adapter."
PROPOSAL = "Proposal: record the lesson that targeted tests run before every commit."
LATER = "Never write entries to the live Muninn store from tests, use a temp home."
LINES = [
    {"type": "user", "message": {"role": "user", "content": PROMPT}, "timestamp": "2026-10-05T10:00:00Z"},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": PROPOSAL}]}},
    {"type": "user", "message": {"role": "user", "content": "yes"}},
    {"type": "user", "message": {"role": "user", "content": LATER}},
]


class StoreCase(unittest.TestCase):
    """A temp MUNINN_HOME, synthetic transcripts and a `muninn` wrapper for the fake first on PATH."""

    with_store = False  # True: create the schema-v2 store up front (a real store exists after `muninn ingest`)

    def setUp(self) -> None:
        """Build the sandbox and point the adapter at it with a cleared probe cache."""
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        projects = self.tmp / "projects" / "p"
        projects.mkdir(parents=True)
        (projects / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(x) for x in LINES) + "\n")
        exe = self.tmp / "bin" / "muninn"
        exe.parent.mkdir()
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        self.env = {
            "PATH": f"{exe.parent}{os.pathsep}{os.environ['PATH']}",
            "MUNINN_HOME": str(self.home),
            "MUNINN_ROOTS": json.dumps({"claude-projects": str(self.tmp / "projects")}),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)
        ma.PROBE_CACHE.clear()
        self.addCleanup(ma.PROBE_CACHE.clear)
        if self.with_store:
            fs.create(self.home)

    def muninn(self, *args: str, extra_env: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        """Run the fake CLI; return (rc, stdout JSON)."""
        p = subprocess.run(["muninn", *args], capture_output=True, text=True, env={**os.environ, **(extra_env or {})})
        return p.returncode, json.loads(p.stdout) if p.stdout.strip().startswith("{") else {"raw": p.stdout}

    def record(self, claim: str, **kw: Any) -> ma.Record:  # noqa: ANN401
        """A loop-scoped lesson citing the first transcript prompt."""
        base: dict[str, Any] = dict(
            scope="loop",
            type="lesson",
            claim=claim,
            cite=f"claude:{SESSION}:1.1",
            quote=PROMPT,
            loop_id="L1",
            cite_role="user",
            cite_kind="prompt",  # library callers declare the anchor
        )
        return ma.Record(**{**base, **kw})

    def written(self, result: object) -> ma.Written:
        """Assert an add succeeded and return the Written value."""
        self.assertIsInstance(result, ma.Written, result)
        assert isinstance(result, ma.Written)
        return result

    def listed(self) -> list[ma.Record]:
        """Adapter listing for loop L1; fails the test on a degrade."""
        got = ma.list_records("loop", "L1")
        self.assertNotIsInstance(got, ma.Degraded, got)
        assert not isinstance(got, ma.Degraded)
        return got

    def sql(self, statement: str, *args: Any) -> None:  # noqa: ANN401
        """Run a direct write against the store file (simulates drift / tampering)."""
        conn = sqlite3.connect(str(fs.db_path(self.home)))
        conn.execute(statement, args)
        conn.commit()
        conn.close()
