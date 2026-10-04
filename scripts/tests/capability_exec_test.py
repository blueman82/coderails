"""Exercise capability.py tests.run and pr.comment: declared commands only, no shell, bounded, scrubbed."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import capability  # noqa: E402

DECLARED = {
    "hello": ["python3", "-c", "print('hi')"],
    "fails": ["python3", "-c", "import sys; print('boom'); sys.exit(3)"],
    "env": ["python3", "-c", "import os; print(sorted(os.environ), os.environ.get('HOME'))"],
    "slow": ["python3", "-c", "import time; time.sleep(30)"],
    "loud": ["python3", "-c", "print('x' * 20000)"],
}


class ExecCase(unittest.TestCase):
    """Run capability.main in-process inside a scratch git repo with a patched declared-command table."""

    def setUp(self) -> None:
        """Create the scratch repo and chdir into it."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "x",
            ],
            check=True,
        )
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.repo)
        patcher = mock.patch.object(capability, "declared_tests", return_value=DECLARED)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, tool: str, args: object) -> tuple[int, dict[str, Any]]:
        """Run main with captured stdout."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": ""}):
            code = capability.main([tool, "--json-args", json.dumps(args)])
        return code, json.loads(out.getvalue())


class TestsRunTests(ExecCase):
    """tests.run executes only names declared in profiles.json."""

    def test_declared_command_runs_with_typed_result(self) -> None:
        """Exit status, output, artifact sha and commit evidence come back typed."""
        code, out = self.call("tests.run", {"name": "hello"})
        self.assertEqual((code, out["ok"], out["exit_status"]), (0, True, 0))
        self.assertEqual(out["result"]["stdout_tail"], "hi\n")
        self.assertFalse(out["result"]["timed_out"])
        self.assertEqual(len(out["artifact_sha"]), 64)
        self.assertEqual({e["kind"] for e in out["evidence"]}, {"command", "commit"})

    def test_failing_command_reports_its_status(self) -> None:
        """A failing suite is a successful capability call carrying exit_status 3."""
        code, out = self.call("tests.run", {"name": "fails"})
        self.assertEqual((code, out["ok"], out["exit_status"]), (0, True, 3))

    def test_arbitrary_commands_are_refused(self) -> None:
        """Undeclared names, command-shaped args and shell syntax never reach subprocess."""
        for args in ({"name": "ls"}, {"name": "hello; ls"}, {"cmd": "ls"}, {"name": "hello", "argv": ["ls"]}, {}):
            with self.subTest(args=args), mock.patch("subprocess.run") as ran:
                code, out = self.call("tests.run", args)
                self.assertEqual((code, out["ok"]), (2, False))
                self.assertIn(out["refusal"], {"capability_tests_unknown_name", "capability_args_invalid"})
                ran.assert_not_called()

    def test_timeout_is_bounded(self) -> None:
        """A command exceeding timeout_s is killed and reported as timed out with status 124."""
        code, out = self.call("tests.run", {"name": "slow", "timeout_s": 1})
        self.assertEqual((code, out["exit_status"], out["result"]["timed_out"]), (0, 124, True))
        self.assertEqual(self.call("tests.run", {"name": "slow", "timeout_s": 99999})[0], 2)

    def test_environment_is_scrubbed(self) -> None:
        """Secrets in the parent environment are not inherited by the declared command."""
        with mock.patch.dict(os.environ, {"SECRET_TOKEN": "s3cret", "GH_TOKEN": "t"}):
            out = self.call("tests.run", {"name": "env"})[1]["result"]["stdout_tail"]
        self.assertNotIn("SECRET_TOKEN", out)
        self.assertNotIn("GH_TOKEN", out)
        self.assertIn("PYTHONDONTWRITEBYTECODE", out)

    def test_home_is_not_the_callers(self) -> None:
        """Repo code under test must not see the caller's real HOME (ssh keys, gh tokens)."""
        with mock.patch.dict(os.environ, {"HOME": "/real/home"}):
            out = self.call("tests.run", {"name": "env"})[1]["result"]["stdout_tail"]
        self.assertNotIn("/real/home", out)

    @unittest.skipUnless(sys.platform == "darwin", "sandbox-exec is macOS only")
    def test_hostile_test_code_is_contained(self) -> None:
        """Negative control: repo test code cannot write outside the repo/tmp or use the network."""
        outside = Path.home() / f".cap_escape_{os.getpid()}"
        self.addCleanup(lambda: outside.unlink() if outside.exists() else None)
        code = (
            "import socket,sys\n"
            f"res=[]\n"
            f"try: open({str(outside)!r},'w').write('x'); res.append('write')\n"
            "except OSError: pass\n"
            "try: socket.create_connection(('127.0.0.1',9),timeout=1)\n"
            "except ConnectionRefusedError: res.append('net')\n"
            "except OSError: pass\n"
            "print('ESCAPED', res)\n"
        )
        DECLARED["evil"] = ["python3", "-c", code]
        self.addCleanup(DECLARED.pop, "evil")
        out = self.call("tests.run", {"name": "evil"})[1]
        self.assertEqual(out["result"]["stdout_tail"], "ESCAPED []\n")
        self.assertFalse(outside.exists())

    def test_unsandboxable_platform_refuses(self) -> None:
        """Where no sandbox exists tests.run refuses (stable code) instead of running repo code unconfined."""
        with mock.patch("sys.platform", "linux"), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPABILITY_TESTS_UNSANDBOXED", None)
            code, out = self.call("tests.run", {"name": "hello"})
        self.assertEqual((code, out["refusal"]), (2, "capability_sandbox_unavailable"))

    def test_output_is_bounded(self) -> None:
        """Only a tail of the output is returned, with the full sha for evidence."""
        result = self.call("tests.run", {"name": "loud"})[1]["result"]
        self.assertLessEqual(len(result["stdout_tail"]), 4000)
        self.assertEqual(len(result["output_sha256"]), 64)

    def test_real_profiles_declare_only_argv_lists(self) -> None:
        """The shipped table is lists of strings, so no shell string can be declared."""
        path = Path(capability.__file__).resolve().parents[1] / "capabilities/profiles.json"
        data: dict[str, Any] = json.loads(path.read_text())
        for argv in data["tests"].values():
            self.assertTrue(all(type(item) is str for item in argv))


