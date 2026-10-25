"""Construct eval markers and compute neutral verdict checksums."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib.artifact_io import JsonObject, array_value, object_value, read_object

EVAL_ARTIFACT_MARKER_VERSION = "v1"
_PATTERN = re.compile(
    r"<!-- coderails-eval-summary v1 pr=[^ ]+ head_sha=[^ ]+ result=(GO|NO-GO) verification_level=([0-2]) -->"
)


def marker(pr: str, head_sha: str, result: str, verification_level: str) -> str:
    """Return the marker carrying an evaluated result and verification level."""
    return (
        f"<!-- coderails-eval-summary {EVAL_ARTIFACT_MARKER_VERSION} pr={pr} "
        f"head_sha={head_sha} result={result} verification_level={verification_level} -->"
    )


_FACTS = re.compile(
    r"<!-- coderails-eval-facts v1 derived_min_level=([0-2]) late_freeze=([01]) suite=([0-9a-f]{16}) -->"
)


def facts_line(derived_min_level: int, late_freeze: bool, suite: str) -> str:
    """Line 2 of the body (additive: line 1 stays the v1 marker the dashboard and integrity gate parse)."""
    return (
        f"<!-- coderails-eval-facts v1 derived_min_level={derived_min_level} "
        f"late_freeze={int(late_freeze)} suite={suite} -->"
    )


def parse_facts(line: str) -> tuple[int, bool, str] | None:
    """(derived_min_level, late_freeze, suite) of a well-formed facts line, else None."""
    match = _FACTS.fullmatch(line)
    return (int(match[1]), match[2] == "1", match[3]) if match else None


def matches_marker(line: str, pr: str, head_sha: str) -> bool:
    """Require a literal PR/head prefix and the closed marker grammar."""
    prefix = f"<!-- coderails-eval-summary {EVAL_ARTIFACT_MARKER_VERSION} pr={pr} head_sha={head_sha} result="
    return line.startswith(prefix) and bool(_PATTERN.fullmatch(line))


def parse_result(line: str) -> str:
    """Extract GO or NO-GO, returning empty text on invalid grammar."""
    match = _PATTERN.fullmatch(line)
    return match[1] if match else ""


def parse_verification_level(line: str) -> str:
    """Extract the verification level, returning empty text on invalid grammar."""
    match = _PATTERN.fullmatch(line)
    return match[2] if match else ""


def compute_go(path: str | Path | JsonObject) -> bool:
    """Require every P0 eval from a path or parsed object to pass; malformed input fails closed."""
    try:
        data = path if isinstance(path, dict) else read_object(path)
        evals = [object_value(item) for item in array_value(data.get("evals"))]
        return all(item.get("priority") != "P0" or item.get("status") == "pass" for item in evals)
    except (OSError, ValueError, TypeError):
        return False


def grading_checksum(path: str | Path, result: str) -> str:
    """Hash ordered id/priority/status projections using jq-compatible canonical JSON."""
    evals = read_object(path).get("evals", [])
    projection = [{key: item.get(key) for key in ("id", "priority", "status")} for item in evals]
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{canonical}\n{result}".encode()).hexdigest()


def main() -> int:
    """Print a marker for command callers without sourcing a shell library."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr")
    parser.add_argument("head_sha")
    parser.add_argument("result")
    parser.add_argument("verification_level")
    args = parser.parse_args()
    print(marker(args.pr, args.head_sha, args.result, args.verification_level), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
