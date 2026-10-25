"""Check exact PR publication and landed wiki commits."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast


def head(checkout: Path) -> str:
    """Read the exact commit at the worker checkout."""
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise ValueError("worker checkout HEAD is unavailable")
    return head


def _merged_on_main(checkout: Path, head: str) -> None:
    """Fetch the current main ref and require the published commit in its history."""
    try:
        fetched = subprocess.run(
            ["git", "-C", str(checkout), "fetch", "--no-tags", "origin", "main"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if fetched.returncode:
            raise ValueError("wiki publication cannot fetch origin/main")
        ancestor = subprocess.run(
            ["git", "-C", str(checkout), "merge-base", "--is-ancestor", head, "FETCH_HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("wiki publication cannot verify origin/main") from error
    if ancestor.returncode:
        raise ValueError("wiki publication is not on origin/main")


def _clean(checkout: Path) -> None:
    """Reject any checkout bytes that were not part of the published commit."""
    try:
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("publication checkout status failed") from error
    if status.returncode or status.stdout.strip():
        raise ValueError("publication requires a clean checkout")


def publication(checkout: Path, *, require_merged: bool = False) -> dict[str, Any]:
    """Read the PR for the exact clean checkout HEAD and optional landed wiki update."""
    _clean(checkout)
    try:
        current_head = head(checkout)
        viewed = subprocess.run(
            ["gh", "pr", "view", "--json", "number,state,headRefOid"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("publication lookup failed") from error
    if viewed.returncode:
        raise ValueError(
            "publication requires a merged PR" if require_merged else "publication requires an open or merged PR"
        )
    try:
        raw: object = json.loads(viewed.stdout)
    except ValueError as error:
        raise ValueError("publication lookup returned invalid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("publication lookup returned invalid PR")
    pr = cast(dict[str, Any], raw)
    states = {"MERGED"} if require_merged else {"OPEN", "MERGED"}
    if (
        type(pr.get("number")) is not int
        or pr["number"] < 1
        or pr.get("state") not in states
        or pr.get("headRefOid") != current_head
    ):
        raise ValueError(
            "publication requires a merged PR at checkout HEAD"
            if require_merged
            else "publication requires an open or merged PR at checkout HEAD"
        )
    if require_merged:
        _merged_on_main(checkout, current_head)
    return {"number": pr["number"], "head": current_head}


def validate_publication(checkout: Path, number: int, head: str, *, require_merged: bool = False) -> None:
    """Keep sealed publication bound to a live open or merged PR at its head."""
    _clean(checkout)
    try:
        viewed = subprocess.run(
            ["gh", "pr", "view", str(number), "--json", "number,state,headRefOid"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("driver publication lookup failed") from error
    if viewed.returncode:
        raise ValueError("driver publication is unavailable")
    try:
        raw: object = json.loads(viewed.stdout)
    except ValueError as error:
        raise ValueError("driver publication response is invalid") from error
    if not isinstance(raw, dict):
        raise ValueError("driver publication response is invalid")
    pr = cast(dict[str, Any], raw)
    states = {"MERGED"} if require_merged else {"OPEN", "MERGED"}
    if pr.get("number") != number or pr.get("headRefOid") != head or pr.get("state") not in states:
        raise ValueError("driver publication no longer matches its PR")
    if require_merged:
        _merged_on_main(checkout, head)
