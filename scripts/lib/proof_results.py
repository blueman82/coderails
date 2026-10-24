"""proof_results.jsonl: the controller-recorded, hash-chained results of frozen proof commands, and their verifier.

Rows sit beside proof.json. kind is freeze (sha256 of the canonical proof.json), run (the controller executed one
frozen cmd) or disposition (a typed no-proof decision). Each row carries prev_sha256 and row_sha256, so deleting or
editing any row breaks the chain. Honest limit: a same-user agent can forge rows the way it can forge a transcript;
this is a cooperating-agent safeguard, not a trust boundary. The latest freeze wins (an agent can re-freeze a
weakened proof set), and the destructive classifier is literal-pattern, not a sandbox.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import runpy
import subprocess
from pathlib import Path
from typing import Any, cast

REASONS: dict[str, str] = {
    "proof_unexecuted": "no run row for this proof; run `python3 scripts/lib/proof.py run <state-dir> --all`.",
    "proof_failed": "the latest run exited nonzero or timed out; fix the cause and re-run the same proof.",
    "proof_expect_mismatch": "the run's exit code or stdout did not match the frozen expect; fix and re-run.",
    "proof_stale_cmd": "proof.json changed after the freeze row, or the run row hashes a different cmd; re-freeze.",
    "proof_stale_head": "the proof ran outside this repository or before HEAD changed; run it again at current HEAD.",
    "proof_chain_broken": "proof_results.jsonl is torn, edited or missing rows; never edit it by hand.",
    "proof_cmd_destructive": "the frozen cmd matches the destructive-command classifier and was never run.",
    "proof_no_proofs": "proof.json holds no non-withdrawn proof and no valid disposition; add a proof or record one.",
    "proof_disposition_no_reason": "a bare 'none' or unknown reason code is rejected; record an enum code + reason.",
    "proof_disposition_legacy": "string disposition 'none: <reason>' accepted; prefer `proof.py disposition`.",
    "proof_withdrawn_unobserved": "a withdrawn proof needs an observed failed/timeout run row and a reason.",
}
RESULTS_NAME = "proof_results.jsonl"
DISPOSITION_CODES = ("docs_only", "no_executable_surface", "research_only", "superseded", "other")
GENESIS = "0" * 64
VERDICT_REASON = {
    "failed": "proof_failed",
    "timeout": "proof_failed",
    "expect_mismatch": "proof_expect_mismatch",
    "refused": "proof_cmd_destructive",
}
_FIELDS = [
    *("seq", "kind", "proof_id", "cmd_sha256", "proof_json_sha256", "session_id", "loop_id", "head_sha", "cwd"),
    *("exit_code", "stdout_sha256", "stderr_sha256", "excerpt", "started", "ended", "expect_matched", "verdict"),
]


class ChainError(ValueError):
    """The results file is unreadable or its hash chain does not verify."""


def sha(text: str) -> str:
    """Return the hex sha256 of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_sha(doc: object) -> str:
    """Hash a proof document canonically, so formatting-only edits do not count as changes."""
    return sha(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _digest(row: dict[str, Any]) -> str:
    return sha(json.dumps({k: v for k, v in row.items() if k != "row_sha256"}, sort_keys=True, ensure_ascii=False))


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Read and chain-verify every row; a missing file is an empty chain."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as error:
        raise ChainError(f"unreadable: {error}") from error
    rows: list[dict[str, Any]] = []
    previous = GENESIS
    for number, line in enumerate(lines, 1):
        try:
            value: object = json.loads(line)
        except ValueError as error:
            raise ChainError(f"row {number} is not JSON") from error
        if not isinstance(value, dict):
            raise ChainError(f"row {number} is not an object")
        row = cast(dict[str, Any], value)
        if row.get("seq") != number or row.get("prev_sha256") != previous or row.get("row_sha256") != _digest(row):
            raise ChainError(f"row {number} breaks the hash chain")
        previous = row["row_sha256"]
        rows.append(row)
    return rows


def append(path: Path, **fields: object) -> dict[str, Any]:
    """Append one chained row under an exclusive lock and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        rows = read_rows(path)
        row: dict[str, Any] = {name: fields.get(name) for name in _FIELDS}
        row["seq"] = len(rows) + 1
        row["prev_sha256"] = rows[-1]["row_sha256"] if rows else GENESIS
        row["row_sha256"] = _digest(row)
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return row


def trace(command: str, outcome: str, reason: str, session_id: object, loop_id: object) -> None:
    """Append a fail-open trace row (proof.freeze|run|gate) when this layout ships trace_row.py."""
    try:
        path = Path(__file__).resolve().parents[2] / "hooks/scripts/lib/trace_row.py"
        runpy.run_path(str(path))["append_row"](
            command, outcome, reason, str(session_id or "proof-nosession"), cast("str | None", loop_id)
        )
    except Exception:  # noqa: BLE001 - tracing never blocks
        return


def find_disposition(state: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Return '<code>: <reason>' for a valid no-proof disposition (code in DISPOSITION_CODES), else ''."""
    value = state.get("proof_disposition")
    if isinstance(value, dict):
        item = cast(dict[str, Any], value)
        code, reason = item.get("reason_code"), item.get("reason")
        if item.get("kind") == "none" and code in DISPOSITION_CODES and isinstance(reason, str) and reason.strip():
            return f"{code}: {reason.strip()}"
    elif isinstance(value, str) and value.startswith("none:") and value[5:].strip():
        trace("proof.gate", "accepted", "proof_disposition_legacy", state.get("session_id"), state.get("loop_id"))
        return f"legacy: {value[5:].strip()}"
    identity = (state.get("session_id"), state.get("loop_id"))
    for row in rows:
        valid = row["verdict"] in DISPOSITION_CODES and str(row["excerpt"] or "").strip()
        if row["kind"] == "disposition" and (row["session_id"], row["loop_id"]) == identity and valid:
            return f"{row['verdict']}: {str(row['excerpt']).strip()}"
    return ""


def disposition_reason(state: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Return '' when a valid no-proof disposition exists, else the reason code it fails with."""
    return "" if find_disposition(state, rows) else "proof_disposition_no_reason"


def _label(item: dict[str, Any], fallback: str) -> str:
    identifier = item.get("id")
    return identifier if isinstance(identifier, str) and identifier else fallback


def _item(entry: object) -> dict[str, Any]:
    return cast(dict[str, Any], entry) if isinstance(entry, dict) else {}


def _git_context(cwd: Path) -> tuple[Path, str] | None:
    """Resolve the repository and HEAD through Git, without trusting a recorded row's cwd as authority."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "HEAD"], cwd=cwd, capture_output=True, text=True, check=False
        )
    except (OSError, ValueError):
        return None
    lines = result.stdout.splitlines()
    if result.returncode or len(lines) != 2 or not lines[1].strip():
        return None
    return Path(lines[0]).resolve(), lines[1].strip()


def _check(
    item: dict[str, Any],
    withdrawn: bool,
    freeze: dict[str, Any],
    runs: dict[str, Any],
    state: dict[str, Any],
    current: tuple[Path, str] | None,
) -> str:
    """Return the reason code a single proof fails with, or '' when its latest run row satisfies it."""
    cmd, run = item.get("cmd"), runs.get(_label(item, ""))
    if not isinstance(cmd, str) or not cmd.strip():
        return "proof_stale_cmd"
    if withdrawn and not (isinstance(item.get("withdrawn_reason"), str) and item["withdrawn_reason"].strip()):
        return "proof_withdrawn_unobserved"
    identity = (state.get("session_id"), state.get("loop_id"))
    if run is None or (run["session_id"], run["loop_id"]) != identity:
        return "proof_withdrawn_unobserved" if withdrawn else "proof_unexecuted"
    if run["cmd_sha256"] != sha(cmd.strip()) or run["proof_json_sha256"] != freeze["proof_json_sha256"]:
        return "proof_stale_cmd"
    recorded_cwd = run.get("cwd")
    recorded = _git_context(Path(recorded_cwd)) if isinstance(recorded_cwd, str) and recorded_cwd else None
    if current is None or recorded is None or recorded[0] != current[0] or run.get("head_sha") != current[1]:
        return "proof_stale_head"
    if withdrawn:
        return "" if run["verdict"] in {"failed", "timeout"} else "proof_withdrawn_unobserved"
    return "" if run["verdict"] == "satisfied" else VERDICT_REASON.get(run["verdict"], "proof_failed")


def verify(proof_doc: dict[str, Any], results_path: Path, state: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (offenders, disclosures): every frozen proof needs a latest satisfied run row on a valid chain."""
    proofs = [_item(p) for p in cast(list[object], proof_doc.get("proofs") or [])]
    withdrawn = [_item(p) for p in cast(list[object], proof_doc.get("withdrawn_proofs") or [])]
    everything = [(_label(p, f"P{i}"), p, False) for i, p in enumerate(proofs)] + [
        (_label(p, f"W{i}"), p, True) for i, p in enumerate(withdrawn)
    ]
    session, loop = state.get("session_id"), state.get("loop_id")
    try:
        rows = read_rows(results_path)
    except ChainError:
        trace("proof.gate", "blocked", "proof_chain_broken", session, loop)
        return [f"{name}(proof_chain_broken)" for name, _, _ in everything], []
    freezes = [r for r in rows if r["kind"] == "freeze" and (r["session_id"], r["loop_id"]) == (session, loop)]
    runs = {r["proof_id"]: r for r in rows if r["kind"] == "run"}
    current = _git_context(Path.cwd())
    offenders: list[str] = []
    disclosures: list[str] = []
    for name, item, is_withdrawn in everything:
        if not freezes or freezes[-1]["proof_json_sha256"] != doc_sha(proof_doc):
            code = "proof_stale_cmd"
        else:
            code = _check(item, is_withdrawn, freezes[-1], runs, state, current)
        if code:
            offenders.append(f"{name}({code})")
            trace("proof.gate", "blocked", code, session, loop)
        elif is_withdrawn:
            disclosures.append(f"{name}: {str(item['withdrawn_reason']).strip().splitlines()[0]}")
    return offenders, disclosures
