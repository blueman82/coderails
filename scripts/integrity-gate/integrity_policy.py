"""Mechanical SHA-bound evidence and bounded policy checks for attestation."""

import re
from typing import Protocol

from integrity_evidence import eval_valid, review_valid
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
        """Post a commit status with the workflow's scoped token."""
        ...


def post_current(client: EvidenceClient, number: int, sha: str, state: str, description: str) -> int:
    """Never post a result for a head that moved during evaluation."""
    try:
        current = object_value(client.get_object(f"pulls/{number}").get("head")).get("sha")
        if current != sha:
            print(f"skip: pr={number} sha={sha} reason=head_moved")
            return 1
        client.post_status(sha, state, description)
    except IntegrityError:
        print(f"skip: pr={number} sha={sha} reason=status_post_failed")
        return 1
    return 0


def fail(client: EvidenceClient, number: int, sha: str, reason: str, *, error: bool = False) -> int:
    """Post a current-head refusal; a moved head has no stale status mutation."""
    posted = post_current(
        client, number, sha, "error" if error else "failure", f"integrity=fail sha={sha} reason={reason}"
    )
    return 1 if posted or error else 0


def check_inputs(client: EvidenceClient, number: int, sha: str, body: str, max_bytes: int) -> int:
    """Validate command evidence, policy paths and the bounded diff before success."""
    if not eval_valid(body, number, sha):
        return fail(client, number, sha, "eval_evidence_invalid", error=True)
    try:
        files: list[JsonObject] = []
        for page in range(1, 32):
            batch = client.get_array(f"pulls/{number}/files?per_page=100&page={page}")
            files.extend(batch)
            if len(batch) < 100:
                break
        else:
            return fail(client, number, sha, "file_list_over_limit", error=True)
    except IntegrityError:
        return fail(client, number, sha, "files_fetch_failed", error=True)
    filenames = [item.get("filename") for item in files]
    filenames.extend(item.get("previous_filename") for item in files if item.get("status") == "renamed")
    if not filenames or any(not isinstance(name, str) or not name for name in filenames):
        return fail(client, number, sha, "file_list_invalid", error=True)
    for name in filenames:
        if isinstance(name, str) and re.match(
            r"^(skills/dashboard/|launchd/|scripts/integrity-gate/|scripts/(merge\.py|lib/(config\.py|eval_|integrity_status\.py|review_artifact\.py))|hooks/scripts/lib/pr_merge_gate\.py|packages/codex/scripts/(merge\.py|lib/(config\.py|eval_|integrity_status\.py|review_artifact\.py))|\.github/workflows/|config\.schema\.json$|packages/codex/config\.schema\.json$)",
            name,
        ):
            return fail(client, number, sha, f"policy_path_{name}")
    try:
        diff = client.get(f"pulls/{number}", "application/vnd.github.v3.diff").rstrip("\n")
    except IntegrityError:
        return fail(client, number, sha, "diff_fetch_failed", error=True)
    if not diff or len(diff.encode()) > max_bytes:
        return fail(client, number, sha, "diff_invalid_or_oversize")
    posted = post_current(
        client,
        number,
        sha,
        "success",
        f"integrity=pass sha={sha} evidence=review,eval,commands policy=checked provenance=sha-bound source=actions",
    )
    if not posted:
        print(f"gated: pr={number} sha={sha} state=success integrity=pass")
    return posted


def gate_pr(client: EvidenceClient, number: int, max_bytes: int, pending_ttl: int) -> int:
    """Attest only exact-head evidence and fail closed on live-fetch errors."""
    del pending_ttl
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
            return fail(client, number, sha, "eval_evidence_missing", error=True)
        body = bodies[-1]
        if "result=GO" not in body.splitlines()[0]:
            return fail(client, number, sha, "eval_result_not_go")
        review = f"<!-- coderails-review-summary v1 pr={number} head_sha={sha} -->"
        reviews = [comment for comment in comments if comment.splitlines()[:1] == [review]]
        if not reviews:
            return fail(client, number, sha, "review_evidence_missing", error=True)
        if not review_valid(reviews[-1], number, sha):
            return fail(client, number, sha, "review_evidence_invalid", error=True)
        return check_inputs(client, number, sha, body, max_bytes)
    except IntegrityError as error:
        print(f"skip: pr={number} sha={sha} reason={error}")
        return 1
