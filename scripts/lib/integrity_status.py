"""Verify the newest configured integrity status for an exact head SHA."""

from __future__ import annotations

import json
from typing import cast

from . import git_common as git
from .artifact_io import array_value, object_value
from .integrity_attestation import parse_attestation


def verify_integrity_status(sha: str, expected_login: str = "github-actions[bot]") -> None:
    """Refuse missing, stale, failed or incorrectly attributed attestations."""
    result = git.run(
        "gh",
        "api",
        f"repos/{git.repo()}/commits/{sha}/statuses",
        "--paginate",
        "--jq",
        '[.[] | select(.context == "integrity-review")]',
        check=True,
    )
    decoder = json.JSONDecoder()
    text = result.stdout.lstrip()
    statuses: list[object] = []
    while text:
        page, end = decoder.raw_decode(text)
        if not isinstance(page, list):
            raise git.WorkflowError("Malformed integrity-review status response")
        statuses.extend(array_value(cast(object, page)))
        text = text[end:].lstrip()
    status = statuses[0] if statuses else None
    fields = object_value(cast(object, status)) if isinstance(status, dict) else None
    verdict = parse_attestation(fields, sha, expected_login)
    if not verdict.ok:
        raise git.WorkflowError(f"integrity-review {verdict.reason_code}: {verdict.detail}")
