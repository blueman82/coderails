"""Capture one authorized source proposal and materialize it once for root publication."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

from hooks.scripts.lib.trace_row import append_row
from scripts.sandbox import containment, source_materialize
from scripts.sandbox import source_capture as capture
from scripts.sandbox.driver_workspace import artifact, authorized_mapping_digest, destination, identity, phase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
import graph_driver_process  # noqa: E402


def _receipt(path: Path, binding: dict[str, Any], status: str, reason: str = "") -> dict[str, Any]:
    proposal = path.parent / "capture.json"
    value = {
        **binding,
        "capture_sha256": capture.digest(proposal) if proposal.exists() else None,
        "status": status,
        "reason": reason,
        "journal_sha256": capture.digest(path.parent / "transfer-journal.json"),
    }
    capture.write_once(path, value)
    return value


def finish_workspace(
    progress: Path,
    state: dict[str, Any],
    identifier: str,
    record: dict[str, Any],
    checkout: Path,
    exit_code: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Capture once, then validate/materialize fixed proposed source without replaying later root edits."""
    owned = identity(state, identifier, record)
    attempt = artifact(progress, identifier)
    workspace_file = attempt / "workspace.json"
    workspace = capture.read_json(workspace_file)
    if any(workspace.get(key) != value for key, value in owned.items()) or workspace["destination"] != str(checkout):
        raise ValueError("driver_workspace_mapping_changed")
    authorized = cast("dict[str, Any] | None", record.get("authorized"))
    if not isinstance(authorized, dict) or capture.digest(attempt / "prompt.txt") != authorized.get("prompt_sha256"):
        raise ValueError("driver_transfer_prompt_changed")
    workspace_sha256 = authorized_mapping_digest(workspace_file, (attempt / "prompt.txt").read_bytes())
    binding: dict[str, Any] = {
        **owned,
        "workspace_sha256": workspace_sha256,
        "destination": str(checkout),
        "driver_run_id": authorized["driver_run_id"],
        "prompt_sha256": authorized["prompt_sha256"],
        "output_sha256": capture.digest(attempt / "output.jsonl"),
        "exit_code": exit_code,
        "worker_result": result,
        "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "head_at_exit": graph_driver_process.exit_head(attempt, exit_code),
    }
    receipt_file, proposal_file = attempt / "transfer.json", attempt / "capture.json"
    if receipt_file.exists() or receipt_file.is_symlink():
        receipt = capture.read_json(receipt_file)
        if any(receipt.get(key) != value for key, value in binding.items()):
            raise ValueError("driver_transfer_binding_changed")
        if receipt.get("capture_sha256") != (capture.digest(proposal_file) if proposal_file.exists() else None):
            raise ValueError("driver_transfer_capture_changed")
        if receipt.get("journal_sha256") != capture.digest(attempt / "transfer-journal.json"):
            raise ValueError("driver_transfer_journal_changed")
        return receipt
    proposal: dict[str, Any]
    try:
        current_phase = capture.read_json(attempt / "transfer-journal.json")["phase"]
        if current_phase in {"quarantined", "materializing", "preparing"}:
            raise ValueError("driver_destination_quarantined")
        if exit_code or result.get("outcome") not in {"done", "skipped"}:
            raise ValueError("driver_transfer_worker_failed")
        if binding["head_at_exit"] != workspace["head"]:
            raise ValueError("driver_destination_exit_head_changed")
        if proposal_file.exists():
            proposal = capture.read_json(proposal_file)
            if any(proposal.get(key) != value for key, value in binding.items()):
                raise ValueError("driver_transfer_capture_binding_changed")
        else:
            if current_phase != "prepared":
                raise ValueError("driver_transfer_capture_incomplete")
            credential = containment.worker_credential()
            if (
                credential is None
                or hashlib.sha256(credential[1].encode()).hexdigest() != workspace["credential_sha256"]
            ):
                raise ValueError("worker_credential_changed_or_missing")
            phase(attempt, "capture_reserved")
            proposal = {
                **binding,
                **capture.freeze(
                    Path(workspace["execution"]),
                    Path(workspace["store"]),
                    workspace["head"],
                    record["contract"]["manifest"],
                    record["contract"]["write_scope"],
                    credential[1],
                ),
            }
            if result.get("outcome") == "skipped" and proposal["tree"] != workspace["baseline_tree"]:
                raise ValueError("driver_transfer_skipped_with_changes")
            capture.write_once(proposal_file, proposal)
            phase(attempt, "captured")
        current = destination(checkout)
        if any(current[key] != workspace[key] for key in current):
            raise ValueError("driver_destination_changed")
        reservation = capture.read_json(Path(workspace["admin"]) / "coderails-driver-reservation.json")
        if reservation != {**owned, "artifact": str(attempt)}:
            raise ValueError("driver_destination_reservation_changed")
        phase(attempt, "materializing")
        source_materialize.apply(checkout, Path(workspace["store"]), workspace["head"], proposal["tree"])
        after = destination_identity(checkout)
        if any(after[key] != workspace[key] for key in after):
            raise ValueError("driver_destination_index_or_head_changed")
        phase(attempt, "materialized")
        append_row("worker_containment", "allowed", "driver_source_materialized", state["session_id"])
        return _receipt(receipt_file, binding, "materialized")
    except (OSError, ValueError) as error:
        phase(attempt, "quarantined", type(error).__name__)
        append_row("worker_containment", "refused", "driver_transfer_quarantined", state["session_id"])
        return _receipt(receipt_file, binding, "quarantined", str(error).split(":", 1)[0])


def destination_identity(path: Path) -> dict[str, str]:
    """Check stable destination administration after source materialization may make it dirty."""
    index = Path(
        capture.git("-C", str(path), "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip()
    )
    return {
        "head": capture.git("-C", str(path), "rev-parse", "HEAD").decode().strip(),
        "branch": capture.git("-C", str(path), "branch", "--show-current").decode().strip(),
        "index_sha256": capture.digest(index) if index.exists() else "absent",
    }
