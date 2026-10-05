"""Codex equivalents: packages/codex/scripts/merge.py and the Codex destructive gate use the mirrored libs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
sys.path.insert(0, str(ROOT))
import scripts.tests.merge_receipt_test as claude_suite  # noqa: E402  # isort: skip


class CodexMergeReceiptTests(claude_suite.MergeReceiptTests):
    """The whole merge.py suite (rejected set, replay, concurrent double use, hook phases) against the Codex package.

    plugin = packages/codex puts only the Codex scripts/lib on the child's sys.path, so the mirrored libs are tested.
    """

    plugin = CODEX

    def test_the_child_really_ran_the_codex_package(self) -> None:
        """The driver imported scripts.merge from packages/codex, not the Claude copy."""
        done = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from scripts import merge; "
             "print(merge.__file__)", str(CODEX)],
            capture_output=True, text=True, check=True, cwd=self.tmp,
        )  # fmt: skip
        self.assertIn("packages/codex/scripts/merge.py", done.stdout)


class CodexDestructiveLeaseTests(unittest.TestCase):
    """Codex destructive gate: authority.denied destructive_shell refuses the allowlisted lease family."""

    LEASE = "git push --force-with-lease origin feat/x"

    def setUp(self) -> None:
        """Feature-branch repo with the opt-in, and a private loop dir."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "feat/x", str(self.repo)], check=True)
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex/destructive_allowlist").write_text("git-push-force-with-lease\n")
        self.loop = self.tmp / "loops"

    def run_hook(self, command: str) -> dict[str, Any]:
        """The hookSpecificOutput for one command ({} when the hook stands aside)."""
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": command}}
        env = os.environ | {
            "PLUGIN_ROOT": str(CODEX),
            "PLUGIN_DATA": str(self.tmp / "data"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
        }
        done = subprocess.run(
            [sys.executable, str(CODEX / "hooks/scripts/destructive_bash_gate.py")], input=json.dumps(payload),
            capture_output=True, text=True, env=env, check=False,
        )  # fmt: skip
        return dict(json.loads(done.stdout)["hookSpecificOutput"]) if done.stdout.strip() else {}

    def test_lease_denied_only_when_the_authority_denies_destructive_shell(self) -> None:
        """No authority allows; denied destructive_shell refuses and traces; the permanent blocklist is unchanged."""
        self.assertEqual(self.run_hook(self.LEASE), {})
        obj = {
            "authority_id": "auth-1", "loop_id": None, "session_id": "s1", "scope": ["code"],
            "denied": ["destructive_shell"], "max_prs": 1, "expires_at": "2999-01-01T00:00:00+00:00",
            "revocable": True, "approval_required_for": ["merge"], "granted_by": "command",
        }  # fmt: skip
        path = self.loop / "s1" / "authority.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(obj))
        out = self.run_hook(self.LEASE)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("authority_denied_destructive_shell", out["permissionDecisionReason"])
        self.assertIn("authority_denied_destructive_shell", (self.loop / "s1" / "trace.jsonl").read_text())
        self.assertEqual(self.run_hook("rm -rf build")["patternId"], "rm-rf")
        self.assertEqual(self.run_hook("ls -la"), {})
        for split in (
            "git push origin \\\n  --force-with-lease feat/x",
            "git \\\n push --force-with-lease origin feat/x",
            "git push \\\n--force-with-lease=feat/x origin feat/x",
        ):  # a continuation line must not split the lease check from the family permanent_pattern allowed
            self.assertIn("authority_denied_destructive_shell", self.run_hook(split)["permissionDecisionReason"], split)


if __name__ == "__main__":
    unittest.main()
