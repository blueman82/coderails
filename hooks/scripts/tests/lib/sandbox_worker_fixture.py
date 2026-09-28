#!/usr/bin/env python3
"""Offline executable fixtures for actual sandbox-runtime containment tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def worker() -> int:
    """Exercise writes from a real worker process without contacting any provider."""
    if "CODERAILS_HEADLESS_RUN" in os.environ:
        raise RuntimeError("worker inherited the headless exemption")
    if os.environ.get("GH_TOKEN") != "sandbox-fixture-token":
        raise RuntimeError("worker did not receive the external fixture token")
    mode = os.environ["SANDBOX_FIXTURE_MODE"]
    if mode == "exit":
        print("failing on purpose")
        return 42
    if mode == "cache":
        cache = Path(os.environ["XDG_CACHE_HOME"])
        (cache / "cache-probe.txt").write_text("cache")
        print(f"xdg-cache-ok:{cache}")
        return 0
    target = Path.home() / "escape-probe"
    if mode == "child":
        result = subprocess.run(
            [sys.executable, "-c", "from pathlib import Path; (Path.home() / 'escape-probe').write_text('escape')"],
            capture_output=True,
            text=True,
            check=False,
        )
        print(result.stderr)
        if result.returncode == 0:
            raise RuntimeError("descendant escaped")
    else:
        Path("inside-probe.txt").write_text("inside")
        try:
            target.write_text("escape")
        except PermissionError as error:
            print(error)
        else:
            raise RuntimeError("worker escaped")
    print("stub-claude-ran")
    return 0


def main() -> int:
    """Dispatch by executable name; npx resolves only the prevalidated local pin."""
    name = Path(sys.argv[0]).name
    if name == "gh":
        if sys.argv[1:] != ["auth", "token"]:
            raise ValueError("unexpected GitHub operation")
        print("sandbox-fixture-token")
        return 0
    if name == "npx":
        if sys.argv[1:3] != ["--yes", "@anthropic-ai/sandbox-runtime@0.0.65"]:
            raise ValueError("sandbox runtime pin changed")
        node = os.environ["SANDBOX_FIXTURE_NODE"]
        os.execv(node, [node, os.environ["SANDBOX_FIXTURE_CLI"], *sys.argv[3:]])
    return worker()


if __name__ == "__main__":
    raise SystemExit(main())
