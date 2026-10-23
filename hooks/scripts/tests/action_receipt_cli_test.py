#!/usr/bin/env python3
"""Pin the owner-run receipt CLI and key tool: signed mint, no-tty refusal, revoke/inspect, key setup."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_test_support import REPOSITORY, git, make_owner, make_repo
from scripts import action_receipt_cli as cli
from scripts import authority_keys as keys
from scripts.lib import action_binding as ab
from scripts.lib import action_receipt as ar
from scripts.lib import receipt_signing as rs

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "scripts" / "action_receipt_cli.py"
PUSH = "git push origin feature:main"


class CliTests(unittest.TestCase):
    """The CLI mints, inspects and revokes against an isolated loop dir and a test-owned key."""

    tmp: tempfile.TemporaryDirectory[str]
    key: Path
    signers: Path
    agent_key: Path
    repo: Path
    feature: str

    @classmethod
    def setUpClass(cls) -> None:
        """Owner key, agent key, repo with a feature branch."""
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        cls.key, cls.signers = make_owner(base / "owner")
        cls.agent_key, _ = make_owner(base / "agent")
        cls.repo = make_repo(base / "repo")
        git(cls.repo, "switch", "-q", "-c", "feature")
        git(cls.repo, "commit", "-q", "--allow-empty", "-m", "two")
        cls.feature = git(cls.repo, "rev-parse", "feature")

    def setUp(self) -> None:
        """Isolated loop dir."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def approve(self, *extra: str, command: str = PUSH, key: Path | None = None) -> tuple[int, str, str]:
        """Run approve-action in-process with a terminal present (tests only): (rc, stdout, stderr)."""
        argv = [
            *("approve-action", "--session", "s1", "--loop", "L1", "--kind", "git_push", "--command", command),
            *("--cwd", str(self.repo), "--key", str(key or self.key), "--signers", str(self.signers)),
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv, tty_ok=lambda: True)
        return code, out.getvalue(), err.getvalue()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the CLI as a subprocess with no controlling terminal."""
        env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": str(self.base)}
        return subprocess.run(
            [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, start_new_session=True
        )

    def reasons(self, session: str = "s1") -> list[str]:
        """Reason codes traced for a session."""
        path = self.base / session / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_mint_computes_binding_and_verifies_like_the_hook(self) -> None:
        """The owner never types a SHA: the receipt binds the feature source sha to refs/heads/main, signed."""
        code, out, err = self.approve()
        self.assertEqual(code, 0, err)
        rec = json.loads(out)
        self.assertEqual(
            (rec["repository"], rec["ref"], rec["artifact_sha"]), (REPOSITORY, "refs/heads/main", self.feature)
        )
        self.assertTrue(rec["single_use"] and rec["nonce"] and rec["signature"]["sig"])
        bind = ab.binding("git_push", PUSH, str(self.repo))
        same = ar.proposed_action("git_push", PUSH, str(self.repo), "feature", bind)
        found, why = ar.find_valid("s1", same, datetime.now(timezone.utc), "L1", self.base, True, self.signers)
        self.assertEqual((found and found["receipt_id"], why), (rec["receipt_id"], "ok"))
        other = ar.proposed_action("git_push", "git push origin feature:release", str(self.repo), "feature", bind)
        self.assertEqual(ar.find_valid("s1", other, datetime.now(timezone.utc), "L1", self.base)[0], None)
        self.assertEqual(self.reasons(), ["receipt_approved"])

    def test_merge_binding_uses_live_pr(self) -> None:
        """A merge receipt binds the PR base ref and live head sha from pr_view."""
        with mock.patch.object(ab, "pr_view", return_value=("main", "d" * 40)):
            command = f"gh pr merge 5 --match-head-commit {'d' * 40}"
            argv = ["approve-action", "--session", "s1", "--kind", "merge", "--command", command,
                    "--cwd", str(self.repo), "--key", str(self.key), "--signers", str(self.signers)]  # fmt: skip
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(argv, tty_ok=lambda: True), 0)
        rec = json.loads(out.getvalue())
        self.assertEqual((rec["ref"], rec["artifact_sha"]), ("refs/heads/main", "d" * 40))

    def test_unknowable_binding_and_untrusted_key_are_refused(self) -> None:
        """No binding, an agent-made key, and an over-long scope are refused with stable codes and no receipt."""
        self.assertEqual(self.approve(command="git push --all")[0], 2)
        self.assertEqual(self.approve(key=self.agent_key)[0], 2)
        self.assertEqual(self.approve("--scope", "x" * 5000)[0], 2)
        self.assertEqual(
            self.reasons(),
            ["receipt_refused_binding_unknown", "receipt_refused_signer_unknown", "receipt_refused_scope_too_long"],
        )
        self.assertFalse(list((self.base / "s1").glob("receipts/*.json")))

    def test_invalid_expiry_is_refused_before_signing(self) -> None:
        """Nonpositive, nonfinite and overflowing durations never create a receipt."""
        for hours in ("0", "-1", "nan", "inf", "1e300"):
            with self.subTest(hours=hours):
                code, _, err = self.approve("--expires-in-hours", hours)
                self.assertEqual(code, 2, err)
                self.assertIn("receipt_refused_expiry_invalid", err)
        self.assertFalse(list((self.base / "s1").glob("receipts/*.json")))

    def test_receipt_cap(self) -> None:
        """The 51st receipt of a session is refused."""
        for _ in range(ar.MAX_RECEIPTS):
            self.assertEqual(self.approve()[0], 0)
        self.assertEqual(self.approve()[0], 2)
        self.assertEqual(self.reasons()[-1], "receipt_refused_too_many")

    def test_no_tty_refuses_to_mint(self) -> None:
        """(f) A subprocess with no controlling terminal exits 2 with receipt_refused_no_tty and writes nothing."""
        result = self.run_cli(
            "approve-action", "--session", "s1", "--kind", "git_push", "--command", PUSH, "--cwd", str(self.repo),
            "--key", str(self.key), "--signers", str(self.signers),
        )  # fmt: skip
        self.assertEqual(result.returncode, 2)
        self.assertIn("receipt_refused_no_tty", result.stderr)
        self.assertEqual(self.reasons(), ["receipt_refused_no_tty"])
        self.assertFalse(list((self.base / "s1").glob("receipts/*.json")))

    def test_no_tty_refusal_does_not_depend_on_the_key(self) -> None:
        """An unencrypted owner key does not relax the rule: the tty is demanded regardless; no flag skips it."""
        result = self.run_cli("approve-action", "--session", "s1", "--kind", "git_push", "--command", PUSH,
                              "--cwd", str(self.repo), "--key", str(self.key))  # fmt: skip
        self.assertIn("receipt_refused_no_tty", result.stderr)
        for flag in ("--reusable", "--artifact-sha=" + "a" * 40, "--tty-ok", "--no-tty-check"):
            bad = self.run_cli("approve-action", "--session", "s1", "--kind", "git_push", "--command", PUSH, flag)
            self.assertEqual(bad.returncode, 2)
            self.assertNotIn("receipt_approved", self.reasons())
        self.assertNotIn("environ", (REPO / "scripts/action_receipt_cli.py").read_text())

    def test_inspect_then_revoke_then_refused(self) -> None:
        """Revoke leaves the receipt inspectable, verification then says revoked, a second revoke is refused."""
        rid = json.loads(self.approve()[1])["receipt_id"]
        shown = json.loads(self.run_cli("inspect-receipt", "--session", "s1", "--receipt-id", rid).stdout)
        self.assertFalse(shown["consumed"])
        self.assertEqual(self.run_cli("revoke-receipt", "--session", "s1", "--receipt-id", rid).returncode, 0)
        bind = ab.binding("git_push", PUSH, str(self.repo))
        same = ar.proposed_action("git_push", PUSH, str(self.repo), "feature", bind)
        got = ar.find_valid("s1", same, datetime.now(timezone.utc), "L1", self.base, False, self.signers)
        self.assertEqual(got, (None, "revoked"))
        self.assertEqual(self.run_cli("revoke-receipt", "--session", "s1", "--receipt-id", rid).returncode, 2)
        self.assertIn("receipt_refused_already_revoked", self.reasons())

    def test_foreign_missing_and_unsafe_ids_refused(self) -> None:
        """A copied receipt, an unknown id and a path-unsafe session are refused with stable codes."""
        rid = json.loads(self.approve()[1])["receipt_id"]
        foreign = self.base / "s2" / "receipts"
        foreign.mkdir(parents=True)
        (foreign / f"{rid}.json").write_text((self.base / "s1" / "receipts" / f"{rid}.json").read_text())
        result = self.run_cli("inspect-receipt", "--session", "s2", "--receipt-id", rid)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(rid, result.stdout)
        self.assertIn("receipt_refused_foreign_session", self.reasons("s2"))
        self.assertEqual(self.run_cli("inspect-receipt", "--session", "s1", "--receipt-id", "nope").returncode, 2)
        self.assertIn("receipt_refused_missing", self.reasons())
        self.assertIn(
            "receipt_refused_unsafe_id",
            self.run_cli("inspect-receipt", "--session", "../x", "--receipt-id", "r").stderr,
        )

    def test_oversized_receipt_file_is_malformed(self) -> None:
        """A hand-written huge receipt is never parsed."""
        path = ar.receipt_path("s1", "big", self.base)
        assert path is not None
        path.parent.mkdir(parents=True)
        path.write_text('{"scope": "' + "x" * (ar.MAX_RECEIPT_BYTES + 1) + '"}')
        self.assertIsNone(ar.read_receipt(path))


class AuthorityKeysTests(unittest.TestCase):
    """init/install-root/show: owner-run key setup that never runs sudo and never overwrites."""

    def setUp(self) -> None:
        """Temp key directory."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "keys"

    def test_init_refuses_without_tty_and_creates_nothing(self) -> None:
        """No terminal: exit 2 and no key directory."""
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(keys.init(self.dir, tty_ok=lambda: False), 2)
        self.assertIn("receipt_refused_no_tty", err.getvalue())
        self.assertFalse(self.dir.exists())

    def test_init_show_and_never_overwrites(self) -> None:
        """With a terminal the key and the signers file are made, show prints fingerprints, a rerun refuses."""
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(keys.init(self.dir, tty_ok=lambda: True, extra=("-q", "-N", "")), 0)
        self.assertIn("cooperating-agent safeguard", out.getvalue())
        signers = self.dir / "receipt_signers"
        self.assertIn(f'{rs.PRINCIPAL} namespaces="{rs.NAMESPACE}" ssh-ed25519', signers.read_text())
        block = rs.sign("b", self.dir / "receipt_ed25519")
        self.assertEqual(rs.check("b", block, signers), "ok")
        with contextlib.redirect_stdout(io.StringIO()) as shown:
            keys.show(self.dir)
        self.assertIn("SHA256:", shown.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(keys.init(self.dir, tty_ok=lambda: True, extra=("-q", "-N", "")), 2)
        self.assertIn("key_exists", err.getvalue())

    def test_install_root_only_prints(self) -> None:
        """The sudo commands are printed for the owner; nothing is installed here."""
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(keys.install_root(self.dir), 0)
        text = out.getvalue()
        self.assertIn("sudo install", text)
        self.assertIn("/Library/Application Support/Coderails/receipt_signers", text)
        self.assertNotIn(
            "subprocess",
            (REPO / "scripts/authority_keys.py").read_text().split("def install_root")[1].split("def _quote")[0],
        )


if __name__ == "__main__":
    unittest.main()
