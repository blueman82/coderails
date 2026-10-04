"""Codex action-authority hook and its parity with the Claude receipt library (same fixtures, same answers)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "packages/codex/hooks/scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOOKS))
import hook_common as codex  # noqa: E402  # isort: skip
from scripts.lib import action_receipt as claude  # noqa: E402  # isort: skip

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
MERGE = "gh pr merge 12 --squash"


def receipt(**over: object) -> dict[str, Any]:
    """A valid merge receipt for MERGE in /repo on main, with overrides."""
    obj: dict[str, Any] = {
        "receipt_id": "r1",
        "authority_id": None,
        "session_id": "s1",
        "loop_id": "L1",
        "action": "merge",
        "exact_payload_hash": claude.proposed_action("merge", MERGE, "/repo", "main")["exact_payload_hash"],
        "artifact_sha": None,
        "scope": "",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "single_use": True,
        "revoked": False,
    }
    obj.update(over)
    return obj


class ParityTests(unittest.TestCase):
    """The vendored Codex subset must agree with scripts/lib/action_receipt on every fixture."""

    def test_proposed_action_identical(self) -> None:
        """Same command/cwd/branch hashes identically, including unparseable quoting."""
        cases = (("merge", MERGE, None), ("git_push", "git push origin main", "abc"), ("merge", "gh 'x", None))
        for kind, segment, sha in cases:
            self.assertEqual(
                claude.proposed_action(kind, segment, "/repo", "main", sha),
                codex.receipt_proposed(kind, segment, "/repo", "main", sha),
            )

    def test_verify_identical_on_every_refusal(self) -> None:
        """One fixture per reason code (plus malformed shapes) gives the same (ok, code) from both."""
        past = (NOW - timedelta(seconds=1)).isoformat()
        good = claude.proposed_action("merge", MERGE, "/repo", "main")
        other = claude.proposed_action("merge", "gh pr merge 13", "/repo", "main")
        cases: list[tuple[object, dict[str, Any], str, str | None, bool]] = [
            (receipt(), good, "s1", "L1", False),
            (receipt(), {**good, "action": "git_push"}, "s1", "L1", False),
            (receipt(), other, "s1", "L1", False),
            (receipt(artifact_sha="a"), {**good, "artifact_sha": "b"}, "s1", "L1", False),
            (receipt(expires_at=past), good, "s1", "L1", False),
            (receipt(revoked=True), good, "s1", "L1", False),
            (receipt(), good, "s1", "L1", True),
            (receipt(), good, "s2", "L1", False),
            (receipt(), good, "s1", "L2", False),
            (receipt(loop_id=None), good, "s1", "L9", False),
            ("x", good, "s1", "L1", False),
            ({"receipt_id": "r1"}, good, "s1", "L1", False),
            (receipt(extra=1), good, "s1", "L1", False),
            (receipt(expires_at="soon"), good, "s1", "L1", False),
            (receipt(single_use="yes"), good, "s1", "L1", False),
        ]
        for index, (rec, proposed, session, loop, consumed) in enumerate(cases):
            with self.subTest(index):
                self.assertEqual(
                    claude.verify(rec, proposed, NOW, session, loop, consumed),
                    codex.receipt_verify(rec, proposed, NOW, session, loop, consumed),
                )

    def test_find_valid_and_consume_identical(self) -> None:
        """Both implementations find, consume once, honour the revoke tombstone and read the same files."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": tmp}):
            good = claude.proposed_action("merge", MERGE, "/repo", "main")
            path = claude.receipt_path("s1", "r1", Path(tmp))
            assert path is not None
            claude.write_receipt(path, receipt())
            self.assertEqual(codex.receipt_find_valid("s1", good, NOW, "L1")[1], "ok")
            self.assertEqual(codex.receipt_find_valid("s1", good, NOW, "L1", True)[1], "ok")
            self.assertTrue(claude.is_consumed(path))  # Codex consume is visible to Claude
            self.assertEqual(codex.receipt_find_valid("s1", good, NOW, "L1", True), (None, "consumed"))
            self.assertEqual(claude.find_valid("s1", good, NOW, "L1", Path(tmp)), (None, "consumed"))
            path.with_suffix(".consumed").unlink()
            claude.revoke_receipt(path)  # Claude tombstone is visible to Codex
            self.assertEqual(codex.receipt_find_valid("s1", good, NOW, "L1"), (None, "revoked"))


