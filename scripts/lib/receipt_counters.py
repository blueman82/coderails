"""Receipt-specific summary over trace counts (stdlib; counts only, never row content).

Input is trace_counts()["by_reason"] in measure_graph_alignment, whose keys are "command/outcome/reason_code" and
which is already deduped by event_id, so this adds only the action_authority / action_receipt view.
"""

from __future__ import annotations

RECEIPT_COMMANDS = ("action_authority", "action_receipt")


def receipt_summary(by_reason: dict[str, int]) -> dict[str, dict[str, int]]:
    """Group receipt/hook rows by reason_code and by outcome; other commands are ignored."""
    codes: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    for key, count in by_reason.items():
        command, _, rest = key.partition("/")
        outcome, _, code = rest.partition("/")
        if command in RECEIPT_COMMANDS:
            codes[code] = codes.get(code, 0) + count
            outcomes[outcome] = outcomes.get(outcome, 0) + count
    return {"by_reason_code": dict(sorted(codes.items())), "by_outcome": dict(sorted(outcomes.items()))}
