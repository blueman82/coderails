"""Run both installed hook copies against headless merge commands in a private home."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DENIED_COMMANDS = (
    'claude -p --dangerously-skip-permissions "gh pr merge 42"',
    'codex exec --dangerously-bypass-approvals-and-sandbox "gh pr merge 42"',
    'echo ready && claude -p "gh pr merge 42 && echo done"',
    'codex -C /tmp exec "gh pr merge 42"',
    'claude --cd /tmp -p "gh pr merge 42"',
)


class InstalledHeadlessGateTests(unittest.TestCase):
    """Use private plugin bundles, a private Git repo and an inert GitHub command."""

    def run_installed_hook(
        self, bundle: Path, hook: str, repo: Path, environment: dict[str, str], transcript: Path, command: str
    ) -> subprocess.CompletedProcess[str]:
        """Send one Bash event to a hook in the private plugin bundle."""
        payload = {
            "cwd": str(repo),
            "session_id": "installed-test",
            "tool_input": {"command": command},
            "transcript_path": str(transcript),
        }
        return subprocess.run(
            [sys.executable, str(bundle / hook)],
            cwd=repo,
            env=environment,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_headless_merge_is_refused_before_external_merge(self) -> None:
        """Both providers refuse the command string that a child could execute."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            repo = base / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "fixture",
                ],
                check=True,
            )
            head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/test/fixture.git"], check=True
            )
            config = repo / ".coderails/workflow.config.yaml"
            config.parent.mkdir()
            config.write_text("diff_manifest: enforce\ndiff_manifest_policy: .coderails/missing-policy.json\n")
            transcript = base / "transcript.jsonl"
            transcript.write_text("")
            binary = base / "bin"
            binary.mkdir()
            requests = base / "gh-requests"
            gh = binary / "gh"
            gh.write_text(
                "#!/usr/bin/env python3\nimport os,sys\n"
                "from pathlib import Path\n"
                "with Path(os.environ['GH_REQUEST_LOG']).open('a') as stream:\n"
                " stream.write(' '.join(sys.argv[1:])+'\\n')\n"
                "if sys.argv[1:3] == ['pr', 'view']:\n"
                " print(os.environ['GH_TEST_HEAD']); raise SystemExit(0)\n"
                "raise SystemExit(1)\n"
            )
            gh.chmod(0o755)
            environment = os.environ | {
                "HOME": str(home),
                "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                "GH_REQUEST_LOG": str(requests),
                "GH_TEST_HEAD": head,
                "CLAUDE_AGENTIC_LOOP_DIR": str(base / "loops"),
                "CODERAILS_AGENTIC_LOOP_DIR": str(base / "loops"),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            }
            for provider, source, hook in (
                ("claude", ROOT, "hooks/scripts/enforce_pr_workflow.py"),
                ("codex", ROOT / "packages/codex", "hooks/scripts/pr_publication_gate.py"),
            ):
                bundle = home / f".{provider}/plugins/cache/coderails/coderails-{provider}/test"
                shutil.copytree(source / "hooks/scripts", bundle / "hooks/scripts")
                shutil.copytree(
                    source / "scripts", bundle / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*_test.py")
                )
                shutil.copytree(source / "skills/agentic-loop/scripts", bundle / "skills/agentic-loop/scripts")
                shutil.copyfile(source / "config.schema.json", bundle / "config.schema.json")
                policy = bundle / "policy/diff-policy.default.json"
                policy.parent.mkdir(parents=True)
                shutil.copyfile(source / "policy/diff-policy.default.json", policy)
                for relative in ("scripts/__init__.py", "hooks/__init__.py", "hooks/scripts/__init__.py"):
                    origin = source / relative
                    if origin.is_file():
                        target = bundle / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(origin, target)
                for command in DENIED_COMMANDS:
                    with self.subTest(provider=provider, command=command):
                        result = self.run_installed_hook(bundle, hook, repo, environment, transcript, command)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn('"deny"', result.stdout, result.stdout + result.stderr)
                        self.assertNotIn("config_rejected", result.stdout, result.stdout + result.stderr)
                        if provider == "codex" and " /tmp " not in command:
                            self.assertIn("diff_manifest:manifest_unreadable", result.stdout)
                for command in (
                    "echo 'claude -p \"gh pr merge 42\"'",
                    'claude -p --system-prompt "gh pr merge 42" "explain the code"',
                    "git push origin feature",
                ):
                    with self.subTest(provider=provider, harmless=command):
                        result = self.run_installed_hook(bundle, hook, repo, environment, transcript, command)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertNotIn('"deny"', result.stdout, result.stdout + result.stderr)
            self.assertNotIn("pr merge", requests.read_text() if requests.exists() else "")


if __name__ == "__main__":
    unittest.main()
