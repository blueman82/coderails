"""Worker-containment summary over trace counts (stdlib; counts only, never row content).

Input is trace_counts()["by_reason"] in measure_graph_alignment ("command/outcome/reason_code" -> count). Rows come
from worker_containment_gate (command worker_containment) and the launcher (command sandbox_launch).
"""

from __future__ import annotations

import json
import sys

COMMANDS = ("worker_containment", "sandbox_launch", "codex_worker")
CODES = (
    "containment_unavailable",
    "containment_fallback_low_risk",
    "containment_ack_required",
    "containment_ack_receipt",
    "containment_gate_failed_open",  # retained trace code from older B6 heads
    "containment_gate_error",
    "sandboxed",
    "sandbox_unavailable",
    "worker_credential_missing",
    "sandbox_workers_off",
    "branch_import_refused",
    "branch_imported",
    "branch_pushed",
    "codex_native_worker_uncontained",
    "contained_process_start",
    "contained_process_complete",
    "contained_process_failed",
    "contained_process_unavailable",
    "driver_workspace_prepared",
    "driver_source_materialized",
    "driver_transfer_quarantined",
)


def containment_summary(by_reason: dict[str, int]) -> dict[str, int]:
    """Count the containment reason codes; every code is present (0 when unseen), other commands are ignored."""
    counts: dict[str, int] = dict.fromkeys(CODES, 0)
    for key, count in by_reason.items():
        command, _, rest = key.partition("/")
        code = rest.partition("/")[2]
        if command in COMMANDS and code in counts:
            counts[code] += count
    return counts


if __name__ == "__main__":
    # Reads the JSON that scripts/measure_graph_alignment.py prints on stdin (see docs/RUNBOOK.md).
    rows = json.load(sys.stdin).get("trace", {}).get("by_reason", {})
    print(json.dumps({"containment": containment_summary(rows)}, indent=2))
