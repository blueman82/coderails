"""Execute eval commands with bounded process groups and isolated stdin."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from .artifact_io import JsonObject, array_value, object_value, read_object, write_object
from .eval_integrity import (
    CMD_ENV,
    CONTROL_ENV,
    CONTROL_PASSES,
    PASS_EXIT_NONZERO,
    IntegrityError,
    sign_suite,
    suite_hash,
    verify_suite,
)
from .eval_signing import remember, report
from .eval_trace import emit


def is_environmental_rc(code: int | float) -> bool:
    """Identify command lookup, permission, timeout and signal failures."""
    return code in (126, 127) or code >= 128


def run_recorded(
    command: str, timeout: float = 10, cwd: str | Path | None = None, input_text: str | None = None
) -> tuple[int, str]:
    """Run a configured Bash command and retain both ends of its output."""
    try:
        with tempfile.TemporaryFile() as output:
            child = subprocess.Popen(
                ["/bin/bash", "-c", command],
                cwd=cwd,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                child.communicate(input_text.encode() if input_text is not None else None, timeout=timeout)
                code = child.returncode if child.returncode >= 0 else 128 - child.returncode
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                code = 142
            output.seek(0)
            text = output.read().decode(errors="replace").rstrip("\n").replace("\n", " ")
    except OSError as error:
        return 127, str(error)
    if len(text) > 500:
        text = text[:250] + " [...] " + text[-250:]
    return code, text


def scripted_evals(data: JsonObject) -> list[JsonObject]:
    """Require enumerable evals and known modes before selecting runnable entries."""
    values = data.get("evals")
    if not isinstance(values, list):
        raise ValueError(".evals is not a JSON array (malformed or absent) — refusing")
    result: list[JsonObject] = []
    for value in array_value(cast(object, values)):
        item = object_value(value)
        if item.get("mode") not in ("scripted", "agent-run"):
            raise ValueError('eval has an unrecognised mode (must be "scripted" or "agent-run")')
        if item["mode"] == "scripted":
            result.append(item)
    return result


def verify_execution(data: JsonObject, timeout: float = 10, cwd: str | Path | None = None) -> None:
    """Re-execute every scripted entry without trusting its recorded outcomes."""
    if str(data.get("verification_level")) == "0":
        return
    for item in scripted_evals(data):
        for key in ("cmd", "negative_control"):
            command = item.get(key)
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"scripted eval {item.get('id', '<unnamed>')} has empty {key}")
            code, output = run_recorded(command.strip(), timeout, cwd)
            if is_environmental_rc(code):
                raise IntegrityError(
                    CMD_ENV if key == "cmd" else CONTROL_ENV,
                    f"eval {item.get('id')} {key} did not execute at the gate (exit {code}). Output: {output}",
                )
            if key == "negative_control" and code == 0:
                raise IntegrityError(
                    CONTROL_PASSES,
                    f"eval {item.get('id')} negative_control exited 0 at the gate — "
                    "a control that passes proves nothing",
                )
            if key == "cmd" and code != 0 and item.get("status") == "pass":
                raise IntegrityError(
                    PASS_EXIT_NONZERO, f"eval {item.get('id')} is recorded pass but its cmd exits {code} at the gate"
                )


def record_smoke(path: str | Path) -> None:
    """Record actual command outcomes atomically without claiming their validity."""
    data = read_object(path)
    if data.get("frozen_hash"):
        verify_suite(data, path=path)  # raises suite_hash_mismatch/chain_* if the oracle moved since freeze
    for item in scripted_evals(data):
        if not isinstance(item.get("id"), str):
            raise ValueError("a scripted eval has a non-string id")
        smoke: JsonObject = {}
        for key, prefix in (("cmd", "cmd"), ("negative_control", "negative_control")):
            command = item.get(key, "")
            code, output = run_recorded(command) if command else (None, "")
            smoke[f"{prefix}_exit"] = code
            smoke[f"{prefix}_output"] = output
        item["smoke"] = smoke
    # Stamp only a never-frozen, never-graded suite: re-stamping would launder an edited oracle. An edit after
    # the first freeze was refused above; record it with post_evals.py amend.
    if not data.get("frozen_hash") and not data.get("grading") and not data.get("amendment_chain"):
        data["frozen_hash"] = suite_hash(data)
        signed = sign_suite(data)  # raises when evals.require_signatures is set and signing is impossible
        write_object(path, data)
        emit(path, "smoke-run", "ok", "frozen")
        if signed == "signed":
            remember(path)
            emit(path, "sign", "ok", "signed")
        else:
            report(path, "sign", signed)
        return
    write_object(path, data)


def validate_smoke(data: JsonObject) -> None:
    """Require recorded non-environmental commands and failing controls."""
    if str(data.get("verification_level")) == "0":
        return
    for item in scripted_evals(data):
        smoke = item.get("smoke")
        if not isinstance(smoke, dict):
            raise ValueError(f"eval {item.get('id')} has missing or malformed smoke evidence")
        smoke = object_value(cast(object, smoke))
        for key in ("cmd_exit", "negative_control_exit"):
            code = smoke.get(key)
            if isinstance(code, bool) or not isinstance(code, (int, float)):
                raise ValueError(f"eval {item.get('id')} smoke evidence needs numeric {key}")
            if is_environmental_rc(code):
                raise ValueError(f"eval {item.get('id')} {key} did not execute at freeze (exit {code})")
            if key == "negative_control_exit" and code == 0:
                raise ValueError(f"eval {item.get('id')} negative_control exited 0 at freeze")
