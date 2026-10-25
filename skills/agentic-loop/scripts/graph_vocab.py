"""Closed stop vocabulary shared by both providers; materialized byte-for-byte, never redefined locally."""

from __future__ import annotations

STOP_CATEGORIES = ("hard-stop", "approval-gate", "awaiting-input", "complete")
STOP_REASON_CODES = (
    "work_complete",
    "needs_human_input",
    "needs_approval",
    "node_hard_stop",
    "environment_blocked",
    "other",
)
