"""Owner/source bindings and honest observations for prepare, durable completion, then local orders apply.

This module never acquires a progress lock or completes a graph. The provider completes progress first;
orders.py subsequently reads it under its one orders lock. Preparation carries no recurrence/tick effect.
Cooperating-agent safeguard: source hashes and observations remain writable by the same user.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import importlib
import json
import os
import re
import runpy
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
CODEX = (ROOT / ".codex-plugin/plugin.json").is_file()
if CODEX:
    sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
    _completion = importlib.import_module("graph_completion")
else:
    _completion = importlib.import_module("hooks.scripts.lib.loop_completion")
WORK_UNIT_CHECK = cast("Callable[[dict[str, Any]], None]", _completion.validate_work_units)
_retro_check: ModuleType | None
try:
    _retro_check = importlib.import_module("scripts.lib.retro_check")
except ModuleNotFoundError as error:
    if error.name != "scripts.lib.retro_check":
        raise
    _retro_check = None
RETRO_CHECK = _retro_check


def sha(value: object) -> str:
    """Canonical JSON hash shared by preparation, application and their observations."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def loop_key(session: str, loop: str) -> str:
    """Unambiguous identity; a reused logical loop in a different session is a distinct completion."""
    return json.dumps([session, loop], separators=(",", ":"), ensure_ascii=False)


