"""Verify the newest root-owned integrity status for an exact head SHA."""

from __future__ import annotations

import json
import re
from typing import cast

from . import git_common as git
from .artifact_io import array_value, object_value


def verify_integrity_status(sha: str, machine_user: str) -> None:
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
    if not isinstance(status, dict):
        raise git.WorkflowError(f"No integrity-review status found for {sha}")
    status = object_value(cast(object, status))
    if status.get("state") != "success":
        raise git.WorkflowError(f"integrity-review status for {sha} is not success")
    creator = status.get("creator")
    if not isinstance(creator, dict) or object_value(cast(object, creator)).get("login") != machine_user:
        raise git.WorkflowError(
            f"integrity-review status for {sha} was not posted by configured machine user '{machine_user}'"
        )
    description = str(status.get("description") or "")
    if not re.search(r"(^|\s)integrity=pass(\s|$)", description) or not re.search(
        r"(^|\s)sha=" + re.escape(sha) + r"(\s|$)", description
    ):
        raise git.WorkflowError(f"integrity-review status for {sha} is not a valid SHA-bound pass attestation")
