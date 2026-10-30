"""Construct and match SHA-bound review artifact markers."""

from __future__ import annotations

import re

REVIEW_ARTIFACT_MARKER_VERSION = "v1"


def marker(pr: str, head_sha: str) -> str:
    """Return the exact marker line for a PR head."""
    return f"<!-- coderails-review-summary {REVIEW_ARTIFACT_MARKER_VERSION} pr={pr} head_sha={head_sha} -->"


def matches_marker(line: str, pr: str, head_sha: str) -> bool:
    """Match literal identity and exact line boundaries."""
    return line == marker(pr, head_sha)


COMPAT_PREFIX = "<!-- coderails-compat-findings"
COMPAT_DISPOSITIONS = ("clean-break", "preserve-compat")  # mirrors graph_vocab.DISPOSITION_KINDS
_COMPAT = re.compile(
    r"<!-- coderails-compat-findings v1 pr=(\S+) head_sha=(\S+) count=(\d+)"
    r" disposition=(clean-break|preserve-compat) -->"
)


def compat_line(pr: str, head_sha: str, count: int, disposition: str) -> str:
    """The second typed line of a review artifact. `count` is the reviewer's own judgement, not a measurement."""
    if count < 0 or disposition not in COMPAT_DISPOSITIONS:
        raise ValueError(f"count must be >= 0 and disposition one of {COMPAT_DISPOSITIONS}")
    return f"{COMPAT_PREFIX} v1 pr={pr} head_sha={head_sha} count={count} disposition={disposition} -->"


def parse_compat_line(line: str, pr: str, head_sha: str) -> tuple[int, str] | None:
    """(count, disposition) when `line` is an exact compat line for this PR head, else None."""
    found = _COMPAT.fullmatch(line)
    if found is None or (found[1], found[2]) != (pr, head_sha):
        return None
    return int(found[3]), found[4]


def compat_problem(bodies: list[str], pr: str, head_sha: str) -> str | None:
    """Allow legacy artifacts; malformed current lines and refusing findings win."""
    refusing = None
    for line in (line for body in bodies for line in body.splitlines() if line.startswith(COMPAT_PREFIX)):
        line_pr = re.search(r"\bpr=(\S+)", line)
        line_head = re.search(r"\bhead_sha=(\S+)", line)
        if (line_pr and line_pr[1] != pr) or (line_head and line_head[1] != head_sha):
            continue
        if _COMPAT.fullmatch(line) is None:
            return "compat_findings_malformed"
        parsed = parse_compat_line(line, pr, head_sha)
        if parsed and parsed[1] == "clean-break" and parsed[0] > 0:
            refusing = "compat_findings_nonzero"
    return refusing


def main() -> int:
    """Print a marker for command callers without sourcing a shell library."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr")
    parser.add_argument("head_sha")
    args = parser.parse_args()
    print(marker(args.pr, args.head_sha), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
