"""A later driver wave accepts a verified descendant of a sealed PR commit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))

import graph_driver_controller  # noqa: E402

from hooks.scripts.tests.lib import claude_transcript_fixture as claude  # noqa: E402

SCRIPT = ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py"


class Case:
    """One disposable graph operated through the public Codex CLI."""

    def __init__(self, base: Path) -> None:
        """Write a pre-conversion graph with one implementation unit."""
        self.path = base / "codex/S/progress.json"
        self.path.parent.mkdir(parents=True)
        state = claude.state(1)
        state.update(session_id="S", loop_id="L")
        state.pop("state_minor")
        for key in ("dispatches", "contract_from_revision"):
            state["graph"].pop(key)
        self.write(state)

    def write(self, state: dict[str, Any]) -> None:
        """Save the disposable state."""
        self.path.write_text(json.dumps(state))

    def read(self) -> dict[str, Any]:
        """Read the disposable state."""
        return cast(dict[str, Any], json.loads(self.path.read_text()))

    def graph(self, command: str, *flags: str) -> subprocess.CompletedProcess[str]:
        """Call one public Codex graph command."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), command, str(self.path), "--session", "S", *flags],
            capture_output=True,
            text=True,
            check=False,
        )


def frozen_evals() -> dict[str, Any]:
    """Give the disposable driver an owned, frozen loop suite."""
    return {
        "scope": "loop",
        "task_ref": "L",
        "session_id": "S",
        "loop_id": "L",
        "verification_level": 1,
        "verification_justification": "test suite",
        "frozen_sha": "fixture",
        "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
        "result": None,
        "grading": None,
    }


class DriverDescendantTests(unittest.TestCase):
    """Use real retained checkouts and a disposable pull ref."""

    @staticmethod
    def checkout(path: Path) -> None:
        """Create one clean worker checkout."""
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=t@example.test",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "sealed",
            ],
            check=True,
        )

    @staticmethod
    def drive(
        case: Case, checkout: Path, command: graph_driver_controller.Command, result: graph_driver_controller.Result
    ) -> dict[str, Any]:
        """Observe one full worker wave through the public driver path."""
        report: dict[str, Any] = {"status": "pending"}
        for _ in range(20):
            report = graph_driver_controller.drive_once(case.path, "S", SCRIPT, checkout, "codex", command, result)
            if report["status"] == "recorded":
                break
        return report

    def test_next_drive_accepts_descendant_and_refuses_unrelated_head(self) -> None:
        """A retained U3 commit may precede the live PR only along its verified ancestry."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = Case(base)
            state = case.read()
            state["work_units"]["1"] = {"status": "pending", "scope": "Build first unit"}
            case.write(state)
            self.assertEqual(case.graph("convert").returncode, 0)
            added = case.graph(
                "add-unit", "--loop-id", "L", "--unit", "2", "--depends-on", "1", "--scope", "Build second unit"
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            old, fresh = base / "old", base / "fresh"
            for checkout in (old, fresh):
                self.checkout(checkout)
            gh = base / "gh-bin" / "gh"
            gh.parent.mkdir()
            gh.write_text(
                "#!/usr/bin/env python3\nimport json, os, subprocess\n"
                "old = os.environ.get('OLD_CHECKOUT', '')\n"
                "moved = os.environ.get('MOVED_PR_HEAD')\n"
                "head = moved if os.path.realpath(os.getcwd()) == os.path.realpath(old) else None\n"
                "head = head or subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()\n"
                "print(json.dumps({'number': 42, 'state': 'OPEN', 'headRefOid': head}))\n"
            )
            gh.chmod(0o755)

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "print('worker')"], None, prompt

            def result(output: Path, _code: int) -> dict[str, Any]:
                parsed: dict[str, Any] = {
                    "outcome": "done",
                    "evidence": "disposable worker",
                    "final_report": {
                        "claims": [{"text": "Done", "label": "verified", "source": "test"}],
                        "did_not_verify": [],
                    },
                }
                (output.parent / "final.json").write_text(json.dumps(parsed))
                return parsed

            with patch.dict(os.environ, PATH=f"{gh.parent}:{os.environ['PATH']}", OLD_CHECKOUT=str(old)):
                first = self.drive(case, old, command, result)
                self.assertEqual(first["status"], "recorded")
                sealed = subprocess.check_output(["git", "-C", str(old), "rev-parse", "HEAD"], text=True).strip()
                remote = base / "remote.git"
                subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
                subprocess.run(["git", "-C", str(old), "remote", "add", "origin", str(remote)], check=True)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(old),
                        "-c",
                        "user.name=Test",
                        "-c",
                        "user.email=t@example.test",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "-m",
                        "descendant",
                    ],
                    check=True,
                )
                descendant = subprocess.check_output(["git", "-C", str(old), "rev-parse", "HEAD"], text=True).strip()
                subprocess.run(["git", "-C", str(old), "push", "-q", "origin", "HEAD:refs/pull/42/head"], check=True)
                subprocess.run(["git", "-C", str(old), "checkout", "-q", "--detach", sealed], check=True)
                orphan = subprocess.check_output(
                    ["git", "-C", str(old), "commit-tree", "4b825dc642cb6eb9a060e54bf8d69288fbee4904"],
                    input="unrelated\n",
                    text=True,
                    env={
                        **os.environ,
                        "GIT_AUTHOR_NAME": "Test",
                        "GIT_AUTHOR_EMAIL": "t@example.test",
                        "GIT_COMMITTER_NAME": "Test",
                        "GIT_COMMITTER_EMAIL": "t@example.test",
                    },
                ).strip()
                subprocess.run(
                    ["git", "-C", str(old), "push", "-q", "origin", f"{orphan}:refs/heads/unrelated"], check=True
                )
                subprocess.run(["git", "-C", str(remote), "update-ref", "refs/pull/42/head", orphan], check=True)
                with patch.dict(os.environ, MOVED_PR_HEAD=orphan), self.assertRaisesRegex(ValueError, "publication"):
                    self.drive(case, fresh, command, result)
                subprocess.run(["git", "-C", str(remote), "update-ref", "refs/pull/42/head", descendant], check=True)
                with patch.dict(os.environ, MOVED_PR_HEAD=descendant):
                    second = self.drive(case, fresh, command, result)
                    self.assertEqual(second["status"], "recorded")
                    self.assertEqual(second["nodes"], ["U3[2]"])


if __name__ == "__main__":
    unittest.main()
