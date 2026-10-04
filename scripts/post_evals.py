#!/usr/bin/env python3
"""Validate, execute and neutrally grade SHA-bound workflow eval artifacts."""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib.artifact_io import array_value, object_value, read_object, write_object
from scripts.lib.eval_artifact import compute_go, grading_checksum
from scripts.lib.eval_execution import record_smoke, scripted_evals, verify_execution
from scripts.lib.eval_integrity import (
    LEGACY_UNHASHED,
    PROGRESS_FOREIGN,
    PROGRESS_MISSING,
    PROGRESS_UNPARSEABLE,
    IntegrityError,
    append_amendment,
    stamp,
    verify_suite,
)
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
    integrity = verify_suite(data)
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
    revision = identity.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool):
        data["revision"] = revision
    write_object(path, data)
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
        ),
    )
    parser.add_argument("path")
    parser.add_argument("arguments", nargs="*")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(bool(error.code))
    try:
        if args.operation == "validate-structure":
            if len(args.arguments) != 2:
                raise ValueError("validate-structure requires <path> <pr> <sha>")
            validate_structure(args.path, *args.arguments)
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
            append_amendment(document, *args.arguments)
            write_object(args.path, document)
        else:
            if len(args.arguments) != 1:
                raise ValueError("validate-embed requires <path> <body_path>")
            validate_embed(args.path, args.arguments[0])
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"post_evals: {error}", file=sys.stderr)
        if isinstance(error, IntegrityError):
            emit(args.path, args.operation, "refuse", error.code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
