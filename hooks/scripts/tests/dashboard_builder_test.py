"""Exercise native builder state, process and hash contracts with inert provider/Git fixtures."""

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from skills.dashboard.scripts.canonical_json import dumps, loads

ROOT = Path(__file__).resolve().parents[3]


class BuilderTests(unittest.TestCase):
    """The actual Python CLI must never invoke a real provider or remote during tests."""

    def setUp(self) -> None:
        """Build a fake primary checkout, durable snapshots and explicit executable doubles."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base / "repo"
        (self.repo / ".git").mkdir(parents=True)
        for relative, name in (
            (".claude-plugin/plugin.json", "coderails"),
            ("packages/codex/.codex-plugin/plugin.json", "coderails-codex"),
        ):
            path = self.repo / relative
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"name": name}))
        self.bin = self.base / "bin"
        self.bin.mkdir()
        git = self.bin / "git"
        git.write_text(
            f"#!{sys.executable}\nimport os,sys\nfrom pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "if args[2]=='worktree': Path(args[4]).mkdir(parents=True,exist_ok=True)\n"
            "raise SystemExit(int(os.environ.get('GIT_FAILURE','0')))\n"
        )
        git.chmod(0o755)
        for name in ("claude", "codex"):
            path = self.bin / name
            path.write_text(
                f"#!{sys.executable}\nimport json,os,sys,time\nfrom pathlib import Path\n"
                "if sys.argv[1]=='--version': print('fixture version'); raise SystemExit(0)\n"
                "build=Path(os.environ['BUILD_FIXTURE'])\n"
                "(build/'args.json').write_text(json.dumps(sys.argv[1:]))\n"
                "time.sleep(float(os.environ.get('CHILD_SLEEP','0')))\n"
                "print(os.environ.get('CHILD_OUTPUT',''))\n"
                "print(os.environ.get('CHILD_ERROR',''),file=sys.stderr)\n"
                "if os.environ.get('WRITE_PR','1')=='1': (build/'pr_url').write_text('https://example.test/pr/1\\n')\n"
                "raise SystemExit(int(os.environ.get('CHILD_STATUS','0')))\n"
            )
            path.chmod(0o755)
        self.env = dict(
            os.environ,
            HOME=str(self.base / "home"),
            CODERAILS_BUILDER_REPO_PATH=str(self.repo),
            CODERAILS_BUILDER_LOCKS_DIR=str(self.base / "locks"),
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            PYTHONDONTWRITEBYTECODE="1",
            BUILDER_HEARTBEAT_SECS="0.01",
        )

    def build(self, name: str = "build") -> Path:
        """Create a correctly hashed approved snapshot and initial claimed state."""
        directory = self.base / name
        directory.mkdir()
        tool = {"proposed_name": "fixture"}
        digest = hashlib.sha256(dumps(loads(json.dumps(tool))).encode()).hexdigest()
        (directory / "snapshot.json").write_text(
            json.dumps(
                {"hash": digest, "toolInput": tool, "status": "approved", "toolName": "workflow-audit:propose-skill"}
            )
        )
        (directory / "state.json").write_text('{"hash":"initial","state":"claimed"}')
        (directory / "prompt.md").write_text("explicit fixture instructions\n")
        return directory

    def run_builder(
        self, directory: Path, provider: str = "claude", **environment: str
    ) -> subprocess.CompletedProcess[str]:
        """Run only a provider whose executable is our private inert test double."""
        root = ROOT if provider == "claude" else ROOT / "packages/codex"
        return subprocess.run(
            [sys.executable, str(root / "skills/dashboard/scripts/run_builder.py"), str(directory)],
            env=dict(self.env, BUILD_FIXTURE=str(directory), **environment),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_jq_numeric_unicode_hash_parity(self) -> None:
        """Use the old executable oracle for numeric spellings that binary floats alter."""
        for raw in (
            '{"a":1.0,"b":1e-6,"c":1e20,"d":1e21,"e":-0.0,"f":1e-7}',
            '{"z":"é😀","a":{"β":[true,null,123456789012345678901234567890]}}',
            "[1.00000e-7,0.0000000,1.200E+3,1.00e+2,0e20]",
            '{"del\x7f":"value\x7f"}',
        ):
            result = subprocess.run(["jq", "-S", "-c", "."], input=raw, capture_output=True, text=True, check=True)
            self.assertEqual(dumps(loads(raw)), result.stdout.rstrip("\n"))
        peer = importlib.import_module("packages.codex.skills.dashboard.scripts.canonical_json")
        self.assertEqual(peer.dumps(peer.loads(raw)), dumps(loads(raw)))

    def test_missing_and_mismatched_snapshot_never_spawn(self) -> None:
        """Both provider boundaries reject malformed or forged durable queue input."""
        for provider in ("claude", "codex"):
            for kind in ("missing", "hash", "filter"):
                with self.subTest(provider=provider, kind=kind):
                    directory = self.build(provider + kind)
                    path = directory / "snapshot.json"
                    value = json.loads(path.read_text())
                    if kind == "missing":
                        path.unlink()
                    else:
                        value["hash" if kind == "hash" else "status"] = "wrong"
                        path.write_text(json.dumps(value))
                    result = self.run_builder(directory, provider)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertFalse((directory / "args.json").exists())
                    reason = json.loads((directory / "state.json").read_text())["failureReason"]
                    self.assertEqual(
                        reason,
                        {
                            "missing": "unparseable_entry:snapshot.json",
                            "hash": "hash_mismatch:wrong",
                            "filter": "filter_mismatch",
                        }[kind],
                    )
                    self.assertFalse((self.base / "locks/builder.lock").exists())

    def test_native_completion_and_flags(self) -> None:
        """Claude owns a PR artifact; Codex owns only the local ready-for-review worktree."""
        for provider in ("claude", "codex"):
            directory = self.build(provider)
            result = self.run_builder(directory, provider)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads((directory / "state.json").read_text())
            arguments = json.loads((directory / "args.json").read_text())
            self.assertEqual(state[f"{provider}Version"], "fixture version")
            self.assertTrue((directory / "heartbeat").exists())
            if provider == "claude":
                self.assertEqual(state["state"], "pr_open")
                self.assertEqual(state["prUrl"], "https://example.test/pr/1")
                for flag in ("--disallowedTools", "Skill(coderails:merge)", "Bash(gh pr merge*)", "Bash(*merge.py*)"):
                    self.assertIn(flag, arguments)
                self.assertEqual(arguments[arguments.index("--max-budget-usd") + 1], "25")
            else:
                self.assertEqual(state["state"], "ready_for_review")
                self.assertIn("sandbox_workspace_write.network_access=false", arguments)
                self.assertEqual(arguments[:3], ["exec", "--sandbox", "workspace-write"])
                self.assertIn(".codex/worktrees/skill-build-", state["worktreePath"])
                self.assertNotIn("prUrl", state)

    def test_failure_classification_and_watchdog(self) -> None:
        """Preserve budget, CLI refusal, last stderr lines and child deadline enforcement."""
        cases = (
            ("nonzero_exit", {"CHILD_STATUS": "7", "CHILD_ERROR": "failure"}),
            ("claude_cli_flag_rejected", {"CHILD_STATUS": "2", "CHILD_ERROR": "unknown option"}),
            ("budget_exceeded", {"CHILD_STATUS": "1", "CHILD_OUTPUT": "error_max_budget_usd"}),
            ("timeout", {"CHILD_SLEEP": "10", "BUILDER_WALL_CLOCK_SECS": "0.1"}),
        )
        for index, (reason, environment) in enumerate(cases):
            directory = self.build(f"failure{index}")
            result = self.run_builder(directory, WRITE_PR="0", **environment)
            self.assertEqual(result.returncode, 1, result.stderr)
            state = json.loads((directory / "state.json").read_text())
            self.assertEqual(state["failureReason"], reason)
            self.assertIn("stderrTail", state)
            self.assertFalse((self.base / "locks/builder.lock").exists())

    def test_queue_timeout_preserves_other_owner(self) -> None:
        """A live lock remains owned by its process when this instance times out queued."""
        directory = self.build()
        lock = self.base / "locks/builder.lock"
        lock.parent.mkdir()
        lock.write_text(str(os.getpid()))
        result = self.run_builder(directory, BUILDER_QUEUE_TIMEOUT_SECS="0", BUILDER_POLL_INTERVAL_SECS="0")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(lock.read_text(), str(os.getpid()))
        self.assertEqual(json.loads((directory / "state.json").read_text())["failureReason"], "queue_timeout")


if __name__ == "__main__":
    unittest.main()
