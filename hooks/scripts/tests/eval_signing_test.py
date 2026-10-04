"""Detached ssh-keygen signatures over frozen eval suites: sign/verify, tamper, downgrade, key handling, traces."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_evals import read_loop_evals_result
from hooks.scripts.tests.lib.post_evals_fixture import ROOT, ArtifactCase, command
from scripts.lib import eval_signing
from scripts.lib.eval_execution import record_smoke
from scripts.lib.eval_integrity import IntegrityError, append_amendment, suite_hash, verify_suite
from scripts.post_evals import grade_loop, main

HAVE_SSH = shutil.which("ssh-keygen") is not None


def code_of(case: unittest.TestCase, call: Callable[[], object]) -> str:
    """Return the reason code of the IntegrityError the call must raise."""
    with case.assertRaises(IntegrityError) as caught:
        call()
    return str(caught.exception.code)


@contextlib.contextmanager
def keys_in(path: str) -> Generator[None]:
    """Point signing at a throwaway keys directory."""
    with patch.dict(os.environ, {"CODERAILS_KEYS_DIR": path}):
        yield


@unittest.skipUnless(HAVE_SSH, "ssh-keygen absent")
class KeyTests(unittest.TestCase):
    """Unit behaviour of eval_signing."""

    def setUp(self) -> None:
        """Fresh keys dir."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keys = str(Path(self.tmp.name) / "keys")
        patcher = patch.dict(os.environ, {"CODERAILS_KEYS_DIR": self.keys})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sign_verify_and_modes(self) -> None:
        """Key is created 0600 and a signature verifies."""
        block = eval_signing.sign("payload")
        self.assertEqual(eval_signing.check(block, "payload"), "verified")
        private = Path(self.keys) / "evals_ed25519"
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertEqual((Path(self.keys) / "allowed_signers").stat().st_mode & 0o777, 0o600)

    def test_tampered_payload(self) -> None:
        """A payload other than the signed one is signature_invalid."""
        block = eval_signing.sign("payload")
        with self.assertRaises(eval_signing.SigningError) as caught:
            eval_signing.check(block, "other")
        self.assertEqual(caught.exception.code, "signature_invalid")

    def test_tampered_signature_bytes(self) -> None:
        """A corrupted signature body is signature_invalid, not signer_unknown."""
        block = eval_signing.sign("payload")
        lines = block["sig"].splitlines()
        lines[2] = lines[2][:-4] + ("AAAA" if not lines[2].endswith("AAAA") else "BBBB")
        with self.assertRaises(eval_signing.SigningError) as caught:
            eval_signing.check({**block, "sig": "\n".join(lines) + "\n"}, "payload")
        self.assertEqual(caught.exception.code, "signature_invalid")

    def test_wrong_key_is_signer_unknown(self) -> None:
        """A valid signature from a key not in allowed_signers is signer_unknown."""
        block = eval_signing.sign("payload")
        with tempfile.TemporaryDirectory() as other, keys_in(other):
            eval_signing.sign("x")  # the verifier trusts only its own key
            with self.assertRaises(eval_signing.SigningError) as caught:
                eval_signing.check(block, "payload")
        self.assertEqual(caught.exception.code, "signer_unknown")

    def test_public_only_verifier(self) -> None:
        """A party holding only allowed_signers verifies without any private key."""
        block = eval_signing.sign("payload")
        with tempfile.TemporaryDirectory() as other, keys_in(other):
            shutil.copy(Path(self.keys) / "allowed_signers", Path(other) / "allowed_signers")
            self.assertEqual(eval_signing.check(block, "payload"), "verified")

    def test_missing_key_is_degraded(self) -> None:
        """No allowed_signers in the verifying environment returns key_missing."""
        block = eval_signing.sign("payload")
        with tempfile.TemporaryDirectory() as empty, keys_in(empty):
            self.assertEqual(eval_signing.check(block, "payload"), "key_missing")

    def test_missing_binary_is_degraded(self) -> None:
        """No ssh-keygen: sign raises key_missing and check degrades."""
        block = eval_signing.sign("payload")
        with patch("scripts.lib.eval_signing.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(eval_signing.check(block, "payload"), "key_missing")
            with self.assertRaises(eval_signing.SigningError) as caught:
                eval_signing.sign("payload")
        self.assertEqual(caught.exception.code, "key_missing")

    def test_loose_private_key_refused(self) -> None:
        """A 0644 private key is refused by sign and check."""
        block = eval_signing.sign("payload")
        os.chmod(Path(self.keys) / "evals_ed25519", 0o644)
        for call in (lambda: eval_signing.check(block, "payload"), lambda: eval_signing.sign("payload")):
            with self.assertRaises(eval_signing.SigningError) as caught:
                call()
            self.assertEqual(caught.exception.code, "key_perms")


@unittest.skipUnless(HAVE_SSH, "ssh-keygen absent")
class SuiteTests(ArtifactCase):
    """Signing wired into the suite lifecycle."""

    def setUp(self) -> None:
        """Freeze a signed suite under throwaway keys."""
        super().setUp()
        self.keys = tempfile.TemporaryDirectory()
        self.addCleanup(self.keys.cleanup)
        patcher = patch.dict(os.environ, {"CODERAILS_KEYS_DIR": self.keys.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data.update(scope="loop")
        self.save()
        record_smoke(self.path)
        self.data = self.reload()

    def amend(self, text: str = "print('v2')") -> None:
        """Edit the oracle and record the amendment, as post_evals amend does."""
        self.data = self.reload()
        self.data["evals"][0]["cmd"] = command(text)
        append_amendment(self.data, "E1", "why", "me")
        self.save()

    def refusal(self, data: dict[str, Any]) -> str:
        """Reason code verify_suite refuses this document with."""
        return code_of(self, lambda: verify_suite(data))

    def test_freeze_signs_and_verifies(self) -> None:
        """Freeze writes a signature that verifies."""
        self.assertEqual(set(self.data["signature"]), {"signer", "payload", "sig"})
        self.assertEqual(verify_suite(self.data), "verified")
        payload = json.loads(self.data["signature"]["payload"])
        self.assertEqual(payload["frozen_hash"], self.data["frozen_hash"])
        self.assertEqual(payload["chain_len"], 0)

    def test_suite_tampered_after_signing(self) -> None:
        """An in-place oracle edit is refused (hash check) and a rewritten hash is refused (signature)."""
        self.data["evals"][0]["cmd"] = command("raise SystemExit(0)")
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload())), "suite_hash_mismatch")
        self.data["frozen_hash"] = suite_hash(self.data)
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload())), "signature_invalid")

    def test_amend_resigns(self) -> None:
        """Each amendment re-signs the new head; the old signature would not verify."""
        old = self.data["signature"]
        self.amend()
        data = self.reload()
        self.assertEqual(verify_suite(data), "verified")
        self.assertNotEqual(data["signature"], old)
        self.assertEqual(json.loads(data["signature"]["payload"])["chain_len"], 1)
        data["signature"] = old
        self.assertEqual(code_of(self, lambda: verify_suite(data)), "signature_invalid")

    def test_truncated_chain_with_consistent_hashes(self) -> None:
        """Dropping the last entry leaves a walkable chain but a different head."""
        self.amend("print(1)")
        self.amend("print(2)")
        data = self.reload()
        data["amendment_chain"].pop()
        data["evals"][0]["cmd"] = command("print(1)")
        self.assertEqual(code_of(self, lambda: verify_suite(data)), "signature_invalid")

    def test_edited_and_reordered_chain(self) -> None:
        """Chain edits and swaps are refused."""
        self.amend("print(1)")
        self.amend("print(2)")
        data = self.reload()
        data["amendment_chain"][0]["reason"] = "rewritten"
        self.assertIn(code_of(self, lambda: verify_suite(data)), ("chain_broken", "signature_invalid"))
        data = self.reload()
        data["amendment_chain"].reverse()
        self.assertIn(code_of(self, lambda: verify_suite(data)), ("chain_broken", "signature_invalid"))

    def test_foreign_identity(self) -> None:
        """A different loop_id or session_id breaks the payload."""
        for key in ("loop_id", "session_id"):
            data = self.reload()
            data[key] = "someone-else"
            self.assertEqual(self.refusal(data), "signature_invalid")

    def test_never_signed_is_legacy_unsigned(self) -> None:
        """A frozen suite with no signature and no signed marker is explicitly legacy_unsigned."""
        data = self.reload()
        del data["signature"]
        self.assertEqual(verify_suite(data), "legacy_unsigned")

    def test_strip_after_grade_is_signature_missing(self) -> None:
        """Downgrade: grading.signed makes a stripped signature an error, never legacy_unsigned."""
        self.assertEqual(grade_loop(self.path), "GO")
        graded = self.reload()
        self.assertTrue(graded["grading"]["signed"])
        self.assertEqual(verify_suite(graded, stamped=True), "verified")
        del graded["signature"]
        self.assertEqual(code_of(self, lambda: verify_suite(graded, stamped=True)), "signature_missing")
        self.data = graded
        self.save()
        self.assertEqual(read_loop_evals_result(self.directory), "TAMPERED:signature_missing")

    def test_grade_adds_identity_and_stays_verified(self) -> None:
        """grade-loop stamps loop/session onto the suite and re-signs so readers still verify."""
        grade_loop(self.path)
        graded = self.reload()
        self.assertEqual(graded["loop_id"], "l")
        self.assertEqual(verify_suite(graded, stamped=True), "verified")
        self.assertEqual(json.loads(graded["signature"]["payload"])["loop_id"], "l")

    def test_require_signatures_refuses_unsigned_and_missing_key(self) -> None:
        """With config requiring signatures, unsigned and key-less environments raise."""
        data = self.reload()
        with patch.object(eval_signing, "required", return_value=True):
            with tempfile.TemporaryDirectory() as empty, keys_in(empty):
                self.assertEqual(code_of(self, lambda: verify_suite(data)), "key_missing")
            stripped = {k: v for k, v in data.items() if k != "signature"}
            self.assertEqual(code_of(self, lambda: verify_suite(stripped)), "signature_missing")

    def test_key_missing_degrades_without_require(self) -> None:
        """No trusted key in the verifying env is a loud non-blocking return."""
        with tempfile.TemporaryDirectory() as empty, keys_in(empty):
            self.assertEqual(verify_suite(self.reload()), "key_missing")

    def test_freeze_without_ssh_keygen_degrades(self) -> None:
        """Freeze still works unsigned, with a trace row and stderr line, when signing is impossible."""
        fresh = self.directory / "fresh"
        fresh.mkdir()
        (fresh / "progress.json").write_text('{"schema_version":3,"session_id":"s","loop_id":"l"}')
        path = fresh / "evals.json"
        skip = ("signature", "frozen_hash")
        path.write_text(json.dumps({k: v for k, v in self.data.items() if k not in skip}))
        err = io.StringIO()
        missing = patch("scripts.lib.eval_signing.subprocess.run", side_effect=FileNotFoundError)
        with missing, contextlib.redirect_stderr(err):
            record_smoke(path)
        frozen = json.loads(path.read_text())
        self.assertIn("frozen_hash", frozen)
        self.assertNotIn("signature", frozen)
        self.assertIn("reason=key_missing", err.getvalue())
        lines = (fresh / "eval_trace.jsonl").read_text().splitlines()
        seen = [(r["command"], r["outcome"], r["reason_code"]) for r in map(json.loads, lines)]
        self.assertIn(("sign", "degraded", "key_missing"), seen)

    def test_torn_amend_never_passes(self) -> None:
        """A crash before re-sign leaves the file untouched; a half-applied amendment fails loudly."""
        self.data = self.reload()
        self.data["evals"][0]["cmd"] = command("print('v2')")
        self.save()
        edited = self.path.read_bytes()
        killed = eval_signing.SigningError("sign_failed", "killed")
        with patch.object(eval_signing, "sign", side_effect=killed), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["amend", str(self.path), "E1", "why", "me"]), 1)
        self.assertEqual(self.path.read_bytes(), edited)  # nothing half-written
        data = self.reload()
        old = data["signature"]
        append_amendment(data, "E1", "why", "me")
        data["signature"] = old  # chain advanced, signature not
        self.assertEqual(code_of(self, lambda: verify_suite(data)), "signature_invalid")

    def test_amend_cannot_launder_a_stripped_signature(self) -> None:
        """Amending a graded suite whose signature was stripped refuses instead of re-signing."""
        grade_loop(self.path)
        data = self.reload()
        del data["signature"]
        self.assertEqual(code_of(self, lambda: append_amendment(data, "E1", "why", "me", "x")), "signature_missing")

    def test_readers_and_trace(self) -> None:
        """Reader maps new codes to TAMPERED and the counter picks up the rows once per event_id."""
        grade_loop(self.path)
        self.assertEqual(read_loop_evals_result(self.directory), "GO")
        data = self.reload()
        data["loop_id"] = "other"
        self.data = data
        self.save()
        self.assertEqual(read_loop_evals_result(self.directory), "TAMPERED:signature_invalid")
        sys.path.insert(0, str(ROOT / "scripts"))
        mga = importlib.import_module("measure_graph_alignment")

        trace = self.directory / "eval_trace.jsonl"
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        keys = {(r["command"], r["outcome"], r["reason_code"]) for r in rows}
        self.assertIn(("sign", "ok", "signed"), keys)
        self.assertIn(("loop-evals-read", "refuse", "signature_invalid"), keys)
        with trace.open("a") as sink:
            sink.write(json.dumps(rows[0]) + "\n")  # duplicate event_id
        counts = cast(dict[str, Any], mga.eval_trace_counts([trace]))
        self.assertEqual(counts["duplicates"], 1)
        self.assertEqual(counts["by_reason"]["loop-evals-read|refuse|signature_invalid"], 1)


if __name__ == "__main__":
    unittest.main()
