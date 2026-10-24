"""Mechanical SHA-bound evidence and bounded policy checks for attestation."""

from __future__ import annotations

import re
from contextlib import suppress
from typing import Protocol

from integrity_evidence import eval_valid, review_valid
from integrity_http import IntegrityError, JsonObject, object_value

ATTESTOR_IMPORT_PATHS = frozenset(
    {
        "scripts.py",
        "scripts/__init__.py",
        "scripts/lib.py",
        "scripts/lib/__init__.py",
        "scripts/lib/artifact_io.py",
        "scripts/lib/config.py",
        "scripts/lib/eval_integrity.py",
        "scripts/lib/eval_signing.py",
        "scripts/lib/eval_trace.py",
    }
)
ATTESTOR_IMPORT_STEMS = tuple(path[:-3] for path in ATTESTOR_IMPORT_PATHS if path.endswith(".py"))
ATTESTOR_PACKAGE_PATHS = tuple(f"{stem}/" for stem in ATTESTOR_IMPORT_STEMS if stem.startswith("scripts/lib/"))
PROTECTED_PREFIXES = (
    "scripts/integrity-gate/",
    "scripts/__pycache__/",
    "scripts/lib/__pycache__/",
    ".github/workflows/",
)
STATUS_CONTEXT = "integrity-review"
STATUS_BUDGET = 900
STATUS_CAP = 1000


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

    def comments(self, number: int) -> list[JsonObject]:
        """Fetch all comments with GitHub author metadata in server order."""
        ...

    def owner_login(self) -> str:
        """Fetch the live repository owner login."""
        ...

    def post_status(self, sha: str, state: str, description: str) -> None:
        """Post a commit status with the workflow's scoped token."""
        ...


def owner_bodies(client: EvidenceClient, number: int, owner: str) -> list[str]:
    """Use only comments that GitHub attributes to the repository owner."""
    bodies: list[str] = []
    for comment in client.comments(number):
        user = object_value(comment.get("user"))
        body = comment.get("body")
        if not isinstance(body, str):
            raise IntegrityError("invalid comment body")
        login = user.get("login")
        if not isinstance(login, str):
            raise IntegrityError("invalid comment author")
        if login.casefold() == owner.casefold():
            bodies.append(body)
    return bodies


def main_prs_at_head(client: EvidenceClient, sha: str) -> list[int]:
    """Read every open main PR before posting a SHA-wide passing status."""
    matches: list[int] = []
    for page in range(1, 32):
        batch = client.get_array(f"pulls?state=open&base=main&per_page=100&page={page}")
        if page == 31 and batch:
            raise IntegrityError("open main PR list exceeds 3000 entries")
        for item in batch:
            number = item.get("number")
            head = object_value(item.get("head"))
            base = object_value(item.get("base"))
            head_sha = head.get("sha")
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < 1
                or not isinstance(head_sha, str)
                or not re.fullmatch(r"[0-9a-f]{40}", head_sha)
                or base.get("ref") != "main"
            ):
                raise IntegrityError("invalid open main PR")
            if head_sha == sha:
                matches.append(number)
        if len(batch) < 100:
            return matches
    raise IntegrityError("open main PR list exceeds 3000 entries")


def status_history(client: EvidenceClient, sha: str) -> tuple[JsonObject | None, int]:
    """Read newest status and count this context before any mutation."""
    latest: JsonObject | None = None
    count = 0
    for page in range(1, 102):
        batch = client.get_array(f"commits/{sha}/statuses?per_page=100&page={page}")
        if page == 101 and batch:
            raise IntegrityError("status history exceeds read limit")
        for item in batch:
            context = item.get("context")
            if isinstance(context, str) and context.casefold() == STATUS_CONTEXT:
                if latest is None:
                    latest = item
                count += 1
                if count >= STATUS_CAP:
                    return latest, count
        if len(batch) < 100:
            return latest, count
    raise IntegrityError("status history exceeds read limit")


def post_if_changed(client: EvidenceClient, sha: str, state: str, description: str) -> int:
    """Reconcile current evidence without consuming a status on every hourly run."""
    if len(description) > 140:
        raise IntegrityError("status description exceeds GitHub limit")
    latest, count = status_history(client, sha)
    if count >= STATUS_BUDGET:
        if latest is not None and latest.get("state") in {"failure", "error"}:
            return 1
        if count >= STATUS_CAP:
            raise IntegrityError("status quota exhausted while latest status passes")
        client.post_status(sha, "error", f"integrity=fail sha={sha} reason=status_budget_exhausted")
        return 1
    creator = (
        object_value(latest.get("creator")) if latest is not None and isinstance(latest.get("creator"), dict) else {}
    )
    if (
        latest is not None
        and latest.get("state") == state
        and latest.get("description") == description
        and creator.get("login") == "github-actions[bot]"
    ):
        return 0
    client.post_status(sha, state, description)
    return 0


