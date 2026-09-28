#!/usr/bin/env python3
"""Retain complete test logs and measure demand-driven retrieval."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import shlex
import shutil
import sys
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, cast


@contextmanager
def file_lock(path: Path, *, exclusive: bool, blocking: bool = True) -> Generator[bool, None, None]:
    """Hold a process-owned lock, skipping busy runs when cleanup must not block."""
    with path.open("a+b") as stream:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(stream, operation | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def timestamp() -> str:
    """Return an auditable UTC observation timestamp."""
    return datetime.now(timezone.utc).isoformat()


def read_object(path: Path) -> dict[str, Any]:
    """Reject malformed measurement records instead of inventing empty history."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return cast(dict[str, Any], value)


def write_record(path: Path, value: dict[str, Any]) -> None:
    """Atomically publish one private measurement without partial concurrent reads."""
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def begin_run(provider: str, repo: Path, command: str) -> Path:
    """Allocate a unique persistent log scoped to provider, project and exact command."""
    if provider not in {"claude", "codex"}:
        raise ValueError("unknown test-output provider")
    project = str(repo.resolve())
    identity = json.dumps([provider, project, command], ensure_ascii=False).encode()
    scope = hashlib.sha256(identity).hexdigest()
    base = Path(os.environ.get("CODERAILS_TEST_OUTPUT_DIR", str(Path.home() / ".coderails/test-output")))
    run = (base / provider / scope / uuid.uuid4().hex).resolve()
    run.mkdir(parents=True, mode=0o700)
    (run / "requests").mkdir(mode=0o700)
    (run / "observations").mkdir(mode=0o700)
    (run / "output.log").touch(mode=0o600, exist_ok=False)
    write_record(
        run / "run.json",
        {
            "schema_version": 1,
            "run_id": run.name,
            "scope_id": scope,
            "provider": provider,
            "project": project,
            "command": command,
            "started_at": timestamp(),
            "exit_code": None,
        },
    )
    return run


def finish_run(run: Path, exit_code: int) -> str:
    """Protect the run from cleanup until finalization and its notice are complete."""
    with file_lock(run / ".lifecycle.lock", exclusive=False):
        return _finish_run(run, exit_code)


def _finish_run(run: Path, exit_code: int) -> str:
    """Measure the complete captured bytes and return a metadata-only failure notice."""
    record = read_object(run / "run.json")
    total_bytes = total_lines = 0
    with (run / "output.log").open("rb") as stream:
        for line in stream:
            total_bytes += len(line)
            total_lines += 1
    record.update(exit_code=exit_code, total_bytes=total_bytes, total_lines=total_lines, finished_at=timestamp())
    write_record(run / "run.json", record)
    rotate_logs(run.parent)
    budget = int(os.environ.get("CODERAILS_TEST_LOG_BUDGET_BYTES", str(1024**3)))
    try:
        record["retention"] = enforce_budget(run.parents[2], run, budget)
    except OSError as error:
        record["retention"] = {"cleanup_error": str(error)}
    write_record(run / "run.json", record)
    reader = shlex.join([sys.executable, str(Path(__file__).resolve()), "read", str(run)])
    return (
        f"Run ID: {run.name}\nFull log: {log_path(run)}\n"
        f"Captured: {total_bytes} bytes, {total_lines} lines; exit status {exit_code}.\n"
        "The complete log is retained. No platform delivery limit is assumed.\n"
        f"Measured reader: {reader}\nChoose --all, --start N --end M, or --search TEXT. "
        "Without a selector, the reader reports metadata only; expand your request as needed."
    )


def log_path(run: Path) -> Path:
    """Locate the complete archive or the still-active raw output."""
    archive = run / "output.log.gz"
    if not archive.exists() and not (run / "output.log").exists() and (run / "retention.json").exists():
        raise ValueError(f"log expired under the storage retention policy; measurements remain in {run}")
    return archive if archive.is_file() else run / "output.log"


def open_log(path: Path) -> BinaryIO:
    """Read complete raw or compressed bytes, including a concurrent rotation."""
    if path.suffix == ".gz":
        return cast(BinaryIO, gzip.open(path, "rb"))
    try:
        return path.open("rb")
    except FileNotFoundError:
        return cast(BinaryIO, gzip.open(path.with_suffix(".log.gz"), "rb"))


