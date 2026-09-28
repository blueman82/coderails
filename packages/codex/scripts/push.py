#!/usr/bin/env python3
"""Stage tracked changes and explicitly named paths, then commit, push and open a PR."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import git_common as git


def commit(message: str, jira_key: str, paths: list[str]) -> None:
    """Stage tracked modifications plus explicit paths without sweeping untracked files."""
    if not git.dirty():
        return
    git.run("git", "add", "-u", check=True)
    if paths:
        git.run("git", "add", "--", *paths, check=True)
    untracked = [line[3:] for line in git.output("git", "status", "--porcelain").splitlines() if line.startswith("??")]
    if untracked:
        print("! Untracked files not staged (run 'git add' explicitly to include them):")
        for path in untracked:
            print(f"!   {path}")
    staged = git.output("git", "diff", "--cached", "--name-only").splitlines()
    if not staged:
        return
    message = message or f"Update {len(staged)} files"
    if jira_key:
        message = f"{jira_key} {message}"
    result = git.run("git", "commit", "-m", message, check=True)
    print(result.stdout, end="")
    print(f"✓ Committed: {message}")


def parse_arguments(arguments: list[str]) -> tuple[bool, str, list[str]]:
    """Preserve the existing first-message and repeated explicit-path CLI."""
    force = False
    message = ""
    paths: list[str] = []
    want_add = False
    for argument in arguments:
        if want_add:
            paths.append(argument)
            want_add = False
        elif argument == "--add":
            want_add = True
        elif argument == "--force-with-lease":
            force = True
        elif not message:
            message = argument
    return force, message, paths


def main(arguments: list[str] | None = None) -> int:
    """Run the feature-branch push workflow with positive remote-ref verification."""
    force, message, paths = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    try:
        current = git.branch()
        git.require_feature()
        git.require_repo()
        jira_key = git.output("git", "config", f"branch.{current}.jira-ticket")
        print(f"→ {git.repo()} ─ {current} → {git.main()}")
        commit(message, jira_key, paths)
        if not git.ahead():
            number = git.pr_num()
            print(f"✓ Up to date │ {git.pr_field(number, 'url')}" if number else "• Nothing to push")
            return 0
        arguments = ["git", "push"] + (["--force-with-lease"] if force else []) + ["-u", "origin", current]
        pushed = git.run(*arguments)
        combined = pushed.stdout + pushed.stderr
        if pushed.returncode:
            print(combined, file=sys.stderr, end="")
            raise git.WorkflowError(f"Push failed (exit {pushed.returncode}) — see error above")
        print("\n".join(line for line in combined.splitlines() if not line.startswith("remote:")))
        if git.output("git", "rev-parse", f"origin/{current}", check=True) != git.output(
            "git", "rev-parse", "HEAD", check=True
        ):
            raise git.WorkflowError(f"Push reported success but origin/{current} does not match local HEAD")
        print(f"✓ Pushed {git.ahead()} commit(s)")
        number = git.pr_num()
        if number:
            git.run("gh", "pr", "comment", number, "-b", "🔄 Pushed")
            print(f"✓ Updated PR #{number} │ {git.pr_field(number, 'url')}")
        else:
            title = current.replace("-", " ").replace("_", " ")
            for prefix in ("feature/", "bug/", "fix/"):
                title = title.removeprefix(prefix)
            if jira_key:
                title = f"{jira_key} {title}"
            url = git.output(
                "gh",
                "pr",
                "create",
                "-t",
                title,
                "-b",
                "\n".join(git.ahead_list().splitlines()[:10]),
                "-B",
                git.main(),
                check=True,
            )
            print(f"✓ Created │ {url}")
        print("━━━ Done ━━━")
        return 0
    except (git.WorkflowError, OSError, ValueError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
