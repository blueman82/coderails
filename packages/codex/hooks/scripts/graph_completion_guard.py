#!/usr/bin/env python3
"""Block Stop while a native Codex graph remains unresolved."""

from __future__ import annotations

import json
import re
import sys
from contextlib import suppress
from pathlib import Path
from typing import cast

from hook_common import (
    RESOURCE_MESSAGE,
    HostResourceError,
    append_trace_row,
    continue_turn,
    graph_output,
    graph_path,
    log,
    loop_state_path,
    payload_object,
    read_input,
    text_field,
)


def unresolved(state: Path) -> bool:
    """Return whether valid graph state still has work or a hard stop."""
    try:
        raw_state: object = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(raw_state, dict):
        return False
    state_object = cast(dict[str, object], raw_state)
    graph = state_object.get("graph")
    if not isinstance(graph, dict):
        return False
    graph_object = cast(dict[str, object], graph)
    if graph_object.get("active_wave") is not None or graph_object.get("hard_stop") is not None:
        return True
    nodes = graph_object.get("nodes")
    joins = graph_object.get("joins")
    if not isinstance(nodes, dict) or not isinstance(joins, dict):
        return False
    node_objects = cast(dict[str, object], nodes)
    join_objects = cast(dict[str, object], joins)
    node_pending = any(
        not isinstance(node, dict) or cast(dict[str, object], node).get("status") not in {"done", "skipped"}
        for node in node_objects.values()
    )
    join_pending = any(
        not isinstance(join, dict) or cast(dict[str, object], join).get("released") is not True
        for join in join_objects.values()
    )
    return node_pending or join_pending


def hard_stop_declaration(message: str) -> bool:
    """Return whether the last nonblank line is an accepted hard-stop declaration."""
    lines = [line for line in message.splitlines() if line.strip()]
    return bool(lines) and lines[-1] in {
        "LOOP-STOP: waiting-on-human",
        "LOOP-STOP: stopped",
        "LOOP-STOP: stall",
    }


def request_human_approval(state: Path, session_id: str, inspection: dict[str, object]) -> None:
    """Emit the established deduplicated unresolved-graph Stop response."""
    loop_id = text_field(inspection, "loop_id")
    revision = inspection.get("revision")
    if not loop_id or not isinstance(revision, int):
        continue_turn("Native graph unresolved; stopping remains blocked.")
        return
    safe_loop = re.sub(r"[^A-Za-z0-9_.-]", "_", loop_id)
    marker = state.parent / f".human-approval-{safe_loop}-{revision}"
    message = json.dumps(
        {
            "decision": "block",
            "reason": "Native graph unresolved; stopping remains blocked.",
            "systemMessage": "Human approval required: the native graph is unresolved. Approve the next action "
            "or resume the loop; stopping remains blocked until the graph is complete.",
        }
    )
    log(f"hook=graph_completion_guard session={session_id} blocked=1")
    created = False
    try:
        marker.mkdir()
        created = True
    except FileExistsError:
        if marker.is_dir():
            continue_turn("Native graph unresolved; stopping remains blocked.")
            return
        log(f"hook=graph_completion_guard session={session_id} human_request=dedupe_write_failed")
    except OSError:
        log(f"hook=graph_completion_guard session={session_id} human_request=dedupe_write_failed")
    try:
        print(message)
    except (OSError, ValueError):
        if created:
            with suppress(OSError):
                marker.rmdir()
        raise


def main() -> int:
    """Block Stop unless graph completion or a declared hard stop permits it."""
    payload = payload_object(read_input())
    if payload.get("stop_hook_active") is True:
        return 0
    session_id = text_field(payload, "session_id")
    cwd = text_field(payload, "cwd")
    if not session_id or not cwd:
        return 0
    state = loop_state_path(cwd, session_id)
    if state is None or not state.is_file():
        return 0
    graph = graph_path()
    try:
        inspection = graph_output(graph, "inspect", str(state))
    except HostResourceError:
        continue_turn(RESOURCE_MESSAGE)
        return 0
    if inspection is None:
        continue_turn("The active Codex graph state is invalid. Repair progress.json before stopping.")
        return 0
    if text_field(inspection, "session_id") != session_id:
        continue_turn("The active Codex graph belongs to another session. Repair the state path before stopping.")
        return 0
    message = text_field(payload, "last_assistant_message")
    if inspection.get("hard_stop") is not None:
        try:
            recorded = graph_output(graph, "consume-stop", str(state), "--session", session_id)
        except HostResourceError:
            recorded = None
        if recorded is not None and recorded.get("stop") is not None:
            log(f"hook=graph_completion_guard session={session_id} recorded_stop=consumed blocked=0")
            return 0
        if hard_stop_declaration(message):
            log(f"hook=graph_completion_guard session={session_id} legacy_text_parse=1 blocked=0")
            append_trace_row("graph_completion_guard", "fallback", "legacy_text_parse", session_id)
            return 0
    try:
        verified = (
            graph_output(
                graph,
                "verify-completion",
                str(state),
                "--session",
                session_id,
                "--evals",
                str(state.parent / "evals.json"),
                "--proof",
                str(state.parent / "proof.json"),
                "--retro",
                str(state.parent / "retro.json"),
                "--transcript",
                text_field(payload, "transcript_path"),
            )
            is not None
        )
    except HostResourceError:
        continue_turn(RESOURCE_MESSAGE)
        return 0
    if verified:
        return 0
    if not unresolved(state):
        continue_turn(
            "The native Codex graph passed graph checks but completion evidence is invalid. "
            "Repair evals, proof, or retro evidence before stopping."
        )
        return 0
    try:
        request_human_approval(state, session_id, inspection)
    except (OSError, ValueError):
        print("Native graph unresolved; required notice could not be emitted. Retry stopping.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
