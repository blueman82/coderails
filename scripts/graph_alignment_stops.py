#!/usr/bin/env python3
"""Count typed stop intents against legacy text/log fallbacks; read-only, counts only, never row content.

Flip rule: if legacy_text_parse still dominates stops_consumed after the first few loops, agents are not running
`graph.py stop`; tighten the text parse instead of retiring it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.measure_graph_alignment import as_dict, as_list, loop_state_roots

FALLBACKS = ("legacy_text_parse", "legacy_log_parse")


def count() -> dict[str, int]:
    """Tally stops[] rows from every progress.json and fallback reason codes from every trace.jsonl, once per event."""
    totals = {"stops_recorded": 0, "stops_consumed": 0, **{code: 0 for code in FALLBACKS}}
    progress = {p.resolve() for base in loop_state_roots() for p in base.glob("*/*/progress.json")}
    for path in sorted(progress):
        try:
            rows = [as_dict(r) for r in as_list(as_dict(json.loads(path.read_text(encoding="utf-8"))).get("stops"))]
        except (OSError, ValueError):
            continue
        totals["stops_recorded"] += sum(1 for r in rows if "consumed" in r)
        totals["stops_consumed"] += sum(1 for r in rows if r.get("consumed") is True)
    seen: set[str] = set()
    for path in sorted({p.resolve() for base in loop_state_roots() for p in base.glob("*/trace.jsonl")}):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = as_dict(json.loads(line))
            except ValueError:
                continue
            event, code = entry.get("event_id"), entry.get("reason_code")
            if isinstance(event, str) and event not in seen and code in FALLBACKS:
                seen.add(event)
                totals[str(code)] += 1
    return totals


def main(argv: list[str] | None = None) -> int:
    """Print one JSON object of counters."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON (the only supported format)")
    parser.parse_args(argv)
    print(json.dumps(count(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
