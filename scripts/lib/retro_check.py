"""The completion gate for retro.json: recompute every source hash, the decisions chain and the teardown steps.

Shared by the Claude gate (`hooks/scripts/lib/loop_completion.py`) and the Codex gate
(`packages/codex/skills/agentic-loop/scripts/graph_artifacts.py`); both call `check(state, retro, state_dir)`. A retro
below schema_version 3, or one without `source_hashes`, was not produced by `retro.py assemble` and is refused.

Reason codes (see docs/RUNBOOK.md, "Memory degraded (Muninn authoritative)"): retro_not_assembled,
retro_source_mismatch (names the field), retro_decisions_chain_broken, retro_steps_missing. A Muninn degrade never
blocks: blocking completion on an external store would deadlock the loop, so `check` returns a disclosure instead.
`loop_stop_counts.complete` is left out of the hash: the hook increments it when it consumes the very declaration this
gate validates. Cooperating-agent safeguard: a same-user agent can re-assemble the retro over edited sources.

Recomputed from sources and compared: decisions_absorbed, envelope, loop_stop_counts, evals, proof_results,
disposition_record, the teardown step order and each required step's evidence_sha256 (proof_run = proof_results.jsonl,
decisions_flushed = decisions_absorbed, retro_assembled = the source hashes, orders_prepared = D4's
owner/source-bound preparation artifact. The later orders_ticked observation is excluded from frozen source hashes.
ADVISORY, not recomputed (they come from per-session traces and transcripts that cannot be replayed at the gate):
`hook_blocks`, `cost`, `models_used`, `memory`, `free`. A forged retro can therefore misstate those, including hiding
order-level Muninn degrade counts; the decision-level degrade disclosure reads the hashed progress.json instead.
`proof.py disposition` records proof_run on purpose (the typed disposition resolves the proof stage), and a full
`proof.py run` over an empty proof.json also records it; the Codex gate refuses an empty proofs list separately.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import decision_record, proof_results, teardown_steps  # noqa: E402

SCHEMA = 3
FILES = ("evals.json", "proof.json", "proof_results.jsonl")


class RetroError(ValueError):
    """A reason-coded refusal; str() is '<code>: <detail>'."""

    def __init__(self, code: str, detail: str) -> None:
        """Keep the code and detail."""
        super().__init__(f"{code}: {detail}")
        self.code = code


def stop_counts(state: dict[str, Any]) -> object:
    """loop_stop_counts without the `complete` category (see the module docstring)."""
    counts: object = state.get("loop_stop_counts")
    if isinstance(counts, dict):
        return {k: v for k, v in cast("dict[str, Any]", counts).items() if str(k).lower() != "complete"}
    return {} if counts is None else counts  # an absent object and an object with no other stops hash the same


def _file_hash(path: Path) -> str | None:
    """sha256 of the canonical JSON of a .json file (a formatting-only rewrite is no edit), else of the bytes."""
    if path.suffix == ".json":
        try:
            return teardown_steps.sha_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return teardown_steps.file_sha(path)


def source_hashes(state: dict[str, Any], state_dir: Path) -> dict[str, str | None]:
    """The sha256 of each source the retro copies from; None for an absent file or key's canonical `null`."""
    out: dict[str, str | None] = {
        "progress.decisions_absorbed": teardown_steps.sha_json(state.get("decisions_absorbed")),
        "progress.loop_stop_counts": teardown_steps.sha_json(stop_counts(state)),
        "progress.authorising_prompt_raw": teardown_steps.sha_json(state.get("authorising_prompt_raw")),
    }
    for name in FILES:
        out[name] = _file_hash(state_dir / name)
    try:
        rows = teardown_steps.hashed_view(teardown_steps.read_rows(state_dir))
    except ValueError:
        out["teardown.jsonl"] = "unreadable"
        return out
    out["teardown.jsonl"] = teardown_steps.sha_json(rows) if rows else None
    return out


