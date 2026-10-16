#!/usr/bin/env python3
"""Detect a project's test command: `detect_test_command.py [--dir D]` prints JSON {command, candidates[]}.

Markers are checked in a fixed order: package.json with a `test` script (npm test), Cargo.toml, pyproject.toml /
setup.py / setup.cfg (pytest -x), go.mod, a Makefile with a `test` target, mix.exs, Gemfile. `candidates` lists every
detected command in that order; `command` is the single candidate, or null when none or several were found (the
caller must ask the user).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, cast


def npm_has_test(path: Path) -> bool:
    """package.json declares a non-empty scripts.test."""
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    scripts = cast("dict[str, Any]", data).get("scripts") if isinstance(data, dict) else None
    command = cast("dict[str, Any]", scripts).get("test") if isinstance(scripts, dict) else None
    return isinstance(command, str) and bool(command.strip())


def make_has_test(path: Path) -> bool:
    """The Makefile defines a `test:` target."""
    try:
        return re.search(r"^test\s*:", path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE) is not None
    except OSError:
        return False


def detect(directory: Path) -> dict[str, object]:
    """Candidates in the documented order and the unambiguous command, if any."""

    def present(*names: str) -> bool:
        return any((directory / name).is_file() for name in names)

    checks = (
        ("npm test", npm_has_test(directory / "package.json")),
        ("cargo test", present("Cargo.toml")),
        ("pytest -x", present("pyproject.toml", "setup.py", "setup.cfg")),
        ("go test ./...", present("go.mod")),
        ("make test", make_has_test(directory / "Makefile")),
        ("mix test", present("mix.exs")),
        ("bundle exec rspec", present("Gemfile")),
    )
    candidates = [command for command, found in checks if found]
    return {"command": candidates[0] if len(candidates) == 1 else None, "candidates": candidates}


def main(argv: list[str] | None = None) -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path.cwd())
    directory = parser.parse_args(argv).dir
    if not directory.is_dir():
        parser.error("directory_unavailable: expected an existing project directory")
    print(json.dumps(detect(directory)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
