"""Codex action-authority hook, its mirrored receipt modules, and parity with the Claude copies."""

from __future__ import annotations

import contextlib
import io
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
CODEX = ROOT / "packages/codex"
HOOKS = CODEX / "hooks/scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOOKS))
import action_authority_gate as codex_gate  # noqa: E402  # isort: skip
from hooks.scripts.tests.receipt_test_support import (  # noqa: E402  # isort: skip
    REPOSITORY,
    git,
    make_owner,
    make_repo,
    signed_receipt,
    store,
)
from scripts.lib import action_binding as ab  # noqa: E402  # isort: skip

MERGE_SHA = "f" * 40
PIN = f"--match-head-commit {MERGE_SHA}"
MERGE = f"gh pr merge 12 --squash {PIN}"


PROBE = """
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import action_receipt as ar, receipt_signing as rs
assert "packages/codex" in ar.__file__, ar.__file__
case = json.loads(sys.argv[2])
rec, prop, signers = case["rec"], case["prop"], Path(case["signers"])
now = datetime.now(timezone.utc)
if case["mode"] == "verify":
    print(json.dumps(ar.verify(rec, prop, now, "s1", None, signers=signers)))
else:
    base = Path(case["base"])
    r, c = ar.find_valid("s1", prop, now, None, base, True, signers)
    print(r["receipt_id"] if r else "NONE:" + c)
"""


