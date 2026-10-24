#!/usr/bin/env python3
"""Run the trusted integrity policy for a PR event or a bounded reconciliation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol, cast

from integrity_http import Client, IntegrityError, JsonObject, log
from integrity_policy import gate_pr


class PrReader(Protocol):
    """Read a bounded page of PR objects."""

    def get_array(self, target: str) -> list[JsonObject]:
        """Fetch one typed GitHub API array."""
        ...


def _number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def select_prs(client: PrReader, event: str, payload: object) -> list[int]:
    """Use only typed PR numbers from the event; reconcile all open PRs hourly."""
    if not isinstance(payload, dict):
        raise IntegrityError("event payload is not an object")
    event_data = cast(JsonObject, payload)
    if event == "pull_request_target":
        pr = event_data.get("pull_request")
        number = _number(cast(JsonObject, pr).get("number")) if isinstance(pr, dict) else None
        return [number] if number else []
    if event == "issue_comment":
        issue = event_data.get("issue")
        number = (
            _number(cast(JsonObject, issue).get("number"))
            if isinstance(issue, dict) and isinstance(cast(JsonObject, issue).get("pull_request"), dict)
            else None
        )
        return [number] if number else []
    if event not in ("schedule", "workflow_dispatch"):
        raise IntegrityError(f"unsupported event {event}")
    numbers: list[int] = []
    for page in range(1, 32):
        batch = client.get_array(f"pulls?state=open&per_page=100&page={page}")
        for item in batch:
            number = _number(item.get("number"))
            if number is None:
                raise IntegrityError("invalid PR number in open list")
            numbers.append(number)
        if len(batch) < 100:
            return numbers
    raise IntegrityError("open PR list exceeds 3000 entries")


def main() -> int:
    """Use only the built-in token; a failed fetch never reports a passing run."""
    slug = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug) or not token or not event_path:
        log("attestation refused: missing GitHub workflow context")
        return 1
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        client = Client(slug, token)
        numbers = select_prs(client, event, payload)
        maximum = int(os.environ.get("INTEGRITY_GATE_MAX_DIFF_BYTES", "204800"))
        if maximum < 1:
            raise ValueError("invalid diff limit")
        results = [gate_pr(client, number, maximum, 0) for number in numbers]
    except (OSError, ValueError, IntegrityError) as error:
        log(f"attestation refused: {error}")
        return 1
    return int(any(results))


if __name__ == "__main__":
    raise SystemExit(main())
