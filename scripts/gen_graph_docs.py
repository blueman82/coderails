#!/usr/bin/env python3
"""Render the generated regions of the agentic-loop docs from graph-spec.yaml and policy.yaml.

Usage: python3 scripts/gen_graph_docs.py [--check] [--root DIR]

Each region sits between `<!-- BEGIN GENERATED graph-spec:NAME -->` and `<!-- END GENERATED graph-spec:NAME -->`.
Without `--check` the regions are rewritten in place; with it nothing is written and the exit status is 1 when any
region differs from what the spec renders (a hand-edited row, or a spec edit that was not regenerated).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_spec  # noqa: E402

MARKER = "<!-- {edge} GENERATED graph-spec:{name} -->"
THRESHOLD_TEXT = {
    "design_doc_min_units": (
        "`S2.7a`/`S2.7b` (spec.md and plan.md) fire only for a loop with at least this many work units or a "
        "cross-unit dependency; the same line Phase 3 draws between one agent and a spawned team"
    ),
    "loop_evals_min_units": (
        "`S2.7c` loop-scope evals are required from this many work units (`loop_dispatch_guard` and "
        "`loop_state_guard` still hard-code the floor of 1: this key documents it, no hook reads it yet)"
    ),
    "retry_max": "default per-node retry bound (the pure core caps it at 5)",
    "repair_attempts_max": "distinct repair attempts per failure (`U5-repair[i]` procedure bound)",
    "graph.profile": (
        "what `graph.py instantiate` builds when `--profile` is absent: `units-only` is the unit lane `U3[i]` plus "
        "`J12-all-units`; `full` is every node and join in the table (guards are conditional procedures)"
    ),
}


def _flat(policy: dict[str, Any]) -> dict[str, Any]:
    return {**{k: v for k, v in policy.items() if k != "graph"}, "graph.profile": policy["graph"]["profile"]}


def _text(value: str, policy: dict[str, Any]) -> str:
    return value.format(**policy)


def table(spec: dict[str, Any], policy: dict[str, Any]) -> str:
    """The node table: one row per spec node, in spec order."""
    rows = [
        "| ID | Kind | Node / true prerequisites | Ready when | Conditional skip or join |",
        "|---|---|---|---|---|",
    ]
    for node in spec["nodes"]:
        cells = [_text(node[key], policy) for key in ("prereq_text", "ready_when", "skip_text")]
        rows.append(f"| `{node['id']}` | `{node['kind']}` | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def diagram(spec: dict[str, Any], _policy: dict[str, Any]) -> str:
    """A mermaid flowchart of every requirement among the graph nodes (guards are cross-cutting, so omitted)."""
    nodes = [n for n in spec["nodes"] if n["kind"] != "guard"]
    ident = {n["id"]: "n_" + re.sub(r"\W", "_", n["id"]) for n in nodes}
    by_base = {n["id"].removesuffix("[i]"): n for n in nodes}
    lines = ["```mermaid", "flowchart TD"]
    for node in nodes:
        shape = ('(["', '"])') if node["kind"] == "join" else ('["', '"]')
        lines.append(f"    {ident[node['id']]}{shape[0]}{node['id']}{shape[1]}")
    for node in nodes:
        for pattern in node["requires"]:
            source = by_base[pattern.removesuffix("[i]")]
            lines.append(f"    {ident[source['id']]} --> {ident[node['id']]}")
    lines.append("```")
    return "\n".join(lines)


def thresholds(_spec: dict[str, Any], policy: dict[str, Any]) -> str:
    """The policy thresholds with their meaning; every policy key must have text."""
    flat = _flat(policy)
    if set(flat) != set(THRESHOLD_TEXT):
        raise SystemExit(f"gen_graph_docs: threshold text must cover exactly {sorted(flat)}")
    rows = ["| Policy key | Value | Meaning |", "|---|---|---|"]
    rows += [f"| `{key}` | `{value}` | {THRESHOLD_TEXT[key]} |" for key, value in flat.items()]
    return "\n".join(rows)


REGIONS: dict[str, dict[str, Callable[[dict[str, Any], dict[str, Any]], str]]] = {
    "skills/agentic-loop/execution-graph.md": {"diagram": diagram, "table": table},
    "skills/agentic-loop/phases-setup.md": {"thresholds": thresholds},
}


def render(text: str, name: str, body: str) -> str:
    """Replace the body between a region's markers; a missing or duplicated marker is an error."""
    begin, end = MARKER.format(edge="BEGIN", name=name), MARKER.format(edge="END", name=name)
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) > text.index(end):
        raise SystemExit(f"gen_graph_docs: region graph-spec:{name} needs exactly one BEGIN then one END marker")
    head, rest = text.split(begin, 1)
    return f"{head}{begin}\n{body}\n{end}" + rest.split(end, 1)[1]


def main(argv: list[str]) -> int:
    """Regenerate (or, with --check, verify) every region."""
    root = Path(argv[argv.index("--root") + 1]).resolve() if "--root" in argv else ROOT
    shared = root / "packages/graph-semantics"
    policy = graph_spec.load_policy(shared / "policy.yaml")
    spec = graph_spec.load_spec(shared / "graph-spec.yaml")
    stale: list[str] = []
    for relative, regions in REGIONS.items():
        path = root / relative
        text = path.read_text(encoding="utf-8")
        updated = text
        for name, build in regions.items():
            updated = render(updated, name, build(spec, policy))
        if updated != text:
            stale.append(f"{relative} ({', '.join(regions)})")
            if "--check" not in argv:
                path.write_text(updated, encoding="utf-8")
    if stale and "--check" in argv:
        print("gen_graph_docs: stale generated regions, run scripts/gen_graph_docs.py: " + "; ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
