#!/usr/bin/env python3
"""Pin receipt signing with REAL ssh-keygen in temp dirs: signature outcomes, trust-root tiers, no-tty minting."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_test_support import make_owner
from scripts.lib import receipt_signing as rs

ROOT = Path(__file__).resolve().parents[3]


class SignatureTests(unittest.TestCase):
    """check() maps every failure to its own stable code."""

    tmp: tempfile.TemporaryDirectory[str]
    key: Path
    signers: Path
    agent_key: Path

    @classmethod
    def setUpClass(cls) -> None:
        """One owner key and one unrelated agent key."""
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        cls.key, cls.signers = make_owner(base / "owner")
        cls.agent_key, _ = make_owner(base / "agent")

    def test_valid_and_tampered(self) -> None:
        """A good signature is ok; a changed body is signature_invalid."""
        block = rs.sign("body", self.key)
        self.assertEqual(rs.check("body", block, self.signers), "ok")
        self.assertEqual(rs.check("body!", block, self.signers), "signature_invalid")

    def test_agent_made_key_is_signer_unknown(self) -> None:
        """A valid signature by a key outside the signers file is signer_unknown, under any claimed principal."""
        for signer in (rs.PRINCIPAL, "agent"):
            block = rs.sign("body", self.agent_key, signer)
            self.assertEqual(rs.check("body", block, self.signers), "signer_unknown")

    def test_missing_malformed_and_no_trust_root(self) -> None:
        """No block, odd blocks, unsafe principal and an absent signers file."""
        block = rs.sign("body", self.key)
        self.assertEqual(rs.check("body", None, self.signers), "signature_missing")
        for odd in ("x", {}, {"signer": "a"}, {**block, "extra": 1}, {**block, "signer": "a b"}, {**block, "sig": ""}):
            self.assertEqual(rs.check("body", odd, self.signers), "signature_invalid", odd)
        self.assertEqual(rs.check("body", block, None), "trust_root_missing")
        self.assertEqual(rs.check("body", block, Path(self.tmp.name) / "nope"), "trust_root_missing")


class TrustRootTests(unittest.TestCase):
    """Two tiers: a genuinely root-owned file wins; otherwise the user tier, labelled; otherwise missing."""

    def setUp(self) -> None:
        """Temp root-tier and user-tier files."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "root_signers"
        self.user = Path(tmp.name) / "user_signers"
        self.root.write_text("x\n")

    @staticmethod
    def stat(uid: int, mode: int = 0o644) -> Callable[[str], Any]:
        """A fake os.stat."""
        return lambda _path: SimpleNamespace(st_uid=uid, st_mode=mode)

    def test_root_tier_needs_root_ownership(self) -> None:
        """Uid 0 and not group/other writable is honoured; a non-root owner or a writable mode is ignored."""
        self.user.write_text("y\n")
        self.assertEqual(rs.resolve_trust_root(self.root, self.user, self.stat(0)), (self.root, rs.ROOT_TIER))
        for fake in (self.stat(501), self.stat(0, 0o664), self.stat(0, 0o666)):
            self.assertEqual(rs.resolve_trust_root(self.root, self.user, fake), (self.user, "trust_root_user_tier"))

    def test_every_ancestor_must_be_root_owned(self) -> None:
        """Negative control: a root-owned file under a user-owned ancestor directory is not the root tier."""
        self.user.write_text("y\n")

        user_owned = str(self.root.parent.parent)  # an ancestor of the file and of its directory

        def stat(path: str) -> SimpleNamespace:
            """Everything root-owned except one ancestor."""
            return SimpleNamespace(st_uid=501 if path == user_owned else 0, st_mode=0o644)

        self.assertEqual(rs.resolve_trust_root(self.root, self.user, stat), (self.user, "trust_root_user_tier"))
        self.assertEqual(rs.resolve_trust_root(self.root, self.user, self.stat(0)), (self.root, rs.ROOT_TIER))

    def test_user_tier_label_and_missing(self) -> None:
        """Without a root tier the user file is used and labelled; with neither the answer is trust_root_missing."""
        self.root.unlink()
        self.user.write_text("y\n")
        self.assertEqual(rs.resolve_trust_root(self.root, self.user), (self.user, "trust_root_user_tier"))
        self.user.unlink()
        self.assertEqual(rs.resolve_trust_root(self.root, self.user), (None, "trust_root_missing"))

    def test_no_environment_override(self) -> None:
        """The default user tier follows HOME only; the module never reads os.environ."""
        self.assertNotIn("os.environ", (ROOT / "scripts/lib/receipt_signing.py").read_text())
        with mock.patch.object(Path, "home", return_value=Path("/nonexistent-home")):
            self.assertEqual(rs.user_signers(), Path("/nonexistent-home/.coderails/keys/receipt_signers"))


