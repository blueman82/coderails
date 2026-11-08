"""Exercise registered publication hooks against real graph-bound push commands."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from packages.tests.graph_manifest_fixture import graph_progress  # noqa: E402


class PushPublicationPreflightTests(unittest.TestCase):
    """Keep Git, graph creation, shell parsing and hook execution real."""

    def setUp(self) -> None:
        """Create a committed local repository and isolated provider state."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = self.directory / "work tree"
        self.loop = self.directory / "loops"
        self.session = "push-hook-owner"
        self.invocation = 0
        self.git("init", "-q", "-b", "feature/push-hook", str(self.repo), cwd=self.directory)
        self.git(
            "-c", "user.name=Fixture", "-c", "user.email=fixture@test", "commit", "-q", "--allow-empty", "-m", "seed"
        )

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        """Read or initialize only the disposable repository."""
        return subprocess.check_output(["git", *arguments], cwd=cwd or self.repo, text=True).strip()

    def invoke(
        self,
        provider: str,
        command: str,
        *,
        session: str | None = None,
        workdir: Path | None = None,
        overrides: dict[str, str] | None = None,
    ) -> str:
        """Run the actual registered hook with a foreign ambient session and directory."""
        plugin = ROOT / "packages/codex" if provider == "codex" else ROOT
        name = "pr_publication_gate.py" if provider == "codex" else "enforce_pr_workflow.py"
        environment = os.environ | {
            "HOME": str(self.directory),
            "PLUGIN_ROOT": str(plugin),
            "CLAUDE_PLUGIN_ROOT": str(plugin),
            "PLUGIN_DATA": str(self.directory / "plugin-data"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.loop),
            "CLAUDE_CODE_SESSION_ID": "foreign-ambient-session",
            "CODERAILS_PUBLICATION_SESSION_ID": "foreign-ambient-session",
            **(overrides or {}),
        }
        tool_input = {"command": command}
        if workdir:
            tool_input["workdir"] = str(workdir)
        payload = {
            "session_id": self.session if session is None else session,
            "cwd": str(ROOT if workdir else self.repo),
            "tool_name": "Bash",
            "tool_input": tool_input,
        }
        before = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.loop.rglob("*") if path.is_file()
        }
        identity = (self.git("rev-parse", "HEAD"), self.git("write-tree"))
        result = subprocess.run(
            [sys.executable, str(plugin / "hooks/scripts" / name)],
            cwd=ROOT,
            env=environment,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        after = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.loop.rglob("*") if path.is_file()
        }
        if evidence := os.environ.get("CODERAILS_HOOK_TEST_LOG_DIR"):
            self.invocation += 1
            destination = Path(evidence)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / f"{self.id().split('.')[-1]}-{provider}-{self.invocation}.json").write_text(
                json.dumps(
                    {
                        "argv": result.args,
                        "process_cwd": str(ROOT),
                        "payload": payload,
                        "plugin": str(plugin),
                        "exit": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "state_before": before,
                        "state_after": after,
                        "head_index_before": identity,
                        "head_index_after": (self.git("rev-parse", "HEAD"), self.git("write-tree")),
                    },
                    indent=2,
                )
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(after, before)
        self.assertEqual((self.git("rev-parse", "HEAD"), self.git("write-tree")), identity)
        return result.stdout

    def test_graph_push_binding_refuses_before_authority_without_changing_state(self) -> None:
        """Removing helper recognition must expose wrong and missing unit bindings."""
        for provider in ("claude", "codex"):
            progress = graph_progress(self.repo, self.loop, ["allowed.py"], session=self.session, provider=provider)
            original = progress.read_bytes()
            plugin = ROOT / "packages/codex" if provider == "codex" else ROOT
            helper = plugin / "scripts/push.py"
            prefix = [sys.executable, str(helper)]
            cases = {
                "wrong-unit": ["--unit", "999", "--progress", str(progress)],
                "missing-unit": ["--progress", str(progress)],
                "missing-progress": ["--unit", "2"],
                "missing-both": [],
                "duplicate-unit": ["--unit", "2", "--unit", "999", "--progress", str(progress)],
                "relative-progress": ["--unit", "2", "--progress", os.path.relpath(progress, self.repo)],
            }
            before = (self.git("rev-parse", "HEAD"), self.git("write-tree"))
            for label, arguments in cases.items():
                with self.subTest(provider=provider, case=label):
                    output = self.invoke(provider, shlex.join([*prefix, *arguments]))
                    self.assertIn('"permissionDecision": "deny"', output)
                    self.assertIn("diff_manifest:manifest_unreadable", output)
                    self.assertEqual(progress.read_bytes(), original)
                    self.assertEqual((self.git("rev-parse", "HEAD"), self.git("write-tree")), before)
            with self.subTest(provider=provider, case="positive"):
                command = shlex.join([*prefix, "--unit", "2", "--progress", str(progress), "Message --unit 999"])
                self.assertEqual(self.invoke(provider, command), "")
                self.assertEqual(self.invoke(provider, command, workdir=self.repo), "")
                self.assertEqual(
                    self.invoke(
                        provider,
                        "cd / && "
                        + shlex.join(["env", "-C", str(self.repo), *prefix, "--unit=2", f"--progress={progress}"]),
                    ),
                    "",
                )
                self.assertEqual(
                    self.invoke(
                        provider, shlex.join([*prefix, "--add", "--unit", "--unit", "2", "--progress", str(progress)])
                    ),
                    "",
                )
            for inert in (
                shlex.join(["echo", f"python3 {helper} --unit 999 --progress {progress}"]),
                shlex.join([sys.executable, str(self.directory / "push.py"), "--unit", "999"]),
                shlex.join([sys.executable, "-c", f"print({str(helper)!r})"]),
            ):
                with self.subTest(provider=provider, case="active-graph-unrelated", command=inert):
                    self.assertEqual(self.invoke(provider, inert), "")
            with self.subTest(provider=provider, case="foreign-session"):
                self.assertIn('"permissionDecision": "deny"', self.invoke(provider, command, session="foreign"))
            foreign = self.directory / "foreign-progress.json"
            foreign.write_bytes(original)
            with self.subTest(provider=provider, case="copied-graph"):
                command = shlex.join([*prefix, "--unit", "2", "--progress", str(foreign)])
                self.assertIn('"permissionDecision": "deny"', self.invoke(provider, command))
            for label, change in (
                ("manifest-changed", {"manifest": ["other.py"]}),
                ("worktree-changed", {"worktree": str(self.directory)}),
                (
                    "foreign-assignment",
                    {
                        "worktree": str(self.directory),
                        "source_manifest_sha256": hashlib.sha256(
                            json.dumps(
                                {"worktree": str(self.directory.resolve()), "manifest": ["allowed.py"]},
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest(),
                    },
                ),
            ):
                state: dict[str, Any] = json.loads(original)
                state["work_units"]["2"].update(change)
                progress.write_text(json.dumps(state))
                with self.subTest(provider=provider, case=label):
                    command = shlex.join([*prefix, "--unit", "2", "--progress", str(progress)])
                    self.assertIn('"permissionDecision": "deny"', self.invoke(provider, command))
                progress.write_bytes(original)
            with self.subTest(provider=provider, case="missing-session"):
                self.assertIn('"permissionDecision": "deny"', self.invoke(provider, command, session=""))
            progress.unlink()

    def test_standalone_and_unrelated_python_commands_keep_their_scope(self) -> None:
        """The exact trusted path is guarded; inert text and other Python scripts are not."""
        for provider in ("claude", "codex"):
            plugin = ROOT / "packages/codex" if provider == "codex" else ROOT
            helper = plugin / "scripts/push.py"
            for command in (
                shlex.join([sys.executable, str(helper), "Standalone change"]),
                shlex.join(["echo", f"python3 {helper} --unit 999"]),
                shlex.join([sys.executable, str(self.directory / "push.py"), "--unit", "999"]),
                shlex.join([sys.executable, "-c", f"print({str(helper)!r})"]),
            ):
                with self.subTest(provider=provider, command=command):
                    self.assertEqual(self.invoke(provider, command), "")

    def test_documented_variables_and_python_options_bind_only_direct_helpers(self) -> None:
        """A documented root or direct interpreter option cannot hide a wrong unit."""
        for provider in ("claude", "codex"):
            progress = graph_progress(self.repo, self.loop, ["allowed.py"], session=self.session, provider=provider)
            plugin = ROOT / "packages/codex" if provider == "codex" else ROOT
            helper = plugin / "scripts/push.py"
            linked = self.directory / f"{provider}-linked-push.py"
            linked.symlink_to(helper)
            variable = "PLUGIN_ROOT" if provider == "codex" else "CLAUDE_PLUGIN_ROOT"
            variable_path = f"${{{variable}}}/scripts/push.py"
            forms = {
                "documented-root": f'python3 "{variable_path}"',
                "unbraced-root": f'python3 "${variable}/scripts/push.py"',
                "no-bytecode": shlex.join([sys.executable, "-B", str(helper)]),
                "bundled-options": shlex.join([sys.executable, "-Bu", str(helper)]),
                "option-values": shlex.join([sys.executable, "-W", "ignore", "-X", "utf8", str(helper)]),
                "attached-options": shlex.join([sys.executable, "-Wignore", "-Xutf8", str(helper)]),
                "long-option": shlex.join([sys.executable, "--check-hash-based-pycs", "always", str(helper)]),
                "end-options": shlex.join([sys.executable, "--", str(helper)]),
                "versioned": shlex.join(["python3.13", str(helper)]),
                "symlink": shlex.join([sys.executable, str(linked)]),
                "wrapper": "env -C " + shlex.quote(str(self.repo)) + f' python3 -B "{variable_path}"',
            }
            for label, prefix in forms.items():
                for unit in ("2", "999"):
                    with self.subTest(provider=provider, case=label, unit=unit):
                        command = prefix + " " + shlex.join(["--unit", unit, "--progress", str(progress)])
                        output = self.invoke(provider, command)
                        if unit == "999":
                            self.assertIn('"permissionDecision": "deny"', output)
                            self.assertIn("diff_manifest:manifest_unreadable", output)
                        else:
                            self.assertEqual(output, "")
            for prefix in (
                shlex.join([sys.executable, "-c", "pass", str(helper)]),
                shlex.join([sys.executable, "-cpass", str(helper)]),
                shlex.join([sys.executable, "-Bcpass", str(helper)]),
                shlex.join([sys.executable, "-m", "example", str(helper)]),
                shlex.join([sys.executable, "-mexample", str(helper)]),
                shlex.join([sys.executable, "-Bmexample", str(helper)]),
                shlex.join([sys.executable, "-W", str(helper), str(self.directory / "other.py")]),
                shlex.join([sys.executable, "-X", str(helper), str(self.directory / "other.py")]),
                shlex.join([sys.executable, "--check-hash-based-pycs=always", str(helper)]),
                f"python3 '{variable_path}'",
                f"python3 '{variable_path}' \"{variable_path}\"",
                f'python3 "\\${{{variable}}}/scripts/push.py"',
                'python3 "$UNRELATED_TEST_ROOT/scripts/push.py"',
            ):
                with self.subTest(provider=provider, case="inert-helper-argument", prefix=prefix):
                    command = prefix + " " + shlex.join(["--unit", "999", "--progress", str(progress)])
                    self.assertEqual(self.invoke(provider, command, overrides={"UNRELATED_TEST_ROOT": str(plugin)}), "")
            progress.unlink()


if __name__ == "__main__":
    unittest.main()
