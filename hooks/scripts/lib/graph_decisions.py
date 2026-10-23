"""Controller command `record-decision`: the only writer of typed `decisions_absorbed` rows (Claude).

One lock and one atomic replace, owner-checked; the pure row logic is the mirrored worker_status.append_decision.
Every outcome leaves a closed reason code in the non-authoritative recovery trace.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .graph_executor import transition
from .graph_recovery import trace

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/agentic-loop/scripts"))
import worker_status  # noqa: E402


def record_decision(
    path: Path,
    session: str,
    fields: dict[str, str | None],
    worker_status_seq: int | None = None,
    human_answer: bool = False,
) -> dict[str, Any]:
    """Append one ledger row under the Claude lock; a refusal writes nothing and leaves one coded trace row."""
    ident: dict[str, Any] = {"session_id": session, "graph": {}}
    inputs: dict[str, Any] = {"session": session, **fields, "worker_status_seq": worker_status_seq}
    refusal: list[worker_status.WorkerResultError] = []
    row: list[dict[str, Any]] = []

    def update(state: dict[str, Any]) -> dict[str, Any]:
        ident.update(loop_id=state["loop_id"], revision=state["revision"])
        try:
            proposed, new = worker_status.append_decision(state, session, fields, worker_status_seq, human_answer)
        except worker_status.WorkerResultError as error:
            refusal.append(error)
            raise
        row.append(new)
        return proposed

    try:
        transition(path, update)
    except ValueError:
        if not refusal:
            raise
        trace(path, ident, "refused", refusal[0].code, inputs, [], "record-decision")
        raise refusal[0] from None
    trace(path, ident, "recorded", "decision_recorded", inputs, [], "record-decision")
    return row[0]