class HookTests(unittest.TestCase):
    """Native Codex PreToolUse payloads (command + session_id) drive the hook as a subprocess."""

    def setUp(self) -> None:
        """Repo on main with an origin, isolated loop dir and HOME, a fake gh and an owner key (user tier)."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = make_repo(self.directory / "repo")
        self.loop = self.directory / "loops"
        keys = self.directory / "home" / ".coderails" / "keys"
        self.key, signers = make_owner(keys)
        signers.rename(keys / "receipt_signers")
        self.agent_key, _ = make_owner(self.directory / "agent")
        gh = self.directory / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(f'#!/bin/sh\necho \'{{"baseRefName":"main","headRefOid":"{MERGE_SHA}"}}\'\n')
        gh.chmod(0o755)
        self.environment = os.environ | {
            "HOME": str(self.directory / "home"),
            "PATH": f"{gh.parent}:{os.environ['PATH']}",
            "PLUGIN_ROOT": str(CODEX),
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

    def mint(
        self, command: str = MERGE, kind: str = "merge", cwd: Path | None = None, rid: str = "r1",
        key: Path | None = None, **over: object,
    ) -> None:  # fmt: skip
        """Store a signed receipt for the hook's view of `command` run in `cwd` on main."""
        where = str(cwd or self.repo)
        bind = (
            {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": MERGE_SHA}
            if kind == "merge" else ab.binding(kind, command, where)
        )  # fmt: skip
        rec = signed_receipt(key or self.key, kind, command, where, "main", bind, receipt_id=rid, **over)
        store(self.loop, rec, "s1")  # a foreign-session receipt still lives in s1's directory

    def reasons(self) -> list[str]:
        """Reason codes traced for s1."""
        path = self.loop / "s1" / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_one_receipt_cannot_authorise_two_identical_segments(self) -> None:
        """A denied chain cannot spend the receipt for its first segment."""
        self.configure("enforce")
        self.mint()
        self.assertTrue(self.denied(f"{MERGE} && {MERGE}"))
        self.assertFalse((self.loop / "s1/receipts/r1.consumed").exists())

    def test_unexpected_error_uses_live_authority_error_policy(self) -> None:
        """Codex denies under enforce or a loaded grant and warns without either."""
        for mode, live, denied in (("advisory", False, False), ("advisory", True, True), ("enforce", False, True)):
            with self.subTest(mode=mode, live=live):
                self.configure(mode)
                output = io.StringIO()
                payload = {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": MERGE}}
                with (
                    mock.patch.dict(os.environ, self.environment),
                    mock.patch.object(codex_gate, "read_input", return_value=""),
                    mock.patch.object(codex_gate, "payload_object", return_value=payload),
                    mock.patch.object(codex_gate, "check_and_consume", side_effect=RuntimeError("unexpected")),
                    mock.patch.object(codex_gate, "read_authority", return_value={"loop_id": None} if live else None),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(codex_gate.main(), 0)
                self.assertEqual(bool(output.getvalue()), denied)
                self.assertEqual(self.reasons()[-1], "denied_gate_error" if denied else "action_authority_failed_open")

    def test_marker_write_error_denies_in_codex_hook(self) -> None:
        """A Codex marker write fault must emit a deny envelope, not fail open."""
        self.configure("enforce")
        self.mint()
        original = Path.write_text

        def write(path: Path, data: str, encoding: str | None = None, errors: str | None = None) -> int:
            if path.suffix == ".consumed":
                original(path, "", encoding=encoding, errors=errors)
                raise OSError("marker write failed")
            return original(path, data, encoding=encoding, errors=errors)

        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": MERGE}}
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environment),
            mock.patch.object(codex_gate, "read_input", return_value=json.dumps(payload)),
            mock.patch.object(Path, "write_text", autospec=True, side_effect=write),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(codex_gate.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("denied_marker_write_failed", self.reasons())
        self.assertFalse((self.loop / "s1/receipts/r1.consumed").exists())

    def test_common_wrappers_are_still_guarded(self) -> None:
        """Env prefix, sudo, subshell, bash -c and gh api merge are guarded like the bare command."""
        self.configure("enforce")
        for command in ("FOO=1 gh pr merge 12", "sudo gh pr merge 12", "(gh pr merge 12)",
                        "bash -c 'git push origin main'", "gh api repos/o/r/pulls/5/merge -X PUT",
                        "gh api -X PUT repos/o/r/pulls/5/merge",
                        "gh api graphql -f query='mutation { mergePullRequest(input: {}) { id } }'",
                        "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { id } }'",
                        ):  # fmt: skip
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_off_and_advisory(self) -> None:
        """No config and off are silent; invalid config denies; advisory warns."""
        self.assertFalse(self.denied(MERGE))  # no config at all
        self.configure("off")
        result = self.run_hook(MERGE)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.reasons(), [])
        self.configure("bogus")
        rejected = self.run_hook(MERGE)
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        self.assertEqual(json.loads(rejected.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("config_rejected", rejected.stdout)
        self.assertEqual(self.reasons(), ["config_bad_value", "config_rejected"])
        self.configure("advisory")
        result = self.run_hook(MERGE)
        self.assertEqual((result.stdout, "advisory" in result.stderr), ("", True))
        self.assertEqual(self.reasons()[-1], "advisory_no_receipt")

    def test_unbindable_merge_with_live_cap_is_denied_before_remote_command(self) -> None:
        """The Codex hook refuses an unknown PR or head while a merge cap is live."""
        self.configure("advisory")
        authority = {
            "authority_id": "a1", "loop_id": None, "session_id": "s1", "scope": ["code"], "denied": [],
            "max_prs": 1, "expires_at": "2999-01-01T00:00:00+00:00", "revocable": True,
            "approval_required_for": ["merge"], "granted_by": "command",
        }  # fmt: skip
        path = self.loop / "s1" / "authority.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(authority))
        remote = self.directory / "remote.log"
        gh = self.directory / "bin" / "gh"
        gh.write_text(
            f'#!/bin/sh\nif [ "$1 $2" = "pr view" ]; then '
            f'echo \'{{"baseRefName":"main","headRefOid":"{MERGE_SHA}"}}\'; '
            f'else echo "$*" >> "{remote}"; fi\n'
        )
        for command in (
            "gh pr merge 12 --squash",
            "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { id } }'",
        ):
            with self.subTest(command=command):
                denied = self.denied(command)
                if not denied:
                    subprocess.run(command, shell=True, env=self.environment, cwd=self.repo, check=True)
                self.assertTrue(denied)
                self.assertFalse(remote.exists())
                self.assertEqual(list((self.loop / "s1" / "merges").glob("*.json")), [])
        self.assertEqual(self.reasons(), ["denied_binding_unknown", "denied_binding_unknown"])

    def test_rejected_set(self) -> None:
        """(c) wrong repository, wrong ref, stale sha, unsigned, agent-signed, expired and foreign-session receipts."""
        self.configure("enforce")
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        cases: tuple[tuple[str, dict[str, Any]], ...] = (
            ("repository_mismatch", {"repository": "github.com/evil/w"}), ("ref_mismatch", {"ref": "refs/heads/x"}),
            ("sha_mismatch", {"artifact_sha": "b" * 40}), ("signature_missing", {"signature": None}),
            ("signer_unknown", {"key": self.agent_key}),
            ("expired", {"expires_at": (past + timedelta(minutes=1)).isoformat(), "issued_at": past.isoformat()}),
            ("foreign_session", {"session_id": "other"}),
        )  # fmt: skip
        for code, over in cases:
            with self.subTest(code=code):
                self.mint(rid=code, **over)
                self.assertTrue(self.denied(MERGE))
                self.assertEqual(self.reasons()[-1], f"denied_{code}")
                (self.loop / "s1" / "receipts" / f"{code}.json").unlink()

    def test_authority_denied_and_max_prs_beat_a_valid_receipt(self) -> None:
        """(a) authority.denied and a spent max_prs refuse before any receipt is consumed."""
        self.configure("enforce")
        obj: dict[str, Any] = {
            "authority_id": "auth-1", "loop_id": None, "session_id": "s1", "scope": ["code"], "denied": ["merge"],
            "max_prs": 0, "expires_at": "2999-01-01T00:00:00+00:00", "revocable": True,
            "approval_required_for": ["merge"], "granted_by": "command",
        }  # fmt: skip
        path = self.loop / "s1" / "authority.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(obj))
        self.mint()
        self.assertTrue(self.denied(MERGE))
        path.write_text(json.dumps(obj | {"denied": []}))
        self.assertTrue(self.denied(MERGE))
        self.assertEqual(self.reasons(), ["denied_authority_denied", "denied_max_prs_exceeded"])
        self.assertFalse((self.loop / "s1" / "receipts" / "r1.consumed").exists())

    def test_subagent_payload_is_the_same_session(self) -> None:
        """(d) Extra agent_id/agent_type fields do not change the session: the parent's receipt is honoured."""
        self.configure("enforce")
        self.mint()
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": MERGE},
                   "agent_id": "a-1", "agent_type": "loop-worker"}  # fmt: skip
        done = subprocess.run(
            [sys.executable, str(HOOKS / "action_authority_gate.py")], input=json.dumps(payload), capture_output=True,
            text=True, env=self.environment, check=False,
        )  # fmt: skip
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertEqual(self.reasons(), ["trust_root_user_tier", "receipt_consumed"])

    def test_enforce_deny_allow_consume_once(self) -> None:
        """No receipt denied; matching signed receipt allowed and consumed; replay denied; other args denied."""
        self.configure("enforce")
        self.assertTrue(self.denied(MERGE))
        self.mint()
        self.assertTrue(self.denied(f"gh pr merge 13 --squash {PIN}"))
        self.assertFalse(self.denied(MERGE))
        self.assertTrue(self.denied(MERGE))
        expected = ["denied_no_receipt", "denied_hash_mismatch", "trust_root_user_tier", "receipt_consumed"]
        expected.append("denied_consumed")
        self.assertEqual(self.reasons(), expected)
        self.assertFalse(self.denied("ls -la"))

    def test_self_minted_and_untrusted_are_denied(self) -> None:
        """Unsigned JSON, an agent-made key and a missing trust root are all denied with their own codes."""
        self.configure("enforce")
        self.mint(rid="a", signature=None)
        self.assertTrue(self.denied(MERGE))
        (self.loop / "s1" / "receipts" / "a.json").unlink()
        self.mint(rid="b", key=self.agent_key)
        self.assertTrue(self.denied(MERGE))
        (self.loop / "s1" / "receipts" / "b.json").unlink()
        self.mint(rid="c")
        (self.directory / "home" / ".coderails" / "keys" / "receipt_signers").unlink()
        self.assertTrue(self.denied(MERGE))
        self.assertEqual(
            self.reasons(), ["denied_signature_missing", "denied_signer_unknown", "denied_trust_root_missing"]
        )

    def test_binding_unknown_stale_sha_and_refspec_source(self) -> None:
        """No origin fails closed; a moved HEAD is sha_mismatch; `feature:main` binds feature, not HEAD."""
        self.configure("enforce")
        self.mint("git push origin main", "git_push")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "moved")
        self.assertTrue(self.denied("git push origin main"))
        (self.loop / "s1" / "receipts" / "r1.json").unlink()
        git(self.repo, "branch", "feature")
        command = "git push origin feature:main"
        git(self.repo, "switch", "-q", "feature")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "feature work")
        git(self.repo, "switch", "-q", "main")
        self.mint(command, "git_push", rid="r2", artifact_sha=git(self.repo, "rev-parse", "HEAD"))
        self.assertTrue(self.denied(command))
        self.mint(command, "git_push", rid="r3")
        self.assertFalse(self.denied(command))
        git(self.repo, "remote", "remove", "origin")
        self.assertTrue(self.denied("git push origin main"))
        self.assertEqual(
            self.reasons(),
            [
                "denied_sha_mismatch",
                "denied_sha_mismatch",
                "trust_root_user_tier",
                "receipt_consumed",
                "denied_binding_unknown",
            ],
        )

    def test_enforce_guards_push_on_main_only(self) -> None:
        """A push on main is guarded; on a feature branch it is not."""
        self.configure("enforce")
        self.assertTrue(self.denied("git push origin main"))
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature/x"], check=True)
        self.assertFalse(self.denied("git push origin feature/x"))

    def test_chain_cd_and_dash_c_are_guarded(self) -> None:
        """Chained second op, `cd other && git push` and `git -C . push origin main` all need their own receipt."""
        self.configure("enforce")
        other = make_repo(self.directory / "other")
        git(self.repo, "branch", "feature")
        self.mint("git push origin feature", "git_push")
        self.assertTrue(self.denied("git push origin feature && git push origin main"))
        self.mint("git push origin main", "git_push", rid="r2")
        self.assertTrue(self.denied(f"cd {other} && git push origin main"))
        self.assertTrue(self.denied("git -C . push origin main"))

    def test_env_prefix_global_options_and_moved_refs_are_denied(self) -> None:
        """Negative controls: env prefix, `-c`, and a ref moved earlier in the chain are denied despite a receipt."""
        self.configure("enforce")
        self.mint("git push origin main", "git_push")
        for command in ("GIT_DIR=/x git push origin main", "git -c a=b push origin main",
                        "git branch -f main HEAD~0 && git push origin main"):  # fmt: skip
            self.assertTrue(self.denied(command), command)
        self.assertEqual(self.reasons(), ["denied_binding_unknown"] * 2 + ["denied_state_mutated_before_guard"])
        self.assertFalse(self.denied("git push origin main"))

    def test_missing_session_and_owner_hint(self) -> None:
        """No session_id: a traced no_session denial; the hint gives the optional receipt command."""
        self.configure("enforce")
        result = self.run_hook("git push origin main", session="")
        self.assertIn("no_session", result.stdout)
        self.assertNotIn("--session  ", result.stdout)
        rows = (self.loop / "_no_session" / "trace.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(rows[0])["reason_code"], "denied_no_session")
        self.assertIn("sign one at a terminal", self.run_hook("git push origin main").stdout)

    def test_registered_with_timeout(self) -> None:
        """Appended last to the ^Bash$ group with a timeout of at least 5."""
        group = json.loads((CODEX / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]
        self.assertEqual(group["matcher"], "^Bash$")
        self.assertIn("action_authority_gate.py", group["hooks"][-1]["command"])
        self.assertGreaterEqual(group["hooks"][-1]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
