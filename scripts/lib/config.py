"""Resolve the nearest workflow configuration within the containing repository."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def config_path(start_dir: str | Path | None = None) -> str:
    """Return the nearest config path, or empty text outside configured repositories."""
    start = Path(start_dir or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
        if result.returncode or not result.stdout.strip():
            return ""
        root = Path(result.stdout.strip()).resolve()
        current = start
        while True:
            candidate = current / ".coderails/workflow.config.yaml"
            if candidate.is_file():
                return str(candidate)
            if current == root or current == current.parent:
                return ""
            current = current.parent
    except OSError:
        return ""


def resolve_config(start_dir: str | Path | None = None) -> str:
    """Read the discovered file or return the NO_CONFIG sentinel."""
    path = config_path(start_dir)
    return Path(path).read_text() if path else "NO_CONFIG\n"


def config_value(path: str | Path, key: str, section: str = "") -> str:
    """Read a workflow scalar using the existing single-level configuration grammar."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return ""
    active = not section
    for line in lines:
        if section and re.fullmatch(re.escape(section) + r":\s*", line):
            active = True
            continue
        if section and line and not line[0].isspace():
            active = False
        prefix = r"\s+" if section else ""
        match = re.match(prefix + re.escape(key) + r":\s*(.*)$", line)
        if active and match:
            return match[1].split("#", 1)[0].strip().strip("\"'")
    return ""


def integrity_machine_user(path: str | Path) -> str:
    """Read the configured root-owned attestor login."""
    return config_value(path, "machine_user", "integrity_review")


def main() -> int:
    """Expose config discovery and content to command frontmatter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("config-path", "resolve-config"))
    parser.add_argument("start_dir", nargs="?")
    args = parser.parse_args()
    result = config_path(args.start_dir) if args.operation == "config-path" else resolve_config(args.start_dir)
    print(result, end="" if result.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
