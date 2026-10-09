#!/usr/bin/env python3
"""Validate, execute and neutrally grade SHA-bound workflow eval artifacts."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import eval_level
from scripts.lib import git_common as git
from scripts.lib.artifact_io import JsonObject, array_value, object_value, read_object, write_object
from scripts.lib.eval_artifact import compute_go, facts_line, grading_checksum, marker
from scripts.lib.eval_execution import record_smoke, scripted_evals, verify_execution
from scripts.lib.eval_integrity import (
    LEGACY_UNHASHED,
    PROGRESS_FOREIGN,
    PROGRESS_MISSING,
    PROGRESS_UNPARSEABLE,
    IntegrityError,
    append_amendment,
    sign_suite,
    stamp,
    suite_hash,
    verify_suite,
)
from scripts.lib.eval_signing import KEY_MISSING, remember, report
from scripts.lib.eval_trace import emit
from scripts.lib.eval_validation import validate_discriminating, validate_embed, validate_structure


def compute_and_validate_result(path: str | Path) -> str:
    """Derive GO or NO-GO exclusively from actual P0 statuses."""
    return "GO" if compute_go(path) else "NO-GO"


def _progress_identity(progress: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Require a regular, parseable sibling progress.json whose ids match any ids already on the suite."""
    if progress.is_symlink():
        raise IntegrityError(PROGRESS_FOREIGN, f"{progress} is a symlink; identity must come from the loop's own file")
    try:
        identity = read_object(progress)
    except FileNotFoundError as error:
        raise IntegrityError(PROGRESS_MISSING, f"{progress} is missing; restore it to grade") from error
    except (OSError, ValueError) as error:
        raise IntegrityError(PROGRESS_UNPARSEABLE, f"{progress} does not parse") from error
    if not all(isinstance(identity.get(key), str) and identity[key].strip() for key in ("session_id", "loop_id")):
        raise IntegrityError(PROGRESS_UNPARSEABLE, f"{progress} does not parse or lacks session_id/loop_id")
    if any(data.get(key) not in (None, identity[key]) for key in ("session_id", "loop_id")):
        raise IntegrityError(PROGRESS_FOREIGN, "suite is stamped for a different session/loop than progress.json")
    return identity


def grade_loop(path: str | Path) -> str:
    """Atomically stamp a structurally valid loop suite and its current identity."""
    validate_structure(path, scope="loop")
    data = read_object(path)
    amendments = data.get("amendments", [])
    if not isinstance(amendments, list):
        raise ValueError(".amendments is malformed (not an array)")
    amendments = [object_value(item) for item in array_value(cast(object, amendments))]
    if any(data.get(key) is not None for key in ("grading", "graded_at", "result")):
        grading = object_value(data.get("grading") or {})
        previous = grading.get("amendments_at_grade", 0)
        previous = previous if isinstance(previous, int) and previous >= 0 else 0
        for amendment in amendments[previous:]:
            identity = amendment.get("regraded_by")
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("amendment(s) added after the prior grade lack a non-blank regraded_by")
    progress = Path(path).with_name("progress.json")
    identity = _progress_identity(progress, data)
    integrity = verify_suite(data, path=path)
    if "signature" in data and integrity != "verified":  # re-signing below would launder it into a local attestation
        raise IntegrityError(KEY_MISSING, "existing signature is unverifiable here; refusing to grade and re-sign it")
    report(path, "verify", integrity)
    if integrity == "verified":
        emit(path, "verify", "ok", "verified")
    verify_execution(data)  # cmd of a recorded pass must still pass; control must fail for a content reason
    if integrity == LEGACY_UNHASHED:
        print(
            "post_evals: reason=legacy_unhashed — suite has no frozen_hash; graded without tamper evidence",
            file=sys.stderr,
        )
        emit(path, "grade-loop", "legacy", LEGACY_UNHASHED)
    if identity.get("schema_version") != 3:
        emit(path, "grade-loop", "legacy", "legacy_progress_schema")
    result = compute_and_validate_result(path)
    data["result"] = result
    data["graded_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["grading"] = {
        "by": "post_evals.py grade-loop",
        "checksum": grading_checksum(path, result),
        "amendments_at_grade": len(amendments),
        **stamp(data),
    }
    data["session_id"], data["loop_id"] = identity["session_id"], identity["loop_id"]
    resigned = "signature" in data  # ids are part of the signed payload; verified above, so re-signing is safe
    if resigned:
        sign_suite(data, strict=True)
        data["grading"]["signed"] = True
    revision = identity.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool):
        data["revision"] = revision
    write_object(path, data)
    if resigned:  # after the write, so the row's sha is the signed file's
        remember(path)
        emit(path, "sign", "ok", "signed")
    return result


