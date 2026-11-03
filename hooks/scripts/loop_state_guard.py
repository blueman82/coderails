#!/usr/bin/env python3
"""Require session-owned loop state and graded completion evals."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import read_payload
from hooks.scripts.lib.agentic_loop_path import sanitise_session_id
from hooks.scripts.lib.hook_state import record_absent_block, unstubbed_grace
from hooks.scripts.lib.loop_evals import EvalStatus, EvalVerdict, read_loop_evals
from hooks.scripts.lib.loop_state_common import (
    LoopState,
    load_progress,
    log,
    read_state,
    stable_invocations,
)
from hooks.scripts.lib.trace_row import append_hook_row as append_row
from scripts.lib import orders_completion


def completion_evals(state: LoopState) -> str:
    """Return a completion block when work units lack current graded loop evidence."""
    units = state.data.get("work_units")
    count = len(cast("dict[str, Any] | list[Any] | str", units)) if isinstance(units, (dict, list, str)) else 0
    if not state.complete or count < 1:
        return ""
    verdict = read_loop_evals(state.path.parent)
    suite = read_state(state.path.parent / "evals.json")
    loop = state.data.get("loop_id")
    if loop and any(suite.get(key) != state.data.get(key) for key in ("session_id", "loop_id", "revision")):
        verdict = EvalVerdict(EvalStatus.STALE)
    status = verdict.status
    if status in {EvalStatus.GO, EvalStatus.VERIFICATION_LEVEL0}:
        log(f"hook=loop_state_guard session={state.session} work_units={count} evals={status.value} blocked=0")
        return ""
    log(f"hook=loop_state_guard session={state.session} work_units={count} evals={verdict.label} blocked=1")
    append_row("loop_state_guard", "blocked", f"eval_verdict_{status.name.lower()}", state.session)
    reasons = {
        EvalStatus.UNJUSTIFIED: "missing a non-blank verification_justification",
        EvalStatus.UNSTAMPED: "missing a valid grading stamp",
        EvalStatus.FROZEN: "FROZEN but never graded — it authorised dispatch, not completion. Do NOT regenerate it",
        EvalStatus.STALE: "STALE: does not belong to the current loop revision",
    }
    explanation = reasons.get(status, f"no passing loop-scope evals.json ({verdict.label})")
    if status is EvalStatus.TAMPERED:
        return (
            f"[loop-state-guard] Loop complete with {count} work-units, but evals.json at:\n"
            f"  {state.path.parent / 'evals.json'}\nfailed its tamper check reason={verdict.tamper_code}. "
            f"Re-running grade-loop will refuse with the same code. Revert the oracle edit, or re-apply it with "
            f"post_evals.py amend, then regrade. Trace row: eval_trace.jsonl beside evals.json."
        )
    return (
        f"[loop-state-guard] Loop complete with {count} work-units, but evals.json at:\n"
        f"  {state.path.parent / 'evals.json'}\nhas {explanation}.\n"
        f"Run the frozen evals, record real evidence, then grade via post_evals.py "
        f"grade-loop {state.path.parent / 'evals.json'}."
    )


def main() -> int:
    """Enforce presence and ownership with a single absent-state grace release."""
    payload = read_payload()
    transcript = str(payload.get("transcript_path") or "")
    if not transcript or not Path(transcript).is_file() or payload.get("stop_hook_active") is True:
        return 0
    session = sanitise_session_id(str(payload.get("session_id") or "?"))
    count = stable_invocations(transcript)
    if not count:
        log(f"hook=loop_state_guard session={session} invocations=0 active=0 blocked=0")
        return 0
    state = load_progress(str(payload.get("cwd") or os.getcwd()), session, count)
    if unstubbed_grace(state, "loop_state_guard"):
        return 0
    if message := completion_evals(state):
        print(message, file=sys.stderr)
        return 2
    if state.complete and state.owned and isinstance(state.data.get("graph"), dict):
        try:
            orders_completion.status(state.path, session)
        except (OSError, ValueError) as error:
            log(f"hook=loop_state_guard session={session} orders=pending blocked=1")
            print(f"[loop-state-guard] Standing-orders teardown is pending: {error}", file=sys.stderr)
            return 2
    if state.complete or state.path.is_file() and state.owned and state.data.get("status") != "complete":
        log(
            f"hook=loop_state_guard session={session} invocations={count} "
            f"status={state.data.get('status', '')} owned=1 blocked=0"
        )
        return 0
    if not state.path.is_file():
        reason = "absent"
        record_absent_block(state)
        message = (
            f"[loop-state-guard] Agentic loop active but no progress.json found.\n"
            f"Create it at this exact path (copy it verbatim — never compute the path yourself):\n  {state.path}\n"
            "Create it with the controller command, never by hand: graph.py start <that path> --session <session> "
            "--loop-id <id> --prompt-file <file>, then graph.py add-unit per work unit.\n"
            "If you loaded the agentic-loop skill only to read it or answer a question about it — no loop is "
            "running — do NOT create this file; this guard stands down after this one block."
        )
    elif state.data.get("schema_version") != 3:
        reason = "invalid_schema"
        message = (
            "[loop-state-guard] progress.json must use schema_version 3 for this loop; legacy state is not adopted."
        )
    elif not state.owned:
        reason = "session_mismatch"
        message = (
            f"[loop-state-guard] progress.json at:\n  {state.path}\nhas session_id "
            f"'{state.data.get('session_id', '')}' "
            f"recorded inside it, but this session is '{session}'. Reinitialise session-owned state; "
            "do not adopt or migrate another loop."
        )
    else:
        reason = "stale_complete_rearmed"
        message = (
            f"[loop-state-guard] A new agentic loop has started, but progress.json at:\n  {state.path}\n"
            "still records the previous loop as complete. Run graph.py start for the new loop before stopping."
        )
    log(
        f"hook=loop_state_guard session={session} invocations={count} "
        f"status={state.data.get('status') or 'absent'} reason={reason} blocked=1"
    )
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("loop_state_guard", main))
