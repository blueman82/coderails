"""Share the closed dispatch contract and v2 envelope across both providers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, cast

import graph_spec
from graph_contract_render import BEGIN as BEGIN
from graph_contract_render import CODES as CODES
from graph_contract_render import CONTRACT_FIELDS as CONTRACT_FIELDS
from graph_contract_render import END as END
from graph_contract_render import render_sections as render_sections
from graph_contract_render import sections_sha256 as sections_sha256
from graph_lessons import query as query_lessons
from graph_required_context import required_context as required_context
from graph_required_context import validate_context
from graph_source import base_ref as base_ref
from graph_source import check_binding
from graph_source import source_binding as source_binding
from graph_vocab import decision_pending, decision_sync_pending

ENVELOPE_VERSION = 2
ENVELOPE_KEY = "CODERAILS_GRAPH_DISPATCH"
MODEL_ROLES = ("fast-mechanical", "default", "frontier")
LIST_FIELDS = ("manifest", "lessons", "write_scope", "skip_phases")
ENVELOPE_FIELDS = ("envelope_version", "dispatch_id", "session_id", "loop_id", "revision", "wave_id", "node_id")
LEGACY_FIELDS = ("session_id", "loop_id", "revision", "wave_id", "node_id")
OFF_SWITCH = "CODERAILS_GRAPH_DISPATCH"  # off/0/false: bypass policy after v2 ownership (default ON)
CAPABILITY_TOOLS = ("repo.inspect", "diff.read", "tests.run", "pr.comment")  # mirrors hooks capability_profiles.TOOLS
CLAUDE_TYPES = ("general-purpose",)  # unguarded roles may also run as this untyped native agent
STATE_MINOR_NEEDED = 3


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


def validate_contract(contract: object, require_context: bool = False) -> dict[str, Any]:
    """Require exactly the closed field set with typed values; raises ValueError naming the first defect."""
    if not isinstance(contract, dict):
        raise ValueError("contract must be an object")
    value = cast(dict[str, Any], contract)
    current_fields = set(CONTRACT_FIELDS)
    v2_fields = current_fields - {"required_context"}
    prior_fields = v2_fields - {"worktree", "source_manifest_sha256", "source_head_sha", "lessons_sha256"}
    allowed = (
        (current_fields,)
        if require_context
        else (prior_fields - {"publication_command"}, prior_fields, v2_fields, current_fields)
    )
    if set(value) not in allowed:
        raise ValueError(f"contract fields must match the current or historical v2 set: {list(CONTRACT_FIELDS)}")
    if value["role"] not in roles():
        raise ValueError("contract role is not a known agent")
    if value["model_role"] not in MODEL_ROLES:
        raise ValueError(f"contract model_role must be one of {MODEL_ROLES}")
    for key in ("base_ref", "scope"):
        if not isinstance(value[key], str) or (key == "base_ref" and not value[key].strip()):
            raise ValueError(f"contract {key} must be a string")
    for key in LIST_FIELDS:
        items = value[key]
        if not isinstance(items, list) or not all(
            isinstance(item, str)
            or (key == "lessons" and isinstance(item, dict) and isinstance(cast(dict[str, Any], item).get("text"), str))
            for item in cast(list[object], items)
        ):
            raise ValueError(f"contract {key} must be an array of strings")
    if (
        "lessons_sha256" in value
        and value["lessons_sha256"] is not None
        and (
            not isinstance(value["lessons_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["lessons_sha256"]) is None
        )
    ):
        raise ValueError("contract lessons_sha256 must be a SHA256 or null")
    if value["disposition"] is not None and not isinstance(value["disposition"], dict):
        raise ValueError("contract disposition must be an object or null")
    if value.get("publication_command") is not None and (
        not isinstance(value["publication_command"], str) or not value["publication_command"].strip()
    ):
        raise ValueError("contract publication_command must be a non-empty string or null")
    if "worktree" in value:
        worktree = value["worktree"]
        if worktree is not None and (not isinstance(worktree, str) or not Path(worktree).is_absolute()):
            raise ValueError("contract worktree must be an absolute path or null")
        digest = value["source_manifest_sha256"]
        if digest is not None and (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
            raise ValueError("contract source_manifest_sha256 must be a SHA256 or null")
        head = value["source_head_sha"]
        if head is not None and (not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) is None):
            raise ValueError("contract source_head_sha must be a Git SHA or null")
    if "required_context" in value:
        validate_context(value["required_context"])
    return value


def unit_fields(
    model_role: str | None,
    write_scope: list[str],
    lessons: list[str],
    scope: str | None,
    base_branch: str | None = None,
    worktree: str | None = None,
) -> dict[str, Any]:
    """The optional contract inputs `add-unit` stores on work_units[u]; only values actually given are kept."""
    if model_role is not None and model_role not in MODEL_ROLES:
        raise ValueError(f"--model-role must be one of {MODEL_ROLES}")
    if base_branch is not None and (
        not base_branch
        or subprocess.run(["git", "check-ref-format", "--branch", base_branch], capture_output=True).returncode
    ):
        raise ValueError("--base-branch must be a valid Git branch")
    if worktree is not None:
        if not Path(worktree).is_absolute():
            raise ValueError("--worktree must be an absolute path")
        worktree = str(Path(worktree).resolve())
    given = {
        "model_role": model_role,
        "write_scope": write_scope or None,
        "lessons": lessons or None,
        "scope": scope,
        "base_branch": base_branch,
        "worktree": worktree,
    }
    return {key: value for key, value in given.items() if value is not None}


def require_source_binding(state: dict[str, Any], record: dict[str, Any]) -> None:
    """Refuse a changed assigned checkout or manifest before a native worker starts."""
    unit = graph_spec.split_id(record["node_id"])[1]
    if unit is None:
        return
    stored = state.get("work_units", {}).get(unit, {})
    contract = validate_contract(record["contract"])
    try:
        check_binding(stored, contract)
    except ValueError as error:
        raise DispatchDeniedError("dispatch_source_mismatch", str(error)) from error


def current_lessons(progress: Path, push_script: Path, session: str) -> dict[str, Any]:
    """Read the provider's current cited lessons before acquiring the graph lock."""
    try:
        return query_lessons(progress, push_script, session)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise DispatchDeniedError("dispatch_lessons_unavailable", str(error)) from error