def smoke_verify(path: str | Path, head_sha: str) -> int:
    """Re-execute a trusted comment's embed in a detached trusted-head worktree."""
    try:
        data = read_object(path)
        if not head_sha:
            raise ValueError("head_sha argument is required")
        if str(data.get("verification_level")) == "0" or not scripted_evals(data):
            return 0
        timeout = float(os.environ.get("POST_EVALS_SMOKE_VERIFY_TIMEOUT", "120"))
        if timeout <= 0:
            raise ValueError("smoke timeout must be positive")
        with tempfile.TemporaryDirectory(prefix="coderails-smoke-") as temporary:
            worktree = Path(temporary) / "tree"
            exists = subprocess.run(
                ["git", "cat-file", "-e", f"{head_sha}^{{commit}}"], capture_output=True, check=False
            )
            if exists.returncode:
                subprocess.run(["git", "fetch", "origin", head_sha], capture_output=True, check=True)
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), head_sha], capture_output=True, check=True
            )
            try:
                verify_execution(data, timeout, worktree)
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)], capture_output=True, check=False
                )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"post_evals: smoke_verify: {error}", file=sys.stderr)
        if isinstance(error, IntegrityError):
            emit(path, "smoke-verify", "refuse", error.code)
        return 1


def pr_number(text: str) -> str:
    """A positive decimal integer only, checked in code before any gh call."""
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError("pr_number_invalid")
    return text


def _inline(value: object) -> str:
    """One line with no backticks or comment openers, so narrative text cannot start a fence or a marker."""
    return re.sub(r"\s+", " ", str(value)).replace("`", "'").replace("<!--", "<!-")


def summary_of(data: JsonObject) -> str:
    """Per-priority pass/fail counts and the amendments (narrative, never validated; flattened to one line each)."""
    evals = [cast(JsonObject, x) for x in cast(list[object], data.get("evals", [])) if isinstance(x, dict)]
    lines = ["## Eval summary"]
    for priority in ("P0", "P1"):
        group = [item for item in evals if item.get("priority") == priority]
        passed = sum(item.get("status") == "pass" for item in group)
        lines.append(f"- {priority}: {passed} pass, {len(group) - passed} fail")
    notes = [cast(JsonObject, x) for x in cast(list[object], data.get("amendments", [])) if isinstance(x, dict)]
    lines += [f"- amendment {_inline(note.get('eval'))}: {_inline(note.get('why'))}" for note in notes]
    return "\n".join(lines)


def comment_for(repo: str, number: str, login: str, top: list[str]) -> dict[str, str] | None:
    """This login's existing comment whose first two lines equal `top` (marker and facts line), if any."""
    listing = git.run(
        "gh", "api", f"repos/{repo}/issues/{number}/comments", "--paginate",
        "--jq", ".[] | {url:.html_url,author:.user.login,body:.body}",
        check=True,
    )  # fmt: skip
    for line in filter(None, listing.stdout.splitlines()):
        comment = cast(dict[str, str], json.loads(line))
        if comment["author"] == login and comment["body"].splitlines()[:2] == top:
            return comment
    return None