class PrCommentTests(ExecCase):
    """pr.comment builds one gh argv list and passes the body on stdin."""

    def test_posts_via_argv_list_with_body_on_stdin(self) -> None:
        """No shell: the body, however hostile, is stdin data and never an argv element."""
        body = "hi $(touch x); `y` | z"
        done = subprocess.CompletedProcess([], 0, stdout="https://example/c/1\n", stderr="")
        with mock.patch.object(capability, "run", return_value=done) as ran:
            code, out = self.call("pr.comment", {"pr": 7, "body": body})
        self.assertEqual((code, out["ok"], out["exit_status"]), (0, True, 0))
        argv, kwargs = ran.call_args.args[0], ran.call_args.kwargs
        self.assertEqual(argv, ["gh", "pr", "comment", "7", "--body-file", "-"])
        self.assertEqual(kwargs["stdin"], body)
        self.assertEqual(out["result"]["url"], "https://example/c/1")

    def test_schema_refusals(self) -> None:
        """Bad pr numbers, empty or oversized bodies and extra keys never reach gh."""
        bad = [
            {"pr": 0, "body": "x"},
            {"pr": True, "body": "x"},
            {"pr": "7", "body": "x"},
            {"pr": 7, "body": ""},
            {"pr": 7, "body": "x" * 4001},
            {"pr": 7, "body": "x", "repo": "other/repo"},
            {"body": "x"},
        ]
        for args in bad:
            with self.subTest(args=args), mock.patch.object(capability, "run") as ran:
                code, out = self.call("pr.comment", args)
                self.assertEqual((code, out["ok"]), (2, False))
                ran.assert_not_called()


if __name__ == "__main__":
    unittest.main()
