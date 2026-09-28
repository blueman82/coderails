#!/usr/bin/env python3
"""Mine deduplicated Claude usage from the owning transcript and linked workers."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import sanitise_session_id
from hooks.scripts.lib.discipline_common import records

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_5m_tokens", "cache_write_1h_tokens")


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def mine_transcripts(transcripts: list[Path]) -> dict[str, dict[str, float]]:
    """Sum the first occurrence of each native message ID across linked transcripts."""
    models: dict[str, dict[str, float]] = {}
    seen: set[str] = set()
    for path in transcripts:
        for record in records(str(path)):
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            message = cast(dict[str, Any], message)
            identifier, model, usage = message.get("id"), message.get("model"), message.get("usage")
            if (
                not isinstance(identifier, str)
                or identifier in seen
                or not isinstance(model, str)
                or model == "<synthetic>"
                or not isinstance(usage, dict)
            ):
                continue
            usage = cast(dict[str, Any], usage)
            seen.add(identifier)
            counts = models.setdefault(model, dict.fromkeys(TOKEN_FIELDS, 0.0))
            creation = usage.get("cache_creation")
            counts["input_tokens"] += _number(usage.get("input_tokens"))
            counts["output_tokens"] += _number(usage.get("output_tokens"))
            counts["cache_read_tokens"] += _number(usage.get("cache_read_input_tokens"))
            counts["cache_write_5m_tokens"] += _number(
                cast(dict[str, Any], creation).get("ephemeral_5m_input_tokens")
                if isinstance(creation, dict)
                else usage.get("cache_creation_input_tokens")
            )
            counts["cache_write_1h_tokens"] += _number(
                cast(dict[str, Any], creation).get("ephemeral_1h_input_tokens") if isinstance(creation, dict) else None
            )
    return models


def mine_token_usage(session: str) -> dict[str, Any]:
    """Return frozen per-model tokens and estimates; infrastructure failures stay advisory."""
    if not session:
        print("loop_cost: empty session id", file=sys.stderr)
        return {
            "error": "loop_cost: empty session id",
            "hint": "mine_token_usage requires a session id as its first argument",
        }
    prices_path = Path(os.environ.get("CLAUDE_MODEL_PRICES_FILE", str(Path(__file__).with_name("model_prices.json"))))
    try:
        prices = json.loads(prices_path.read_text())
        if not isinstance(prices, dict) or not isinstance(cast(dict[str, Any], prices).get("per_mtok", {}), dict):
            raise ValueError("prices must contain an object of model rates")
    except (OSError, ValueError):
        print(f"loop_cost: prices file not found or invalid at {prices_path}", file=sys.stderr)
        return {}
    prices = cast(dict[str, Any], prices)
    projects = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude/projects")))
    session = sanitise_session_id(session)
    orchestrator = next((path for path in sorted(projects.glob(f"*/{session}.jsonl")) if path.is_file()), None)
    if orchestrator is None:
        print(f"loop_cost: no transcript found for session {session} under {projects}", file=sys.stderr)
        return {
            "error": f"loop_cost: no transcript found for session {session}",
            "hint": (
                "check the session id is the live orchestrator session and CLAUDE_PROJECTS_DIR "
                "points at the right projects dir"
            ),
        }
    transcripts = [orchestrator, *sorted((orchestrator.parent / session / "subagents").rglob("*.jsonl"))]
    models = mine_transcripts(transcripts)
    unpriced: list[str] = []
    rates = prices.get("per_mtok", {})
    rate_names = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
    for model, tokens in models.items():
        rate = rates.get(model, rates.get(re.sub(r"-[0-9]{8}$", "", model)))
        if not isinstance(rate, dict):
            tokens["usd_estimate"] = 0
            unpriced.append(model)
        else:
            tokens["usd_estimate"] = sum(
                tokens[field] * _number(cast(dict[str, Any], rate).get(name)) / 1_000_000
                for field, name in zip(TOKEN_FIELDS, rate_names)
            )
    window = os.environ.get("CLAUDE_HEADLESS_WINDOW_SECS", "3600")
    seconds = int(window) if window.isdigit() else 3600
    excluded = 0
    try:
        stamp = int(orchestrator.stat().st_mtime)
        excluded = sum(
            abs(int(path.stat().st_mtime) - stamp) <= seconds
            for path in orchestrator.parent.glob("*.jsonl")
            if path != orchestrator and path.is_file()
        )
    except OSError:
        pass
    return {
        "schema_version": 1,
        "prices_as_of": prices.get("prices_as_of", ""),
        "price_source": prices.get("price_source", ""),
        "per_model": models,
        "total_tokens": sum(tokens[key] for tokens in models.values() for key in TOKEN_FIELDS),
        "total_usd_estimate": sum(tokens["usd_estimate"] for tokens in models.values()),
        "transcripts_scanned": len(transcripts),
        "unpriced_models": sorted(unpriced),
        "models_used": sorted(models),
        "headless_children_excluded_count": excluded,
        "notes": (
            "headless claude -p child sessions excluded from per_model/total_tokens (own "
            "top-level session, no parent linkage to attribute their tokens) — see "
            "headless_children_excluded_count for how many candidates were detected in the "
            "same project dir within the activity window"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(mine_token_usage(sys.argv[1] if len(sys.argv) > 1 else "")))
