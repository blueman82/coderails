#!/usr/bin/env python3
"""Measure provider graph-alignment evidence: hook counts, bootstrap bytes, gate telemetry, state divergence.

Read-only. Emits counts and paths only; never reads or prints transcript, prompt or log-message content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import trace_counters  # noqa: E402
from scripts.lib.receipt_counters import receipt_summary  # noqa: E402

MEMORY_COUNTERS = Path(__file__).with_name("lib") / "memory_counters.py"
HOOK_FIELD = re.compile(r"(?:^|\s)hook=([A-Za-z0-9_.-]+)")
FLAG_FIELDS = ("blocked", "would_block", "warned", "demoted")
WORK_UNIT_TERMINAL = frozenset({"done", "dropped"})
GRAPH_SUCCESS = frozenset({"done", "skipped"})
GRAPH_SEMANTICS_COPIES = (
    "packages/graph-semantics/graph_semantics.py",
    "skills/agentic-loop/scripts/graph_semantics.py",
    "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
)
LOCK_REASONS = ("lock_busy", "lock_stolen_age", "lock_stolen_dead_owner")
ADAPTER_DIRS = {"claude": "skills/agentic-loop/scripts", "codex": "packages/codex/skills/agentic-loop/scripts"}


def as_dict(value: object) -> dict[str, Any]:
    """Return value if it is a JSON object, else {}."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def as_list(value: object) -> list[object]:
    """Return value if it is a JSON array, else []."""
    return cast(list[object], value) if isinstance(value, list) else []


def read_object(path: Path) -> dict[str, Any]:
    """Return a JSON object from path, or {} when unreadable, malformed or not an object."""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return as_dict(value)


def hook_counts(hooks_json: Path) -> dict[str, int]:
    """Count registered hook commands per event type, plus a total; {} when the file is absent."""
    events = as_dict(read_object(hooks_json).get("hooks"))
    if not events:
        return {}
    counts = {event: sum(len(as_list(as_dict(g).get("hooks"))) for g in as_list(m)) for event, m in events.items()}
    counts["total"] = sum(counts.values())
    return counts


def injected_bytes(script: Path, root_env: dict[str, str]) -> int | None:
    """Run a SessionStart hook with an empty payload and return the UTF-8 size of its additionalContext."""
    if not script.is_file():
        return None
    env = {**os.environ, **root_env}
    try:
        result = subprocess.run(
            [sys.executable, str(script)], input="{}", capture_output=True, text=True, env=env, timeout=15, check=False
        )
        output = cast(dict[str, Any], json.loads(result.stdout))
        context = output["hookSpecificOutput"]["additionalContext"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    return len(str(context).encode("utf-8"))


def file_bytes(path: Path) -> int | None:
    """Return the byte size of a file, or None when it is missing."""
    return path.stat().st_size if path.is_file() else None


def bootstrap_bytes(root: Path) -> dict[str, Any]:
    """Measure what each provider's SessionStart hook injects (empty payload: no cwd, no session, no nudge)."""
    claude_script = root / "hooks/scripts/inject_bootstrap.py"
    codex_script = root / "packages/codex/hooks/scripts/inject_bootstrap.py"
    return {
        "claude": {
            "source": "hooks/scripts/inject_bootstrap.py",
            "injected_bytes": injected_bytes(claude_script, {"CLAUDE_PLUGIN_ROOT": str(root)}),
            "skill_bytes": file_bytes(root / "skills/using-coderails/SKILL.md"),
        },
        "codex": {
            "source": "packages/codex/hooks/scripts/inject_bootstrap.py",
            "injected_bytes": injected_bytes(codex_script, {"PLUGIN_ROOT": str(root / "packages/codex")}),
            "deferred_skill_bytes": file_bytes(root / "packages/codex/skills/using-coderails/SKILL.md"),
        },
    }


def parse_telemetry(log_path: Path) -> dict[str, Any]:
    """Count per-gate total/decisions/blocked/would_block/warned/demoted from `hook=<name> ...` lines; zeros if missing.

    `total` is every line naming the hook; `decisions` is the subset carrying a `blocked=0|1` field.
    """
    gates: dict[str, dict[str, int]] = {}
    lines = 0
    first = last = ""
    try:
        with log_path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = HOOK_FIELD.search(line)
                if not match:
                    continue
                lines += 1
                gate = gates.setdefault(match.group(1), {"total": 0, "decisions": 0, **dict.fromkeys(FLAG_FIELDS, 0)})
                gate["total"] += 1
                gate["decisions"] += bool(re.search(r"(?:^|\s)blocked=[01](?:\s|$)", line))
                for flag in FLAG_FIELDS:
                    if re.search(rf"(?:^|\s){flag}=1(?:\s|$)", line):
                        gate[flag] += 1
                first = first or line.split(" ", 1)[0]
                last = line.split(" ", 1)[0]
    except OSError:
        pass
    return {
        "log": str(log_path),
        "lines": lines,
        "first_timestamp": first,
        "last_timestamp": last,
        "gates": dict(sorted(gates.items())),
    }


def telemetry_paths() -> dict[str, Path]:
    """Resolve each provider's discipline log exactly as its log() does, honouring the redirect env vars."""
    claude = os.environ.get("CLAUDE_DISCIPLINE_LOG", str(Path.home() / ".claude/discipline.log"))
    data_dir = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails/codex")))
    codex = os.environ.get("CODERAILS_DISCIPLINE_LOG", str(data_dir / "discipline.log"))
    return {"claude": Path(claude), "codex": Path(codex)}


def loop_state_roots() -> list[Path]:
    """Return candidate agentic-loop state roots for both providers, de-duplicated."""
    default = Path.home() / ".coderails/agentic-loop"
    candidates = [
        Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(default))),
        Path(os.environ.get("CODERAILS_AGENTIC_LOOP_DIR", str(default))),
        Path.home() / ".claude/agentic-loop",
        Path.home() / ".codex/agentic-loop",
    ]
    return list(dict.fromkeys(candidates))


