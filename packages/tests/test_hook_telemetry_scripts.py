"""Hooks stay runnable as plain scripts and block (not allow) when the host is exhausted."""

from __future__ import annotations

import errno
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts import hook_common as common  # noqa: E402
from hooks.scripts.lib import hook_telemetry as tel  # noqa: E402

CLAUDE_STOP = [
    "check_confidence_labels",
    "check_verify_loop",
    "loop_state_guard",
    "loop_stall_guard",
    "unregistered_loop_guard",
    "offload_push_guard",
]
CODEX_STOP = ["graph_completion_guard", "check_confidence_labels"]


def rows(directory: str) -> list[dict[str, Any]]:
    """Read the telemetry rows written under a directory."""
    path = Path(directory) / "hook_telemetry.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class ScriptModeTests(unittest.TestCase):
    """Hooks and helper CLIs must still work as plain scripts, with or without the telemetry lib."""

    def test_agentic_loop_path_cli_runs_as_a_script(self) -> None:
        """Test the documented CLI (commands/prep.md) exits 0 when run as a file."""
        script = ROOT / "hooks/scripts/lib/agentic_loop_path.py"
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip().endswith("progress.json"))

    def test_hooks_exit_zero_when_telemetry_is_unimportable(self) -> None:
        """Test real hook processes survive the telemetry lib being unimportable."""
        runner = (
            "import runpy,sys;"
            "sys.modules['hooks.scripts.lib.hook_telemetry']=None;sys.modules['lib.hook_telemetry']=None;"
            "runpy.run_path(sys.argv[1], run_name='__main__')"
        )
        claude = (*CLAUDE_STOP, "inject_context", "destructive_bash_gate")
        scripts = [
            *(ROOT / "hooks/scripts" / f"{name}.py" for name in claude),
            *(ROOT / "packages/codex/hooks/scripts" / f"{name}.py" for name in CODEX_STOP),
        ]
        for script in scripts:
            with self.subTest(script.name), tempfile.TemporaryDirectory() as tmp:
                proc = subprocess.run(
                    [sys.executable, "-c", runner, str(script)],
                    input='{"hook_event_name":"Stop","session_id":"s"}',
                    text=True,
                    capture_output=True,
                    cwd=script.parent,
                    env={**os.environ, "HOME": tmp, "PLUGIN_DATA": tmp, "CLAUDE_DISCIPLINE_LOG": f"{tmp}/d.log"},
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_codex_graph_output_records_native_signal_and_raises_on_resource(self) -> None:
        """Test the Codex graph wrapper tags a signal-killed child and keeps EMFILE distinct."""
        scripts = ROOT / "packages/codex/hooks/scripts"
        code = f"""
import errno, subprocess, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, {str(scripts)!r})
import hook_common as h
killed = subprocess.CompletedProcess([], -6, stdout="", stderr="")
with patch.object(h.subprocess, "run", return_value=killed):
    assert h.graph_output(Path("g"), "inspect") is None
with patch.object(h.subprocess, "run", side_effect=OSError(errno.EMFILE, "x")):
    try:
        h.graph_output(Path("g"), "inspect")
    except h.HostResourceError:
        pass
    else:
        raise SystemExit("no raise")
"""
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": tmp}
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            (row,) = rows(tmp)
            self.assertEqual((row["hook"], row["cause"], row["signal"]), ("graph_output", "native_signal", "SIGABRT"))

    def test_fd_count_is_bounded_across_100_real_stop_hook_processes(self) -> None:
        """Test 100 real Stop-hook processes leave this process and each hook's own fd count bounded."""
        script = ROOT / "hooks/scripts/check_confidence_labels.py"
        with tempfile.TemporaryDirectory() as tmp:
            log = f"{tmp}/d.log"
            env = {**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": tmp, "CLAUDE_DISCIPLINE_LOG": log, "HOME": tmp}
            before = tel.open_fds() or 0
            for _ in range(100):
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    input='{"hook_event_name":"Stop","session_id":"s"}',
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
            got = rows(tmp)
            self.assertEqual(len(got), 100)
            counts = [r["open_fds"] for r in got if r["open_fds"] is not None]
            self.assertLessEqual(max(counts) - min(counts), 1)
            self.assertLessEqual(tel.open_fds() or 0, before + 1)


class GateFailClosedTests(unittest.TestCase):
    """Blocking PreToolUse gates deny, rather than allow, when the host cannot deliver the payload."""

    def test_each_claude_gate_denies_on_host_exhaustion(self) -> None:
        """Test destructive, PR-workflow, no-edit and action-authority gates emit the resource denial."""
        for name in ("destructive_bash_gate", "enforce_pr_workflow", "no_edit_on_main", "action_authority_gate"):
            with self.subTest(name):
                module: Any = importlib.import_module(f"hooks.scripts.{name}")
                buffer = io.StringIO()
                exhausted = common.HostResourceError(errno.EMFILE, "x")
                with patch.object(module, "read_payload", side_effect=exhausted), redirect_stdout(buffer):
                    self.assertEqual(module.main(), 0)
                decision = json.loads(buffer.getvalue())["hookSpecificOutput"]
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertEqual(decision["permissionDecisionReason"], common.RESOURCE_MESSAGE)


if __name__ == "__main__":
    unittest.main()
