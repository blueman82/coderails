"""Review-hardening tests for hook telemetry: fail-open default, strict gates, deny cause, parity."""

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
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import hook_telemetry as tel  # noqa: E402

common: Any = importlib.import_module("hooks.scripts.hook_common")

default: Callable[[], Any] = common.read_payload
strict: Callable[[], Any] = common.read_payload_strict
STRICT_GATES = ("action_authority_gate", "destructive_bash_gate", "enforce_pr_workflow", "no_edit_on_main")
FAIL_OPEN_CALLERS = (
    "agent_only_gate",
    "check_confidence_labels",
    "check_verify_loop",
    "comment_citation_gate",
    "crack_on_gate",
    "loop_stall_guard",
    "loop_state_guard",
    "offload_push_guard",
    "quality_feedback",
    "remember_inject_cap_guard",
    "reviewer_bash_allowlist",
    "test_gate",
    "unregistered_loop_guard",
    "verification_volume_ceiling",
    "voice_announce",
    "wiki_taxonomy_gate",
)


def denied(code: int) -> int:
    """Emit a deny decision, then return code."""
    common.deny("no")
    return code


def rows(directory: str) -> list[dict[str, Any]]:
    """Read telemetry rows."""
    path = Path(directory) / "hook_telemetry.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class ReadPayloadTests(unittest.TestCase):
    """read_payload fails open; read_payload_strict is the only raiser."""

    def test_default_read_fails_open_and_logs_on_every_resource_errno(self) -> None:
        """Test every resource errno returns {} and logs for the default reader."""
        for number in sorted(common.RESOURCE_ERRNOS):
            with self.subTest(errno.errorcode[number]), patch("sys.stdin") as stdin, patch.object(common, "log") as log:
                stdin.fileno.side_effect = OSError(number, "x")
                self.assertEqual(default(), {})
            self.assertIn("resource_exhausted", log.call_args[0][0])

    def test_strict_read_raises_on_every_resource_errno(self) -> None:
        """Test the strict reader raises HostResourceError with the generic message."""
        for number in sorted(common.RESOURCE_ERRNOS):
            with self.subTest(errno.errorcode[number]), patch("sys.stdin") as stdin, patch.object(common, "log"):
                stdin.fileno.side_effect = OSError(number, "x")
                with self.assertRaises(common.HostResourceError) as caught:
                    strict()
            self.assertNotIn("progress.json", str(caught.exception))

    def test_strict_read_still_fails_open_on_non_resource_errors(self) -> None:
        """Test EBADF and bad JSON are {} for the strict reader too."""
        with patch("sys.stdin") as stdin:
            stdin.fileno.side_effect = OSError(errno.EBADF, "bad")
            self.assertEqual(strict(), {})

    def test_message_is_generic_for_non_graph_gates(self) -> None:
        """Test the Claude resource message does not tell a gate to leave progress.json alone."""
        self.assertNotIn("progress.json", common.RESOURCE_MESSAGE)

    def test_only_deny_gates_use_the_strict_reader(self) -> None:
        """Test strict gates import read_payload_strict and every other caller keeps read_payload."""
        for name in STRICT_GATES:
            text = (ROOT / "hooks/scripts" / f"{name}.py").read_text()
            self.assertIn("read_payload_strict", text, name)
        for name in FAIL_OPEN_CALLERS:
            text = (ROOT / "hooks/scripts" / f"{name}.py").read_text()
            self.assertNotIn("read_payload_strict", text, name)

    def test_non_deny_hook_survives_exhaustion_in_a_real_process(self) -> None:
        """Test a fail-open hook exits 0 (not a traceback) when its stdin read is exhausted."""
        code = (
            "import errno,runpy,sys\n"
            f"sys.path.insert(0,{str(ROOT)!r})\n"
            "from unittest.mock import patch\n"
            "class S:\n"
            "    def fileno(self): raise OSError(errno.EMFILE,'x')\n"
            "sys.stdin=S()\n"
            f"runpy.run_path({str(ROOT / 'hooks/scripts/check_confidence_labels.py')!r}, run_name='__main__')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": tmp, "CLAUDE_DISCIPLINE_LOG": f"{tmp}/d.log"}
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class NoEditOnMainResourceTests(unittest.TestCase):
    """no_edit_on_main's git probes must deny, not fail open, on resource exhaustion."""

    def run_main(self, side_effect: BaseException) -> tuple[int, str]:
        """Run main on a source edit with subprocess.run failing."""
        module: Any = importlib.import_module("hooks.scripts.no_edit_on_main")
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x/app.py"}, "cwd": "/tmp"}
        buffer = io.StringIO()
        with (
            patch.object(module, "read_payload_strict", return_value=payload),
            patch.object(module.subprocess, "run", side_effect=side_effect),
            redirect_stdout(buffer),
        ):
            return module.main(), buffer.getvalue()

    def test_first_probe_resource_error_denies(self) -> None:
        """Test EMFILE from the branch probe denies with the resource message."""
        code, out = self.run_main(OSError(errno.EMFILE, "x"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"], common.RESOURCE_MESSAGE)

    def test_second_probe_resource_error_denies(self) -> None:
        """Test EMFILE from the toplevel probe (after branch main) denies too."""
        module: Any = importlib.import_module("hooks.scripts.no_edit_on_main")
        main_branch = subprocess.CompletedProcess([], 0, stdout="main\n", stderr="")
        code, out = self.run_main_sequence(module, [main_branch, OSError(errno.ENFILE, "x")])
        self.assertEqual(code, 0)
        self.assertIn("Host resource exhaustion", out)

    def run_main_sequence(self, module: ModuleType, results: list[Any]) -> tuple[int, str]:
        """Run main on a SKILL.md edit with sequential subprocess outcomes."""
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/skills/a/SKILL.md"}, "cwd": "/tmp"}
        buffer = io.StringIO()
        with (
            patch.object(module, "read_payload_strict", return_value=payload),
            patch.object(module.subprocess, "run", side_effect=results),
            redirect_stdout(buffer),
        ):
            return module.main(), buffer.getvalue()

    def test_non_resource_oserror_is_not_reported_as_exhaustion(self) -> None:
        """Test ENOENT (git missing) keeps its previous behaviour and is not the resource denial."""
        module: Any = importlib.import_module("hooks.scripts.no_edit_on_main")
        with self.assertRaises(OSError) as caught:
            self.run_main(FileNotFoundError(errno.ENOENT, "no git"))
        self.assertNotIsInstance(caught.exception, common.HostResourceError)
        del module


class RunBehaviourTests(unittest.TestCase):
    """run(): deny cause, exit-code passthrough, stderr discipline, SIGTERM write guard."""

    def setUp(self) -> None:
        """Point telemetry at a temp dir."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        env = patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": self.dir})
        env.start()
        self.addCleanup(env.stop)

    def test_deny_json_is_recorded_as_deny_not_ok(self) -> None:
        """Test a hook that emits deny() and returns 0 records cause deny."""
        with redirect_stdout(io.StringIO()):
            tel.run("g", partial(denied, 0))
        self.assertEqual(rows(self.dir)[0]["cause"], "deny")

    def test_deny_followed_by_nonzero_exit_keeps_its_exit_cause(self) -> None:
        """Test a deny flag never relabels a block (2) or other exit (1) as deny."""
        for value, cause in ((2, "block"), (1, "exit")):
            with self.subTest(value), redirect_stdout(io.StringIO()):
                tel.run("g", partial(denied, value))
            self.assertEqual(rows(self.dir)[-1]["cause"], cause)

    def test_deny_flag_does_not_leak_into_a_clean_run(self) -> None:
        """Test an allow run after no deny stays ok."""
        tel.run("g", lambda: 0)
        self.assertEqual(rows(self.dir)[0]["cause"], "ok")

    def test_codex_deny_is_also_recorded(self) -> None:
        """Test the Codex deny() marks the same flag (run in a clean process)."""
        scripts = ROOT / "packages/codex/hooks/scripts"
        code = (
            f"import sys;sys.path.insert(0,{str(scripts)!r})\n"
            "import hook_common as h\n"
            "from lib import hook_telemetry as t\n"
            "t.run('g', lambda: (h.deny('no'), 0)[1])\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": self.dir},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(rows(self.dir)[0]["cause"], "deny")

    def test_exit_codes_pass_through_unchanged(self) -> None:
        """Test 0, 1, 2, 3 and None all pass through run() and get a matching cause."""
        for value, cause in ((0, "ok"), (1, "exit"), (2, "block"), (3, "exit"), (None, "ok")):
            with self.subTest(value):
                self.assertEqual(tel.run("g", partial(int, value or 0)), value or 0)
                self.assertEqual(rows(self.dir)[-1]["cause"], cause)

    def test_write_failure_line_is_suppressed_on_exit_2(self) -> None:
        """Test stderr (the model-visible block reason on exit 2) is not polluted by telemetry."""
        for code, expected in ((2, ""), (0, "hook_telemetry: write failed")):
            with self.subTest(code), patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": "/dev/null/x"}):
                with patch("sys.stderr") as err:
                    tel.record("h", "block", exit_code=code)
                printed = "".join(call.args[0] for call in err.write.call_args_list)
                self.assertTrue(printed.startswith(expected), printed)
                self.assertEqual(printed == "", code == 2)

    def test_sigterm_still_exits_143_when_stderr_write_fails(self) -> None:
        """Test a failing os.write in the SIGTERM handler cannot replace SystemExit(143)."""
        code = (
            f"import os,signal,sys;sys.path.insert(0,{str(ROOT)!r})\n"
            "from hooks.scripts.lib import hook_telemetry as t\n"
            "os.close(2)\n"
            "t.run('slow', lambda: os.kill(os.getpid(), signal.SIGTERM) or 0)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            env={**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": self.dir},
        )
        self.assertEqual(proc.returncode, 143)
        self.assertEqual(rows(self.dir)[0]["cause"], "sigterm")


class WrapParityTests(unittest.TestCase):
    """A wrapped gate behaves byte-for-byte like the unwrapped one, including when telemetry is unimportable."""

    RUNNER = (
        "import runpy,sys;"
        "sys.modules['hooks.scripts.lib.hook_telemetry']=None;sys.modules['lib.hook_telemetry']=None;"
        "runpy.run_path(sys.argv[1], run_name='__main__')"
    )

    def run_gate(self, script: Path, payload: dict[str, Any], wrapped: bool, tmp: str) -> tuple[int, str]:
        """Run one gate as a process, with or without the telemetry lib."""
        env = {**os.environ, "HOME": tmp, "CODERAILS_HOOK_TELEMETRY_DIR": tmp, "CLAUDE_DISCIPLINE_LOG": f"{tmp}/d.log"}
        argv = [sys.executable, str(script)] if wrapped else [sys.executable, "-c", self.RUNNER, str(script)]
        proc = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=ROOT)
        return proc.returncode, proc.stdout

    def test_destructive_gate_decisions_match_wrapped_and_unwrapped(self) -> None:
        """Test deny and allow decisions are identical with and without telemetry."""
        script = ROOT / "hooks/scripts/destructive_bash_gate.py"
        cases = {"deny": "git reset --hard HEAD", "allow": "echo hello"}
        for label, command in cases.items():
            payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                wrapped = self.run_gate(script, payload, True, tmp)
                bare = self.run_gate(script, payload, False, tmp)
                self.assertEqual(wrapped, bare)
                self.assertEqual("deny" in wrapped[1], label == "deny", wrapped)
                self.assertEqual(rows(tmp)[-1]["cause"], "deny" if label == "deny" else "ok")

    def test_every_hook_entrypoint_is_wrapped_by_run(self) -> None:
        """Test voice_announce and Codex wiki_taxonomy_gate are wrapped (not exempt)."""
        for path in (
            ROOT / "hooks/scripts/voice_announce.py",
            ROOT / "packages/codex/hooks/scripts/wiki_taxonomy_gate.py",
        ):
            text = path.read_text()
            self.assertIn(f'run("{path.stem}", main)', text, path.name)
            self.assertIn("except ImportError", text, path.name)

    def test_voice_announce_runs_unwrapped_and_wrapped(self) -> None:
        """Test voice_announce exits 0 as a process with and without telemetry."""
        script = ROOT / "hooks/scripts/voice_announce.py"
        for wrapped in (True, False):
            with self.subTest(wrapped), tempfile.TemporaryDirectory() as tmp:
                code, _ = self.run_gate(script, {"hook_event_name": "Stop", "session_id": "s"}, wrapped, tmp)
                self.assertEqual(code, 0)


class ImportFallbackTests(unittest.TestCase):
    """A missing telemetry module is recorded once in the discipline log by lib code."""

    def test_lib_fallback_logs_once(self) -> None:
        """Test destructive_patterns logs a telemetry-unavailable line when the import fails."""
        with tempfile.TemporaryDirectory() as tmp:
            log = f"{tmp}/d.log"
            code = (
                f"import sys;sys.path.insert(0,{str(ROOT)!r})\n"
                "sys.modules['hooks.scripts.lib.hook_telemetry']=None\n"
                "from hooks.scripts.lib import destructive_patterns as d\n"
                "d.git_output('.', 'status'); d.git_output('.', 'status')\n"
            )
            env = {**os.environ, "CLAUDE_DISCIPLINE_LOG": log}
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            text = Path(log).read_text()
            self.assertEqual(text.count("hook_telemetry unavailable"), 1)


class DocsTests(unittest.TestCase):
    """Docs and docstrings stay true."""

    def test_reference_places_host_resource_error_in_hook_common(self) -> None:
        """Test REFERENCE.md no longer lists HostResourceError under hook_telemetry."""
        reference = (ROOT / "docs/REFERENCE.md").read_text()
        row = next(line for line in reference.splitlines() if "lib/hook_telemetry.py" in line)
        self.assertNotIn("HostResourceError", row)
        marker = "| `hooks/scripts/hook_common.py`"
        common_row = next(line for line in reference.splitlines() if line.startswith(marker))
        self.assertIn("HostResourceError", common_row)

    def test_action_authority_docstring_names_the_resource_denial(self) -> None:
        """Test the docstring no longer claims fail open on any error."""
        doc = importlib.import_module("hooks.scripts.action_authority_gate").__doc__ or ""
        self.assertNotIn("Any own error fails open", doc)
        self.assertIn("resource", doc)

    def test_unused_telemetry_helpers_are_gone(self) -> None:
        """Test dead helpers without a production caller were removed."""
        self.assertFalse(hasattr(tel, "child_failed"))
        self.assertFalse(hasattr(tel, "classify_returncode"))

    def test_module_docstring_lists_every_row_field(self) -> None:
        """Test the module docstring names each field a row carries."""
        for field in ("ts", "hook", "cause", "exit", "duration_ms", "open_fds", "pid"):
            self.assertIn(field, tel.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