def statuses(items: object) -> list[object]:
    """Return the `status` of every entry in a mapping; None for malformed entries."""
    return [as_dict(entry).get("status") for entry in as_dict(items).values()]


def classify(state: dict[str, Any]) -> dict[str, bool]:
    """Classify one progress.json: presence flags and terminal-state divergence (strict and lenient).

    Strict: a work_unit is terminal only when its status is exactly `done` or `dropped` (the completion rule).
    Lenient: free-text statuses that begin with `done` or `dropped` also count as terminal.
    """
    units = as_dict(state.get("work_units"))
    nodes = as_dict(as_dict(state.get("graph")).get("nodes"))
    both = bool(units) and bool(nodes)
    graph_complete = all(s in GRAPH_SUCCESS for s in statuses(nodes))
    strict = all(s in WORK_UNIT_TERMINAL for s in statuses(units))
    lenient = all(isinstance(s, str) and s.startswith(tuple(WORK_UNIT_TERMINAL)) for s in statuses(units))
    return {
        "work_units": bool(state.get("work_units")),
        "graph_nodes": bool(nodes),
        "both": both,
        "divergent": both and strict != graph_complete,
        "divergent_lenient": both and lenient != graph_complete,
    }


def graph_vs_work_units() -> dict[str, Any]:
    """Scan `<root>/*/*/progress.json` read-only and count loops by work_units/graph/divergence."""
    seen: set[Path] = set()
    totals = dict.fromkeys(
        ("loops", "with_work_units", "with_graph_nodes", "with_both", "divergent", "divergent_lenient"), 0
    )
    for base in loop_state_roots():
        for path in sorted(base.glob("*/*/progress.json")):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            flags = classify(read_object(path))
            totals["loops"] += 1
            totals["with_work_units"] += flags["work_units"]
            totals["with_graph_nodes"] += flags["graph_nodes"]
            totals["with_both"] += flags["both"]
            totals["divergent"] += flags["divergent"]
            totals["divergent_lenient"] += flags["divergent_lenient"]
    return {"roots": [str(r) for r in loop_state_roots()], **totals}


def trace_counts() -> dict[str, Any]:
    """Count `<root>/*/trace.jsonl` rows once per event_id (torn/keyless skipped); counts only, never row inputs."""
    seen: set[str] = set()
    by_reason: dict[str, int] = {}
    rows = duplicates = malformed = 0
    for path in sorted({p.resolve() for base in loop_state_roots() for p in base.glob("*/trace.jsonl")}):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = as_dict(json.loads(line))
            except ValueError:
                row = {}
            event_id = row.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                malformed += 1
            elif event_id in seen:
                duplicates += 1
            else:
                seen.add(event_id)
                rows += 1
                key = f"{row.get('command')}/{row.get('outcome')}/{row.get('reason_code')}"
                by_reason[key] = by_reason.get(key, 0) + 1
    counts = {"rows": rows, "duplicates": duplicates, "malformed": malformed, "receipts": receipt_summary(by_reason)}
    return {**counts, "by_reason": dict(sorted(by_reason.items()))}