def retro_step_hashes(state: dict[str, Any], state_dir: Path) -> dict[str, str | None]:
    """Hash sources for a retro_assembled receipt without self-reference, retaining the preparation evidence."""
    out = source_hashes(state, state_dir)
    try:
        rows = teardown_steps.hashed_view(teardown_steps.read_rows(state_dir))
    except ValueError:
        out["teardown.jsonl"] = "unreadable"
    else:
        prior = [row for row in rows if row["step"] != "retro_assembled"]
        out["teardown.jsonl"] = teardown_steps.sha_json(prior) if prior else None
    return out


def proof_summary(state_dir: Path) -> dict[str, Any]:
    """Latest verdict per proof id plus any typed no-proof disposition, from the chained results file."""
    try:
        rows = proof_results.read_rows(state_dir / proof_results.RESULTS_NAME)
    except proof_results.ChainError:
        return {"error": "proof_chain_broken"}
    verdicts = {r["proof_id"]: r["verdict"] for r in rows if r["kind"] == "run"}
    notes = [f"{r['verdict']}: {r['excerpt']}" for r in rows if r["kind"] == "disposition"]
    return {"verdicts": verdicts, "disposition": notes[-1] if notes else ""}


def disposition_record(state: dict[str, Any]) -> dict[str, Any]:
    """Per work-unit disposition; `found` false means no record was kept (an audit failure, not a pass)."""
    units: object = state.get("work_units")
    listed = cast("dict[str, Any]", units) if isinstance(units, dict) else {}
    found: dict[str, Any] = {}
    for name, unit in listed.items():
        found[name] = cast("dict[str, Any]", unit).get("disposition") if isinstance(unit, dict) else None
    return {"units": found, "found": any(v for v in found.values())}


