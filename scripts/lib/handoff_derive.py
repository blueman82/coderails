#!/usr/bin/env python3
"""Derive a handoff skeleton from recorded loop state, read-only (provider-neutral).

    handoff_derive.py <progress.json> --session S

Prints one JSON object `{goal, decisions[{id, cite, ...}], done, next_steps, open_questions[], lessons[], degraded[]}`
that the handoff skill (Step 0) uses instead of re-deriving from conversation memory. Inputs: the provider graph.py
`summarize` and `inspect` (subprocess), the typed decisions (progress rows plus Muninn's `list`), the standing-order
lessons (`lessons.joined`) and the proof results. Nothing is written. A source that cannot answer is listed in
`degraded[]` as `{source, reason}` with a reason code from docs/RUNBOOK.md; it is never skipped silently. Exit 0 when
nothing degraded (or only the explicit `memory_backend_off` opt-out), 3 when a source degraded (the skeleton is still
printed with everything that could be read), 2 when the state file itself is unreadable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import decision_record, lessons, proof_results, proof_suite, teardown_steps  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402

GRAPH = ROOT / "skills/agentic-loop/scripts/graph.py"  # the same relative path in both provider layouts
GRAPH_TIMEOUT_S = 30
GOAL_MAX = 300


def _graph(command: str, state: Path) -> dict[str, Any] | None:
    """The parsed JSON of `graph.py <command> <state>`, or None when the graph cannot answer."""
    try:
        run = subprocess.run(
            [sys.executable, str(GRAPH), command, str(state)],
            capture_output=True,
            text=True,
            timeout=GRAPH_TIMEOUT_S,
            check=False,
        )
        value: object = json.loads(run.stdout) if run.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _names(value: object) -> list[str]:
    """Node names from a list that may hold strings or {id|node: ...} objects."""
    out: list[str] = []
    for item in teardown_steps.as_list(value):
        name: object = cast("dict[str, Any]", item).get("id") if isinstance(item, dict) else None
        out.append(str(name) if name else str(cast("object", item)))
    return out


def decisions(
    state: dict[str, Any], loop_id: str, session: str, degraded: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Progress rows (with the K-id and cite when Muninn holds them) plus Muninn decisions the rows do not name."""
    listed = ma.list_records("loop", loop_id, type="decision", session_id=session)
    records: dict[str, ma.Record] = {}
    if isinstance(listed, ma.Degraded):
        degraded.append({"source": "decisions", "reason": listed.reason})
    else:
        records = {str(r.id): r for r in listed}
    rows: object = state.get("decisions_absorbed")
    try:
        decision_record.ensure_chain(state)
    except ValueError:
        degraded.append({"source": "decisions", "reason": "decision_invalid_chain"})
        rows = []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(teardown_steps.as_list(rows), start=1):
        row = cast("dict[str, Any]", item) if isinstance(item, dict) else {"decision": str(item)}
        muninn: object = row.get("muninn")
        kid: object = cast("dict[str, Any]", muninn).get("id") if isinstance(muninn, dict) else None
        found = records.get(str(kid)) if kid else None
        if not isinstance(listed, ma.Degraded):
            field = cast("dict[str, Any]", muninn) if isinstance(muninn, dict) else {}
            if field.get("state") != "written":
                reason = field.get("reason_code")
                degraded.append({"source": "decisions", "reason": str(reason) if reason else "decision_not_cited"})
            elif not kid or not found or not found.cite:
                degraded.append({"source": "decisions", "reason": "decision_cite_missing"})
        seen.update([str(kid)] if kid else [])
        out.append(
            {
                "id": str(kid) if kid else None,
                "cite": found.cite if found else None,
                "seq": row.get("seq", index),
                "phase": row.get("phase"),
                "text": row.get("decision"),
                "source": "progress",
            }
        )
    out += [
        {"id": k, "cite": r.cite, "seq": None, "phase": None, "text": r.claim, "source": "muninn"}
        for k, r in sorted(records.items())
        if k not in seen
    ]
    return out


