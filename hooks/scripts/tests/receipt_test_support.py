"""Real ssh-keygen fixtures for signed-receipt tests: the test plays the owner (empty passphrase, temp dirs)."""

from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import action_receipt as ar
from scripts.lib import receipt_signing as rs

ORIGIN = "https://github.com/acme/widgets.git"
REPOSITORY = "github.com/acme/widgets"


def make_owner(directory: Path, name: str = "receipt_ed25519", passphrase: str = "") -> tuple[Path, Path]:
    """Create a key and a signers file naming it as the owner; return (private key, signers file)."""
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-C", rs.PRINCIPAL, "-f", str(key)],
        check=True, capture_output=True,
    )  # fmt: skip
    signers = directory / f"{name}_signers"
    pub = key.with_name(key.name + ".pub").read_text().strip()
    signers.write_text(f'{rs.PRINCIPAL} namespaces="{rs.NAMESPACE}" {pub}\n')
    return key, signers


def git(cwd: Path, *args: str) -> str:
    """Run git in cwd and return stdout."""
    cmd = ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def make_repo(path: Path, origin: str = ORIGIN) -> Path:
    """A repo on main with one commit and the given origin URL (never contacted)."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "remote", "add", "origin", origin)
    git(path, "commit", "-q", "--allow-empty", "-m", "one")
    return path


def signed_receipt(
    key: Path, kind: str, command: str, cwd: str, branch: str, bind: dict[str, str] | None, session: str = "s1",
    now: datetime | None = None, /, **over: object,
) -> dict[str, Any]:  # fmt: skip
    """A valid receipt for the exact action, signed with `key`; overrides are applied BEFORE signing."""
    now = now or datetime.now(timezone.utc)
    proposed = ar.proposed_action(kind, command, cwd, branch, bind)
    obj: dict[str, Any] = {
        "receipt_id": str(uuid.uuid4()), "authority_id": None, "session_id": session, "loop_id": None,
        "action": kind, "exact_payload_hash": proposed["exact_payload_hash"], "repository": proposed["repository"],
        "ref": proposed["ref"], "artifact_sha": proposed["artifact_sha"], "nonce": uuid.uuid4().hex, "scope": "",
        "issued_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(),
        "single_use": True, "revoked": False, "signature": None,
    }  # fmt: skip
    obj.update(over)
    if "signature" not in over:  # an explicit signature (even None) is kept: that is how unsigned receipts are built
        obj["signature"] = rs.sign(ar.body_text(obj), key)
    return obj


def store(base: Path, obj: dict[str, Any], session: str | None = None) -> Path:
    """Write the receipt under `session` (default: its own session_id) and return its path."""
    path = ar.receipt_path(session or obj["session_id"], obj["receipt_id"], base)
    assert path is not None and ar.write_receipt(path, obj)
    return path