class HookTests(unittest.TestCase):
    """Native Codex PreToolUse payloads (command + session_id) drive the hook as a subprocess."""

    def setUp(self) -> None:
        """Repo on main and isolated loop dir."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.loop = self.directory / "loops"
        self.environment = os.environ | {
            "HOME": str(self.directory / "home"),
            "PLUGIN_ROOT": str(ROOT / "packages/codex"),
            "PLUGIN_DATA": str(self.directory / "data"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
        }

    def configure(self, value: str | None) -> None:
        """Write (or skip) the config line."""
        if value is not None:
            (self.repo / ".coderails").mkdir(exist_ok=True)
            (self.repo / ".coderails/workflow.config.yaml").write_text(f"action_authority: {value}\n")

    def run_hook(self, command: str, session: str = "s1") -> subprocess.CompletedProcess[str]:
        """Run the hook on one Bash event."""
        payload = {
            "session_id": session,
            "cwd": str(self.repo),
            "tool_name": "Bash",
            "hook_event_name": "PreToolUse",
            "tool_input": {"command": command},
        }
        return subprocess.run(
            [sys.executable, str(HOOKS / "action_authority_gate.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.environment,
            check=False,
        )

    def denied(self, command: str, session: str = "s1") -> bool:
        """True when the hook emitted a deny decision."""
        result = self.run_hook(command, session)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return False
        return bool(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny")

    def mint(self, command: str = MERGE, kind: str = "merge") -> None:
        """Write a receipt via the Claude library for the hook's view of the command."""
        now = datetime.now(timezone.utc)
        proposed = claude.proposed_action(kind, command, str(self.repo), "main")
        path = claude.receipt_path("s1", "r1", self.loop)
        assert path is not None
        claude.write_receipt(
            path,
            receipt(
                loop_id=None,
                action=kind,
                exact_payload_hash=proposed["exact_payload_hash"],
                issued_at=now.isoformat(),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            ),
        )

    def reasons(self) -> list[str]:
        """Reason codes traced for s1."""
        path = self.loop / "s1" / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_off_and_advisory(self) -> None:
        """Off is silent; advisory warns and traces but never denies."""
        for value in (None, "off", "bogus"):
            self.configure(value)
            result = self.run_hook(MERGE)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.reasons(), [])
        self.configure("advisory")
        result = self.run_hook(MERGE)
        self.assertEqual((result.stdout, "advisory" in result.stderr), ("", True))
        self.assertEqual(self.reasons(), ["advisory_no_receipt"])

    def test_enforce_deny_allow_consume_once(self) -> None:
        """No receipt denied; matching receipt allowed and consumed; second use denied; other args denied."""
        self.configure("enforce")
        self.assertTrue(self.denied(MERGE))
        self.mint()
        self.assertTrue(self.denied("gh pr merge 13 --squash"))
        self.assertFalse(self.denied(MERGE))
        self.assertTrue(self.denied(MERGE))
        expected = ["denied_no_receipt", "denied_hash_mismatch", "receipt_consumed", "denied_consumed"]
        self.assertEqual(self.reasons(), expected)
        self.assertFalse(self.denied("ls -la"))

    def test_enforce_guards_push_on_main_only(self) -> None:
        """A push on main is guarded; on a feature branch it is not."""
        self.configure("enforce")
        self.assertTrue(self.denied("git push origin main"))
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature/x"], check=True)
        self.assertFalse(self.denied("git push origin feature/x"))

    def test_registered_with_timeout(self) -> None:
        """Appended last to the ^Bash$ group with a timeout of at least 5."""
        group = json.loads((ROOT / "packages/codex/hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]
        self.assertEqual(group["matcher"], "^Bash$")
        self.assertIn("action_authority_gate.py", group["hooks"][-1]["command"])
        self.assertGreaterEqual(group["hooks"][-1]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