class AgentMintingTests(unittest.TestCase):
    """A passphrase-protected key cannot sign without a tty; an agent-made key signs but is not trusted."""

    def test_passphrase_key_cannot_sign_without_tty(self) -> None:
        """Real `ssh-keygen -Y sign` on a passphrase key in a session with no controlling terminal fails."""
        with tempfile.TemporaryDirectory() as tmp:
            key, _ = make_owner(Path(tmp), passphrase="correct horse")
            done = subprocess.run(
                ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", rs.NAMESPACE],
                input="body", capture_output=True, text=True, start_new_session=True, timeout=30, check=False,
            )  # fmt: skip
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(done.stdout, "")

    def test_have_tty_false_without_controlling_terminal(self) -> None:
        """In a new session /dev/tty cannot be opened, which is what the minting CLI keys on."""
        code = (
            f"import sys; sys.path.insert(0, {str(ROOT)!r});"
            "from scripts.lib.receipt_signing import have_tty; print(have_tty())"
        )
        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, start_new_session=True, check=False
        )
        self.assertEqual(done.stdout.strip(), "False")


class CounterTests(unittest.TestCase):
    """trust_summary counts signature, trust-root and binding refusals from trace counts."""

    def test_trust_summary(self) -> None:
        """denied_/advisory_ prefixes are folded; unrelated commands and codes are ignored."""
        from scripts.lib.receipt_counters import trust_summary

        got = trust_summary({
            "action_authority/denied/denied_signature_missing": 2,
            "action_authority/advisory/advisory_signer_unknown": 1,
            "action_authority/allowed/trust_root_user_tier": 4,
            "action_authority/denied/denied_sha_mismatch": 3,
            "action_receipt/refused/receipt_refused_no_tty": 5,
            "other/denied/denied_signature_missing": 9,
            "action_authority/denied/denied_no_receipt": 7,
        })  # fmt: skip
        self.assertEqual(
            {k: v for k, v in got.items() if v},
            {"signature_missing": 2, "signer_unknown": 1, "trust_root_user_tier": 4, "sha_mismatch": 3,
             "receipt_refused_no_tty": 5},
        )  # fmt: skip


class CounterCliTests(unittest.TestCase):
    """receipt_counters has a CLI over measure_graph_alignment's trace.by_reason, like manifest_counters."""

    def test_cli_prints_receipt_and_trust_summaries(self) -> None:
        """Piped by_reason in, JSON receipts + trust out; the new state_mutated_before_guard code is counted."""
        rows = {"trace": {"by_reason": {"action_authority/denied/denied_state_mutated_before_guard": 2}}}
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/lib/receipt_counters.py")], input=json.dumps(rows),
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        out = json.loads(done.stdout)
        self.assertEqual(out["trust"]["state_mutated_before_guard"], 2)
        self.assertEqual(out["receipts"]["by_outcome"], {"denied": 2})


class DocsTests(unittest.TestCase):
    """The honest limit is written where readers look, and the mechanism is not oversold."""

    def test_cooperating_agent_safeguard_wording(self) -> None:
        """The decision record, AGENTS.md and the RUNBOOK say 'cooperating-agent safeguard'; residuals are listed."""
        record = (ROOT / "docs/decisions/p3-human-only-minting.md").read_text()
        for text in (record, (ROOT / "AGENTS.md").read_text(), (ROOT / "docs/RUNBOOK.md").read_text()):
            self.assertIn("cooperating-agent safeguard", text)
        for residual in ("agent-writable", "Accessibility", "NOT verified", "command text the hook sees",
                         ".consumed", "fills the receipts directory", "fails open", "default ON"):  # fmt: skip
            self.assertIn(residual, record)


if __name__ == "__main__":
    unittest.main()