def evals_section(state_dir: Path) -> dict[str, Any]:
    """The retro's evals summary, read from <state-dir>/evals.json."""
    try:
        loaded: object = json.loads((state_dir / "evals.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        loaded = {}
    evals = cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}
    return {"result": evals.get("result"), "amendments": evals.get("amendments", [])}


def _prepared_sources(state: dict[str, Any], revision: int) -> list[dict[str, Any]]:
    """Match the final pre-preparation Stop after the Claude hook consumes it."""
    source = copy.deepcopy(state)
    root = Path(__file__).resolve().parents[2]
    if (root / ".codex-plugin/plugin.json").is_file() and source.get("status") == "complete":
        completion = source.get("completion")
        if not isinstance(completion, dict):
            return []
        completion_record = cast("dict[str, Any]", completion)
        if (
            type(completion_record.get("revision")) is not int
            or completion_record["revision"] != source.get("revision", 0) - 1
        ):
            return []
        source["revision"] = completion_record["revision"]
    elif "completion" in source:
        return []
    teardown_steps.normalize_consumed_complete_stop(source)
    for key in ("status", "completion", "completed_marker"):
        source.pop(key, None)
    counts = source.get("loop_stop_counts")
    if isinstance(counts, dict):
        typed_counts = cast("dict[str, Any]", counts)
        remaining = {k: v for k, v in typed_counts.items() if k != "complete"}
        source.pop("loop_stop_counts")
        if remaining:
            source["loop_stop_counts"] = remaining
    if revision != source.get("revision"):
        return []
    return [source]


def _preparation_evidence(state: dict[str, Any], state_dir: Path, rows: list[dict[str, Any]]) -> str | None:
    """Validate D4's latest source-bound preparation receipt and return its evidence hash."""
    prepared_rows = [row for row in rows if row.get("step") == "orders_prepared"]
    if not prepared_rows:
        return None
    row = prepared_rows[-1]
    binding = row.get("binding")
    fields = {"repo_dir", "state_dir", "session_id", "loop_id", "revision", "progress_sha256"}
    if not isinstance(binding, dict):
        return None
    bound = cast("dict[str, Any]", binding)
    if set(bound) != fields:
        return None
    session, loop = state.get("session_id"), state.get("loop_id")
    if (
        row.get("session_id") != session
        or row.get("loop_id") != loop
        or type(row.get("revision")) is not int
        or row.get("revision") != bound.get("revision")
        or bound.get("repo_dir") != str(state_dir.parent.resolve())
        or bound.get("state_dir") != str(state_dir.resolve())
        or bound.get("session_id") != session
        or bound.get("loop_id") != loop
        or type(bound.get("revision")) is not int
        or not isinstance(bound.get("progress_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", bound["progress_sha256"])
    ):
        return None
    if not any(
        bound["progress_sha256"] == teardown_steps.sha_json(s) for s in _prepared_sources(state, bound["revision"])
    ):
        return None

    path = state_dir / f"orders-prepared-{hashlib.sha256(str(loop).encode()).hexdigest()}.json"
    try:
        if path.is_symlink():
            return None
        prepared: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(prepared, dict):
        return None
    prepared_record = cast("dict[str, Any]", prepared)
    if (
        type(prepared_record.get("schema")) is not int
        or prepared_record.get("schema") != 1
        or prepared_record.get("binding") != bound
        or not isinstance(prepared_record.get("records"), list)
    ):
        return None
    digest = teardown_steps.sha_json(prepared_record)
    if row.get("evidence_sha256") != digest:
        return None
    timestamp = row.get("ts")
    if not isinstance(timestamp, str):
        return None
    try:
        datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return digest


def _evidence_problem(state: dict[str, Any], state_dir: Path, rows: list[dict[str, Any]]) -> str:
    """Name the first required step whose latest row's evidence_sha256 does not recompute from the live sources."""
    latest = {r["step"]: r for r in rows}
    pre = retro_step_hashes(state, state_dir)
    expected: dict[str, object] = {
        "proof_run": teardown_steps.file_sha(state_dir / proof_results.RESULTS_NAME),
        "orders_prepared": _preparation_evidence(state, state_dir, rows),
        "decisions_flushed": teardown_steps.sha_json(state.get("decisions_absorbed")),
        "retro_assembled": teardown_steps.sha_json(pre),
    }
    base_fields = {"step", "ts", "session_id", "loop_id", "evidence_sha256"}
    for step in teardown_steps.REQUIRED:
        row = latest.get(step)
        if (
            row is None
            or row.get("session_id") != state.get("session_id")
            or row.get("loop_id") != state.get("loop_id")
        ):
            return step
        if step != "orders_prepared":
            if set(row) != base_fields or not isinstance(row.get("ts"), str):
                return step
            try:
                datetime.datetime.fromisoformat(row["ts"])
            except ValueError:
                return step
        if (step == "orders_prepared" and expected[step] is None) or row.get("evidence_sha256") != expected[step]:
            return step
    return ""


def memory_disclosure(state: dict[str, Any], retro: dict[str, Any]) -> list[str]:
    """Counts and reason codes of decisions and orders that never reached Muninn (informational, never blocking)."""
    rows: object = state.get("decisions_absorbed")
    codes: dict[str, int] = {}
    for item in teardown_steps.as_list(rows):
        field: object = cast("dict[str, Any]", item).get("muninn") if isinstance(item, dict) else None
        if isinstance(field, dict):
            f = cast("dict[str, Any]", field)
            if f.get("state") in ("pending", "degraded"):
                code = str(f.get("reason_code") or "pending")
                codes[code] = codes.get(code, 0) + 1
    out: list[str] = []
    if codes:
        out.append(
            f"Memory degraded: {sum(codes.values())} decision(s) not in Muninn ("
            + ", ".join(f"{c}: {n}" for c, n in sorted(codes.items()))
            + ")"
        )
    memory: object = retro.get("memory")
    degraded: object = cast("dict[str, Any]", memory).get("degraded") if isinstance(memory, dict) else None
    for command, counts in sorted(cast("dict[str, Any]", degraded).items()) if isinstance(degraded, dict) else []:
        if command.startswith("order.") and isinstance(counts, dict):
            c = cast("dict[str, int]", counts)
            out.append(
                f"Memory degraded: {sum(c.values())} {command} event(s) ("
                + ", ".join(f"{k}: {v}" for k, v in sorted(c.items()))
                + ")"
            )
    return out


def check(state: dict[str, Any], retro: dict[str, Any], state_dir: Path) -> list[str]:
    """Raise RetroError on a stale, hand-written or tampered retro; return Muninn-degrade disclosures otherwise."""
    version = retro.get("schema_version")
    stored: object = retro.get("source_hashes")
    if isinstance(version, bool) or not isinstance(version, int) or version < SCHEMA or not isinstance(stored, dict):
        raise RetroError(
            "retro_not_assembled", f"retro.json must be schema_version {SCHEMA}+; run `python3 scripts/lib/retro.py "
            "assemble <state-dir> --session <session_id>`"
        )  # fmt: skip
    have = cast("dict[str, Any]", stored)
    fresh = source_hashes(state, state_dir)
    changed = sorted(k for k in fresh if fresh[k] != have.get(k))
    if changed:
        raise RetroError(
            "retro_source_mismatch", f"{', '.join(changed)} changed after assembly; re-run retro.py assemble"
        )
    for field, current in (
        ("decisions_absorbed", state.get("decisions_absorbed")),
        ("envelope", state.get("authorising_prompt_raw")),
    ):
        if retro.get(field) != current:
            raise RetroError(
                "retro_source_mismatch", f"retro.{field} differs from progress.json; re-run retro.py assemble"
            )
    if stop_counts({"loop_stop_counts": retro.get("loop_stop_counts")}) != stop_counts(state):
        raise RetroError(
            "retro_source_mismatch", "retro.loop_stop_counts differs from progress.json; re-run retro.py assemble"
        )
    rows: object = state.get("decisions_absorbed")
    start = state.get("chain_started_seq")
    bad = decision_record.verify_chain(teardown_steps.as_list(rows), start if isinstance(start, int) else None)
    if bad:
        raise RetroError(
            "retro_decisions_chain_broken",
            "decisions_absorbed fails verify_chain at " + ", ".join(f"seq {b['seq']} ({b['reason']})" for b in bad),
        )
    for field, derived in (
        ("evals", evals_section(state_dir)),
        ("proof_results", proof_summary(state_dir)),
        ("disposition_record", disposition_record(state)),
    ):
        if retro.get(field) != derived:
            raise RetroError(
                "retro_source_mismatch", f"retro.{field} differs from its sources; re-run retro.py assemble"
            )
    try:
        teardown_rows = teardown_steps.read_rows(state_dir)
        done = teardown_steps.steps_done(teardown_rows)
    except ValueError as error:
        raise RetroError("retro_steps_missing", "teardown.jsonl is unreadable") from error
    problem = teardown_steps.order_problem(done)
    if problem:
        raise RetroError("retro_steps_missing", f"teardown steps {problem}")
    unbound = _evidence_problem(state, state_dir, teardown_rows)
    if unbound:
        raise RetroError(
            "retro_steps_missing", f"teardown step {unbound} evidence does not match its sources; re-run the step"
        )
    teardown: object = retro.get("teardown")
    listed: object = cast("dict[str, Any]", teardown).get("steps_done") if isinstance(teardown, dict) else None
    required = [s for s in done if s in teardown_steps.REQUIRED]
    if [s for s in teardown_steps.as_list(listed) if s in teardown_steps.REQUIRED] != required:
        raise RetroError(
            "retro_steps_missing", "retro.teardown.steps_done differs from teardown.jsonl; re-run retro.py assemble"
        )
    return memory_disclosure(state, retro)
