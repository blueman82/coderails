#!/usr/bin/env python3
"""Offline executable fixtures for actual sandbox-runtime containment tests (baked-in paths, scrubbed env safe)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REAL_HOME = Path("@REAL_HOME@")  # replaced when the fixture is installed: the owner's home, NOT the worker's HOME
NODE, CLI = "@NODE@", "@CLI@"


def worker() -> int:
    """Exercise writes from a real worker process without contacting any provider; the prompt names the mode."""
    leaked = [name for name in ("CODERAILS_HEADLESS_RUN", "GH_TOKEN", "GITHUB_TOKEN") if name in os.environ]
    if leaked:
        raise RuntimeError(f"worker inherited {leaked}")
    if Path.home() == REAL_HOME or not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("worker did not get an isolated HOME and the worker credential")
    mode = sys.argv[sys.argv.index("-p") + 1].strip()
    if mode == "exit":
        print("failing on purpose")
        return 42
    if mode == "cache":
        cache = Path(os.environ["XDG_CACHE_HOME"])
        (cache / "cache-probe.txt").write_text("cache")
        print(f"xdg-cache-ok:{cache}")
        return 0
    target = REAL_HOME / "escape-probe"
    if mode == "child":
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('escape')",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        print(result.stderr)
        if result.returncode == 0:
            raise RuntimeError("descendant escaped")
    else:
        Path("inside-probe.txt").write_text("inside")
        (Path.home() / ".claude.json").write_text("{}")  # the worker's own config lives in its scratch HOME
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
    if name == "npx":
        if sys.argv[1:3] != ["--yes", "@anthropic-ai/sandbox-runtime@0.0.65"]:
            raise ValueError("sandbox runtime pin changed")
        os.execv(NODE, [NODE, CLI, *sys.argv[3:]])
    return worker()


if __name__ == "__main__":
    raise SystemExit(main())
