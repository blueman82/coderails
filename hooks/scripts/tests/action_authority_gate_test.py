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

    def mint(
        self, command: str, kind: str, session: str = "s1", cwd: Path | None = None, rid: str = "r1", **over: object
    ) -> str:
        """Write a receipt matching the hook's view of `command` run in `cwd` (default the repo) on main."""
        now = datetime.now(timezone.utc)
        proposed = ar.proposed_action(kind, command, str(cwd or self.repo), "main")
        obj: dict[str, Any] = {
            "receipt_id": rid, "authority_id": None, "session_id": session, "loop_id": None, "action": kind,
            "exact_payload_hash": proposed["exact_payload_hash"], "artifact_sha": None, "scope": "",
            "issued_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(),
            "single_use": True, "revoked": False,
        }  # fmt: skip
        obj.update(over)
        path = ar.receipt_path(session, rid, self.loop)
        assert path is not None
        ar.write_receipt(path, obj)
        return rid

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

    def second_repo(self) -> Path:
        """A second repo, also on main."""
        other = self.directory / "other"
        other.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
        return other

    def test_chained_second_guarded_op_needs_its_own_receipt(self) -> None:
        """A receipt for the first segment never authorises a chained second guarded operation."""
        self.configure("enforce")
        self.mint("git push origin feature", "git_push")
        self.assertTrue(
            self.denied("action_authority_gate", self.payload("git push origin feature && git push origin main"))
        )
        self.mint("gh pr merge 1", "merge", rid="r2")
        self.assertTrue(self.denied("action_authority_gate", self.payload("gh pr merge 1 && gh pr merge 2")))
        self.mint("gh pr merge 2", "merge", rid="r3")
        self.assertFalse(self.denied("action_authority_gate", self.payload("gh pr merge 1 && gh pr merge 2")))

    def test_cd_into_other_repo_binds_the_real_directory(self) -> None:
        """A receipt for `git push` in repoA does not authorise `cd repoB && git push`; one minted for repoB does."""
        self.configure("enforce")
        other = self.second_repo()
        self.mint("git push", "git_push")
        self.assertTrue(self.denied("action_authority_gate", self.payload(f"cd {other} && git push")))
        self.mint("git push", "git_push", cwd=other, rid="r2")
        self.assertFalse(self.denied("action_authority_gate", self.payload(f"cd {other} && git push")))

    def test_artifact_sha_is_checked_against_real_head(self) -> None:
        """A push receipt bound to HEAD's sha verifies; a wrong sha is refused sha_mismatch."""
        self.configure("enforce")
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
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.mint(PUSH, "git_push", artifact_sha="0" * 40)
        self.assertTrue(self.denied("action_authority_gate", self.payload(PUSH)))
        self.assertEqual(self.reasons(), ["denied_sha_mismatch"])
        self.mint(PUSH, "git_push", rid="r2", artifact_sha=head)
        self.assertFalse(self.denied("action_authority_gate", self.payload(PUSH)))

    def test_missing_session_denied_as_no_session_and_traced(self) -> None:
        """No session_id: deny code no_session (not malformed), a trace row exists, no blank --session in the hint."""
        self.configure("enforce")
        payload = self.payload(PUSH)
        del payload["session_id"]
        result = self.invoke("action_authority_gate", payload)
        self.assertIn("no_session", result.stdout)
        self.assertNotIn("--session  ", result.stdout)
        self.assertEqual(self.reasons("_no_session"), ["denied_no_session"])

    def test_failed_open_row_carries_error_class_and_loop(self) -> None:
        """The failed-open row records the error class (hashed input) and stderr names the class and message."""
        self.configure("enforce")
        payload = self.payload(MERGE)
        with (
            mock.patch.object(gate, "read_payload", return_value=payload),
            mock.patch.object(gate, "read_authority", side_effect=ZeroDivisionError("boom")),
            mock.patch.dict("os.environ", {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
            mock.patch("sys.stderr") as err,
        ):
            self.assertEqual(gate.main(), 0)
        row = json.loads((self.loop / "s1" / "trace.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["reason_code"], "action_authority_failed_open")
        self.assertIn("error_class", row["inputs"])
        self.assertIn("ZeroDivisionError", "".join(c.args[0] for c in err.write.call_args_list))

    def test_one_receipt_cannot_authorise_two_identical_segments(self) -> None:
        """A single-use receipt is spent once: a chain repeating the same guarded command is denied."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        chained = f"echo x; {PUSH} && {PUSH}"
        self.assertTrue(self.denied("action_authority_gate", self.payload(chained)))
        self.assertNotIn("denied_no_receipt", self.reasons())
        self.mint(PUSH, "git_push", rid="r2")
        self.mint(PUSH, "git_push", rid="r3")
        self.assertFalse(self.denied("action_authority_gate", self.payload(chained)))

    def test_concurrent_hooks_one_receipt_exactly_one_allowed(self) -> None:
        """Four parallel hook processes on one receipt: the O_EXCL claim decides, so one allows and three deny."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        procs = [
            subprocess.Popen(
                [sys.executable, str(ROOT / "hooks/scripts/action_authority_gate.py")], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, text=True, env=self.environment,
            )
            for _ in range(4)
        ]  # fmt: skip
        outs = [p.communicate(json.dumps(self.payload(PUSH)))[0] for p in procs]
        self.assertEqual(sum("deny" not in out for out in outs), 1)
        self.assertEqual(self.reasons().count("receipt_consumed"), 1)

    def test_common_wrappers_are_still_guarded(self) -> None:
        """Env prefix, env/sudo/time, subshell, brace group, bash -c and gh api merge need the same receipt."""
        self.configure("enforce")
        wrapped = [
            "FOO=1 git push origin main", "env git push origin main", "sudo git push origin main",
            "(git push origin main)", "{ git push origin main; }", "bash -c 'git push origin main'",
            'sh -c "git push origin main"', "time git push origin main",
        ]  # fmt: skip
        for command in wrapped:
            with self.subTest(command=command):
                self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        for command in ("sudo gh pr merge 5", "(gh pr merge 5)", "gh api repos/o/r/pulls/5/merge -X PUT"):
            with self.subTest(command=command):
                self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.mint(PUSH, "git_push")
        self.assertFalse(self.denied("action_authority_gate", self.payload("FOO=1 git push origin main")))

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
