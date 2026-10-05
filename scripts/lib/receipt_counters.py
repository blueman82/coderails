"""Receipt-specific summary over trace counts (stdlib; counts only, never row content).

Input is trace_counts()["by_reason"] in measure_graph_alignment, whose keys are "command/outcome/reason_code" and
which is already deduped by event_id, so this adds only the action_authority / action_receipt view.
"""

from __future__ import annotations

import json
import sys

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


SIGNATURE_CODES = (
    "signature_missing",
    "signature_invalid",
    "signer_unknown",
    "trust_root_missing",
    "trust_root_user_tier",
    "binding_unknown",
    "receipt_refused_no_tty",
)
BINDING_CODES = (
    "hash_mismatch", "repository_mismatch", "ref_mismatch", "sha_mismatch", "consumed", "state_mutated_before_guard",
)  # fmt: skip


def trust_summary(by_reason: dict[str, int]) -> dict[str, int]:
    """Count signature, trust-root and binding refusals plus user-tier allows (denied_/advisory_ prefix stripped).

    trust_root_user_tier counts allows resting on the agent-writable tier: a cooperating-agent safeguard, not a
    boundary.
    """
    counts: dict[str, int] = dict.fromkeys((*SIGNATURE_CODES, *BINDING_CODES), 0)
    for key, count in by_reason.items():
        command, _, rest = key.partition("/")
        code = rest.partition("/")[2].removeprefix("denied_").removeprefix("advisory_")
        if command in RECEIPT_COMMANDS and code in counts:
            counts[code] += count
    return counts


GATE_CODES = (
    "authority_denied",
    "max_prs_exceeded",
    "action_authority_bad_mode",
    "authority_denied_destructive_shell",
    "no_receipt",
    "merge_py_receipt_executed",
)


def gate_summary(by_reason: dict[str, int]) -> dict[str, int]:
    """Count default-on gate outcomes: authority refusals, bad mode values, merge.py refusals and executed merges.

    denied_ / advisory_ / merge_py_ prefixes are stripped, so the hook, enforce_pr_workflow and merge.py add up.
    """
    counts: dict[str, int] = dict.fromkeys(GATE_CODES, 0)
    for key, count in by_reason.items():
        command, _, rest = key.partition("/")
        code = rest.partition("/")[2]
        if code != "merge_py_receipt_executed":
            code = code.removeprefix("denied_").removeprefix("advisory_").removeprefix("merge_py_")
        if command in RECEIPT_COMMANDS and code in counts:
            counts[code] += count
    return counts


if __name__ == "__main__":
    # Reads the JSON that scripts/measure_graph_alignment.py prints on stdin (see docs/RUNBOOK.md).
    rows = json.load(sys.stdin).get("trace", {}).get("by_reason", {})
    print(json.dumps({"receipts": receipt_summary(rows), "trust": trust_summary(rows)}, indent=2))