def object_file(path: Path) -> dict[str, Any]:
    """Read a required object-shaped source without empty-on-error fallback."""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("order_loop_unknown") from error
    except (OSError, ValueError) as error:
        raise ValueError("order_source_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("order_source_invalid")
    return cast("dict[str, Any]", value)


@lru_cache(maxsize=1)
def semantics() -> dict[str, Any]:
    """Use the installed provider's maintained pure schema-3 validator and eligibility calculation."""
    return runpy.run_path(str(ROOT / "skills/agentic-loop/scripts/graph_semantics.py"))


def source_state(state: dict[str, Any]) -> dict[str, Any]:
    """Normalize only fields the actual provider completion operation changes."""
    source = copy.deepcopy(state)
    if CODEX and state["status"] == "complete":
        completion = state.get("completion")
        if not isinstance(completion, dict):
            raise ValueError("order_source_invalid")
        completion = cast("dict[str, Any]", completion)
        if type(completion.get("revision")) is not int:
            raise ValueError("order_source_invalid")
        if completion["revision"] != state["revision"] - 1:
            raise ValueError("order_source_mismatch")
        source["revision"] = completion["revision"]
    elif "completion" in state:
        raise ValueError("order_source_invalid")
    for key in ("status", "completion", "completed_marker"):
        source.pop(key, None)
    counts = source.get("loop_stop_counts")
    if isinstance(counts, dict):
        source["loop_stop_counts"] = {k: v for k, v in cast("dict[str, Any]", counts).items() if k != "complete"}
    return source


def owned(
    repo_dir: Path, session: object, loop: object, complete: bool = False
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Validate real directory/session/logical-loop inputs and return their separate bound source identities."""
    if (
        not isinstance(session, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", session)
        or not isinstance(loop, str)
        or not loop.strip()
    ):
        raise ValueError("order_wrong_session")
    state_dir = repo_dir / session
    path = state_dir / "progress.json"
    if state_dir.is_symlink() or path.is_symlink() or state_dir.resolve().parent != repo_dir.resolve():
        raise ValueError("order_wrong_session")
    state = object_file(path)
    try:
        semantics()["validate"](state)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("order_source_invalid") from error
    if state.get("session_id") != session or state.get("loop_id") != loop:
        raise ValueError("order_wrong_session")
    if state.get("status") not in ("in-progress", "complete") or not isinstance(state.get("created"), str):
        raise ValueError("order_source_invalid")
    try:
        datetime.datetime.fromisoformat(state["created"])
    except ValueError as error:
        raise ValueError("order_source_invalid") from error
    if not isinstance(state.get("authorising_prompt_raw"), str) or not state["authorising_prompt_raw"].strip():
        raise ValueError("order_source_invalid")
    try:
        WORK_UNIT_CHECK(state)
    except ValueError as error:
        raise ValueError("order_loop_ineligible") from error
    if semantics()["can_complete"](state)["eligible"] is not True:
        raise ValueError("order_loop_ineligible")
    if complete and state["status"] != "complete":
        raise ValueError("order_not_complete")
    source = source_state(state)
    binding = {
        "repo_dir": str(repo_dir.resolve()),
        "state_dir": str(state_dir.resolve()),
        "session_id": session,
        "loop_id": loop,
        "revision": source["revision"],
        "progress_sha256": sha(source),
    }
    return state_dir, state, binding


def preparation_path(state_dir: Path, loop: str) -> Path:
    """Keep separate preparations when one native session runs more than one logical loop."""
    return state_dir / f"orders-prepared-{hashlib.sha256(loop.encode()).hexdigest()}.json"


def valid_record(row: dict[str, Any]) -> bool:
    """Validate the shared typed identity/claim/store fields without conflating them with lifecycle counters."""
    if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("id", "failure_mode", "lesson")):
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", row["id"]) or row.get("scope") not in ("repo", "agnostic"):
        return False
    field = row.get("muninn")
    if not isinstance(field, dict):
        return False
    field = cast("dict[str, Any]", field)
    if field.get("state") not in ("written", "pending", "degraded", "disabled"):
        return False
    kid = field.get("id")
    if kid is not None and (not isinstance(kid, str) or not re.fullmatch(r"K\d+", kid)):
        return False
    return field.get("state") != "written" or kid is not None


def prepared(state_dir: Path, binding: dict[str, Any], required: bool = False) -> dict[str, Any]:
    """Read this exact preparation; observations alone never authorize local application."""
    path = preparation_path(state_dir, binding["loop_id"])
    if not path.exists() and not required:
        return {"schema": 1, "binding": binding, "records": []}
    value = object_file(path)
    if type(value.get("schema")) is not int or value["schema"] != 1 or value.get("binding") != binding:
        raise ValueError("order_source_mismatch")
    raw_rows = value.get("records")
    rows = cast("list[Any]", raw_rows)
    if not isinstance(raw_rows, list):
        raise ValueError("order_source_invalid")
    if any(not isinstance(r, dict) for r in rows):
        raise ValueError("order_source_invalid")
    ids: set[str] = set()
    for raw_row in rows:
        row = cast("dict[str, Any]", raw_row)
        if not valid_record(row) or not isinstance(row.get("ts"), str) or len(" ".join(row["lesson"].split())) > 500:
            raise ValueError("order_source_invalid")
        datetime.datetime.fromisoformat(row["ts"])
        if row["id"] in ids:
            raise ValueError("order_source_invalid")
        ids.add(row["id"])
    return value


def prepare(
    repo_dir: Path, session: str, loop: str, ledger: dict[str, Any], refresh_from_sha256: str | None = None
) -> tuple[Path, dict[str, Any]]:
    """Bind inputs or explicitly refresh the CURRENT preparation; the caller holds the orders lock."""
    state_dir, state, binding = owned(repo_dir, session, loop)
    if refresh_from_sha256 is None:
        return state_dir, prepared(state_dir, binding)
    old = object_file(preparation_path(state_dir, loop))
    prior = old.get("binding")
    if not isinstance(prior, dict):
        raise ValueError("order_source_invalid")
    prior = cast("dict[str, Any]", prior)
    if set(prior) != set(binding):
        raise ValueError("order_source_invalid")
    immutable = ("repo_dir", "state_dir", "session_id", "loop_id")
    if state["status"] != "in-progress" or any(prior[k] != binding[k] for k in immutable):
        raise ValueError("order_source_mismatch")
    if type(prior.get("revision")) is not int or prior["revision"] < 1 or prior["revision"] > binding["revision"]:
        raise ValueError("order_source_mismatch")
    if not isinstance(prior.get("progress_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", prior["progress_sha256"]):
        raise ValueError("order_source_invalid")
    old = prepared(state_dir, prior, required=True)
    if refresh_from_sha256 != sha(old):
        raise ValueError("order_source_mismatch")
    if loop_key(session, loop) in ledger["ticked_loops"] or any(
        e["session_id"] == session and e["loop_id"] == loop for row in ledger["orders"] for e in row["evidence"]
    ):
        raise ValueError("order_source_mismatch")
    old["binding"] = binding
    return state_dir, old


def observe(state_dir: Path, step: str, binding: dict[str, Any], evidence: str) -> None:
    """Append a truthful preparation/post-save observation; fail loudly so callers can report pending teardown."""
    path = state_dir / "teardown.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    rows = [json.loads(line) for line in lines]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("order_source_invalid")
    if any(
        row.get("step") == step and row.get("binding") == binding and row.get("evidence_sha256") == evidence
        for row in rows
    ):
        return
    row = {
        "step": step,
        "session_id": binding["session_id"],
        "loop_id": binding["loop_id"],
        "revision": binding["revision"],
        "binding": binding,
        "evidence_sha256": evidence,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    data = (json.dumps(row, sort_keys=True) + "\n").encode()
    descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        if os.write(descriptor, data) != len(data):
            raise OSError("incomplete orders observation")
    finally:
        os.close(descriptor)


def retro_count(repo_dir: Path) -> int:
    """Count distinct logical loops only after their owned completed progress and retrospective sources validate."""
    loops: set[str] = set()
    for path in repo_dir.glob("*/retro.json"):
        try:
            retro = object_file(path)
            if type(retro.get("schema_version")) is not int or retro["schema_version"] < 2:
                continue
            if retro.get("status") != "complete" or retro.get("session_id") != path.parent.name:
                continue
            loop = retro.get("loop_id")
            if not isinstance(loop, str) or not loop.strip():
                continue
            _, state, _ = owned(repo_dir, path.parent.name, loop, complete=True)
            if not isinstance(retro.get("created"), str) or not retro["created"]:
                continue
            datetime.datetime.fromisoformat(retro["created"])
            if retro["schema_version"] >= 3:
                if RETRO_CHECK is None:
                    raise ValueError("order_retro_validator_unavailable")
                RETRO_CHECK.check(state, retro, path.parent)
                loops.add(loop)
                continue
            lists = ("artifacts", "review_themes", "decisions_absorbed", "models_used")
            if any(not isinstance(retro.get(k), list) for k in lists):
                continue
            if not isinstance(retro.get("summary"), str) or not retro["summary"].strip():
                continue
            if not isinstance(retro.get("cost"), dict) or not isinstance(retro.get("loop_stop_counts"), dict):
                continue
            if any(type(n) is not int or n < 0 for n in retro["loop_stop_counts"].values()):
                continue
            if type(retro.get("revision")) is not int or retro["revision"] != state["revision"]:
                continue
            hashes = retro.get("source_hashes")
            if not isinstance(hashes, dict) or "progress.json" not in hashes:
                continue
            hashes = cast("dict[str, Any]", hashes)
            for name, expected in hashes.items():
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError("order_source_invalid")
                if name == "progress.json":
                    actual = hashlib.sha256(path.with_name(name).read_bytes()).hexdigest()
                elif name.startswith("progress."):
                    actual = sha(state.get(name.split(".", 1)[1]))
                elif name in ("evals.json", "proof.json", "proof_results.jsonl", "teardown.jsonl"):
                    source = path.with_name(name).read_bytes()
                    actual = sha(json.loads(source)) if name.endswith(".json") else hashlib.sha256(source).hexdigest()
                else:
                    raise ValueError("order_source_invalid")
                if actual != expected:
                    raise ValueError("order_source_mismatch")
            loops.add(loop)
        except ValueError as error:
            if str(error) == "order_retro_validator_unavailable":
                raise
            continue
        except (OSError, TypeError, KeyError, AttributeError):
            continue
    return len(loops)
