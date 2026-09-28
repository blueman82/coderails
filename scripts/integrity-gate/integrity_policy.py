"""Mechanical SHA-bound evidence and bounded policy checks for attestation."""

import json
import re
from datetime import datetime, timezone
from typing import Protocol

from integrity_http import IntegrityError, JsonObject, object_value


class EvidenceClient(Protocol):
    """REST operations consumed by the mechanical policy."""

    def get_object(self, target: str) -> JsonObject:
        """Fetch one JSON object."""
        ...

    def get_array(self, target: str) -> list[JsonObject]:
        """Fetch an array of JSON objects."""
        ...

    def get(self, target: str, accept: str = "application/vnd.github+json") -> str:
        """Fetch a checked HTTP body."""
        ...

    def comments(self, number: int) -> list[str]:
        """Fetch all comment bodies in server order."""
        ...

    def post_status(self, sha: str, state: str, description: str) -> None:
        """Post a status only with a live verified machine identity."""
        ...


def should_gate(statuses: list[JsonObject], pending_ttl: int) -> bool:
    """Consider fresh heads and retry expired pending statuses, preserving terminal ones."""
    if not statuses:
        return True
    newest = statuses[0]
    if newest.get("state") != "pending":
        return False
    created = newest.get("created_at")
    if not isinstance(created, str):
        return False
    try:
        instant = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - instant).total_seconds() >= pending_ttl


def valid_evidence(body: str, sha: str) -> bool:
    """Check the first embedded JSON object's schema and exact head binding."""
    match = re.search(r"^```json\s*\n(.*?)^```\s*$", body, re.MULTILINE | re.DOTALL)
    if not match:
        return False
    try:
        value = object_value(json.loads(match[1]))
    except (ValueError, IntegrityError):
        return False
    version = value.get("schema_version")
    return (
        isinstance(version, (int, float))
        and not isinstance(version, bool)
        and version >= 1
        and isinstance(value.get("task_ref"), str)
        and isinstance(value.get("frozen_sha"), str)
        and value.get("head_sha") == sha
        and isinstance(value.get("evals"), list)
    )


def fail(client: EvidenceClient, sha: str, reason: str, *, error: bool = False) -> int:
    """Post the mechanical refusal with its original retry-status semantics."""
    client.post_status(sha, "error" if error else "failure", f"integrity=fail sha={sha} reason={reason}")
    return 1 if error else 0


def check_inputs(client: EvidenceClient, number: int, sha: str, body: str, max_bytes: int) -> int:
    """Validate command evidence, policy paths and the bounded diff before success."""
    if not valid_evidence(body, sha):
        return fail(client, sha, "eval_evidence_invalid", error=True)
    try:
        files = client.get_array(f"pulls/{number}/files?per_page=100")
    except IntegrityError:
        return fail(client, sha, "files_fetch_failed", error=True)
    filenames = [item.get("filename") for item in files]
    if not filenames or any(not isinstance(name, str) or not name for name in filenames):
        return fail(client, sha, "file_list_invalid", error=True)
    for name in filenames:
        if isinstance(name, str) and re.match(
            r"^(skills/dashboard/|launchd/|scripts/integrity-gate/|\.github/workflows/)", name
        ):
            return fail(client, sha, f"policy_path_{name}")
    try:
        diff = client.get(f"pulls/{number}", "application/vnd.github.v3.diff").rstrip("\n")
    except IntegrityError:
        return fail(client, sha, "diff_fetch_failed", error=True)
    if not diff or len(diff.encode()) > max_bytes:
        return fail(client, sha, "diff_invalid_or_oversize")
    client.post_status(sha, "pending", f"integrity=pending sha={sha}")
    client.post_status(
        sha,
        "success",
        f"integrity=pass sha={sha} evidence=review,eval,commands "
        "policy=checked provenance=sha-bound independent=machine",
    )
    print(f"gated: pr={number} sha={sha} state=success integrity=pass")
    return 0


def gate_pr(client: EvidenceClient, number: int, max_bytes: int, pending_ttl: int) -> int:
    """Attest only exact-head evidence and fail closed on live-fetch errors."""
    try:
        head = object_value(client.get_object(f"pulls/{number}").get("head"))
        sha = head.get("sha")
    except IntegrityError:
        sha = None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        print(f"skip: pr={number} reason=head_sha_fetch_failed")
        return 1
    try:
        comments = client.comments(number)
        prefix = f"<!-- coderails-eval-summary v1 pr={number} head_sha={sha} "
        bodies = [
            body
            for body in comments
            if any(line.startswith(prefix) and line.endswith(" -->") for line in body.splitlines())
        ]
        if not bodies:
            print(f"skip: pr={number} sha={sha} reason=no_eval_artifact")
            return 0
        statuses = [
            item
            for item in client.get_array(f"commits/{sha}/statuses?per_page=100")
            if item.get("context") == "integrity-review"
        ]
        if not should_gate(statuses, pending_ttl):
            print(f"skip: pr={number} sha={sha} reason=already_terminal_or_fresh_pending")
            return 0
        body = bodies[-1]
        if "result=GO" not in body.splitlines()[0]:
            return fail(client, sha, "eval_result_not_go")
        review = f"<!-- coderails-review-summary v1 pr={number} head_sha={sha} -->"
        if not any(review in comment.splitlines() for comment in client.comments(number)):
            return fail(client, sha, "review_evidence_missing", error=True)
        return check_inputs(client, number, sha, body, max_bytes)
    except IntegrityError as error:
        print(f"skip: pr={number} sha={sha} reason={error}")
        return 1