def post(number: str, path: str, progress: str) -> int:
    """Validate, stamp gate facts in code and post (or reuse) the artifact for the PR's current head."""
    head = git.pr_field(number, "headRefOid")
    if not head:
        raise ValueError("could not resolve the PR head SHA")
    validate_structure(path, number, head, progress=progress)
    validate_discriminating(path)
    data = read_object(path)
    changes = eval_level.pr_changes(number, head) or []
    facts, minimum = eval_level.derive(changes, eval_level.progress_units(progress), data, eval_level.load_policy())
    late = eval_level.suite_late(data, eval_level.branch_base(head))
    suite = suite_hash(data)
    gate = {**facts, "derived_min_level": minimum, "late_freeze": late, "suite_hash": suite}
    top = [marker(number, head, "NO-GO", str(data["verification_level"])), facts_line(minimum, late, suite[:16])]
    embed = json.dumps({**data, "gate_facts": gate}, indent=2, ensure_ascii=False)
    body = "\n".join([*top, summary_of(data), "", "```json", embed, "```", ""])
    with tempfile.TemporaryDirectory(prefix="coderails-evals-") as directory:
        body_path = Path(directory) / "body.md"
        body_path.write_text(body)
        validate_embed(path, body_path)
        result = compute_and_validate_result(path)
        top[0] = marker(number, head, result, str(data["verification_level"]))
        body_path.write_text(top[0] + "\n" + body.partition("\n")[2])
        repo = git.repo()
        existing = comment_for(repo, number, git.output("gh", "api", "user", "-q", ".login", check=True), top)
        if git.pr_field(number, "headRefOid") != head:
            raise ValueError(f"stale: PR head moved from {head} before posting; re-run the evals on the new head")
        if existing:
            print(f"Artifact already posted for SHA {head} — skipping duplicate post.\nExisting: {existing['url']}")
        else:
            reply = git.run(
                "gh", "api", f"repos/{repo}/issues/{number}/comments", "-F", f"body=@{body_path}",
                "--jq", "{url:.html_url}",
                check=True,
            )  # fmt: skip
            print(f"Posted: {json.loads(reply.stdout)['url']}")
    if git.pr_field(number, "headRefOid") != head:
        raise ValueError(f"stale: PR head moved from {head} during posting; this artifact must not be used")
    print(f"result={result} verification_level={data['verification_level']} derived_min_level={minimum} head={head}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch existing workflow operations with fail-closed status codes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "validate-structure",
            "validate-discriminating",
            "smoke-run",
            "smoke-verify",
            "compute-result",
            "validate-embed",
            "grade-loop",
            "amend",
            "post",
        ),
    )
    parser.add_argument("path")
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--progress", default="", help="progress.json whose work_units raise the derived level")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(bool(error.code))
    try:
        if args.operation == "validate-structure":
            if len(args.arguments) != 2:
                raise ValueError("validate-structure requires <path> <pr> <sha>")
            validate_structure(args.path, args.arguments[0], args.arguments[1], progress=args.progress)
        elif args.operation == "post":
            if len(args.arguments) != 1:
                raise ValueError("post requires <pr_number> <evals.json>")
            return post(pr_number(args.path), args.arguments[0], args.progress)
        elif args.operation == "validate-discriminating":
            validate_discriminating(args.path)
        elif args.operation == "smoke-run":
            record_smoke(args.path)
        elif args.operation == "smoke-verify":
            if len(args.arguments) != 1:
                raise ValueError("smoke-verify requires <path> <head_sha>")
            return smoke_verify(args.path, args.arguments[0])
        elif args.operation == "compute-result":
            print(compute_and_validate_result(args.path), end="")
        elif args.operation == "grade-loop":
            print(grade_loop(args.path), end="")
        elif args.operation == "amend":
            if len(args.arguments) not in (3, 4):
                raise ValueError("amend requires <path> <eval_id> <reason> <actor> [regraded_by]")
            document = read_object(args.path)
            eval_id, reason, actor, *rest = args.arguments
            append_amendment(document, eval_id, reason, actor, rest[0] if rest else "", args.path)
            write_object(args.path, document)
            if "signature" in document:
                emit(args.path, "sign", "ok", "signed")
        else:
            if len(args.arguments) != 1:
                raise ValueError("validate-embed requires <path> <body_path>")
            validate_embed(args.path, args.arguments[0])
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"post_evals: {error}", file=sys.stderr)
        if isinstance(error, IntegrityError):
            subject = args.arguments[0] if args.operation == "post" and args.arguments else args.path
            emit(subject, args.operation, "refuse", error.code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
