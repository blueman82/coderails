#!/usr/bin/env python3
"""Render the generated regions of the agentic-loop docs from graph-spec.yaml and policy.yaml.

Usage: python3 scripts/gen_graph_docs.py [--check] [--root DIR]

Each region sits between `<!-- START GENERATED graph-spec:NAME -->` and `<!-- END GENERATED graph-spec:NAME -->`.
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
        "Run `S2.7a` and `S2.7b` if the loop has this number of units or more, or if units depend on each other. "
        "Phase 3 uses the same conditions to select one agent or a team."
    ),
    "loop_evals_min_units": (
        "Run the `S2.7c` loop evals if the loop has this number of work units or more. "
        "`loop_dispatch_guard` and `loop_state_guard` use a fixed minimum of 1. No hook reads this key."
    ),
    "retry_max": "Default limit for retries for one node. The graph core sets a maximum of 5.",
    "repair_attempts_max": "Limit for different repairs to try for each problem in `U5-repair[i]`.",
    "graph.profile": (
        "`graph.py instantiate` uses this value if you do not specify `--profile`. "
        "`units-only` includes `U3[i]` and `J12-all-units`. "
        "`full` includes all nodes and joins in the table. Each guard has its own condition."
    ),
}

# These descriptions change the rendered text only. The runtime hashes the spec and
# can use its original text in worker prompts. Key by source text so a spec edit
# renders the new text and the generated-file check can detect the change.
TABLE_WORDING = {
    "Start state (`graph.py start`)": "Start the loop with `graph.py start`.",
    "path helper returns the session-owned state path": "The path helper gives the session its loop path.",
    "never skipped": "Do not skip.",
    "Improve prompt": "Revise the prompt.",
    "prompt is adopted, revised, or explicit opt-out is recorded": (
        "The workflow records the prompt selection. Accept the proposed prompt, revise it, or record an opt-out."
    ),
    "full-autonomous auto-adopts; otherwise one bounded input point": (
        "Full autonomy accepts the proposed prompt automatically. In other modes, get user input at one step."
    ),
    "never a gate; no model switch is performed by the orchestrator": (
        "This notice does not block the workflow. The orchestrator does not change the model."
    ),
    "never spawn implementation before this node": "Start implementation only after this node.",
    "design scout returned a recommendation and flip-condition": (
        "The scout gives a recommendation and the condition that would change it."
    ),
    "disposition scout returned a result for every retirement unit": (
        "The scout gives a result for each retirement unit."
    ),
    "all triggered scouts returned; orchestrator validated and absorbed both results in one state write": (
        "All applicable scouts give results. The orchestrator checks them and records them in one write."
    ),
    "same predicate as `S2.7a`; `S2.7b` is sequential after it": (
        "Use the same condition as `S2.7a`. Start `S2.7b` after `S2.7a`."
    ),
    (
        "required for any `work_units >= {loop_evals_min_units}` loop or an irreversible-surface trigger; NOT "
        "gated by `S2.7a`'s ≥{design_doc_min_units}-work-unit threshold"
    ): (
        "Run if `work_units >= {loop_evals_min_units}` or if an irreversible operation is in scope. The `S2.7a` "
        "minimum of {design_doc_min_units} units does not apply here."
    ),
    "skip only for a unit with no PR; required before its merge gate": (
        "Skip only if the unit has no PR. Complete this step before its merge gate."
    ),
    "blind `proof.json` exists, or explicit no-executable disposition is recorded": (
        "A blind `proof.json` exists, or the record says the loop has no executable surface."
    ),
    "required for every executable loop; independent of `S2.7a/b`": (
        "Run for each loop with an executable surface. The conditions for `S2.7a/b` do not apply here."
    ),
    "every build unit has one recorded model role": "The record has one model role for each build unit.",
    "may run beside independent evidence branches; never releases a unit without its required inputs": (
        "This node can run in parallel with branches that collect their own results. A unit must have all "
        "necessary inputs before it can start."
    ),
    "all inputs for the first eligible unit are present": "All inputs exist for the first eligible unit.",
    "later units wait on their own true prerequisites": "Each subsequent unit waits for its own prerequisites.",
    "worker produced the unit's committed artifact/OPEN PR terminal state": (
        "The worker has made the unit's committed artifact or opened its PR, as specified."
    ),
    "units with `blockedBy` dependencies wait; independent units may run in waves": (
        "A unit with unfinished `blockedBy` dependencies waits. Units without dependencies on each other can "
        "run in waves."
    ),
    (
        "artifact, worktree, PR, and worker report were checked by the orchestrator (a "
        "`NEEDS_DECISION`/`OUTSIDE_SCOPE`/`IRREVERSIBLE_ACTION` result is validated by `record-wave` through "
        "`scripts/worker_status.py`, recorded in `worker_statuses` with one typed stop row, and counts as a "
        "failed attempt; the orchestrator surfaces it to the human)"
    ): (
        "The orchestrator checks the artifact, worktree, PR, and worker report. For `NEEDS_DECISION`, "
        "`OUTSIDE_SCOPE`, or `IRREVERSIBLE_ACTION`, `record-wave` checks the result through "
        "`scripts/worker_status.py`. It records the result in `worker_statuses` with one typed stop row. This "
        "counts as one unsuccessful try. The orchestrator tells the user."
    ),
    "idle is not failure; failed artifact check enters repair": (
        "Inactivity alone does not show a problem. If the check rejects the artifact, start repair."
    ),
    "required review Skill, security/deploy review when triggered, and SHA-bound post-review artifact exist": (
        "Run the mandatory `/pr-review-toolkit:review-pr` Skill. Run `security-review` and `deploy-safety` when "
        "the policy requires them. The post-review artifact must apply to the PR head SHA."
    ),
    "review findings go to `U5[i]`; no merge on a missing artifact": (
        "Send problems from the inspection to `U5[i]`. Merge only when the artifact exists."
    ),
    "source-of-truth premise is confirmed and diagnosis is disconfirmed": (
        "The source proves the premise. The check disproves the diagnosis."
    ),
    "premise disproven is a hard-stop; otherwise spawn the repair worker": (
        "If the source disproves the premise, stop. If it proves the premise, dispatch the repair worker."
    ),
    "distinct fix attempt applied and locally verified": "The worker makes a different repair and checks it locally.",
    "back to `U4[i]`; at most {repair_attempts_max} distinct attempts per failure": (
        "Go back to `U4[i]`. For each problem, try a different repair up to {repair_attempts_max} times."
    ),
    "current unit is verified and any in-scope confirmation decision is resolved": (
        "The current unit passes its checks. The user or workflow has made each applicable decision in scope."
    ),
    "no extra ask inside the envelope": "Continue without a new approval if the envelope permits the work.",
    "skip when no push/deploy surface; these phases do not add generic policy": (
        "Skip if the unit has no push or deploy step. These phases add no general policy."
    ),
    "`U4b-review[i]`, `U6[i]`, `U7/8[i]`, PR-scope eval, review artifact, and integrity attestation": (
        "`U4b-review[i]`, `U6[i]`, `U7/8[i]`, the PR-scope eval, the inspection artifact, and the integrity attestation"
    ),
    "exact-head review/eval/integrity checks and gate-time smoke pass; merge reports `MERGED`": (
        "The inspection, eval, integrity, and gate-time smoke checks pass for the PR head SHA. The merge "
        "reports `MERGED`."
    ),
    "any missing/stale/failing gate enters `U5-repair[i]` or hard-stop after retry bound": (
        "If a gate has no result, gives a stale result, or fails, go to `U5-repair[i]`. Stop if the retry limit "
        "prevents repair."
    ),
    "`U4[i]` artifact check shows dispatch failure/idle without artifact": (
        "The `U4[i]` artifact check shows that dispatch did not succeed or the worker has no output and no artifact."
    ),
    "new versioned worker name and fresh dispatch exist": "A new versioned worker name and a new dispatch exist.",
    "not triggered by an idle ping alone; returns to `U4[i]`": (
        "An idle ping alone does not cause a respawn. After a respawn, go back to `U4[i]`."
    ),
    "every unit's merge gate passed": "The merge gate passed for each unit.",
    "each merged PR and dependent deployment evidence is freshly rechecked": (
        "Check each merged PR and its dependent deployment results again."
    ),
    "any respawn path": "Each respawn path",
    "every replacement worker name is versioned": "Each replacement worker name includes a version.",
    "cross-cutting Phase 10 guard; no standalone work": (
        "Apply this guard during Phase 10. It has no work of its own."
    ),
    "every worker dispatch and report": "Each worker dispatch and report",
    "cross-cutting Phase 11 guard; no standalone work": (
        "Apply this guard during Phase 11. It has no work of its own."
    ),
    "every artifact boundary": "Each artifact boundary",
    "cross-cutting Phase 12 guard; `J12-all-units` is its final aggregate join": (
        "Apply this guard during Phase 12. `J12-all-units` is the last join for this guard."
    ),
    "clustered wiki ingest and lint landed and were verified on `origin/main`": (
        "The grouped wiki ingest and lint changes are on `origin/main`. Check that branch for the changes."
    ),
    "skip only when no wiki update is in scope; still record the skip": (
        "Skip only if no wiki update is in scope. Record the skip."
    ),
    "one `/sync-docs` audit completed and findings triaged": (
        "One `/sync-docs` audit has run. The auditor has classified the results."
    ),
    "every frozen proof command ran verbatim in the orchestrator session and passed": (
        "Each frozen proof command ran without changes in the orchestrator session and passed."
    ),
    "absent proof requires the recorded no-executable disposition": (
        "If there is no proof, the record must say the loop has no executable surface."
    ),
    "Phase 13 report, cost, decisions, artifacts, eval result, standing orders, and feedback are written": (
        "The record includes the Phase 13 report, cost, decisions, artifacts, eval result, "
        "`standing-orders.md`, and feedback."
    ),
    "never a mid-loop checkpoint": "Run at the end of the loop.",
    "final aggregate verification passes; `progress.json` is complete and `retro.json` is valid": (
        "The last set of checks passes. `progress.json` is complete and `retro.json` passes validation."
    ),
    "terminal node; emits `LOOP-STOP: complete`": "The graph ends here. The node gives `LOOP-STOP: complete`.",
}


def _flat(policy: dict[str, Any]) -> dict[str, Any]:
    return {**{k: v for k, v in policy.items() if k != "graph"}, "graph.profile": policy["graph"]["profile"]}


def _text(value: str, policy: dict[str, Any]) -> str:
    return TABLE_WORDING.get(value, value).format(**policy)


def table(spec: dict[str, Any], policy: dict[str, Any]) -> str:
    """The node table: one row per spec node, in spec order."""
    rows = [
        "| ID | Type | Node / prerequisites | Conditions to satisfy | Conditional skip or join |",
        "|---|---|---|---|---|",
    ]
    for node in spec["nodes"]:
        cells = [_text(node[key], policy) for key in ("prereq_text", "ready_when", "skip_text")]
        if node["id"] == "U4[i]":
            cells[1] = cells[1].replace("`scripts/worker_status.py`", "`skills/agentic-loop/scripts/worker_status.py`")
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
    begin, end = MARKER.format(edge="START", name=name), MARKER.format(edge="END", name=name)
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) > text.index(end):
        raise SystemExit(f"gen_graph_docs: region graph-spec:{name} needs exactly one START then one END marker")
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