def require_current_lessons(record: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Refuse an old lesson snapshot before worker launch."""
    if validate_contract(record["contract"]).get("lessons_sha256") != snapshot["sha256"]:
        raise DispatchDeniedError("dispatch_lessons_stale", "current lessons changed after begin-wave")


def publication_command(node_id: str, progress: Path, push_script: Path) -> str | None:
    """Render the exact executable publication command for a unit worker."""
    unit = graph_spec.split_id(node_id)[1]
    node = graph_spec.node_for(graph_spec.load_spec(), node_id)
    if unit is None or node is None or node.get("agent_role") != "loop-worker":
        return None
    return shlex.join(["python3", str(push_script.resolve()), "--unit", unit, "--progress", str(progress.resolve())])


def require_publication(record: dict[str, Any], progress: Path, push_script: Path) -> None:
    """Reject a stored command that differs from this node's actual publication target."""
    expected = publication_command(record["node_id"], progress, push_script)
    contract = validate_contract(record.get("contract"))
    if contract.get("publication_command") != expected:
        raise DispatchDeniedError("dispatch_publication_mismatch", "publication command does not bind this unit")


def build_contract(
    state: dict[str, Any],
    node_id: str,
    base: str,
    progress: Path | None = None,
    push_script: Path | None = None,
    lesson_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The contract for one node: unit inputs (defaults applied), role and skip_phases from the graph spec."""
    spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
    unit = graph_spec.split_id(node_id)[1]
    stored = cast(dict[str, Any], state.get("work_units", {}).get(unit, {})) if unit else {}
    node = graph_spec.node_for(spec, node_id)
    manifest = list(stored.get("manifest", []))
    source = {"worktree": stored.get("worktree"), "source_manifest_sha256": None, "source_head_sha": None}
    if source["worktree"] is not None:
        try:
            source.update(source_binding(str(source["worktree"]), manifest))
        except ValueError as error:
            raise DispatchDeniedError("dispatch_source_mismatch", str(error)) from error
    if (progress is None) != (push_script is None):
        raise ValueError("publication needs both progress and push script paths")
    lesson_rows: list[Any] = cast(list[Any], lesson_snapshot["lessons"]) if lesson_snapshot else []
    contract: dict[str, Any] = {
        "role": (node or {}).get("agent_role") or "loop-worker",
        "model_role": stored.get("model_role", "default"),
        "base_ref": base,
        **source,
        "manifest": manifest,
        "publication_command": (
            publication_command(node_id, progress, push_script) if progress and push_script else None
        ),
        "disposition": stored.get("disposition"),  # null until the disposition-scout record exists
        "lessons": [*stored.get("lessons", []), *lesson_rows],
        "lessons_sha256": lesson_snapshot["sha256"] if lesson_snapshot else None,
        "write_scope": list(stored.get("write_scope", manifest)),
        "skip_phases": [n["id"] for n in spec["nodes"] if graph_spec.skip_when_met(state, spec, policy, n["id"])],
        "scope": stored.get("scope", ""),
        "required_context": required_context(state, node_id),
    }
    require_source_binding(state, {"node_id": node_id, "contract": contract})
    return contract


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
    if live and decision_sync_pending(state):
        raise DispatchDeniedError("decision_pending", "cannot authorize while decision sync is pending")
    if live and decision_pending(state, record["node_id"]):
        raise DispatchDeniedError("decision_pending", "cannot authorize a node with a pending worker decision")
    return record


def check_dispatch(state: dict[str, Any], env: dict[str, Any], prompt: str, live: bool) -> dict[str, Any]:
    """Cross-check an owned prompt against its stored contract and rendered sections."""
    validate_dispatch_state(state)
    record = check_ownership(state, env, live)
    try:
        cutoff = state["graph"].get("context_from_revision") if state.get("state_minor", 0) >= 3 else None
        needs_context = type(cutoff) is int and record["revision"] >= cutoff
        contract = validate_contract(record.get("contract"), require_context=needs_context)
        if needs_context and contract["required_context"] != required_context(state, record["node_id"]):
            raise DispatchDeniedError("dispatch_context_mismatch", "required context differs from task facts")
        altered = record.get("envelope_version") != ENVELOPE_VERSION
        altered = altered or sections_sha256(contract) != record.get("prompt_sections_sha256")
    except DispatchDeniedError:
        raise
    except (ValueError, TypeError) as error:
        raise DispatchDeniedError("dispatch_contract_altered", f"stored contract is invalid: {error}") from error
    if altered:
        raise DispatchDeniedError("dispatch_contract_altered", "stored contract no longer matches its sections hash")
    if render_sections(contract) not in prompt:
        raise DispatchDeniedError("dispatch_sections_missing", "prompt lacks the rendered contract sections verbatim")
    return record


def assert_role(contract: dict[str, Any], requested: str, prefix: str, generic: tuple[str, ...] | None) -> None:
    """Guard typed roles; generic names allowed Claude agents, while None means an omitted Codex type."""
    role = contract["role"]
    if requested == prefix + role:
        return
    untyped = not requested if generic is None else requested in generic
    if role in guarded_roles() or not untyped:
        shown = requested or "no agent type"
        raise DispatchDeniedError("role_mismatch", f"role {role} cannot be dispatched as {shown}")


def require_converted(state: dict[str, Any]) -> None:
    """begin-wave and authorize need a state converted to the dispatch-contract minor."""
    validate_dispatch_state(state)
    if state.get("state_minor", 0) < STATE_MINOR_NEEDED:
        raise DispatchDeniedError("dispatch_state_unconverted", "run graph.py convert: state predates the contract")


def validate_dispatch_state(state: dict[str, Any]) -> None:
    """Reject malformed current-minor cutoffs that would bypass native evidence revalidation."""
    minor = state.get("state_minor", 0)
    if type(minor) is not int or minor < 0 or minor > STATE_MINOR_NEEDED:
        raise DispatchDeniedError("dispatch_state_unconverted", "state has an invalid dispatch minor")
    if minor < 2:
        return
    graph = state["graph"]
    start = graph.get("contract_from_revision")
    if not isinstance(graph.get("dispatches"), dict) or type(start) is not int or not 1 <= start <= state["revision"]:
        raise DispatchDeniedError("dispatch_state_unconverted", "current state lacks a valid contract cutoff")
    if minor >= 3:
        context_start = graph.get("context_from_revision")
        if type(context_start) is not int or not start <= context_start <= state["revision"]:
            raise DispatchDeniedError("dispatch_state_unconverted", "current state lacks a valid context cutoff")
