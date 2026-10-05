"""lessons.py: the promotion-routine selection and the verbatim dispatch contract list, against the fake muninn."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.tests.fake_muninn_case import PROMPT, SESSION, StoreCase  # noqa: E402

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
            args = ["record", "--failure-mode", mode, "--lesson", f"Lesson for {mode}.", "--loop", f"{mode}{n}"]
            args += ["--scope", scope, "--quote", PROMPT, "--evidence-session", sid]
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
            (self.dir / f"sess{n}").mkdir()
            (self.dir / f"sess{n}" / "retro.json").write_text("{}")
        self.assertEqual(self.call(LESSONS, "predicate")[1]["graduation"]["retro_count"], 10)
