"""Keep one worker process identifiable across driver restarts."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

_CHILDREN: dict[str, subprocess.Popen[bytes]] = {}


@contextmanager
def lease(state_path: Path) -> Iterator[None]:
    """Allow one controller without nesting the provider's graph state lock."""
    lock = state_path.with_name(state_path.name + ".driver.lock")
    with lock.open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("driver controller already owns this graph") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _write(path: Path, value: dict[str, Any]) -> None:
    """Replace one small process record without exposing partial JSON."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    """Treat missing or malformed process records as unresolved."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _live(pid: int, token: str) -> bool:
    """Check the token in the wrapper's process command to reject PID reuse."""
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False
    )
    return result.returncode == 0 and token in result.stdout and "--worker" in result.stdout


def observe(artifact: Path, timeout: float) -> dict[str, Any]:
    """Return a terminal code, a proven live handle, or an unresolved attempt."""
    if timeout < 0:
        raise ValueError("observation timeout must be nonnegative")
    deadline = time.monotonic() + timeout
    while True:
        launch = _read(artifact / "launch.json")
        terminal = _read(artifact / "terminal.json")
        if launch is None:
            return {"status": "unresolved"}
        token = launch.get("token")
        if terminal is not None and token and terminal.get("token") == token:
            code = terminal.get("exit_code")
            if type(code) is int:
                child = _CHILDREN.pop(token, None)
                if child is not None:
                    child.wait(timeout=1)
                return {"status": "finished", "exit_code": code}
        pid = launch.get("pid")
        if type(pid) is int and isinstance(token, str) and _live(pid, token):
            if time.monotonic() >= deadline:
                return {"status": "running"}
        elif time.monotonic() >= deadline:
            return {"status": "unresolved"}
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))


def start(
    artifact: Path,
    command: list[str],
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
    stdin_path: Path | None = None,
) -> dict[str, Any]:
    """Reserve the attempt before launch; a restart never starts it again."""
    if not command or not cwd.is_dir() or not artifact.is_dir():
        raise ValueError("worker command, checkout or artifact directory is invalid")
    if stdin_path is not None and (stdin_path.is_symlink() or not stdin_path.is_file()):
        raise ValueError("worker prompt is not a regular file")
    token = secrets.token_hex(16)
    try:
        with (artifact / "launch.json").open("x", encoding="utf-8") as stream:
            json.dump({"status": "reserved", "token": token}, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ValueError("worker attempt was already launched or reserved") from error
    try:
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(artifact),
                token,
                str(cwd),
                str(stdin_path) if stdin_path is not None else "-",
                *command,
            ],
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _CHILDREN[token] = child
    except OSError:
        _write(artifact / "terminal.json", {"token": token, "exit_code": 127})
        return {"status": "finished", "exit_code": 127}
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        launch = _read(artifact / "launch.json")
        if launch is not None and launch.get("status") == "started":
            return {"status": "started"}
        time.sleep(0.01)
    return {"status": "unresolved"}


def _worker(artifact: Path, token: str, cwd: Path, stdin_path: Path | None, command: list[str]) -> int:
    """Write the wrapper identity before starting the child, then retain its exit."""
    _write(artifact / "launch.json", {"status": "started", "token": token, "pid": os.getpid()})
    input_stream = None
    try:
        input_stream = stdin_path.open("rb") if stdin_path is not None else None
        with (artifact / "output.jsonl").open("xb") as output:
            code = subprocess.run(
                command,
                cwd=cwd,
                stdin=input_stream if input_stream is not None else subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
    except (OSError, ValueError):
        code = 127
    finally:
        if input_stream is not None:
            input_stream.close()
    _write(artifact / "terminal.json", {"token": token, "exit_code": code})
    return code


if __name__ == "__main__":
    if len(sys.argv) < 7 or sys.argv[1] != "--worker":
        raise SystemExit(2)
    incoming = None if sys.argv[5] == "-" else Path(sys.argv[5])
    raise SystemExit(_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), incoming, sys.argv[6:]))
