#!/usr/bin/env python3
"""Shared implementation metadata validation for the graph runtimes."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from runtime.parallel_review import PARALLEL_REVIEW_GATE

def _test_callback_records(graph: dict[str, Any], handler: Callable[[str], str]) -> dict[str, Any]:
    return {
        name: {
            "provider": "codex", "skill_id": f"test.callback.{name}",
            "implementation_path": "codex/tests", "test_only": True,
            "outcome": (lambda name=name: handler(name)),
        }
        for name in graph["nodes"]
    }


def _metadata_error(record: Any, *, catalog_root: Path | None = None) -> str | None:
    if not isinstance(record, dict):
        return "implementation mapping must be an object"
    if record.get("provider") != "codex":
        return "provider must be codex"
    if not isinstance(record.get("skill_id"), str) or not record["skill_id"].strip():
        return "skill_id is required"
    if not isinstance(record.get("implementation_path"), str) or not record["implementation_path"].strip():
        return "implementation_path is required"
    if record.get("catalog_route") is not None:
        if catalog_root is None:
            return "catalog resolver root is required"
        try:
            package_catalog = catalog_root / "catalog.json"
            if package_catalog.is_file():
                catalog = json.loads(package_catalog.read_text(encoding="utf-8"))
                route = catalog.get("routes", {}).get(record.get("catalog_kind", "skills"), {}).get(str(record["catalog_route"]))
                if not isinstance(route, Mapping) or route.get("status") != "active":
                    raise ValueError("unknown or inactive package route")
                expected = str(route["path"])
                if not (catalog_root / expected).is_file():
                    raise ValueError("package route target is missing")
            else:
                catalog_dir = catalog_root / "codex"
                if str(catalog_dir) not in sys.path:
                    sys.path.insert(0, str(catalog_dir))
                from catalog import resolve  # type: ignore
                resolved = resolve(str(record["catalog_route"]), kind=record.get("catalog_kind"), root=catalog_root)
                expected = resolved.relative_to(catalog_root).as_posix()
            if expected != record["implementation_path"]:
                return f"catalog path mismatch: expected {expected}"
        except Exception as error:
            return f"catalog route unavailable: {error}"
    adapter = record.get("adapter")
    if adapter is not None and adapter != "codex-exec":
        return "adapter must be codex-exec"
    command = record.get("command")
    test_outcome = record.get("outcome")
    if command is not None and (not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command)):
        return "command must be a non-empty string array"
    if command is None and adapter != "codex-exec" and not (record.get("test_only") and test_outcome is not None):
        return "executable command is required"
    if adapter == "codex-exec" and (not isinstance(record.get("prompt"), str) or not record["prompt"].strip()):
        return "Codex exec prompt is required"
    if record.get("gate") and record.get("mode", "live") != "fixture":
        run = record.get("_run")
        provenance = record.get("provenance")
        if not isinstance(run, Mapping) or not all(isinstance(run.get(key), str) and run[key].strip() for key in ("run_id", "revision", "head")):
            return "live gate requires run_id, revision, and head context"
        if not isinstance(record.get("artifact_path"), str) or not record["artifact_path"].strip():
            return "live gate requires artifact_path"
        if not isinstance(provenance, Mapping) or provenance.get("provider") != "codex" or any(provenance.get(key) != run[key] for key in ("run_id", "revision", "head")):
            return "live gate provenance is not bound to the current run"
        if record.get("gate") == PARALLEL_REVIEW_GATE and not isinstance(record.get("frozen_input_digest"), str):
            return "parallel-review gate requires frozen_input_digest"
    return None