def rotate_logs(scope_dir: Path) -> None:
    """Atomically compress immutable completed output; never rotate an active run."""
    for metadata in scope_dir.glob("*/run.json"):
        if read_object(metadata).get("exit_code") is None:
            continue
        raw = metadata.with_name("output.log")
        if not raw.exists():
            continue
        archive = metadata.with_name("output.log.gz")
        temporary = metadata.with_name(f".{uuid.uuid4().hex}.gz.tmp")
        try:
            with raw.open("rb") as source, gzip.open(temporary, "wb") as target:
                shutil.copyfileobj(source, target)
            temporary.chmod(0o600)
            os.replace(temporary, archive)
            raw.unlink(missing_ok=True)
        except FileNotFoundError:
            if not archive.is_file():
                raise
        finally:
            temporary.unlink(missing_ok=True)


def enforce_budget(base: Path, protected: Path, budget: int) -> dict[str, Any]:
    """Serialize cleanup passes so deletion and remaining-byte measurements agree."""
    base.mkdir(parents=True, exist_ok=True)
    with file_lock(base / ".cleanup.lock", exclusive=True):
        return _enforce_budget(base, protected, budget)


def _enforce_budget(base: Path, protected: Path, budget: int) -> dict[str, Any]:
    """Delete oldest completed archives, retaining active output and the current run."""
    if budget < 0:
        raise ValueError("test-log storage budget must be nonnegative")
    archives: list[tuple[int, Path, int]] = []
    for archive in base.rglob("output.log.gz"):
        try:
            metadata = read_object(archive.with_name("run.json"))
            if metadata.get("exit_code") is not None:
                stat = archive.stat()
                archives.append((stat.st_mtime_ns, archive, stat.st_size))
        except FileNotFoundError:
            continue
    total = sum(size for _, _, size in archives)
    expired = 0
    for _, archive, size in sorted(archives):
        if total <= budget:
            break
        if archive.parent.resolve() == protected.resolve():
            continue
        with file_lock(archive.parent / ".lifecycle.lock", exclusive=True, blocking=False) as acquired:
            if not acquired:
                continue
            tombstone = archive.with_name("retention.json")
            expiration = {
                "state": "deleting",
                "reason": "storage-budget",
                "at": timestamp(),
                "compressed_bytes": size,
                "budget_bytes": budget,
            }
            write_record(tombstone, expiration)
            archive.unlink(missing_ok=True)
            write_record(tombstone, {**expiration, "state": "expired"})
            total -= size
            expired += 1
    return {
        "budget_bytes": budget,
        "remaining_compressed_bytes": total,
        "expired_logs": expired,
        "over_budget": total > budget,
    }


def merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Coalesce inclusive requested line intervals without a fixed window width."""
    result: list[list[int]] = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1] + 1:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def search_ranges(path: Path, text: str, before: int, after: int) -> list[list[int]]:
    """Locate literal matches with exactly the surrounding context requested by the caller."""
    result: list[list[int]] = []
    with open_log(path) as stream:
        for number, line in enumerate(stream, 1):
            if text in line.decode("utf-8", errors="replace"):
                result.append([max(1, number - before), number + after])
    return merge_ranges(result)


def select_output(path: Path, ranges: list[list[int]]) -> tuple[str, int, int]:
    """Read requested complete lines; retain raw-byte and rendered-byte accounting separately."""
    parts: list[str] = []
    source_bytes = lines = 0
    with open_log(path) as stream:
        for number, line in enumerate(stream, 1):
            if any(start <= number <= end for start, end in ranges):
                parts.append(line.decode("utf-8", errors="replace"))
                source_bytes += len(line)
                lines += 1
    return "".join(parts), source_bytes, lines


def read_output(args: argparse.Namespace) -> dict[str, Any]:
    """Keep the source available throughout selection and request publication."""
    with file_lock(args.run.resolve() / ".lifecycle.lock", exclusive=False):
        return _read_output(args)


def _read_output(args: argparse.Namespace) -> dict[str, Any]:
    """Retrieve uncapped content on demand and record exactly what this reader emitted."""
    run = args.run.resolve()
    record = read_object(run / "run.json")
    if record.get("exit_code") is None:
        raise ValueError("run is unfinished; its complete measurements are not available")
    if (args.start is None) != (args.end is None):
        raise ValueError("--start and --end must be supplied together")
    if args.start is not None and not 1 <= args.start <= args.end:
        raise ValueError("line ranges must be positive and ordered")
    if args.before < 0 or args.after < 0 or ((args.before or args.after) and args.search is None):
        raise ValueError("nonnegative context requires --search")
    if sum((args.all, args.start is not None, args.search is not None)) > 1 or args.search == "":
        raise ValueError("choose exactly one nonempty selector")
    explicit = args.all or args.start is not None or args.search is not None
    full, ranges = False, []
    if args.start is not None:
        ranges = [[args.start, args.end]]
    elif args.search is not None:
        ranges = search_ranges(log_path(run), args.search, args.before, args.after)
    full = full or args.all
    total = record["total_lines"]
    demand = [[1, total]] if full and total else ranges
    selected = merge_ranges([[start, min(end, total)] for start, end in demand if start <= total])
    text, source_bytes, lines = select_output(log_path(run), selected)
    request_path = run / "requests" / f"{uuid.uuid4().hex}.json"
    response: dict[str, Any] = {
        "run_id": record["run_id"],
        "log_path": str(log_path(run)),
        "total_bytes": record["total_bytes"],
        "total_lines": total,
        "text": text,
        "selected_ranges": selected,
        "returned_source_bytes": source_bytes,
        "returned_text_bytes": len(text.encode("utf-8")),
        "omitted_lines": total - lines,
        "policy_truncated": False,
        "delivered_bytes": None,
        "delivery_truncated": None,
        "request_path": str(request_path),
        "selection": "explicit" if explicit else "metadata",
        "guidance": "Use --all, --start N --end M, or --search TEXT. Direct file reads are unobserved.",
    }
    serialized = json.dumps(response, ensure_ascii=False) + "\n"
    write_record(
        request_path,
        {
            **{key: value for key, value in response.items() if key != "text"},
            "scope_id": record["scope_id"],
            "at": timestamp(),
            "explicit": explicit,
            "all": bool(args.all),
            "demand_ranges": demand if explicit else [],
            "emitted_response_bytes": len(serialized.encode("utf-8")),
            "requested": {
                "start": args.start,
                "end": args.end,
                "search": args.search,
                "before": args.before,
                "after": args.after,
                "all": args.all,
            },
        },
    )
    return response


def observe_delivery(args: argparse.Namespace) -> dict[str, Any]:
    """Record attributed downstream observations without overwriting the raw request."""
    request = args.request.resolve()
    original = read_object(request)
    if args.delivered_bytes < 0 or not args.source.strip():
        raise ValueError("delivery observation needs nonnegative bytes and a nonblank source")
    if request.parent.name != "requests" or original.get("request_path") != str(request):
        raise ValueError("observation must refer to the original reader request")
    observation = {
        "request_path": str(request),
        "at": timestamp(),
        "source": args.source,
        "delivered_bytes": args.delivered_bytes,
        "delivery_truncated": args.truncated == "yes",
    }
    target = request.parent.parent / "observations" / f"{uuid.uuid4().hex}.json"
    write_record(target, observation)
    return {**observation, "observation_path": str(target)}


def main() -> int:
    """Expose measured retrieval without inferring a platform delivery budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    reader = commands.add_parser("read")
    reader.add_argument("run", type=Path)
    reader.add_argument("--all", action="store_true")
    reader.add_argument("--start", type=int)
    reader.add_argument("--end", type=int)
    reader.add_argument("--search")
    reader.add_argument("--before", type=int, default=0)
    reader.add_argument("--after", type=int, default=0)
    observation = commands.add_parser("observe")
    observation.add_argument("request", type=Path)
    observation.add_argument("--delivered-bytes", required=True, type=int)
    observation.add_argument("--truncated", required=True, choices=("yes", "no"))
    observation.add_argument("--source", required=True)
    try:
        args = parser.parse_args()
        response = read_output(args) if args.operation == "read" else observe_delivery(args)
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"test-output: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
