#!/usr/bin/env python3
"""Stage tracked changes and explicitly named paths, then commit, push and open a PR."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import git_common as git
from scripts.lib import manifest_policy


def refuse_publication(code: str, message: str) -> None:
    """Record a unit preflight refusal before raising its stable reason code."""
    manifest_policy.trace(
        manifest_policy.publication_session() or "publication",
        "refused",
        code.removeprefix("publication:"),
        command="publication",
    )
    raise git.WorkflowError(f"{code}: {message}")


def unit_manifest(unit: str | None, progress: str | None) -> tuple[list[str], str | None] | None:
    """Bind an optional publication request to a registered unit and its assigned checkout."""
    if (unit is None) != (progress is None):
        raise git.WorkflowError("--unit and --progress must be provided together")
    if unit is None or progress is None:
        return None
    try:
        state: object = json.loads(Path(progress).resolve().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise git.WorkflowError(f"cannot read unit progress: {error}") from error
    if not isinstance(state, dict):
        raise git.WorkflowError("unit progress must be an object")
    units: object = cast(dict[str, Any], state).get("work_units")
    entry: object = cast(dict[str, Any], units).get(unit) if isinstance(units, dict) else None
    if not isinstance(entry, dict):
        raise git.WorkflowError("publication unit is not registered")
    record = cast(dict[str, Any], entry)
    manifest: object = record.get("manifest")
    if (
        not isinstance(manifest, list)
        or not manifest
        or not all(isinstance(path, str) and bool(path) for path in cast(list[object], manifest))
    ):
        raise git.WorkflowError("publication unit needs a nonempty manifest")
    assigned = record.get("worktree")
    if (
        not isinstance(assigned, str)
        or not assigned.strip()
        or not Path(assigned).is_absolute()
        or Path(assigned).resolve() != Path(git.output("git", "rev-parse", "--show-toplevel", check=True)).resolve()
    ):
        refuse_publication("publication:worktree_invalid", "publication worktree does not match the unit")
    base = record.get("base_branch")
    if base is not None and (not isinstance(base, str) or not base or base.startswith("-")):
        raise git.WorkflowError("publication base branch is invalid")
    state_fields = cast(dict[str, Any], state)
    if any(
        not isinstance(state_fields.get(key), str) or not str(state_fields[key]).strip()
        for key in ("session_id", "loop_id")
    ):
        refuse_publication("publication:graph_owner_missing", "publication graph owner is missing")
    return cast(list[str], manifest), base if isinstance(base, str) else None


def commit(message: str, jira_key: str, paths: list[str], manifest: list[str] | None = None) -> None:
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
    staged = [
        path for path in git.run("git", "diff", "--cached", "--name-only", "-z", check=True).stdout.split("\0") if path
    ]
    if manifest is not None and any(not manifest_policy.matches(path, manifest) for path in staged):
        refuse_publication("diff_manifest:out_of_manifest", "publication staged paths exceed the unit manifest")
    if not staged:
        return
    message = message or f"Update {len(staged)} files"
    if jira_key:
        message = f"{jira_key} {message}"
    result = git.run("git", "commit", "-m", message, check=True)
    print(result.stdout, end="")
    print(f"✓ Committed: {message}")


def check_publication_diff(manifest: list[str], recorded_base: str | None) -> None:
    """Refuse a PR diff containing paths outside its registered unit."""
    number = git.pr_num()
    base = git.pr_field(number, "baseRefName", "") if number else recorded_base or git.main()
    if not base or (recorded_base and base != recorded_base):
        refuse_publication("publication:base_mismatch", "publication base branch does not match the unit")
    raw = git.output("git", "diff", "--raw", "-z", "-M", f"origin/{base}...HEAD", check=True)
    violations = manifest_policy.check(manifest_policy.parse_raw_z(raw), {}, manifest)["violations"]
    if violations:
        refuse_publication("diff_manifest:out_of_manifest", "publication branch diff exceeds the unit manifest")


def parse_arguments(arguments: list[str]) -> tuple[bool, str, list[str], str | None, str | None]:
    """Preserve the existing first-message and repeated explicit-path CLI."""
    force = False
    message = ""
    paths: list[str] = []
    want_add = False
    unit: str | None = None
    progress: str | None = None
    seen: set[str] = set()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if want_add:
            paths.append(argument)
            want_add = False
        elif argument == "--add":
            want_add = True
        elif argument == "--force-with-lease":
            force = True
        elif argument in ("--unit", "--progress") or argument.startswith(("--unit=", "--progress=")):
            flag, equals, value = argument.partition("=")
            if not equals:
                index += 1
                value = arguments[index] if index < len(arguments) else ""
            if flag in seen or not value or value.startswith("--"):
                raise git.WorkflowError(f"diff_manifest:manifest_unreadable: invalid {flag} value")
            seen.add(flag)
            if flag == "--unit":
                unit = value
            else:
                progress = value
        elif argument.startswith("--"):
            raise git.WorkflowError(f"unknown push option: {argument}")
        elif not message:
            message = argument
        index += 1
    if want_add:
        raise git.WorkflowError("--add requires a path")
    return force, message, paths, unit, progress


def main(arguments: list[str] | None = None) -> int:
    """Run the feature-branch push workflow with positive remote-ref verification."""
    try:
        force, message, paths, unit, progress = parse_arguments(sys.argv[1:] if arguments is None else arguments)
        current = git.branch()
        git.require_feature()
        git.require_repo()
        publication = unit_manifest(unit, progress)
        manifest = publication[0] if publication else None
        jira_key = git.output("git", "config", f"branch.{current}.jira-ticket")
        print(f"→ {git.repo()} ─ {current} → {publication[1] if publication and publication[1] else git.main()}")
        commit(message, jira_key, paths, manifest)
        if publication is not None:
            check_publication_diff(publication[0], publication[1])
        if not git.ahead():
            number = git.pr_num()
            print(f"✓ Up to date │ {git.pr_field(number, 'url')}" if number else "• Nothing to push")
            return 0
        if publication is not None:
            base = git.output("git", "rev-parse", f"origin/{publication[1]}", check=True) if publication[1] else ""
            manifest_policy.gate(unit=unit or "", progress=progress or "", base=base)
        else:
            manifest_policy.gate()
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
                publication[1] if publication and publication[1] else git.main(),
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
