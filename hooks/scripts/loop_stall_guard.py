#!/usr/bin/env python3
"""Require an explicit loop stop and validate completion evidence before release."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import read_payload
from hooks.scripts.lib.agentic_loop_path import sanitise_session_id
from hooks.scripts.lib.discipline_common import stable_text
from hooks.scripts.lib.graph_dispatch import validate_graph_completion, validate_graph_shape
from hooks.scripts.lib.loop_completion import validate_completion
from hooks.scripts.lib.loop_evals import read_loop_evals_result
from hooks.scripts.lib.loop_state_common import (
    LOOP_STOP_VOCAB,
    LoopState,
    atomic_progress_update,
    consume_stop,
    load_progress,
    log,
    read_state,
    recorded_stop,
    stable_invocations,
    stop_category,
    stop_ran_this_turn,
    unstubbed_grace,
)
from hooks.scripts.lib.stall_notice import marker_name, record_notice, seen, status_notice
from hooks.scripts.lib.trace_row import append_row


def graph_unresolved(state: LoopState) -> bool:
    """Report unresolved validated graph nodes, joins, waves, or hard stops."""
    graph = state.data.get("graph")
    if not isinstance(graph, dict):
        return False
    graph = cast(dict[str, Any], graph)
    validate_graph_shape(state.path)
    return (
        graph.get("active_wave") is not None
        or graph.get("hard_stop") is not None
        or any(node.get("status") not in {"done", "skipped"} for node in graph["nodes"].values())
        or any(join.get("released") is not True for join in graph["joins"].values())
    )


def emit_human_request(state: LoopState) -> str:
    """Emit the deduplicated unresolved-graph notice; return the status text for the model-facing stderr."""
    name = marker_name(state.data, state.session)
    base = (
        "Human approval required: the native graph is unresolved. Approve the next action "
        "or resume the loop; stopping remains blocked until the graph is complete."
    )
    if name is None:
        log(f"hook=loop_stall_guard session={state.session} human_request=no_marker_key")
        try:
            print(json.dumps({"systemMessage": base}))
            sys.stdout.flush()
        except (OSError, ValueError) as error:
            raise ValueError("could not emit the required human request; retry stopping") from error
        return ""
    if seen(state.path, name):
        return ""
    graph_cli = Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts/graph.py"
    status = status_notice(graph_cli, state.path, state.session, log)  # never raises
    try:
        print(json.dumps({"systemMessage": f"{base}\n{status}"}))
        sys.stdout.flush()  # the marker must not outlive an undelivered notice
    except (OSError, ValueError) as error:
        raise ValueError("could not emit the required human request; retry stopping") from error
    record_notice(state.path, state.session, name, log)  # only after the notice is out
    return status


def blocked_message(status: str) -> str:
    """Stop-block reason; carries the status line and dispatch hint, since the model sees only stderr."""
    return "Native graph unresolved; stopping remains blocked." + (f"\n{status}" if status else "")


def complete(state: LoopState, transcript: str) -> list[str]:
    """Check completion artifacts, current eval bindings, and native graph evidence."""
    messages = validate_completion(state, transcript)
    if not isinstance(state.data.get("graph"), dict):
        raise ValueError("graph shape is missing or malformed")
    validate_graph_completion(state.path, state.session)
    suite = read_state(state.path.parent / "evals.json")
    verdict = read_loop_evals_result(state.path.parent)
    if any(suite.get(key) != state.data.get(key) for key in ("session_id", "loop_id", "revision")):
        verdict = "STALE"
    if verdict not in {"GO", "VERIFICATION_LEVEL0"}:
        raise ValueError(f"loop evals are {verdict}; run and grade the frozen suite via post_evals.py grade-loop")
    for name in ("proof.json", "retro.json"):
        path = state.path.parent / name
        if name == "proof.json" and not path.is_file():
            continue
        artifact = read_state(path)
        if any(artifact.get(key) != state.data.get(key) for key in ("session_id", "loop_id")):
            raise ValueError(f"{name} belongs to another loop")
    return messages


def main() -> int:
    """Block undeclared stops and refuse incomplete or unaudited completion."""
    payload = read_payload()
    transcript = str(payload.get("transcript_path") or "")
    if not transcript or not Path(transcript).is_file() or payload.get("stop_hook_active") is True:
        return 0
    session = sanitise_session_id(str(payload.get("session_id") or "?"))
    count = stable_invocations(transcript)
    if not count:
        return 0
    state = load_progress(str(payload.get("cwd") or os.getcwd()), session, count)
    if unstubbed_grace(state, "loop_stall_guard"):
        return 0
    recorded = recorded_stop(state.data)
    if recorded and not stop_ran_this_turn(transcript):  # a row from an earlier turn is stale, never a release
        if state.path.is_file():
            append_row(
                "loop_stall_guard", "fallback", "stale_stop_row", session, str(state.data.get("loop_id") or "") or None
            )
        recorded = None
    category = str(recorded["category"]) if recorded else ""
    if not recorded:
        text, _ = stable_text(
            transcript,
            int(os.environ.get("CLAUDE_HOOK_TAIL_LINES", "300")),
            int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5")),
            float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3")),
        )
        category = stop_category(text)
        if category and state.path.is_file():  # never fabricate loop state for a loop that has none
            loop_id = str(state.data.get("loop_id") or "") or None
            append_row("loop_stall_guard", "fallback", "legacy_text_parse", session, loop_id)
    try:
        if category:
            if category.lower() == "complete" and graph_unresolved(state):
                raise ValueError(blocked_message(emit_human_request(state)))
            messages = complete(state, transcript) if category.lower() == "complete" else []
            if messages:
                print(json.dumps({"systemMessage": "\n".join(messages)}))

            def increment(data: dict[str, Any]) -> dict[str, Any]:
                counters = data.setdefault("loop_stop_counts", {})
                if not isinstance(counters, dict):
                    raise ValueError("loop_stop_counts must be an object")
                counters = cast(dict[str, Any], counters)
                counters[category] = counters.get(category, 0) + 1
                if recorded:  # consume in the same write that counts it, so a repeated Stop cannot double-count
                    consume_stop(data, recorded["seq"])
                return data

            if not atomic_progress_update(state.path, increment):
                log(f"hook=loop_stall_guard session={session} counter_write=json_failed category={category}")
            log(f"hook=loop_stall_guard session={session} invocations={count} declared=1 blocked=0")
            return 0
        if state.complete:
            return 0
        if graph_unresolved(state):
            raise ValueError(blocked_message(emit_human_request(state)))
    except ValueError as error:
        print(f"[loop-stall-guard] {error}", file=sys.stderr)
        return 2
    log(f"hook=loop_stall_guard session={session} invocations={count} declared=0 blocked=1")
    print(
        "[loop-stall-guard] Active agentic loop, no LOOP-STOP declaration in your last message.\n"
        f"Continue the loop, OR end your message with:\n  LOOP-STOP: <{LOOP_STOP_VOCAB}> — <reason>\n"
        'Declaring complete means the loop is done: set progress.json status to "complete" and run Phase 13.',
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
