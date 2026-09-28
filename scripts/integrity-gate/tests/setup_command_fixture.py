"""Inert local executable fixture for owner setup recovery tests."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    """Record argv and respond to only the expected read-only GitHub calls."""
    root = Path(os.environ["INTEGRITY_SETUP_FIXTURE"])
    args = sys.argv[1:]
    with (root / "calls.jsonl").open("a") as stream:
        stream.write(json.dumps(args) + "\n")
    scenario = os.environ["INTEGRITY_SETUP_SCENARIO"]
    if args[:2] == ["repo", "view"]:
        count_path = root / "repo-count"
        count = int(count_path.read_text()) + 1 if count_path.exists() else 1
        count_path.write_text(str(count))
        if scenario == "repo-fail" or scenario == "repo-recover" and count == 1:
            return 1
        print("octo/coderails")
        return 0
    if args == ["api", "repos/octo/coderails/rulesets?per_page=100"]:
        count_path = root / "rules-count"
        count = int(count_path.read_text()) + 1 if count_path.exists() else 1
        count_path.write_text(str(count))
        print("{invalid" if count == 1 else "[]")
        return 0
    return 97


if __name__ == "__main__":
    raise SystemExit(main())
