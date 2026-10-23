"""The single parser for the integrity-review attestation (the only place that knows `integrity=pass` / `sha=`)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

CODES = ("attest_missing", "attest_not_success", "attest_wrong_creator", "attest_not_bound")


@dataclass(frozen=True)
class Attestation:
    """Verdict on one commit status: `ok` or exactly one closed `reason_code`."""

    ok: bool
    reason_code: str
    detail: str


def format_attestation(sha: str, extra: str = "") -> str:
    """Render the description the root-owned daemon writes, so writer and parser round-trip."""
    base = f"integrity=pass sha={sha}"
    return f"{base} {extra}" if extra else base


def _token(description: str, token: str) -> bool:
    return re.search(r"(^|\s)" + re.escape(token) + r"(\s|$)", description) is not None


def parse_attestation(status: Mapping[str, Any] | None, sha: str, machine_user: str) -> Attestation:
    """Check the newest status: present, success, posted by `machine_user`, bound to `sha`."""
    state = status.get("state") if isinstance(status, Mapping) else None
    if not state:
        return Attestation(False, "attest_missing", f"no integrity-review status found for {sha}")
    assert isinstance(status, Mapping)
    if state != "success":
        return Attestation(False, "attest_not_success", f"integrity-review status for {sha} is '{state}'")
    creator: object = status.get("creator")
    login = cast("Mapping[str, Any]", creator).get("login", "") if isinstance(creator, Mapping) else ""
    if login != machine_user:
        return Attestation(False, "attest_wrong_creator", f"posted by '{login}', not machine user '{machine_user}'")
    description = status.get("description")
    bound = isinstance(description, str) and _token(description, "integrity=pass") and _token(description, f"sha={sha}")
    if not bound:
        return Attestation(False, "attest_not_bound", f"integrity-review status for {sha} is not a SHA-bound pass")
    return Attestation(True, "ok", "")
