"""Tamper-evident suite hash and amendment hash chain for frozen eval suites.

Detection only: there is no signing key and no attestation. An actor who can rewrite the whole file
(oracle, chain and grading stamp together) is not caught; accidental and in-place edits are.
Script files a cmd references are not hashed; only cmd/control text and inline fixtures are.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import cast

from .artifact_io import JsonObject

LEGACY_UNHASHED = "legacy_unhashed"
SUITE_HASH_MISMATCH = "suite_hash_mismatch"
CHAIN_BROKEN = "chain_broken"
CHAIN_TRUNCATED = "chain_truncated"
PROGRESS_MISSING = "progress_missing"
PROGRESS_FOREIGN = "progress_foreign"
PROGRESS_UNPARSEABLE = "progress_unparseable"
CONTROL_PASSES = "control_passes"
CONTROL_ENV = "control_env"
PASS_EXIT_NONZERO = "pass_exit_nonzero"
FIXTURE_FORMULA_NOT_IN_CMD = "fixture_formula_not_in_cmd"

ORACLE_KEYS = ("id", "priority", "mode", "cmd", "negative_control", "fixtures", "expected", "assert")


class IntegrityError(ValueError):
    """A refusal carrying a stable reason code; str() always contains reason=<code>."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Format the message so every refusal prints its code."""
        super().__init__(f"reason={code}" + (f": {detail}" if detail else ""))
        self.code = code


def _sha(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def suite_hash(data: JsonObject) -> str:
    """Hash the oracle: per-eval oracle keys plus task_ref, scope and verification_level.

    status, smoke, result, grading and the amendment arrays are excluded: they change after freeze.
    """
    raw = data.get("evals")
    entries: list[JsonObject] = []
    for item in cast(list[object], raw) if isinstance(raw, list) else []:
        if isinstance(item, dict):
            e = cast(JsonObject, item)
            entries.append({k: e[k] for k in ORACLE_KEYS if k in e})
    return _sha({**{k: data.get(k) for k in ("task_ref", "scope", "verification_level")}, "evals": entries})


def _chain(data: JsonObject) -> list[JsonObject]:
    chain = data.get("amendment_chain", [])
    if not isinstance(chain, list) or not all(isinstance(e, dict) for e in cast(list[object], chain)):
        raise IntegrityError(CHAIN_BROKEN, "amendment_chain is malformed")
    return cast(list[JsonObject], chain)


def _entry_hash(entry: JsonObject) -> str:
    return _sha({k: v for k, v in entry.items() if k != "hash"})


def _walk(data: JsonObject) -> str:
    """Require contiguous seq, linked prev_hash and recomputed hashes; return the head hash."""
    head = data.get("frozen_hash")
    if not isinstance(head, str) or not head:
        raise IntegrityError(CHAIN_BROKEN, "amendment_chain present without frozen_hash")
    for index, entry in enumerate(_chain(data)):
        if entry.get("seq") != index + 1 or entry.get("prev_hash") != head or entry.get("hash") != _entry_hash(entry):
            raise IntegrityError(CHAIN_BROKEN, f"amendment_chain entry {index + 1} fails seq/prev_hash/hash")
        head = entry["hash"]
    return head


def verify_suite(data: JsonObject, stamped: bool = False) -> str:
    """Return "verified" or LEGACY_UNHASHED, or raise IntegrityError.

    stamped=True (merge/completion readers) also requires grading.suite_hash to equal the current hash,
    which makes an amendment after grading stale until regraded; grade time passes False.
    """
    raw = data.get("grading")
    grading: JsonObject = cast(JsonObject, raw) if isinstance(raw, dict) else {}
    current = suite_hash(data)
    if not data.get("frozen_hash"):
        if data.get("amendment_chain"):
            raise IntegrityError(CHAIN_BROKEN, "amendment_chain present without frozen_hash")
        if stamped and grading.get("suite_hash") not in (None, current):
            raise IntegrityError(SUITE_HASH_MISMATCH, "oracle changed since grading")
        return LEGACY_UNHASHED
    _walk(data)
    chain = _chain(data)
    length = grading.get("chain_len")
    if isinstance(length, int) and not isinstance(length, bool):
        if len(chain) < length:
            raise IntegrityError(CHAIN_TRUNCATED, f"{len(chain)} entries, {length} were graded")
        if length and chain[length - 1]["hash"] != grading.get("chain_head"):
            raise IntegrityError(CHAIN_BROKEN, "graded chain head no longer in chain")
    expected = chain[-1]["suite_hash_after"] if chain else data["frozen_hash"]
    if current != expected or (stamped and grading.get("suite_hash") not in (None, current)):
        raise IntegrityError(SUITE_HASH_MISMATCH, "oracle differs from the frozen/amended hash")
    return "verified"


def append_amendment(data: JsonObject, eval_id: str, reason: str, actor: str, regraded_by: str = "") -> None:
    """Record an already-made oracle edit on the chain and on the legacy amendments array."""
    legacy: JsonObject = {"eval": eval_id, "why": reason, "actor": actor}
    if regraded_by:
        legacy["regraded_by"] = regraded_by
    if data.get("frozen_hash"):
        head = _walk(data)
        chain = _chain(data)
        entry: JsonObject = {
            "seq": len(chain) + 1,
            "eval": eval_id,
            "reason": reason,
            "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actor": actor,
            "prev_hash": head,
            "suite_hash_after": suite_hash(data),
        }
        entry["hash"] = _entry_hash(entry)
        data["amendment_chain"] = [*chain, entry]
        legacy["ts"] = entry["ts"]
    data["amendments"] = [*data.get("amendments", []), legacy]


def stamp(data: JsonObject) -> JsonObject:
    """Fields grade-loop adds to the grading object."""
    chain = _chain(data) if data.get("frozen_hash") else []
    return {
        "suite_hash": suite_hash(data),
        "integrity": "verified" if data.get("frozen_hash") else LEGACY_UNHASHED,
        "chain_len": len(chain),
        "chain_head": chain[-1]["hash"] if chain else data.get("frozen_hash"),
    }
