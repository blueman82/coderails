#!/usr/bin/env python3
"""Receipt signatures over `ssh-keygen -Y sign/verify` (namespace coderails-receipt).

The user-tier signers file is writable by the same user as the agent. It is a cooperating-agent safeguard,
not an independent approval boundary. A missing signers file gives trust_root_missing.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

NAMESPACE = "coderails-receipt"
PRINCIPAL = "coderails-owner"
USER_TIER, MISSING = "trust_root_user_tier", "trust_root_missing"
_SIGNER = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


class SigningError(Exception):
    """A signing refusal carrying a stable reason code."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Keep the code beside the message."""
        super().__init__(detail or code)
        self.code = code


def keys_dir() -> Path:
    """The user-tier directory (key pair and signers file)."""
    return Path.home() / ".coderails" / "keys"


def user_signers() -> Path:
    """The user-tier signers file."""
    return keys_dir() / "receipt_signers"


def resolve_trust_root(user: Path | None = None) -> tuple[Path | None, str]:
    """Return the user-tier signers file when present, or a missing-trust-root reason."""
    user = user or user_signers()
    return (user, USER_TIER) if user.is_file() else (None, MISSING)


def _run(args: list[str], stdin: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise SigningError("sign_failed", f"ssh-keygen unavailable: {error}") from error


def sign(text: str, key: Path, signer: str = PRINCIPAL, timeout: float = 300) -> dict[str, str]:
    """Sign text with the private key at `key`; an encrypted key makes ssh-keygen prompt on /dev/tty."""
    done = _run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", NAMESPACE], text, timeout)
    if done.returncode or not done.stdout:
        raise SigningError("sign_failed", f"ssh-keygen sign failed: {done.stderr.strip()}")
    return {"signer": signer, "sig": done.stdout}


def check(text: str, block: object, signers: Path | None) -> str:
    """ok, or signature_missing | signature_invalid | trust_root_missing | signer_unknown."""
    if block is None:
        return "signature_missing"
    fields = cast("dict[str, Any]", block) if isinstance(block, dict) else {}
    armored, signer = fields.get("sig"), fields.get("signer")
    if set(fields) != {"signer", "sig"} or not isinstance(armored, str) or not armored:
        return "signature_invalid"
    if not isinstance(signer, str) or not _SIGNER.match(signer):
        return "signature_invalid"
    if signers is None or not signers.is_file():
        return MISSING
    with tempfile.TemporaryDirectory() as scratch:
        sig = Path(scratch) / "body.sig"
        try:
            sig.write_bytes(armored.encode("ascii"))
            if _run(["ssh-keygen", "-Y", "check-novalidate", "-n", NAMESPACE, "-s", str(sig)], text).returncode:
                return "signature_invalid"
            trusted = _run(
                ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", signer, "-n", NAMESPACE, "-s", str(sig)],
                text,
            )
        except UnicodeEncodeError:
            return "signature_invalid"
        except SigningError:
            return MISSING
    return "signer_unknown" if trusted.returncode else "ok"


def have_tty() -> bool:
    """True when this process can open its controlling terminal (what ssh-keygen needs to ask a passphrase)."""
    try:
        os.close(os.open("/dev/tty", os.O_RDWR))
    except OSError:
        return False
    return True
