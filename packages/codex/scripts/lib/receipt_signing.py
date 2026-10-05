#!/usr/bin/env python3
"""Receipt signatures over `ssh-keygen -Y sign/verify` (namespace coderails-receipt) and the two-tier trust root.

Trust root tiers, in order:
  root  /Library/Application Support/Coderails/receipt_signers - honoured only when the file and its directory are
        owned by uid 0 and not group/other writable. Owner-installed with sudo; this is the real boundary.
  user  ~/.coderails/keys/receipt_signers - writable by the same user as the agent, so it is a
        cooperating-agent safeguard only (traced as trust_root_user_tier), not a boundary.
Neither present: trust_root_missing (deny). There is deliberately NO environment-variable override of the trust
root: an env knob would be a bypass. Callers and tests pass the path as an argument.
The owner key is passphrase-protected; ssh-keygen asks on /dev/tty, so an agent without a tty cannot sign.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, cast

NAMESPACE = "coderails-receipt"
PRINCIPAL = "coderails-owner"
ROOT_SIGNERS = Path("/Library/Application Support/Coderails/receipt_signers")
ROOT_TIER, USER_TIER, MISSING = "trust_root_root_tier", "trust_root_user_tier", "trust_root_missing"
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


def _root_owned(path: Path, stat: Callable[[str], Any]) -> bool:
    try:  # the file and EVERY ancestor directory: a user-writable ancestor could swap the root-owned directory
        return all(s.st_uid == 0 and not s.st_mode & 0o022 for s in map(stat, map(str, (path, *path.parents))))
    except OSError:
        return False


def resolve_trust_root(
    root: Path = ROOT_SIGNERS, user: Path | None = None, stat: Callable[[str], Any] = os.stat
) -> tuple[Path | None, str]:
    """(signers file, tier reason): the root tier when genuinely root-owned, else the user tier, else missing."""
    if root.is_file() and _root_owned(root, stat):
        return root, ROOT_TIER
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
        sig.write_text(armored)
        try:
            if _run(["ssh-keygen", "-Y", "check-novalidate", "-n", NAMESPACE, "-s", str(sig)], text).returncode:
                return "signature_invalid"
            trusted = _run(
                ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", signer, "-n", NAMESPACE, "-s", str(sig)],
                text,
            )
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
