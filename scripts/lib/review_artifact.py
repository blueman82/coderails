"""Construct and match SHA-bound review artifact markers."""

REVIEW_ARTIFACT_MARKER_VERSION = "v1"


def marker(pr: str, head_sha: str) -> str:
    """Return the exact marker line for a PR head."""
    return f"<!-- coderails-review-summary {REVIEW_ARTIFACT_MARKER_VERSION} pr={pr} head_sha={head_sha} -->"


def matches_marker(line: str, pr: str, head_sha: str) -> bool:
    """Match literal identity and exact line boundaries."""
    return line == marker(pr, head_sha)


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
