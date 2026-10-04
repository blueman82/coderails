"""Detached ssh-keygen -Y signature over a frozen eval suite's head (stdlib + subprocess only).

Detection of edits made without the key; NOT adversary-proof against a same-user agent, which can read the
0600 private key and re-sign. Keys live outside the repo: $CODERAILS_KEYS_DIR or ~/.coderails/keys.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from .config import config_path, config_value
from .eval_trace import emit

NAMESPACE = "coderails-evals"
PRINCIPAL = "coderails-evals"
VERIFIED = "verified"
LEGACY_UNSIGNED = "legacy_unsigned"
KEY_MISSING = "key_missing"
KEY_PERMS = "key_perms"
SIGNATURE_INVALID = "signature_invalid"
SIGNATURE_MISSING = "signature_missing"
SIGNER_UNKNOWN = "signer_unknown"
SIGN_FAILED = "sign_failed"


class SigningError(Exception):
    """A signing refusal carrying a stable reason code."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Keep the code beside the message."""
        super().__init__(detail or code)
        self.code = code


def keys_dir() -> Path:
    """Directory holding the key pair and allowed_signers."""
    return Path(os.environ.get("CODERAILS_KEYS_DIR") or Path.home() / ".coderails" / "keys")


def required() -> bool:
    """True when workflow.config.yaml sets evals.require_signatures: true (default false)."""
    path = config_path()
    return bool(path) and config_value(path, "require_signatures", "evals").lower() == "true"


def _run(args: list[str], stdin: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise SigningError(KEY_MISSING, f"ssh-keygen unavailable: {error}") from error


def _check_perms(private: Path) -> None:
    if private.exists() and private.stat().st_mode & 0o077:
        raise SigningError(KEY_PERMS, f"{private} must be mode 0600")


def _ensure_key() -> Path:
    directory = keys_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = directory / "evals_ed25519"
    if not private.exists():
        made = _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", PRINCIPAL, "-f", str(private)], "")
        if made.returncode:
            raise SigningError(SIGN_FAILED, f"ssh-keygen key creation failed: {made.stderr.strip()}")
    _check_perms(private)
    allowed = directory / "allowed_signers"
    if not allowed.exists():
        public = private.with_name(private.name + ".pub").read_text().strip()
        allowed.write_text(f'{PRINCIPAL} namespaces="{NAMESPACE}" {public}\n')
        allowed.chmod(0o600)
    return private


def sign(text: str) -> dict[str, str]:
    """Sign text with the local key (created on first use); return the stored signature block."""
    private = _ensure_key()
    done = _run(["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", NAMESPACE], text)
    if done.returncode or not done.stdout:
        raise SigningError(SIGN_FAILED, f"ssh-keygen sign failed: {done.stderr.strip()}")
    return {"signer": PRINCIPAL, "payload": text, "sig": done.stdout}


def check(block: object, text: str) -> str:
    """Return VERIFIED or KEY_MISSING (verifier has no ssh-keygen or no allowed_signers); else raise SigningError."""
    fields = cast(dict[str, Any], block) if isinstance(block, dict) else {}
    armored = fields.get("sig")
    if fields.get("payload") != text or not isinstance(armored, str):
        raise SigningError(SIGNATURE_INVALID, "signature block is malformed or signs a different payload")
    _check_perms(keys_dir() / "evals_ed25519")
    allowed = keys_dir() / "allowed_signers"
    if not allowed.is_file():
        return KEY_MISSING
    with tempfile.TemporaryDirectory() as scratch:
        sig = Path(scratch) / "payload.sig"
        sig.write_text(armored)
        try:
            plain = _run(["ssh-keygen", "-Y", "check-novalidate", "-n", NAMESPACE, "-s", str(sig)], text)
        except SigningError:
            return KEY_MISSING
        if plain.returncode:
            raise SigningError(SIGNATURE_INVALID, "signature does not verify")
        trusted = _run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", PRINCIPAL, "-n", NAMESPACE, "-s", str(sig)], text
        )
        if trusted.returncode:
            raise SigningError(SIGNER_UNKNOWN, "signature is valid but its key is not in allowed_signers")
    return VERIFIED


def remember(path: str | Path) -> None:
    """Record on this host (in the keys dir) that this suite path was signed; fail-open, detection aid only."""
    try:
        if not was_signed(path):
            with open(keys_dir() / "signed_suites", "a", encoding="utf-8") as ledger:
                ledger.write(os.path.realpath(path) + "\n")
    except OSError:
        return


def was_signed(path: object) -> bool:
    """True when this host signed a suite at this path, so a later strip is a downgrade, not a legacy suite."""
    try:
        text = (keys_dir() / "signed_suites").read_text(encoding="utf-8")
    except OSError:
        return False
    return path is not None and os.path.realpath(cast(str, path)) in text.splitlines()


def report(path: str | Path, command: str, result: str) -> None:
    """Make a non-verified outcome loud: stderr reason line plus a fail-open trace row (never silent)."""
    if result in (LEGACY_UNSIGNED, KEY_MISSING):
        print(f"eval_signing: reason={result} - suite is not signature-verified here", file=sys.stderr)
        emit(path, command, "legacy" if result == LEGACY_UNSIGNED else "degraded", result)