def post_current(client: EvidenceClient, number: int, sha: str, state: str, description: str) -> int:
    """Never post a result for a head that moved during evaluation."""
    try:
        pr = client.get_object(f"pulls/{number}")
        current = object_value(pr.get("head")).get("sha")
        if current != sha:
            print(f"skip: pr={number} sha={sha} reason=head_moved")
            return 1
        if state == "success" and pr.get("state") != "open":
            post_if_changed(client, sha, "error", f"integrity=fail sha={sha} reason=state_changed")
            return 1
        if state == "success" and object_value(pr.get("base")).get("ref") != "main":
            post_if_changed(client, sha, "error", f"integrity=fail sha={sha} reason=base_changed")
            return 1
        return post_if_changed(client, sha, state, description)
    except IntegrityError:
        if state == "success":
            with suppress(IntegrityError):
                client.post_status(sha, "error", f"integrity=fail sha={sha} reason=final_pr_fetch_failed")
        print(f"skip: pr={number} sha={sha} reason=status_post_failed")
        return 1


def fail(client: EvidenceClient, number: int, sha: str, reason: str, *, error: bool = False) -> int:
    """Post a current-head refusal; a moved head has no stale status mutation."""
    posted = post_current(
        client, number, sha, "error" if error else "failure", f"integrity=fail sha={sha} reason={reason}"
    )
    return 1 if posted or error else 0


def check_inputs(
    client: EvidenceClient, number: int, sha: str, body: str, review_body: str, owner: str, max_bytes: int, count: int
) -> int:
    """Validate command evidence, policy paths and the bounded diff before success."""
    if not eval_valid(body, number, sha):
        return fail(client, number, sha, "eval_evidence_invalid", error=True)
    if count >= 3000:
        return fail(client, number, sha, "file_count_at_api_cap", error=True)
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
    if len(files) != count:
        return fail(client, number, sha, "file_count_mismatch", error=True)
    for name in filenames:
        if isinstance(name, str) and (
            name in ATTESTOR_IMPORT_PATHS
            or name.startswith(PROTECTED_PREFIXES)
            or any(name.startswith(f"{stem}.") for stem in ATTESTOR_IMPORT_STEMS)
            or name.startswith(ATTESTOR_PACKAGE_PATHS)
        ):
            return fail(client, number, sha, "policy_path_protected")
    try:
        diff = client.get(f"pulls/{number}", "application/vnd.github.v3.diff").rstrip("\n")
    except IntegrityError:
        return fail(client, number, sha, "diff_fetch_failed", error=True)
    if not diff or len(diff.encode()) > max_bytes:
        return fail(client, number, sha, "diff_invalid_or_oversize")
    try:
        current_bodies = owner_bodies(client, number, owner)
    except IntegrityError:
        return fail(client, number, sha, "comment_recheck_failed", error=True)
    eval_prefix = f"<!-- coderails-eval-summary v1 pr={number} head_sha={sha} "
    review_marker = f"<!-- coderails-review-summary v1 pr={number} head_sha={sha} -->"
    current_evals = [item for item in current_bodies if item.startswith(eval_prefix)]
    current_reviews = [item for item in current_bodies if item.splitlines()[:1] == [review_marker]]
    if not current_evals or not current_reviews or current_evals[-1] != body or current_reviews[-1] != review_body:
        return fail(client, number, sha, "evidence_changed", error=True)
    try:
        main_numbers = main_prs_at_head(client, sha)
    except IntegrityError:
        return fail(client, number, sha, "main_roster_fetch_failed", error=True)
    if main_numbers != [number]:
        return fail(client, number, sha, "shared_or_missing_main_head", error=True)
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
    count: object = None
    base: object = None
    state: object = None
    try:
        pr = client.get_object(f"pulls/{number}")
        head = object_value(pr.get("head"))
        sha = head.get("sha")
        base = pr.get("base")
        state = pr.get("state")
        count = pr.get("changed_files")
    except IntegrityError:
        sha = None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        print(f"skip: pr={number} reason=head_sha_fetch_failed")
        return 1
    if state == "closed":
        print(f"skip: pr={number} sha={sha} reason=closed")
        return 0
    if state != "open":
        return fail(client, number, sha, "state_invalid", error=True)
    try:
        base_ref = object_value(base).get("ref")
    except IntegrityError:
        return fail(client, number, sha, "base_invalid", error=True)
    if not isinstance(base_ref, str) or not base_ref:
        return fail(client, number, sha, "base_invalid", error=True)
    if base_ref != "main":
        print(f"skip: pr={number} sha={sha} reason=non_main_base")
        return 0
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return fail(client, number, sha, "file_count_invalid", error=True)
    try:
        owner = client.owner_login()
        comments = owner_bodies(client, number, owner)
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
        return check_inputs(client, number, sha, body, reviews[-1], owner, max_bytes, count)
    except Exception as error:
        reason = "evaluation_input_error" if isinstance(error, IntegrityError) else "evaluation_internal_error"
        print(f"refuse: pr={number} sha={sha} reason={reason} type={type(error).__name__}")
        try:
            return fail(client, number, sha, reason, error=True)
        except Exception as post_error:
            print(f"skip: pr={number} sha={sha} reason=error_status_post_failed type={type(post_error).__name__}")
        return 1
