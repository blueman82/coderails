#!/usr/bin/env python3
"""Validate native Codex review summaries and post the SHA-bound review artifact with its passes."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import git_common as git
from scripts.lib import review_artifact, review_passes


def validate_summary(path: str | Path) -> None:
    """Require no-findings or all populated severity sections without ambiguity."""
    review_passes.validate_summary_text(Path(path).read_text())


def pr_number(text: str) -> int:
    """Argparse type: a positive decimal integer only, checked before any gh call."""
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise argparse.ArgumentTypeError("pr_number_invalid")
    return int(text)


def sections(summary: Path, extra: list[str]) -> list[tuple[str, str]]:
    """(name, validated text) for review-pr and each NAME=FILE pass; names are plain, unique, never review-pr."""
    found = [("review-pr", summary)]
    for item in extra:
        name, separator, filename = item.partition("=")
        if not separator or not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in dict(found):
            raise ValueError(f"--pass must be NAME=FILE with a new lowercase name, got {item!r}")
        found.append((name, Path(filename)))
    texts = [(name, source.read_text()) for name, source in found]
    for _, text in texts:
        review_passes.validate_summary_text(text)
    return texts


def comment_for(repo: str, number: int, login: str, head: str, top: list[str]) -> dict[str, str] | None:
    """Reuse only the author's newest recognized artifact for this head when its whole body is valid."""
    listing = git.run(
        "gh", "api", f"repos/{repo}/issues/{number}/comments", "--paginate",
        "--jq", ".[] | {url:.html_url,author:.user.login,created:.created_at,body:.body}",
        check=True,
    )  # fmt: skip
    newest = None
    for line in filter(None, listing.stdout.splitlines()):
        comment = cast(dict[str, str], json.loads(line))
        if comment["author"] == login and any(
            review_artifact.matches_marker(line, str(number), head) for line in comment["body"].splitlines()
        ):
            newest = comment
    if (
        newest is not None
        and newest["body"].splitlines()[:2] == top
        and review_passes.parse(newest["body"], str(number), head) is not None
    ):
        return newest
    return None


def post(number: int, summary: Path, extra: list[str]) -> int:
    """Post (or reuse) the artifact for the PR's current head; a head that moves mid-post is refused as stale."""
    texts = sections(summary, extra)
    head = git.pr_field(str(number), "headRefOid")
    if not head:
        raise ValueError("could not resolve the PR head SHA")
    passes = [
        {"name": n, "verdict": (v := review_passes.verdict_from_summary(t)), "blocking": v == "fail",
         "summary_sha256": review_passes.summary_sha256(t)}
        for n, t in texts
    ]  # fmt: skip
    top = [review_artifact.marker(str(number), head), review_passes.render(head, passes)]
    repo = git.repo()
    login = git.output("gh", "api", "user", "-q", ".login", check=True)
    comment = comment_for(repo, number, login, head, top)
    if git.pr_field(str(number), "headRefOid") != head:
        raise ValueError(f"stale: PR head moved from {head} before posting; review the new head")
    if comment:
        print(f"Artifact already posted for SHA {head} — skipping duplicate post.\nExisting: {comment['url']}")
    else:
        body = "\n".join(top + [review_passes.tail(texts)])
        with tempfile.TemporaryDirectory(prefix="coderails-review-") as directory:
            path = Path(directory) / "body.md"
            path.write_text(body)
            reply = git.run(
                "gh", "api", f"repos/{repo}/issues/{number}/comments", "-F", f"body=@{path}",
                "--jq", "{url:.html_url,author:.user.login,created:.created_at}",
                check=True,
            )  # fmt: skip
        comment = json.loads(reply.stdout)
        print(f"Posted: {comment['url']}")
    if git.pr_field(str(number), "headRefOid") != head:
        raise ValueError(f"stale: PR head moved from {head} during posting; this artifact must not be used")
    return 0  # the Codex copy keeps no provider-local review cache


def post_main(arguments: list[str]) -> int:
    """Parse and run `post <int> --summary FILE [--pass NAME=FILE ...]`."""
    parser = argparse.ArgumentParser(prog="post_review.py post")
    parser.add_argument("pr", type=pr_number)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--pass", dest="passes", action="append", default=[], metavar="NAME=FILE")
    try:
        args = parser.parse_args(arguments)
    except SystemExit as error:
        return int(bool(error.code))
    try:
        return post(args.pr, args.summary, args.passes)
    except (OSError, ValueError, KeyError, git.WorkflowError) as error:
        print(f"post: {error}", file=sys.stderr)
        return 1


def main(arguments: list[str] | None = None) -> int:
    """Validate a summary, or post the artifact, without creating provider-local review caches."""
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments[:1] == ["post"]:
        return post_main(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate",))
    parser.add_argument("path", type=Path)
    try:
        args = parser.parse_args(arguments)
    except SystemExit as error:
        return int(bool(error.code))
    try:
        validate_summary(args.path)
    except (OSError, ValueError) as error:
        print(f"validate_summary: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
