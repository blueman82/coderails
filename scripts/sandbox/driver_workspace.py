"""Prepare one contained execution clone while reserving root's publication checkout."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

from hooks.scripts.lib.trace_row import append_row
from scripts.installer.files import atomic_bytes
from scripts.sandbox import containment
from scripts.sandbox import source_capture as capture
from scripts.sandbox.render_settings import render_settings


def identity(state: dict[str, Any], identifier: str, record: dict[str, Any]) -> dict[str, Any]:
    """Require the actual issued live driver record without consuming native authority."""
    graph = state["graph"]
    active = graph.get("active_wave")
    node_id = record["node_id"]
    node = graph["nodes"][node_id]
    if (
        graph.get("dispatch_mode") != "driver"
        or record.get("dispatch_mode") != "driver"
        or graph.get("dispatches", {}).get(identifier) != record
        or not active
        or active["wave_id"] != record["wave_id"]
        or node_id not in active["nodes"]
        or record["revision"] != state["revision"]
        or record["attempt"] != node["retry"]["attempts"] + node["respawn"]["generation"] + 1
    ):
        raise ValueError("driver_workspace_foreign_or_stale")
    return {
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "node_id": node_id,
        "dispatch_id": identifier,
        "revision": record["revision"],
        "wave_id": record["wave_id"],
        "attempt": record["attempt"],
        "contract_sha256": hashlib.sha256(
            json.dumps(record["contract"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def artifact(progress: Path, identifier: str) -> Path:
    """Keep root-owned records under the existing driver attempt directory."""
    if not identifier.startswith("disp_") or not identifier.removeprefix("disp_").isalnum():
        raise ValueError("driver_workspace_dispatch_invalid")
    path = progress.parent / "driver-evidence" / identifier
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("driver_workspace_artifact_symlink")
    path.mkdir(parents=True, exist_ok=True)
    return path


def phase(attempt: Path, value: str, detail: str = "") -> None:
    """Record intent before effects, without a nested lock or automatic rollback."""
    atomic_bytes(attempt / "transfer-journal.json", json.dumps({"phase": value, "detail": detail}).encode())


def destination(path: Path) -> dict[str, str]:
    """Inspect only the trusted root destination, never the worker clone."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("driver_destination_invalid")
    path = path.resolve(strict=True)
    branch = capture.git("-C", str(path), "branch", "--show-current").decode().strip()
    if branch in {"", "main", "master"}:
        raise ValueError("driver_destination_branch")
    if capture.git("-C", str(path), "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("driver_destination_dirty")
    admin = Path(capture.git("-C", str(path), "rev-parse", "--absolute-git-dir").decode().strip())
    if any((admin / name).exists() for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "rebase-merge", "rebase-apply")):
        raise ValueError("driver_destination_operation_active")
    index = Path(
        capture.git("-C", str(path), "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip()
    )
    return {
        "destination": str(path),
        "branch": branch,
        "head": capture.git("-C", str(path), "rev-parse", "HEAD").decode().strip(),
        "repository": capture.git("-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir")
        .decode()
        .strip(),
        "index_sha256": capture.digest(index) if index.exists() else "absent",
        "admin": str(admin),
    }


def prepare_workspace(
    progress: Path,
    state: dict[str, Any],
    identifier: str,
    record: dict[str, Any],
    checkout: Path,
) -> dict[str, Any]:
    """Create C before prompt authorization; D remains the caller's pristine checkout."""
    owned = identity(state, identifier, record)
    attempt = artifact(progress, identifier)
    saved = attempt / "workspace.json"
    if saved.exists() or saved.is_symlink():
        workspace = capture.read_json(saved)
        if any(workspace.get(key) != value for key, value in owned.items()) or workspace["destination"] != str(
            checkout
        ):
            raise ValueError("driver_workspace_mapping_changed")
        if capture.read_json(attempt / "transfer-journal.json")["phase"] == "quarantined":
            raise ValueError("driver_destination_quarantined")
        return workspace
    if record.get("authorized") is not None or (attempt / "launch.json").exists():
        raise ValueError("driver_workspace_legacy_unfinished")
    baseline = destination(checkout)
    with tempfile.TemporaryDirectory(prefix="coderails-driver-baseline-") as temporary:
        baseline_store = Path(temporary) / "source.git"
        capture.git("clone", "--quiet", "--bare", "--no-hardlinks", str(checkout), str(baseline_store))
        trusted_entries = capture.tree_entries(baseline_store, baseline["head"])
        if capture.raw_entries(checkout, baseline_store, trusted_entries) != trusted_entries:
            raise ValueError("driver_destination_source_drift")
    if not containment.runtime_present(Path.home(), shutil.which, platform.system()):
        raise ValueError("sandbox_unavailable")
    credential = containment.worker_credential()
    if credential is None:
        raise ValueError("worker_credential_missing")
    reservation = Path(baseline["admin"]) / "coderails-driver-reservation.json"
    capture.write_once(reservation, {**owned, "artifact": str(attempt)})
    phase(attempt, "preparing")
    try:
        scratch = Path(tempfile.mkdtemp(prefix="sw.", dir=os.environ.get("TMPDIR", "/tmp"))).resolve()
        clone, store = scratch / "clone", attempt / "source.git"
        capture.git("clone", "--quiet", "--bare", "--no-hardlinks", str(checkout), str(store))
        capture.git("clone", "--quiet", "--no-checkout", "--no-hardlinks", str(checkout), str(clone))
        capture.git("--git-dir", str(clone / ".git"), "read-tree", baseline["head"])
        entries = capture.tree_entries(store, baseline["head"])
        capture.seed(clone, store, entries)
        render_settings(str(clone), str(scratch), str(attempt / "srt-settings.json"))
        workspace = {
            **owned,
            **baseline,
            "schema_version": 1,
            "execution": str(clone),
            "scratch": str(scratch),
            "store": str(store),
            "settings": str(attempt / "srt-settings.json"),
            "settings_sha256": capture.digest(attempt / "srt-settings.json"),
            "baseline_tree": capture.store_git(store, "rev-parse", baseline["head"] + "^{tree}").decode().strip(),
            "credential_sha256": hashlib.sha256(credential[1].encode()).hexdigest(),
        }
        capture.write_once(saved, workspace)
        phase(attempt, "prepared")
        append_row("worker_containment", "allowed", "driver_workspace_prepared", state["session_id"])
        return workspace
    except (OSError, ValueError) as error:
        phase(attempt, "quarantined", str(error))
        raise


def authorized_mapping_digest(path: Path, prompt_bytes: bytes) -> str:
    """Require the exact mapping digest bound by the authorized prompt."""
    marker = re.search(rb"\nWorkspace SHA256: ([0-9a-f]{64})\n", prompt_bytes)
    current = capture.digest(path)
    if marker is None or marker.group(1).decode() != current:
        raise ValueError("driver_workspace_mapping_mismatch")
    return current


def validate_prepared(path: Path, prompt_bytes: bytes) -> dict[str, Any]:
    """Bind a prepared sandbox launch to the actual authorized driver slot and immutable input."""
    workspace = capture.read_json(path)
    progress = path.parents[2] / "progress.json"
    state = capture.read_json(progress)
    identifier = workspace["dispatch_id"]
    record = state["graph"]["dispatches"][identifier]
    owned = identity(state, identifier, record)
    if path != artifact(progress, identifier) / "workspace.json" or any(
        workspace.get(key) != value for key, value in owned.items()
    ):
        raise ValueError("driver_workspace_foreign")
    authorized = cast("dict[str, Any] | None", record.get("authorized"))
    if not isinstance(authorized, dict) or hashlib.sha256(prompt_bytes).hexdigest() != authorized.get("prompt_sha256"):
        raise ValueError("driver_workspace_prompt_mismatch")
    authorized_mapping_digest(path, prompt_bytes)
    if capture.read_json(path.parent / "transfer-journal.json")["phase"] != "prepared":
        raise ValueError("driver_workspace_not_launchable")
    if Path(workspace["execution"]).is_symlink() or not Path(workspace["execution"]).is_dir():
        raise ValueError("driver_workspace_execution_invalid")
    if capture.digest(Path(workspace["settings"])) != workspace["settings_sha256"]:
        raise ValueError("driver_workspace_settings_changed")
    current = destination(Path(workspace["destination"]))
    if any(
        current.get(key) != workspace[key]
        for key in ("destination", "branch", "head", "repository", "index_sha256", "admin")
    ):
        raise ValueError("driver_destination_changed")
    return workspace
