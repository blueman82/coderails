#!/usr/bin/env python3
"""Discover Python hook suites with isolated Git environment and honest skip totals."""

from __future__ import annotations

import argparse
import codecs
import contextlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

GIT_ENVIRONMENT = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
}


def isolated_environment() -> dict[str, str]:
    """Remove Git repository selectors and all indexed configuration overrides."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in GIT_ENVIRONMENT and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }


def discover(directory: Path) -> list[Path]:
    """Return supported Python test filenames exactly once in stable order."""
    return sorted(
        {
            path
            for pattern in ("*_test.py", "test_*.py", "*.test.py")
            for path in directory.glob(pattern)
            if path.is_file()
        }
    )


def _signal_group(process: subprocess.Popen[bytes], kind: signal.Signals) -> None:
    """Stop a suite and any subprocesses it started."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, kind)


def _run_one(
    suite: Path,
    directory: Path,
    environment: dict[str, str],
    timeout: float,
    active: set[subprocess.Popen[bytes]],
    lock: threading.Lock,
    stopping: threading.Event,
    output_path: Path,
) -> tuple[int, float]:
    """Capture one complete suite result without interleaving another suite's output."""
    started = time.monotonic()
    with lock:
        if stopping.is_set():
            output_path.write_text("Runner interrupted before this suite started.\n")
            return 1, 0.0
        output = output_path.open("wb")
        try:
            process = subprocess.Popen(
                [sys.executable, str(suite)],
                cwd=directory,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            output.close()
            output_path.write_text(f"Suite could not start: {error}\n")
            return 1, time.monotonic() - started
        active.add(process)
    try:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)
            process.wait()
            output.write(f"\nSuite timed out after {timeout:g}s.\n".encode())
            return 124, time.monotonic() - started
        except Exception:
            _signal_group(process, signal.SIGKILL)
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=1)
            raise
        _signal_group(process, signal.SIGKILL)
        return process.returncode, time.monotonic() - started
    finally:
        output.close()
        with lock:
            active.discard(process)


def _print_output(path: Path) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    last = b""
    with path.open("rb") as source:
        if stream is None:
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            for chunk in iter(lambda: source.read(65536), b""):
                last = chunk[-1:]
                sys.stdout.write(decoder.decode(chunk))
            sys.stdout.write(decoder.decode(b"", final=True))
        else:
            for chunk in iter(lambda: source.read(65536), b""):
                last = chunk[-1:]
                stream.write(chunk)
    if last != b"\n":
        print()
    sys.stdout.flush()


def _interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def run_suites(directory: Path, *, jobs: int | None = None, suite_timeout: float = 300) -> int:
    """Run all discovered suites, separating prerequisite skips from genuine success."""
    retired = list(directory.glob("*.test.sh"))
    if retired:
        print("run_all: ERROR — shell test retirement is incomplete; refusing partial coverage", file=sys.stderr)
        return 1
    suites = discover(directory)
    if not suites:
        print(f"run_all: ERROR — no Python test files found in {directory}", file=sys.stderr)
        return 1
    workers = min(jobs if jobs is not None else min(os.cpu_count() or 1, 12), len(suites))
    if workers < 1 or suite_timeout <= 0:
        print("run_all: ERROR — jobs and suite timeout must be positive", file=sys.stderr)
        return 1
    print(f"run_all: running {len(suites)} suites with {workers} workers", flush=True)
    failed = 0
    skipped = 0
    lock = threading.Lock()
    stopping = threading.Event()
    active: set[subprocess.Popen[bytes]] = set()
    environment = isolated_environment()
    started = time.monotonic()
    outcomes: dict[Path, str] = {}
    previous_term = signal.signal(signal.SIGTERM, _interrupt)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="coderails-suite-output-") as temporary,
            ThreadPoolExecutor(max_workers=workers) as pool,
        ):
            futures: dict[Future[tuple[int, float]], tuple[Path, Path]] = {}
            try:
                for index, suite in enumerate(suites):
                    output_path = Path(temporary) / f"{index:03}.log"
                    future = pool.submit(
                        _run_one,
                        suite,
                        directory,
                        environment,
                        suite_timeout,
                        active,
                        lock,
                        stopping,
                        output_path,
                    )
                    futures[future] = (suite, output_path)
                for future in as_completed(futures):
                    suite, output_path = futures[future]
                    try:
                        code, elapsed = future.result()
                    except Exception as error:
                        code, elapsed = 1, 0.0
                        with output_path.open("ab") as output:
                            output.write(f"\nSuite runner failed: {error}\n".encode())
                    print(f"\n=== {suite.name} ===", flush=True)
                    _print_output(output_path)
                    if code == 0:
                        outcomes[suite] = "PASS"
                        print(f"OK ({elapsed:.1f}s)", flush=True)
                    elif code == 3:
                        skipped += 1
                        outcomes[suite] = "SKIP"
                        print(f"SKIPPED (prerequisite): {suite.name}", flush=True)
                    else:
                        failed += 1
                        outcomes[suite] = "FAIL"
                        print(f"FAILED (exit {code})", flush=True)
            except KeyboardInterrupt:
                with lock:
                    stopping.set()
                    running = list(active)
                for future in futures:
                    future.cancel()
                for process in running:
                    _signal_group(process, signal.SIGTERM)
                time.sleep(0.2)
                for process in running:
                    _signal_group(process, signal.SIGKILL)
                print("run_all: interrupted; active suites stopped", file=sys.stderr, flush=True)
                return 130
    finally:
        signal.signal(signal.SIGTERM, previous_term)
    print("\n--- run_all: suite status ---")
    for suite in suites:
        print(f"{outcomes[suite]} {suite.name}")
    print(f"\n--- run_all: {len(suites) - failed - skipped}/{len(suites)} suites passed, {skipped} skipped ---")
    print(f"run_all: elapsed {time.monotonic() - started:.1f}s")
    if skipped == len(suites):
        print(f"WARNING: all {len(suites)} suites skipped — nothing was actually verified", file=sys.stderr)
        return 1
    return int(bool(failed))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, help="maximum concurrent suites (default: up to 12 CPUs)")
    args = parser.parse_args()
    raise SystemExit(run_suites(Path(__file__).resolve().parent, jobs=args.jobs))
