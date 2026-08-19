#!/usr/bin/env python3
"""Provider-neutral parallel-review evidence validation."""

from __future__ import annotations

import json
from datetime import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PARALLEL_REVIEW_GATE = "parallel-review"
REVIEW_PROVIDERS = {"cl" + "aude", "codex"}

def _parallel_review_input(value: Mapping[str, Any] | Path) -> Mapping[str, Any] | None:
    if isinstance(value, Path):
        try:
            value = json.loads(value.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
    return value if isinstance(value, Mapping) else None


def _parallel_review_input_digest(record: Mapping[str, Any] | None) -> str | None:
    if not record:
        return None
    return record.get("digest") or record.get("frozen_input_digest")


def _valid_parallel_review_canonical(record: Mapping[str, Any] | None, node: str) -> bool:
    if not isinstance(record, Mapping):
        return False
    expected_node = node.replace("J4b-review", "U4b-review", 1)
    return (
        record.get("schema_version") == 1
        and record.get("node") == expected_node
        and isinstance(record.get("artifact_ref"), str)
        and bool(record["artifact_ref"].strip())
        and record.get("digest_algorithm") == "sha256"
        and isinstance(record.get("digest"), str)
        and bool(record["digest"].strip())
    )


def _valid_parallel_review_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def evaluate_parallel_review_join(
    canonical_input: Mapping[str, Any] | Path,
    reviewer_records: Mapping[str, Mapping[str, Any] | Path | None],
    *,
    reviewer_outcomes: Mapping[str, str] | None = None,
    expected_run: Mapping[str, str] | None = None,
    node: str = "J4b-review[i]",
    evaluated_by: str = "neutral-join",
    evaluated_at: str = "",
) -> dict[str, Any]:
    """Validate independent review evidence and return the durable join record.

    This is deliberately pure: the neutral caller owns persistence, while each
    provider owns only its own evidence file. A skipped pair is an intentional
    non-review; every asymmetric or invalid pair is a hard-stop.
    """
    canonical = _parallel_review_input(canonical_input)
    providers = tuple(sorted(set((reviewer_outcomes or {}).keys()) | set(reviewer_records.keys())))
    outcomes = reviewer_outcomes or {provider: "done" for provider in providers}
    inputs: dict[str, Any] = {}
    base = {
        "schema_version": 1,
        "node": node,
        "policy": "unanimous",
        "frozen_input_digest": _parallel_review_input_digest(canonical),
        "inputs": inputs,
        "outcome": "hard-stop",
        "hard_stop_reason": None,
        "evaluated_at": evaluated_at,
        "evaluated_by": evaluated_by,
    }
    if set(providers) != REVIEW_PROVIDERS:
        base["hard_stop_reason"] = "missing-evidence"
        return base
    if all(outcomes.get(provider) == "skipped" for provider in providers):
        base["outcome"] = "skipped"
        return base
    if canonical is None:
        base["hard_stop_reason"] = "missing-evidence"
        return base
    if not _valid_parallel_review_canonical(canonical, node):
        base["hard_stop_reason"] = "mismatched-evidence"
        return base

    canonical_digest = _parallel_review_input_digest(canonical)
    for provider in providers:
        record = _parallel_review_input(reviewer_records.get(provider))
        verdict = record.get("verdict") if isinstance(record, Mapping) else None
        inputs[provider] = {
            "run_id": record.get("run_id") if record else None,
            "revision": record.get("revision") if record else None,
            "head": record.get("head") if record else None,
            "outcome": verdict.get("outcome") if isinstance(verdict, Mapping) else None,
            "verdict_ref": str(reviewer_records.get(provider)) if isinstance(reviewer_records.get(provider), Path) else None,
        }
        if outcomes.get(provider) == "skipped" or record is None:
            base["hard_stop_reason"] = "missing-evidence"
            return base
        required_fields = ("run_id", "revision", "head", "frozen_input_digest")
        if (
            record.get("schema_version") != 1
            or record.get("gate") != PARALLEL_REVIEW_GATE
            or record.get("provider") != provider
            or record.get("digest_algorithm") != "sha256"
            or any(not isinstance(record.get(field), str) or not record[field].strip() for field in required_fields)
            or not _valid_parallel_review_timestamp(record.get("written_at"))
        ):
            base["hard_stop_reason"] = "mismatched-evidence"
            return base
        if expected_run and any(record.get(key) != expected_run.get(key) for key in ("run_id", "revision", "head")):
            base["hard_stop_reason"] = "stale-evidence"
            return base
        if record.get("frozen_input_digest") != canonical_digest:
            base["hard_stop_reason"] = "mismatched-evidence"
            return base
        verdict = record.get("verdict")
        if not isinstance(verdict, Mapping) or verdict.get("outcome") not in {"approve", "reject"} or not str(verdict.get("reasoning", "")).strip():
            base["hard_stop_reason"] = "conflicting-verdicts"
            return base

    if all(inputs[provider]["outcome"] == "approve" for provider in providers):
        base["outcome"] = "pass"
    else:
        base["hard_stop_reason"] = "conflicting-verdicts"
    return base
