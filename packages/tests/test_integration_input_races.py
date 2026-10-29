"""A pre-lock input read cannot authorize changed graph assignments."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT))
import graph_contract  # noqa: E402
import graph_dispatch_inputs  # noqa: E402

from packages.tests.provider_fixture import Provider  # noqa: E402

RACE = """import json, runpy, subprocess, sys
from pathlib import Path
from unittest.mock import patch
plugin, operation, progress, session, assigned, expected = sys.argv[1:]
script = Path(plugin) / 'skills/agentic-loop/scripts/graph.py'
sys.path.insert(0, str(script.parent))
sys.path.insert(0, plugin)
import graph_dispatch_inputs
original = graph_dispatch_inputs.prefetch
def racing(*args, **kwargs):
    preview, snapshot = original(*args, **kwargs)
    result = subprocess.run([
        sys.executable, str(script), 'assign-worktree', progress,
        '--session', session, '--loop-id', 'fixture-loop', '--unit', '1', '--worktree', assigned,
    ], capture_output=True, text=True, check=True, timeout=10)
    Path(expected).write_bytes(Path(progress).read_bytes())
    return preview, snapshot
sys.argv = [str(script), operation, progress]
with patch.object(graph_dispatch_inputs, 'prefetch', side_effect=racing):
    runpy.run_path(str(script), run_name='__main__')
"""


class InputRaceTests(unittest.TestCase):
    """Exercise both the shared transaction check and the actual provider transactions."""

    def test_every_prefetch_checks_owner_revision_and_owned_inputs(self) -> None:
        """Null and non-null snapshots refuse races, while unchanged empty/nonempty contexts remain valid."""
        preview: dict[str, Any] = {
            "session_id": "owner",
            "loop_id": "logical-loop",
            "revision": 1,
            "work_units": {"1": {"status": "pending"}},
            "graph": {"dispatches": {}},
        }
        for rows in ([], [{"text": "Retain an eligible local lesson"}]):
            snapshot = {"lessons": rows, "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
            graph_dispatch_inputs.check_revision(preview, copy.deepcopy(preview), snapshot)
        graph_dispatch_inputs.check_revision(preview, copy.deepcopy(preview), None)
        timestamp_only = {**preview, "updated_at": "later preparation receipt"}
        graph_dispatch_inputs.check_revision(preview, timestamp_only, None)
        for key, value in (("session_id", "other"), ("loop_id", "other"), ("revision", 2)):
            with self.subTest(key=key), self.assertRaises(graph_contract.DispatchDeniedError):
                graph_dispatch_inputs.check_revision(preview, {**preview, key: value}, None)
        assigned = copy.deepcopy(preview)
        assigned["work_units"]["1"].update(worktree="/assigned", manifest=["src/**"])
        with self.assertRaises(graph_contract.DispatchDeniedError):
            graph_dispatch_inputs.check_revision(preview, assigned, None)

    def test_assignment_race_refuses_before_native_or_driver_wave_write(self) -> None:
        """An actual no-revision assignment survives; begin-wave must not write an unstartable wave over it."""
        for name in ("claude", "codex"):
            for operation in ("begin-wave", "begin-driver-wave"):
                with self.subTest(provider=name, operation=operation), tempfile.TemporaryDirectory() as temporary:
                    provider = Provider(Path(temporary), name)
                    state = provider.state()
                    state["work_units"] = {"1": {"status": "pending"}}
                    provider.write(state)
                    if operation == "begin-driver-wave":
                        provider.success("cutover-driver", "--session", provider.session)
                    assigned = provider.home / "assigned"
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
                            "--allow-empty",
                            "-qm",
                            "source",
                        ],
                        check=True,
                    )
                    expected = provider.home / "concurrent-progress.json"
                    runner = provider.home / "race.py"
                    runner.write_text(RACE)
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(runner),
                            str(provider.plugin),
                            operation,
                            str(provider.path),
                            provider.session,
                            str(assigned.resolve()),
                            str(expected),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=20,
                        env=provider.environment,
                        cwd=provider.checkout,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("dispatch_lessons_stale", result.stderr)
                    self.assertEqual(provider.path.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