def recovery_counters() -> dict[str, Any]:
    """Count recoveries, controller starts/add-units/refusals, retries from loop state and advisory trace."""
    seen: set[Path] = set()
    refused = failed = stale = recovered = starts = add_units = legacy_refusals = 0
    codes: dict[str, int] = {}
    refusals: dict[str, int] = {}
    for base in loop_state_roots():
        for path in sorted(base.glob("*/*/progress.json")):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            for node in as_dict(as_dict(read_object(path).get("graph")).get("nodes")).values():
                entry = as_dict(node)
                failed += as_dict(entry.get("retry")).get("attempts", 0) or 0
                stale += as_dict(entry.get("respawn")).get("generation", 0) or 0
                refused += sum(as_dict(e).get("outcome") == "launch_refused" for e in as_list(entry.get("evidence")))
            try:
                lines = path.with_name("recovery-trace.jsonl").read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            events: set[str] = set()
            for line in lines:
                try:
                    row = as_dict(json.loads(line))
                except ValueError:
                    continue
                key = row.get("event_id") or (
                    "|".join(str(row.get(k)) for k in ("ts", "command", "outcome", "reason_code", "inputs_sha256"))
                    if row.get("ts") and row.get("inputs_sha256")
                    else None
                )  # a command writes one row per node: count events, not rows; keyless legacy rows count singly
                if key is not None:
                    if key in events:
                        continue
                    events.add(str(key))
                code = str(row.get("reason_code"))
                codes[code] = codes.get(code, 0) + 1
                recovered += row.get("outcome") == "recovered"
                legacy_refusals += code == "legacy_task_identity_refused"
                starts += row.get("command") == "start" and row.get("outcome") in {"created", "rearmed"}
                add_units += row.get("command") == "add-unit" and row.get("outcome") == "registered"
                if row.get("outcome") == "refused" and row.get("command") in {"start", "add-unit"}:
                    refusals[code] = refusals.get(code, 0) + 1
    return {
        "recoveries": recovered,
        "legacy_task_refusals": legacy_refusals,
        "refused_spawns": refused,
        "retries_by_cause": {"failed": failed, "stale_recovery": stale},
        "trace_rows_by_reason_code": dict(sorted(codes.items())),
        "controller": {"starts": starts, "add_units": add_units, "refusals_by_reason": dict(sorted(refusals.items()))},
    }


def line_count(path: Path) -> int | None:
    """Return the number of lines in a file, or None when it is missing."""
    try:
        return len(path.read_bytes().splitlines())
    except OSError:
        return None


def duplication(root: Path) -> dict[str, Any]:
    """Report line counts of the graph_semantics copies, byte-identity among them, and adapter script totals."""
    copies = {rel: line_count(root / rel) for rel in GRAPH_SEMANTICS_COPIES}
    digests = {hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in GRAPH_SEMANTICS_COPIES if copies[rel]}
    adapters = {
        provider: {p.name: line_count(p) for p in sorted((root / rel).glob("*.py"))}
        for provider, rel in ADAPTER_DIRS.items()
    }
    return {
        "graph_semantics_lines": copies,
        "graph_semantics_distinct_contents": len(digests),
        "adapter_lines": adapters,
        "adapter_total_lines": {p: sum(v or 0 for v in files.values()) for p, files in adapters.items()},
    }


def lock_events() -> dict[str, int]:
    """Count non-authoritative lock events per reason code, deduped by event_id across all loop-state roots."""
    counts: dict[str, int] = dict.fromkeys(LOCK_REASONS, 0)
    seen: set[str] = set()
    for root in loop_state_roots():
        try:
            logs = sorted(root.rglob("lock-events.jsonl"))
        except OSError:
            continue
        for log in logs:
            try:
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = as_dict(json.loads(line))
                except ValueError:
                    continue
                event_id, reason = row.get("event_id"), row.get("reason")
                if isinstance(event_id, str) and event_id not in seen and reason in counts:
                    seen.add(event_id)
                    counts[cast(str, reason)] += 1
    return counts


def eval_trace_counts(extra: list[Path]) -> dict[str, Any]:
    """Count eval_trace.jsonl rows (command|outcome|reason_code) deduped by event_id; no row content is kept."""
    return trace_counters.eval_trace_counts(
        [f for r in loop_state_roots() for f in sorted(r.glob("*/*/eval_trace.jsonl"))] + extra
    )


def measure(root: Path, extra_traces: list[Path] | None = None) -> dict[str, Any]:
    """Assemble the full measurement object for a repository root."""
    return {
        "root": str(root),
        "hook_counts": {
            "claude": hook_counts(root / "hooks/hooks.json"),
            "codex": hook_counts(root / "packages/codex/hooks/hooks.json"),
        },
        "bootstrap_bytes": bootstrap_bytes(root),
        "gate_blocks": {provider: parse_telemetry(path) for provider, path in telemetry_paths().items()},
        "graph_vs_work_units": graph_vs_work_units(),
        "trace": trace_counts(),
        "memory": runpy.run_path(str(MEMORY_COUNTERS))["memory_counts"](loop_state_roots()),
        "recovery": recovery_counters(),
        "duplication": duplication(root),
        "lock_events": lock_events(),
        "eval_trace": eval_trace_counts(extra_traces or []),
        "context": trace_counters.context_counts(
            [f for r in loop_state_roots() for f in sorted(r.glob("*/trace.jsonl"))]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, fail closed on a missing root, and print one JSON object."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="repository root to measure")
    parser.add_argument("--json", action="store_true", help="print JSON (the only supported format)")
    parser.add_argument("--eval-trace", action="append", default=[], help="extra eval_trace.jsonl (PR-scope sinks)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"measure_graph_alignment: root is not a directory: {root}", file=sys.stderr)
        return 2
    print(json.dumps(measure(root.resolve(), [Path(p) for p in args.eval_trace]), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