def lesson_rows(repo_dir: Path, degraded: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The cited standing orders as the dispatch contract serves them; a degrade is reported, never hidden."""
    try:
        ledger = ol.open_ledger(repo_dir)
        if not any(o["status"] == "active" for o in ledger["orders"]):
            return []  # nothing to serve, so there is nothing for a degraded Muninn to hide
        got = lessons.joined(ledger)
    except ol.ChainError:
        degraded.append({"source": "lessons", "reason": "order_chain_broken"})
        return []
    except ValueError:
        degraded.append({"source": "lessons", "reason": "order_state_error"})
        return []
    if "degraded" in got:
        degraded.append({"source": "lessons", "reason": str(got["degraded"])})
        return []
    return cast("list[dict[str, Any]]", lessons.contract(got)["lessons"])


def proof_lines(state_dir: Path, state: dict[str, Any], degraded: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    """Show recorded proof verdicts separately from verified work and name unresolved proofs."""
    try:
        proof_doc, rows, cutoff = proof_suite.active_suite(state_dir / "proof.json", state)
    except proof_results.ChainError:
        degraded.append({"source": "proofs", "reason": "proof_chain_broken"})
        return [], []
    except proof_suite.SuiteError as error:
        degraded.append({"source": "proofs", "reason": str(error).split(":", 1)[0]})
        return [], []
    if proof_doc is None:
        return [], []
    if not isinstance(proof_doc.get("proofs"), list):
        degraded.append({"source": "proofs", "reason": "proof_unreadable"})
        return [], []
    active = {
        item["id"]: item["cmd"]
        for item, _ in proof_suite.items(proof_doc)
        if isinstance(item.get("id"), str) and isinstance(item.get("cmd"), str)
    }
    latest = {
        r["proof_id"]: r["verdict"]
        for r in rows
        if r["seq"] > cutoff
        and r["kind"] == "run"
        and (r["session_id"], r["loop_id"]) == (state.get("session_id"), state.get("loop_id"))
        and r["proof_json_sha256"] == proof_results.doc_sha(proof_doc)
        and r["proof_id"] in active
        and r["cmd_sha256"] == proof_results.sha(active[r["proof_id"]])
    }
    recorded: list[str] = []
    next_steps: list[str] = []
    for item in cast("list[object]", proof_doc["proofs"]):
        if not isinstance(item, dict) or not isinstance(cast("dict[str, Any]", item).get("id"), str):
            degraded.append({"source": "proofs", "reason": "proof_unreadable"})
            return [], []
        name = cast("dict[str, Any]", item)["id"]
        verdict = latest.get(name, "unexecuted")
        line = f"proof {name}: {verdict}"
        recorded.append(line)
        next_steps.append(f"verify {line}" if verdict == "satisfied" else line)
    return recorded, next_steps


def derive(state_path: Path, session: str) -> tuple[dict[str, Any], int]:
    """Return (skeleton, exit code)."""
    try:
        loaded: object = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"reason_code": "handoff_state_unreadable"}, 2
    if not isinstance(loaded, dict):
        return {"reason_code": "handoff_state_unreadable"}, 2
    state = cast("dict[str, Any]", loaded)
    if state.get("session_id") != session:
        return {"reason_code": "handoff_wrong_session"}, 2
    degraded: list[dict[str, str]] = []
    summary, inspected = _graph("summarize", state_path), _graph("inspect", state_path)
    for name, got in (("summarize", summary), ("inspect", inspected)):
        if got is None:
            degraded.append({"source": name, "reason": "graph_unavailable"})
    summary, inspected = summary or {}, inspected or {}
    graph: object = state.get("graph")
    nodes_value: object = cast("dict[str, Any]", graph).get("nodes") if isinstance(graph, dict) else None
    nodes = cast("dict[str, Any]", nodes_value) if isinstance(nodes_value, dict) else {}
    skipped = sorted(
        name
        for name, node in nodes.items()
        if isinstance(node, dict) and cast("dict[str, Any]", node).get("status") == "skipped"
    )
    completed = [name for name in _names(summary.get("done")) if name not in skipped]
    prompt = " ".join(str(state.get("authorising_prompt_raw") or "").split())
    hard_stop: object = inspected.get("hard_stop")
    proof_recorded, proof_next = proof_lines(state_path.parent, state, degraded)
    skeleton: dict[str, Any] = {
        "goal": prompt[:GOAL_MAX],
        "decisions": decisions(state, str(state.get("loop_id") or ""), session, degraded),
        "done": completed,
        "recorded_proof_results": proof_recorded,
        "next_steps": [
            *_names(summary.get("active")),
            *_names(summary.get("ready")),
            *_names(summary.get("pending")),
            *proof_next,
        ],
        "open_questions": ([f"hard stop: {json.dumps(hard_stop, sort_keys=True)}"] if hard_stop else [])
        + (["skipped work: " + ", ".join(skipped)] if skipped else []),
        "lessons": lesson_rows(state_path.parent.parent, degraded),
        "degraded": degraded,
    }
    blocking = [d for d in degraded if d["reason"] != "memory_backend_off"]
    ol.trace(
        "handoff.derive",
        "degraded" if blocking else "derived",
        blocking[0]["reason"] if blocking else "ok",
        session,
        cast("str | None", state.get("loop_id")),
    )
    return skeleton, 3 if blocking else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("state", type=Path, help="the loop's progress.json")
    ap.add_argument("--session", required=True)
    a = ap.parse_args(argv)
    payload, code = derive(a.state, a.session)
    print(json.dumps(payload, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
