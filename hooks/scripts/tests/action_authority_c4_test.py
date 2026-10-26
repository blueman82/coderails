"""Check mixed repository modes and Git global options in both provider hooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.receipt_hook_case import PUSH, ReceiptHookCase  # noqa: E402
from hooks.scripts.tests.receipt_test_support import make_repo  # noqa: E402

CODEX = ROOT / "packages/codex"


class C4Tests(ReceiptHookCase):
    """Run the same guarded command in the Claude and Codex installs."""

    def denied_by(self, provider: str, command: str, session: str) -> bool:
        """Return the provider's Bash denial for one session."""
        payload = self.payload(command, session)
        if provider == "claude":
            return self.denied("action_authority_gate", payload)
        result = subprocess.run(
            [sys.executable, str(CODEX / "hooks/scripts/action_authority_gate.py")],
            input=json.dumps(payload), capture_output=True, text=True, check=False,
            env=self.environment | {"PLUGIN_ROOT": str(CODEX), "PLUGIN_DATA": str(self.directory / "data")},
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)
        output: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
        return bool(output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")

    def selected_repos(self, first_mode: str, second_mode: str) -> tuple[Path, Path]:
        """Create two source selected repositories with distinct receipt modes."""
        self.configure("off")
        first = make_repo(self.directory / "first")
        second = make_repo(self.directory / "second")
        for repo, mode in ((first, first_mode), (second, second_mode)):
            config = repo / ".coderails/workflow.config.yaml"
            config.parent.mkdir()
            config.write_text(f"action_authority: {mode}\n")
        return first, second

    def test_advisory_push_warns_and_enforce_push_claims(self) -> None:
        """An advisory mismatch never promotes its action to enforce."""
        first, second = self.selected_repos("advisory", "enforce")
        command = f"cd {first} && {PUSH}; cd {second} && {PUSH}"
        for provider, session in (("claude", "s1"), ("codex", "s2")):
            with self.subTest(provider=provider):
                self.mint(
                    "git push --porcelain origin main", "git_push", session=session, cwd=first, rid=f"a-{session}"
                )
                self.mint(PUSH, "git_push", session=session, cwd=second, rid=f"r-{session}")
                self.assertFalse(self.denied_by(provider, command, session))
                self.assertEqual(self.reasons(session)[:2], ["trust_root_user_tier", "receipt_consumed"])
                self.assertEqual(self.reasons(session)[2], "advisory_hash_mismatch")
                self.assertFalse((self.loop / session / "receipts" / f"a-{session}.consumed").exists())
                self.assertTrue(self.denied_by(provider, f"cd {second} && {PUSH}", session))

    def test_advisory_authority_denial_keeps_enforce_receipt(self) -> None:
        """A live denial blocks the whole command before any receipt claim."""
        first, second = self.selected_repos("advisory", "enforce")
        command = f"cd {first} && {PUSH}; cd {second} && {PUSH}"
        for provider, session in (("claude", "s1"), ("codex", "s2")):
            with self.subTest(provider=provider):
                self.mint(PUSH, "git_push", session=session, cwd=second, rid=f"r-{session}")
                self.grant(denied=["push_main"], session_id=session, authority_id=f"a-{session}")
                self.assertTrue(self.denied_by(provider, command, session))
                self.assertEqual(self.reasons(session)[-1], "denied_authority_denied")
                self.grant(denied=[], session_id=session, authority_id=f"a-{session}")
                self.assertFalse(self.denied_by(provider, f"cd {second} && {PUSH}", session))

    def test_later_enforce_refusal_keeps_earlier_receipt(self) -> None:
        """A second enforce failure leaves the first valid receipt unused."""
        first, second = self.selected_repos("enforce", "enforce")
        command = f"cd {first} && {PUSH}; cd {second} && {PUSH}"
        for provider, session in (("claude", "s1"), ("codex", "s2")):
            with self.subTest(provider=provider):
                self.mint(PUSH, "git_push", session=session, cwd=first, rid=f"r-{session}")
                self.assertTrue(self.denied_by(provider, command, session))
                self.assertNotIn("receipt_consumed", self.reasons(session))
                self.assertFalse(self.denied_by(provider, f"cd {first} && {PUSH}", session))

    def test_no_pager_dash_c_binds_but_config_option_does_not(self) -> None:
        """A harmless Git option keeps the target; -c is still unbindable."""
        self.configure("enforce")
        selected = f"git --no-pager -C '{self.repo}' push origin main"
        for provider, session in (("claude", "s1"), ("codex", "s2")):
            with self.subTest(provider=provider):
                self.assertTrue(self.denied_by(provider, selected, session))
                self.assertEqual(self.reasons(session), ["denied_no_receipt"])
                self.assertTrue(self.denied_by(provider, "git -c a=b push origin main", session))
                self.assertEqual(self.reasons(session)[-1], "denied_binding_unknown")


if __name__ == "__main__":
    import unittest

    unittest.main()
