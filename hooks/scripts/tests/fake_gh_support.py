"""Shared fake `gh` executable for external-enforcement tests; never touches the real gh or its auth."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

FAKE = """#!{python}
import json, os, sys
argv = sys.argv[1:]
joined = " ".join(argv)
stdin = sys.stdin.read() if "--input" in argv else ""
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps({{"argv": argv, "stdin": stdin}}) + "\\n")
for route in json.load(open(os.environ["FAKE_GH_ROUTES"])):
    if route["match"] in joined:
        sys.stdout.write(route.get("stdout", ""))
        sys.stderr.write(route.get("stderr", ""))
        sys.exit(route.get("rc", 0))
sys.stderr.write("fake gh: no route for " + joined)
sys.exit(1)
"""


def install(directory: Path, routes: list[dict[str, Any]]) -> dict[str, str]:
    """Write an executable fake gh plus its routes; return env entries that put it first on PATH."""
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE.format(python=sys.executable))
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    route_file = directory / "routes.json"
    route_file.write_text(json.dumps(routes))
    log = directory / "gh.log"
    log.touch()
    return {
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "FAKE_GH_ROUTES": str(route_file),
        "FAKE_GH_LOG": str(log),
    }


def calls(env: dict[str, str]) -> list[dict[str, Any]]:
    """Return every recorded fake-gh invocation."""
    return [json.loads(line) for line in Path(env["FAKE_GH_LOG"]).read_text().splitlines() if line]
