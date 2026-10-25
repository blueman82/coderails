"""Claude dispatch and completion evaluation verdicts with grading provenance."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from .loop_state_common import read_state

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.eval_artifact import compute_go, grading_checksum
from scripts.lib.eval_integrity import LEGACY_UNHASHED, IntegrityError, verify_suite
from scripts.lib.eval_signing import report
from scripts.lib.eval_trace import emit


def evals_are_frozen(document: dict[str, Any]) -> bool:
    """Check the freeze-time subset that may authorize dispatch, never completion."""
    level = document.get("verification_level")
    entries = document.get("evals")
    if not isinstance(level, (int, float)) or isinstance(level, bool) or level < 1:
        return False
    if document.get("result") is not None or document.get("grading") is not None:
        return False
    if not isinstance(document.get("frozen_sha"), str) or not document["frozen_sha"].strip():
        return False
    if not isinstance(entries, list) or not any(
        isinstance(item, dict) and cast(dict[str, Any], item).get("priority") == "P0"
        for item in cast(list[object], entries)
    ):
        return False
    for item in cast(list[object], entries):
        if (
            not isinstance(item, dict)
            or not isinstance(cast(dict[str, Any], item).get("id"), str)
            or not cast(dict[str, Any], item)["id"].strip()
        ):
            return False
        if cast(dict[str, Any], item).get("mode") not in {"scripted", "agent-run"}:
            return False
        if cast(dict[str, Any], item)["mode"] == "scripted" and any(
            not isinstance(cast(dict[str, Any], item).get(key), str) or not cast(dict[str, Any], item)[key].strip()
            for key in ("cmd", "negative_control")
        ):
            return False
    return True


class EvalStatus(str, Enum):
    """Closed loop-eval outcomes; STALE is assigned by callers that compare the suite to the current loop."""

    GO = "GO"
    VERIFICATION_LEVEL0 = "VERIFICATION_LEVEL0"
    FROZEN = "FROZEN"
    NO_GO = "NO-GO"
    ABSENT = "ABSENT"
    UNJUSTIFIED = "UNJUSTIFIED"
    UNSTAMPED = "UNSTAMPED"
    STALE = "STALE"
    TAMPERED = "TAMPERED"


@dataclass(frozen=True)
class EvalVerdict:
    """A status plus, for TAMPERED only, the integrity error code as a field (never a sliced string)."""

    status: EvalStatus
    tamper_code: str | None = None

    @property
    def label(self) -> str:
        """Human rendering only; callers match on `status` and `tamper_code`."""
        return self.status.value + (f":{self.tamper_code}" if self.tamper_code else "")


def read_loop_evals(loop_dir: Path) -> EvalVerdict:
    """Classify the loop suite and require matching stamps for passing verdicts."""
    path = loop_dir / "evals.json"
    document = read_state(path)
    if document.get("scope") != "loop":
        return EvalVerdict(EvalStatus.ABSENT)
    justification = document.get("verification_justification")
    if not isinstance(justification, str) or not justification.strip():
        return EvalVerdict(EvalStatus.UNJUSTIFIED)
    result = document.get("result")
    if result == "NO-GO":
        return EvalVerdict(EvalStatus.NO_GO)
    if result == "GO":
        verdict = EvalStatus.GO
    elif document.get("verification_level") == 0:
        verdict = EvalStatus.VERIFICATION_LEVEL0
    elif evals_are_frozen(document):
        return EvalVerdict(EvalStatus.FROZEN)
    else:
        return EvalVerdict(EvalStatus.NO_GO)
    grading = document.get("grading")
    if (
        not isinstance(grading, dict)
        or not cast(dict[str, Any], grading).get("by")
        or not cast(dict[str, Any], grading).get("checksum")
    ):
        return EvalVerdict(EvalStatus.UNSTAMPED)
    try:
        checksum = grading_checksum(str(path), str(result or ""))
    except (OSError, ValueError, TypeError):
        return EvalVerdict(EvalStatus.UNSTAMPED)
    if not checksum or checksum != grading["checksum"]:
        return EvalVerdict(EvalStatus.UNSTAMPED)
    if verdict is EvalStatus.GO and not compute_go(path):
        return EvalVerdict(EvalStatus.NO_GO)
    try:
        integrity = verify_suite(document, stamped=True, path=path)
    except IntegrityError as error:
        emit(path, "loop-evals-read", "refuse", error.code)
        return EvalVerdict(EvalStatus.TAMPERED, error.code)
    if integrity == LEGACY_UNHASHED:
        emit(path, "loop-evals-read", "legacy", LEGACY_UNHASHED)
    report(path, "loop-evals-read", integrity)  # legacy_unsigned / key_missing are loud, never silent
    return EvalVerdict(verdict)
