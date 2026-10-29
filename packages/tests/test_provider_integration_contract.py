"""Native provider tests for assigned source and current lesson dispatch contracts."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
import graph_contract

from packages.tests.provider_fixture import Provider


class IntegrationContractTests(unittest.TestCase):
    """Run source and lesson checks through both real provider CLIs and dispatch hooks."""

    def setUp(self) -> None:
        """Create a separate temporary provider home for each case."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.count = 0

    def fresh(self, name: str) -> Provider:
        """Return a new native provider fixture."""
        self.count += 1
        base = self.root / str(self.count)
        base.mkdir()
        return Provider(base, name)

    def begin_wave(self, provider: Provider, operation: str = "begin-wave") -> subprocess.CompletedProcess[str]:
        """Bound the held-lock negative control even when the prefetch guard is absent."""
        return subprocess.run(
            [
                sys.executable,
                str(provider.plugin / "skills/agentic-loop/scripts/graph.py"),
                operation,
                str(provider.path),
            ],
            capture_output=True,
            text=True,
            env=provider.environment,
            cwd=provider.checkout,
            timeout=10,
            check=False,
        )

    def reason(self, provider: Provider) -> str:
        """Read the last refusal reason from the native trace."""
        rows = provider.path.with_name("recovery-trace.jsonl").read_text().splitlines()
        return str(json.loads(rows[-1])["reason_code"])

    def verdict(self, provider: Provider, request: dict[str, Any]) -> bool:
        """Return whether the native dispatch hook denied a worker request."""
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return bool(result.stdout) and json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def refuse(self, provider: Provider, request: dict[str, Any], code: str) -> None:
        """Check refusal code and byte preservation of progress."""
        before = provider.path.read_bytes()
        self.assertTrue(self.verdict(provider, request), (provider.name, code))
        self.assertEqual(provider.path.read_bytes(), before)
        self.assertEqual(self.reason(provider), code)

    def test_assigned_source_cannot_change_before_worker_launch(self) -> None:
        """Both native guards reject a changed registered checkout or manifest."""
        for name in ("claude", "codex"):
            for defect in ("valid", "manifest", "worktree", "missing", "head", "dirty"):
                with self.subTest(provider=name, defect=defect):
                    provider = self.fresh(name)
                    state = provider.state()
                    worktree = str((provider.home / "assigned").resolve())
                    Path(worktree).mkdir()
                    subprocess.run(["git", "init", "-q", worktree], check=True)
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            worktree,
                            "-c",
                            "user.name=Fixture",
                            "-c",
                            "user.email=fixture@test",
                            "commit",
                            "-q",
                            "--allow-empty",
                            "-m",
                            "base",
                        ],
                        check=True,
                    )
                    unit: dict[str, Any] = {"worktree": worktree, "manifest": ["docs/**"]}
                    unit.update(graph_contract.source_binding(worktree, unit["manifest"]))
                    state["work_units"] = {"1": unit}
                    provider.write(state)
                    provider.success("begin-wave")
                    request = provider.request()
                    current = provider.read()
                    if defect == "valid":
                        self.assertFalse(self.verdict(provider, request))
                        continue
                    assigned = current["work_units"]["1"]
                    if defect == "manifest":
                        assigned["manifest"] = ["src/**"]
                    elif defect == "worktree":
                        assigned["worktree"] = str(provider.path.parent)
                    elif defect == "missing":
                        del assigned["worktree"]
                    elif defect == "dirty":
                        (Path(worktree) / "changed.txt").write_text("changed")
                    else:
                        (Path(worktree) / "changed.txt").write_text("changed")
                        subprocess.run(["git", "-C", worktree, "add", "changed.txt"], check=True)
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                worktree,
                                "-c",
                                "user.name=Fixture",
                                "-c",
                                "user.email=fixture@test",
                                "commit",
                                "-q",
                                "-m",
                                "changed",
                            ],
                            check=True,
                        )
                    provider.write(current)
                    self.refuse(provider, request, "dispatch_source_mismatch")

    def test_registered_unit_binds_current_lessons_and_refuses_bad_ledger(self) -> None:
        """Both native begin-wave commands use the real lesson reader and keep progress unchanged on refusal."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                state = provider.state()
                state["work_units"] = {"1": {"manifest": ["src/**"]}}
                provider.write(state)
                provider.success("begin-wave")
                record = next(iter(provider.read()["graph"]["dispatches"].values()))
                reader = provider.plugin / "scripts/lib/lessons.py"
                done = subprocess.run(
                    [
                        sys.executable,
                        str(reader),
                        "--dir",
                        str(provider.path.parent.parent),
                        "--session",
                        provider.session,
                        "query",
                        "--format",
                        "contract",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=provider.environment,
                    cwd=provider.checkout,
                )
                lesson_contract = json.loads(done.stdout)
                self.assertEqual(record["contract"]["lessons"], lesson_contract["lessons"])
                self.assertEqual(record["contract"]["lessons_sha256"], lesson_contract["sha256"])
                bad = self.fresh(name)
                failed = bad.state()
                failed["work_units"] = {"1": {"manifest": ["src/**"]}}
                bad.write(failed)
                (bad.path.parent.parent / "orders.json").write_text("{bad", encoding="utf-8")
                before = bad.path.read_bytes()
                result = self.begin_wave(bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dispatch_lessons_unavailable", result.stderr)
                self.assertEqual(bad.path.read_bytes(), before)

    def test_lesson_query_runs_before_progress_lock(self) -> None:
        """A held provider lock makes the lesson reader refuse before begin-wave can wait for that lock."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                state = provider.state()
                state["work_units"] = {"1": {"manifest": ["src/**"]}}
                provider.write(state)
                before = provider.path.read_bytes()
                lock = Path(f"{provider.path}.lock")
                if name == "claude":
                    lock.mkdir()
                    result = self.begin_wave(provider)
                else:
                    with lock.open("a+", encoding="utf-8") as stream:
                        fcntl.flock(stream, fcntl.LOCK_EX)
                        result = self.begin_wave(provider)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dispatch_lessons_unavailable", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_driver_wave_binds_the_same_current_lesson_contract(self) -> None:
        """The retained driver adapters consume current lessons through both public CLIs."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                state = provider.state()
                state["work_units"] = {"1": {"manifest": ["src/**"]}}
                provider.write(state)
                provider.success("cutover-driver", "--session", provider.session)
                provider.success("begin-driver-wave")
                record = next(iter(provider.read()["graph"]["dispatches"].values()))
                self.assertIsNotNone(record["contract"].get("lessons_sha256"))

    def test_driver_authorization_checks_assigned_source_before_consuming_slot(self) -> None:
        """Both public driver authorizers refuse a changed source assignment and keep progress unchanged."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                assigned = provider.home / "assigned"
                assigned.mkdir()
                subprocess.run(["git", "init", "-q", str(assigned)], check=True)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(assigned),
                        "-c",
                        "user.name=Fixture",
                        "-c",
                        "user.email=fixture@test",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "-m",
                        "base",
                    ],
                    check=True,
                )
                unit: dict[str, Any] = {"worktree": str(assigned.resolve()), "manifest": ["docs/**"]}
                unit.update(graph_contract.source_binding(str(assigned), unit["manifest"]))
                state = provider.state()
                state["work_units"] = {"1": unit}
                provider.write(state)
                provider.success("cutover-driver", "--session", provider.session)
                wave = provider.success("begin-driver-wave")
                issued = wave["dispatches"][0]
                identifier = issued["dispatch_id"]
                prompt = provider.path.parent / "driver-evidence" / identifier / "prompt.txt"
                prompt.parent.mkdir(parents=True)
                prompt.write_text(issued["prompt_prefix"] + "\n" + issued["prompt_sections"])
                changed = provider.read()
                changed["work_units"]["1"]["manifest"] = ["src/**"]
                provider.write(changed)
                before = provider.path.read_bytes()
                result = provider.call(
                    "authorize-driver",
                    "--session",
                    provider.session,
                    "--dispatch-id",
                    identifier,
                    "--role",
                    "loop-worker",
                    "--driver-run-id",
                    "fixture-attempt",
                    "--prompt-file",
                    str(prompt),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dispatch_source_mismatch", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_late_worktree_assignment_binds_source_before_dispatch(self) -> None:
        """The retained assignment CLI stores the source digest consumed by begin-wave."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                assigned = provider.home / "assigned"
                assigned.mkdir()
                subprocess.run(["git", "init", "-q", str(assigned)], check=True)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(assigned),
                        "-c",
                        "user.name=Fixture",
                        "-c",
                        "user.email=fixture@test",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "-m",
                        "base",
                    ],
                    check=True,
                )
                state = provider.state()
                state["work_units"] = {"1": {"status": "pending", "manifest": ["docs/**"]}}
                provider.write(state)
                provider.success(
                    "assign-worktree",
                    "--session",
                    provider.session,
                    "--loop-id",
                    "fixture-loop",
                    "--unit",
                    "1",
                    "--worktree",
                    str(assigned.resolve()),
                )
                provider.success("begin-wave")

    def test_erased_lesson_digest_cannot_disable_current_lesson_check(self) -> None:
        """A changed issued contract cannot turn required current lessons into an opt-out."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                state = provider.state()
                state["work_units"] = {"1": {"manifest": ["docs/**"]}}
                provider.write(state)
                provider.success("begin-wave")
                state = provider.read()
                record = next(iter(state["graph"]["dispatches"].values()))
                record["contract"]["lessons_sha256"] = None
                record["prompt_sections_sha256"] = graph_contract.sections_sha256(record["contract"])
                provider.write(state)
                self.refuse(provider, provider.request(), "dispatch_lessons_stale")

    def test_old_muninn_refuses_before_worker_dispatch(self) -> None:
        """An old Muninn CLI cannot supply an empty-looking lesson contract."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                config = provider.home / ".coderails/workflow.config.yaml"
                config.write_text("memory:\n  backend: muninn\n", encoding="utf-8")
                binary = provider.home / "bin/muninn"
                binary.parent.mkdir()
                binary.write_text("#!/bin/sh\nprintf 'legacy help\\n'\n", encoding="utf-8")
                binary.chmod(0o755)
                provider.environment["PATH"] = str(binary.parent) + os.pathsep + provider.environment["PATH"]
                state = provider.state()
                state["work_units"] = {"1": {"manifest": ["src/**"]}}
                provider.write(state)
                before = provider.path.read_bytes()
                result = self.begin_wave(provider)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("muninn_old_ledger", result.stderr)
                self.assertIn("dispatch_lessons_unavailable", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
