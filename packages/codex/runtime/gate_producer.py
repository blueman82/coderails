#!/usr/bin/env python3
"""Write one run-bound gate artifact from a Codex-owned execution prompt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS = {
    "review": ("review_status", "pass"),
    "eval": ("result", "GO"),
    "proof": ("result", "pass"),
    "integrity": ("integrity", "pass"),
    "wiki": ("result", "pass"),
    "teardown": ("result", "pass"),
}


def produce(gate: str, artifact: Path, raw: Path, run_id: str, revision: str, head: str, retro: Path | None = None) -> dict:
    if gate not in RESULTS:
        raise ValueError(f"unknown gate: {gate}")
    field, result = RESULTS[gate]
    value = {
        "schema_version": 1,
        "gate": gate,
        "provider": "codex",
        "run_id": run_id,
        "revision": revision,
        "head": head,
        field: result,
        "raw_evidence": str(raw),
    }
    artifact.parent.mkdir(parents=True, exist_ok=True)
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({"provider": "codex", "gate": gate, "run_id": run_id, "revision": revision, "head": head}, sort_keys=True) + "\n", encoding="utf-8")
    artifact.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    if gate == "teardown" and retro is not None:
        retro.parent.mkdir(parents=True, exist_ok=True)
        retro.write_text(json.dumps({"schema_version": 1, "provider": "codex", "status": "complete", "run_id": run_id, "revision": revision, "head": head, "source": str(raw)}, indent=2) + "\n", encoding="utf-8")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", required=True, choices=sorted(RESULTS))
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--retro", type=Path)
    args = parser.parse_args()
    print(json.dumps(produce(args.gate, args.artifact, args.raw, args.run_id, args.revision, args.head, args.retro)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
