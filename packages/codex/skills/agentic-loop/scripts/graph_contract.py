"""Closed dispatch contract and v2 envelope shared by both providers; materialized byte-for-byte.

`begin-wave` stores one record per dispatched node in `graph.dispatches`; the worker prompt must carry the record's
first-line envelope and its rendered contract block verbatim. `check_dispatch` cross-checks a prompt against the stored
record, `assert_role` pins the requested provider role to the contract's role. Pure apart from `base_ref` (one `git
remote` call) and reading capabilities/profiles.json, the single source of the role enum.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import graph_spec
from graph_vocab import decision_pending

ENVELOPE_VERSION = 2
ENVELOPE_KEY = "CODERAILS_GRAPH_DISPATCH"
MODEL_ROLES = ("fast-mechanical", "default", "frontier")
CONTRACT_FIELDS = (
    "role",
    "model_role",
    "base_ref",
    "manifest",
    "disposition",
    "lessons",
    "write_scope",
    "skip_phases",
    "scope",
)
LIST_FIELDS = ("manifest", "lessons", "write_scope", "skip_phases")
ENVELOPE_FIELDS = ("envelope_version", "dispatch_id", "session_id", "loop_id", "revision", "wave_id", "node_id")
LEGACY_FIELDS = ("session_id", "loop_id", "revision", "wave_id", "node_id")
CODES = (
    "dispatch_missing_envelope",
    "dispatch_unknown_id",
    "dispatch_foreign",
    "dispatch_stale_revision",
    "dispatch_replayed",
    "dispatch_contract_altered",
    "dispatch_sections_missing",
    "dispatch_state_unconverted",
    "role_mismatch",
    "dispatch_unauthorized",
)
OFF_SWITCH = "CODERAILS_GRAPH_DISPATCH"  # off/0/false: bypass policy after v2 ownership (default ON)
BEGIN, END = "CODERAILS_GRAPH_CONTRACT v2", "END CODERAILS_GRAPH_CONTRACT"
CAPABILITY_TOOLS = ("repo.inspect", "diff.read", "tests.run", "pr.comment")  # mirrors hooks capability_profiles.TOOLS
CLAUDE_TYPES = ("general-purpose",)  # unguarded roles may also run as this untyped native agent
STATE_MINOR_NEEDED = 2


class DispatchDeniedError(ValueError):
    """A coded dispatch refusal; `code` is one of CODES and is also the trace reason."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the closed code beside the human message and show both in str()."""
        super().__init__(f"{message} [reason_code={code}]")
        self.code, self.message = code, message


def dispatch_off() -> bool:
    """True when the operator set the dispatch off-switch in the hook/CLI environment."""
    return os.environ.get(OFF_SWITCH, "").strip().lower() in ("off", "0", "false")


