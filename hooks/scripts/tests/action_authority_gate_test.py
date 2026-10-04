#!/usr/bin/env python3
"""Pin the opt-in action-authority hook: off/advisory/enforce, receipt consume, fail-open, existing gates untouched."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import action_authority_gate as gate
from hooks.scripts.tests.native_hook_test_support import HookCase
from scripts.lib import action_receipt as ar

ROOT = Path(__file__).resolve().parents[3]
MERGE = "gh pr merge 12 --squash"
PUSH = "git push origin main"


class GateTests(HookCase):
    """A real temp repo on main with a config file drives the hook as a subprocess."""

    def setUp(self) -> None:
        """Repo on main, no config yet."""
        super().setUp()
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)

    def configure(self, value: str | None) -> None:
        """Write (or skip) the action_authority config line."""
        if value is not None:
            (self.repo / ".coderails").mkdir(exist_ok=True)
            (self.repo / ".coderails/workflow.config.yaml").write_text(f"action_authority: {value}\n")

    def payload(self, command: str, session: str = "s1") -> dict[str, Any]:
        """A Bash PreToolUse payload."""
        return {
            "hook_event_name": "PreToolUse",
            "session_id": session,
            "cwd": str(self.repo),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

    def mint(self, command: str, kind: str, session: str = "s1", **over: object) -> str:
        """Write a receipt matching the hook's view of `command` in the repo on main."""
        now = datetime.now(timezone.utc)
        proposed = ar.proposed_action(kind, command, str(self.repo), "main")
        obj: dict[str, Any] = {
            "receipt_id": "r1", "authority_id": None, "session_id": session, "loop_id": None, "action": kind,
            "exact_payload_hash": proposed["exact_payload_hash"], "artifact_sha": None, "scope": "",
            "issued_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(),
            "single_use": True, "revoked": False,
        }  # fmt: skip
        obj.update(over)
        path = ar.receipt_path(session, "r1", self.loop)
        assert path is not None
        ar.write_receipt(path, obj)
        return "r1"

    def reasons(self, session: str = "s1") -> list[str]:
        """Reason codes traced for a session."""
        path = self.loop / session / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_off_is_silent_for_absent_unknown_and_off(self) -> None:
        """Absent config, off, and junk values never deny, warn or trace."""
        for value in (None, "off", "yes", ""):
            with self.subTest(value=value):
                self.configure(value)
                result = self.invoke("action_authority_gate", self.payload(MERGE))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.reasons(), [])

    def test_advisory_warns_and_traces_never_denies(self) -> None:
        """Advisory without a receipt: stderr warning plus a trace row, no denial."""
        self.configure("advisory")
        result = self.invoke("action_authority_gate", self.payload(MERGE))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn("advisory", result.stderr)
        self.assertEqual(self.reasons(), ["advisory_no_receipt"])

    def test_enforce_denies_without_receipt_and_allows_with_one_once(self) -> None:
        """Enforce: denied without; allowed and consumed with a matching receipt; second use denied."""
        self.configure("enforce")
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.mint(MERGE, "merge")
        self.assertFalse(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertEqual(self.reasons(), ["denied_no_receipt", "receipt_consumed", "denied_consumed"])

    def test_enforce_refuses_different_args_foreign_session_and_unguarded(self) -> None:
        """Different args and a receipt minted for another session are refused; unguarded commands pass."""
        self.configure("enforce")
        self.mint(MERGE, "merge")
        self.assertTrue(self.denied("action_authority_gate", self.payload("gh pr merge 13 --squash")))
        self.assertEqual(self.reasons(), ["denied_hash_mismatch"])
        self.mint(MERGE, "merge", session="s2", session_id="s1")  # foreign: lives in s2's dir, embeds s1
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE, "s2")))
        self.assertEqual(self.reasons("s2"), ["denied_foreign_session"])
        for command in ("ls -la", "gh pr create", "git status"):
            self.assertFalse(self.denied("action_authority_gate", self.payload(command)), command)
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature/x"], check=True)
        self.assertFalse(self.denied("action_authority_gate", self.payload("git push origin feature/x")))

    def test_enforce_guards_git_push_to_main(self) -> None:
        """A push on main needs a push receipt."""
        self.configure("enforce")
        self.assertTrue(self.denied("action_authority_gate", self.payload(PUSH)))
        self.mint(PUSH, "git_push")
        self.assertFalse(self.denied("action_authority_gate", self.payload(PUSH)))

    def test_hook_error_fails_open_with_reason(self) -> None:
        """An injected exception exits 0 without denying and traces action_authority_failed_open."""
        self.configure("enforce")
        payload = self.payload(MERGE)
        with (
            mock.patch.object(gate, "read_payload", return_value=payload),
            mock.patch.object(gate, "find_valid", side_effect=RuntimeError("boom")),
            mock.patch.dict("os.environ", {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(self.reasons(), ["action_authority_failed_open"])

    def test_subagent_session_id_differs_is_foreign(self) -> None:
        """A worker whose session_id differs from the minter's is refused as foreign_session (documented limit)."""
        self.configure("enforce")
        self.mint(MERGE, "merge", session="parent")
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE, "worker")))
        self.assertEqual(self.reasons("worker"), ["denied_no_receipt"])

    def test_registered_after_existing_gates(self) -> None:
        """Pure append: the Bash group keeps its original order with the new hook last, timeout >= 5."""
        group = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]["hooks"]
        names = [item["command"].rsplit("/", 1)[1].rstrip('"') for item in group]
        self.assertEqual(
            names,
            [
                "destructive_bash_gate.py", "enforce_pr_workflow.py", "test_gate.py",
                "verification_volume_ceiling.py", "reviewer_bash_allowlist.py", "action_authority_gate.py",
            ],
        )  # fmt: skip
        self.assertGreaterEqual(group[-1]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
