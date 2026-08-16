#!/usr/bin/env python3
"""Write one run-bound gate artifact from a Codex-owned execution prompt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.codex_exec import invoke  # noqa: E402

RESULTS = {
    "review": ("review_status", "pass"),
    "eval": ("result", "GO"),
    "proof": ("result", "pass"),
    "integrity": ("integrity", "pass"),
    "wiki": ("result", "pass"),
    "teardown": ("result", "pass"),
}


def produce(gate: str, artifact: Path, raw: Path, run_id: str, revision: str, head: str, cwd: str, retro: Path | None = None, executor=invoke) -> dict:
    if gate not in RESULTS:
        raise ValueError(f"unknown gate: {gate}")
    prompt = f"Codex E3 {gate} gate: report GATE_{gate.upper()}_OK. Do not edit files or run commands."
    outcome, output = executor(prompt, cwd)
    if outcome != "done":
        raise RuntimeError(f"Codex gate execution failed for {gate}: {output}")
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
    raw.write_text(output, encoding="utf-8")
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
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--retro", type=Path)
    args = parser.parse_args()
    print(json.dumps(produce(args.gate, args.artifact, args.raw, args.run_id, args.revision, args.head, args.cwd, args.retro)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