def load_profiles() -> dict[str, Any]:
    """The nearest capabilities/profiles.json above this file (repo root, or the Codex plugin root)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "capabilities" / "profiles.json"
        if candidate.is_file():
            return cast(dict[str, Any], json.loads(candidate.read_text(encoding="utf-8")))
    raise ValueError("capabilities/profiles.json not found")


def roles() -> tuple[str, ...]:
    """The role enum: every agent name in profiles.json."""
    return tuple(sorted(load_profiles()["agents"]))


def guarded_roles() -> frozenset[str]:
    """Roles whose Bash is capability-only: they must be dispatched as their own typed agent, never generic."""
    return frozenset(
        name
        for name, caps in load_profiles()["agents"].items()
        if "shell.raw" not in caps and any(cap in CAPABILITY_TOOLS for cap in caps)
    )


def validate_contract(contract: object) -> dict[str, Any]:
    """Require exactly the closed field set with typed values; raises ValueError naming the first defect."""
    if not isinstance(contract, dict):
        raise ValueError("contract must be an object")
    value = cast(dict[str, Any], contract)
    if set(value) != set(CONTRACT_FIELDS):
        raise ValueError(f"contract fields must be exactly {list(CONTRACT_FIELDS)}")
    if value["role"] not in roles():
        raise ValueError("contract role is not a known agent")
    if value["model_role"] not in MODEL_ROLES:
        raise ValueError(f"contract model_role must be one of {MODEL_ROLES}")
    for key in ("base_ref", "scope"):
        if not isinstance(value[key], str) or (key == "base_ref" and not value[key].strip()):
            raise ValueError(f"contract {key} must be a string")
    for key in LIST_FIELDS:
        items = value[key]
        if not isinstance(items, list) or not all(isinstance(item, str) for item in cast(list[object], items)):
            raise ValueError(f"contract {key} must be an array of strings")
    if value["disposition"] is not None and not isinstance(value["disposition"], dict):
        raise ValueError("contract disposition must be an object or null")
    return value


def render_sections(contract: dict[str, Any]) -> str:
    """The deterministic text block a worker prompt must carry verbatim (one JSON value per line)."""
    lines = [f"{key}: {json.dumps(contract[key], sort_keys=True)}" for key in CONTRACT_FIELDS]
    return "\n".join([BEGIN, *lines, END])


def sections_sha256(contract: dict[str, Any]) -> str:
    """Digest of the rendered block; stored at begin-wave and recomputed from the stored contract on every check."""
    return hashlib.sha256(render_sections(contract).encode("utf-8")).hexdigest()


def base_ref() -> str:
    """origin/main when an origin remote exists in the current directory's repository, else main."""
    try:
        done = subprocess.run(["git", "remote"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return "main"
    return "origin/main" if "origin" in done.stdout.split() else "main"


def unit_fields(
    model_role: str | None, write_scope: list[str], lessons: list[str], scope: str | None
) -> dict[str, Any]:
    """The optional contract inputs `add-unit` stores on work_units[u]; only values actually given are kept."""
    if model_role is not None and model_role not in MODEL_ROLES:
        raise ValueError(f"--model-role must be one of {MODEL_ROLES}")
    given = {"model_role": model_role, "write_scope": write_scope or None, "lessons": lessons or None, "scope": scope}
    return {key: value for key, value in given.items() if value is not None}


def build_contract(state: dict[str, Any], node_id: str, base: str) -> dict[str, Any]:
    """The contract for one node: unit inputs (defaults applied), role and skip_phases from the graph spec."""
    spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
    unit = graph_spec.split_id(node_id)[1]
    stored = cast(dict[str, Any], state.get("work_units", {}).get(unit, {})) if unit else {}
    node = graph_spec.node_for(spec, node_id)
    manifest = list(stored.get("manifest", []))
    return {
        "role": (node or {}).get("agent_role") or "loop-worker",
        "model_role": stored.get("model_role", "default"),
        "base_ref": base,
        "manifest": manifest,
        "disposition": stored.get("disposition"),  # null until the disposition-scout record exists
        "lessons": list(stored.get("lessons", [])),
        "write_scope": list(stored.get("write_scope", manifest)),
        "skip_phases": [n["id"] for n in spec["nodes"] if graph_spec.skip_when_met(state, spec, policy, n["id"])],
        "scope": stored.get("scope", ""),
    }


def dispatch_id(loop_id: str, wave_id: str, node_id: str, attempt: int) -> str:
    """A stable id for one node attempt in one wave."""
    return "disp_" + hashlib.sha256(f"{loop_id}|{wave_id}|{node_id}|{attempt}".encode()).hexdigest()[:16]


def make_record(
    state: dict[str, Any], node_id: str, wave_id: str, attempt: int, contract: dict[str, Any], mode: str | None
) -> tuple[str, dict[str, Any]]:
    """(dispatch_id, record) for graph.dispatches; the caller adds provider fields such as task_name."""
    validate_contract(contract)
    return dispatch_id(state["loop_id"], wave_id, node_id, attempt), {
        "node_id": node_id,
        "wave_id": wave_id,
        "revision": state["revision"],
        "attempt": attempt,
        "contract": contract,
        "envelope_version": ENVELOPE_VERSION,
        "prompt_sections_sha256": sections_sha256(contract),
        "final_report_required": True,
        "dispatch_mode": mode,
        "authorized": None,
    }


def prompt_prefix(state: dict[str, Any], identifier: str, record: dict[str, Any]) -> str:
    """The first prompt line: the v2 ownership envelope for this record."""
    fields = {
        "envelope_version": ENVELOPE_VERSION,
        "dispatch_id": identifier,
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "revision": record["revision"],
        "wave_id": record["wave_id"],
        "node_id": record["node_id"],
    }
    return ENVELOPE_KEY + "=" + json.dumps(fields, sort_keys=True)


def parse_envelope(prompt: object, allow_legacy: bool = False) -> dict[str, Any]:
    """Read the first-line envelope: exactly the v2 fields (or, for history only, the five-field v1)."""
    if not isinstance(prompt, str) or not prompt.startswith(ENVELOPE_KEY + "="):
        raise DispatchDeniedError("dispatch_missing_envelope", "missing graph dispatch envelope")
    try:
        result = json.loads(prompt.split("\n", 1)[0].split("=", 1)[1])
    except ValueError as error:
        raise DispatchDeniedError("dispatch_missing_envelope", "malformed graph dispatch envelope") from error
    if not isinstance(result, dict):
        raise DispatchDeniedError("dispatch_missing_envelope", "dispatch envelope must be an object")
    found = cast(dict[str, Any], result)
    legacy = set(found) == set(LEGACY_FIELDS)
    if not (set(found) == set(ENVELOPE_FIELDS) or (allow_legacy and legacy)):
        raise DispatchDeniedError("dispatch_missing_envelope", "invalid dispatch envelope fields: need the v2 set")
    if not legacy and found["envelope_version"] != ENVELOPE_VERSION:
        raise DispatchDeniedError("dispatch_missing_envelope", "unsupported dispatch envelope version")
    for key in ("dispatch_id", "session_id", "loop_id", "wave_id", "node_id"):
        if key in found and (not isinstance(found[key], str) or not found[key].strip()):
            raise DispatchDeniedError("dispatch_missing_envelope", f"invalid dispatch envelope {key}")
    if type(found["revision"]) is not int or found["revision"] < 1:
        raise DispatchDeniedError("dispatch_missing_envelope", "invalid dispatch envelope revision")
    return found


def check_ownership(state: dict[str, Any], env: dict[str, Any], live: bool) -> dict[str, Any]:
    """Bind a v2 envelope to its issued node and wave, including when dispatch policy is explicitly off."""
    found: object = cast(dict[str, Any], state["graph"].get("dispatches", {})).get(env["dispatch_id"])
    if not isinstance(found, dict):
        raise DispatchDeniedError("dispatch_unknown_id", "dispatch envelope names no begin-wave record")
    record = cast(dict[str, Any], found)
    if any(env[key] != state[key] for key in ("session_id", "loop_id")):
        raise DispatchDeniedError("dispatch_foreign", "dispatch envelope belongs to another session or loop")
    current = state["revision"] if live else record.get("revision")
    if env["revision"] != current or env["revision"] != record.get("revision"):
        raise DispatchDeniedError("dispatch_stale_revision", "dispatch envelope revision is not the record's")
    if any(env[key] != record.get(key) for key in ("node_id", "wave_id")):
        raise DispatchDeniedError("dispatch_foreign", "dispatch envelope does not own the recorded node and wave")
    active = state["graph"].get("active_wave")
    if live and not (active and active["wave_id"] == record["wave_id"] and record["node_id"] in active["nodes"]):
        raise DispatchDeniedError("dispatch_foreign", "dispatch envelope does not own an exact node in the active wave")
    if live and decision_pending(state, record["node_id"]):
        raise DispatchDeniedError("decision_pending", "cannot authorize a node with a pending worker decision")
    return record


def check_dispatch(state: dict[str, Any], env: dict[str, Any], prompt: str, live: bool) -> dict[str, Any]:
    """Cross-check an owned prompt against its stored contract and rendered sections."""
    record = check_ownership(state, env, live)
    try:
        contract = validate_contract(record.get("contract"))
        altered = record.get("envelope_version") != ENVELOPE_VERSION
        altered = altered or sections_sha256(contract) != record.get("prompt_sections_sha256")
    except (ValueError, TypeError) as error:
        raise DispatchDeniedError("dispatch_contract_altered", f"stored contract is invalid: {error}") from error
    if altered:
        raise DispatchDeniedError("dispatch_contract_altered", "stored contract no longer matches its sections hash")
    if render_sections(contract) not in prompt:
        raise DispatchDeniedError("dispatch_sections_missing", "prompt lacks the rendered contract sections verbatim")
    return record


def assert_role(contract: dict[str, Any], requested: str, prefix: str, generic: tuple[str, ...] | None) -> None:
    """Guarded roles need their own typed agent; other roles accept only a truly omitted or generic type.

    `generic` lists the accepted untyped agents (Claude); None accepts only an omitted type (Codex).
    """
    role = contract["role"]
    if requested == prefix + role:
        return
    untyped = not requested if generic is None else requested in generic
    if role in guarded_roles() or not untyped:
        shown = requested or "no agent type"
        raise DispatchDeniedError("role_mismatch", f"role {role} cannot be dispatched as {shown}")


def require_converted(state: dict[str, Any]) -> None:
    """begin-wave and authorize need a state converted to the dispatch-contract minor."""
    minor = state.get("state_minor", 0)
    if type(minor) is not int or minor < STATE_MINOR_NEEDED or "dispatches" not in state["graph"]:
        raise DispatchDeniedError("dispatch_state_unconverted", "run graph.py convert: state predates the contract")
