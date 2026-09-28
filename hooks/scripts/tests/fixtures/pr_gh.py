#!/usr/bin/env python3
"""Provide native process-boundary GitHub responses for offline hook verification."""

import base64
import json
import os
import re
import sys
from typing import Any


def main() -> int:
    """Model only the exact read-only API calls that the workflow guard issues."""
    arguments = " ".join(sys.argv[1:])
    if os.environ.get("MOCK_GH_FETCH_FAIL"):
        return 1
    if arguments.startswith("pr list ") and "--json number" in arguments:
        print("99")
    elif arguments.startswith("pr view ") and "--json headRefOid" in arguments:
        print(os.environ.get("MOCK_GH_HEAD_SHA", os.environ["FIXTURE_HEAD_SHA"]))
    elif arguments.startswith("api user "):
        print("testuser")
    elif arguments.startswith("repo view ") and "--json viewerPermission" in arguments:
        print("WRITE")
    elif "/comments" in arguments:
        if os.environ.get("MOCK_GH_COMMENTS_FAIL"):
            return 1
        body = os.environ.get("MOCK_GH_COMMENT_BODY")
        if body is None:
            number = re.search(r"/issues/([0-9]+)/comments", arguments)
            if number is None:
                return 1
            sha = os.environ.get("MOCK_GH_HEAD_SHA", os.environ["FIXTURE_HEAD_SHA"])
            suite: dict[str, Any] = {
                "verification_level": 0,
                "verification_justification": "stub",
                "head_sha": sha,
                "evals": [],
            }
            body = (
                f"<!-- coderails-eval-summary v1 pr={number[1]} head_sha={sha} result=GO verification_level=1 -->\n"
                f"```json\n{json.dumps(suite)}\n```\n"
            )
        if body:
            print(base64.b64encode(body.encode()).decode())
    elif "/statuses" in arguments:
        if os.environ.get("MOCK_TR_STATUSES_FAIL"):
            return 1
        print(os.environ.get("MOCK_TR_STATUSES_JSON", "[]"))
    else:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
