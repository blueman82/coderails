"""Owned orders preparation/receipts; no graph completion or progress lock. Same-user evidence is mutable."""

from __future__ import annotations

import copy
import datetime
import hashlib
import importlib
import json
import math
import re
import runpy
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from hooks.scripts.test_output import file_lock
from scripts.lib.orders_atomic import write_bytes

ROOT = Path(__file__).resolve().parents[2]
CODEX = (ROOT / ".codex-plugin/plugin.json").is_file()
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
if CODEX:
    _completion = importlib.import_module("graph_completion")
else:
    _completion = importlib.import_module("hooks.scripts.lib.loop_completion")
WORK_UNIT_CHECK = cast("Callable[[dict[str, Any]], None]", _completion.validate_work_units)
_retro_check = None
try:
    _retro_check = importlib.import_module("scripts.lib.retro_check")
except ModuleNotFoundError as error:
    if error.name != "scripts.lib.retro_check":
        raise
RETRO_CHECK = _retro_check


def sha(value: object) -> str:
    """Canonical JSON hash shared by preparation, application and their observations."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def loop_key(session: str, loop: str) -> str:
    """Unambiguous identity; a reused logical loop in a different session is a distinct completion."""
    return json.dumps([session, loop], separators=(",", ":"), ensure_ascii=False)


def object_file(path: Path) -> dict[str, Any]:
    """Read a required object-shaped source without empty-on-error fallback."""
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("order_wrong_session")
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
    if isinstance(counts := source.get("loop_stop_counts"), dict):
        remaining = {k: v for k, v in cast("dict[str, Any]", counts).items() if k != "complete"}
        source.pop("loop_stop_counts")
        source.update({"loop_stop_counts": remaining} if remaining else {})
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
    path = state_dir / f"orders-prepared-{hashlib.sha256(loop.encode()).hexdigest()}.json"
    if state_dir.is_symlink() or path.is_symlink():
        raise ValueError("order_wrong_session")
    return path


def valid_record(row: dict[str, Any]) -> bool:
    """Validate the shared typed identity/claim/store fields without conflating them with lifecycle counters."""
    if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("id", "failure_mode", "lesson")):
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", row["id"]) or row.get("scope") not in ("repo", "agnostic"):
        return False
    for key, value in row.items():
        if key not in ("lesson_source", "replaces_source") or (key == "replaces_source" and value is None):
            continue
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
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


def require_identity(order: dict[str, Any], failure_mode: str | None, scope: str) -> None:
    """One order id binds its failure mode and scope, including every direct ledger recurrence caller."""
    if order["scope"] != scope or (failure_mode is not None and order["failure_mode"] != failure_mode):
        raise ValueError("order_id_collision")


def staged(repo_dir: Path) -> list[dict[str, Any]]:
    """Validate retained preparations as historical identities, without asserting present source eligibility."""
    rows: list[dict[str, Any]] = []
    for path in repo_dir.glob("*/orders-prepared-*.json"):
        if path.is_symlink() or path.parent.is_symlink() or path.parent.resolve().parent != repo_dir.resolve():
            raise ValueError("order_wrong_session")
        value = object_file(path)
        raw = value.get("binding")
        if not isinstance(raw, dict):
            raise ValueError("order_source_invalid")
        binding = cast("dict[str, Any]", raw)
        if set(binding) != {"repo_dir", "state_dir", "session_id", "loop_id", "revision", "progress_sha256"}:
            raise ValueError("order_source_invalid")
        if (
            binding["repo_dir"] != str(repo_dir.resolve())
            or binding["state_dir"] != str(path.parent.resolve())
            or binding["session_id"] != path.parent.name
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", path.parent.name)
        ):
            raise ValueError("order_wrong_session")
        loop = binding["loop_id"]
        if (
            not isinstance(loop, str)
            or not loop.strip()
            or preparation_path(path.parent, loop) != path
            or type(binding["revision"]) is not int
            or binding["revision"] < 1
            or not isinstance(binding["progress_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", binding["progress_sha256"])
        ):
            raise ValueError("order_source_invalid")
        rows.extend(cast("list[dict[str, Any]]", prepared(path.parent, binding, required=True)["records"]))
    return rows


def check_staged_identity(repo_dir: Path, ledger: dict[str, Any], order: dict[str, Any]) -> None:
    """Check all owned staged history and the ledger under the orders lock, before any store write or apply."""
    for prior in [*ledger["orders"], *staged(repo_dir)]:
        if prior["id"] == order["id"]:
            require_identity(prior, order["failure_mode"], order["scope"])


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


def _finite_float(value: str) -> float:
    """Reject named nonfinite values and overflowing exponent tokens at every nested JSON position."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("order_source_invalid")
    return number


def observe(
    state_dir: Path, step: str | None = None, bound: dict[str, Any] | None = None, digest: str = "", emit: bool = True
) -> bool:
    """Validate under the teardown lock; absent step is preflight, otherwise publish the bound truthful receipt."""
    path = state_dir / "teardown.jsonl"
    lock = state_dir / "teardown.jsonl.lock"
    if state_dir.is_symlink() or path.is_symlink() or lock.is_symlink():
        raise ValueError("order_wrong_session")
    with file_lock(lock, exclusive=True) as acquired:
        if not acquired:
            raise ValueError("order_state_error")
        try:
            prior = path.read_bytes()
        except FileNotFoundError:
            prior = b""
        if prior and not prior.endswith(b"\n"):
            raise ValueError("order_source_invalid")
        rows = [
            json.loads(line, parse_float=_finite_float, parse_constant=_finite_float)
            for line in prior.decode("utf-8").split("\n")[:-1]
        ]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("order_source_invalid")
        if step is None:
            return False
        if bound is None:
            raise ValueError("order_source_invalid")
        if any(
            row.get("step") == step and row.get("binding") == bound and row.get("evidence_sha256") == digest
            for row in rows
        ):
            return True
        if not emit:
            return False
        row = {
            "step": step,
            "session_id": bound["session_id"],
            "loop_id": bound["loop_id"],
            "revision": bound["revision"],
            "binding": bound,
            "evidence_sha256": digest,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        write_bytes(path, prior + (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        return True


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
                    source_path = path.with_name(name)
                    if source_path.is_symlink():
                        raise ValueError("order_wrong_session")
                    source = source_path.read_bytes()
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
