"""Tamper-evident suite hash and amendment hash chain for frozen eval suites.

Detection only. A suite-level ssh-keygen signature (eval_signing) binds frozen_hash, chain head and ids to a
key; an actor holding that key (any same-user process) can still rewrite the whole file and re-sign, and a
rollback to an earlier validly-signed state is not detected beyond grading.chain_len.
Script files a cmd references are not hashed; only cmd/control text and inline fixtures are.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import cast

from . import eval_signing
from .artifact_io import JsonObject
from .eval_signing import KEY_MISSING, LEGACY_UNSIGNED, SIGNATURE_MISSING, SigningError

LEGACY_UNHASHED = "legacy_unhashed"
SUITE_HASH_MISMATCH = "suite_hash_mismatch"
CHAIN_BROKEN = "chain_broken"
CHAIN_TRUNCATED = "chain_truncated"
PROGRESS_MISSING = "progress_missing"
PROGRESS_FOREIGN = "progress_foreign"
PROGRESS_UNPARSEABLE = "progress_unparseable"
CONTROL_PASSES = "control_passes"
CONTROL_ENV = "control_env"
CMD_ENV = "cmd_env"
INTEGRITY_STRIPPED = "integrity_stripped"
PASS_EXIT_NONZERO = "pass_exit_nonzero"
FIXTURE_FORMULA_NOT_IN_CMD = "fixture_formula_not_in_cmd"

ORACLE_KEYS = ("id", "priority", "mode", "cmd", "negative_control", "fixtures", "expected", "assert")


class IntegrityError(ValueError):
    """A refusal carrying a stable reason code; str() always contains reason=<code>."""

    def __init__(self, code: str, detail: str = "") -> None:
        """Format the message so every refusal prints its code."""
        super().__init__(f"reason={code}" + (f": {detail}" if detail else ""))
        self.code = code


def _canon(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: object) -> str:
    return hashlib.sha256(_canon(value).encode()).hexdigest()


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


def _payload(data: JsonObject, head: str, length: int) -> str:
    """Canonical text the suite signature covers; signature itself lives outside suite_hash and every entry."""
    ids = {k: data.get(k) for k in ("loop_id", "session_id")}
    return _canon({"frozen_hash": data.get("frozen_hash"), "chain_head": head, "chain_len": length, **ids})


def _signed_before(data: JsonObject, path: object = None) -> bool:
    """Signed per grading.signed, this host's signed-suites ledger (needs path), or required config."""
    raw = data.get("grading")
    graded = isinstance(raw, dict) and cast(JsonObject, raw).get("signed") is True
    return graded or eval_signing.was_signed(path) or eval_signing.required()


def sign_suite(data: JsonObject, strict: bool = False) -> str:
    """Sign the current chain head into data["signature"]; return "signed" or KEY_MISSING (degraded).

    Raises IntegrityError on any failure when strict, or when config requires signatures.
    """
    text = _payload(data, _walk(data), len(_chain(data)))
    try:
        data["signature"] = eval_signing.sign(text)
    except SigningError as error:
        if error.code == KEY_MISSING and not strict and not eval_signing.required():
            return KEY_MISSING
        raise IntegrityError(error.code, str(error)) from error
    return "signed"


def _check_signature(data: JsonObject, head: str, length: int, path: object = None) -> str:
    if "signature" not in data:
        if _signed_before(data, path):
            raise IntegrityError(SIGNATURE_MISSING, "signature removed from a suite that was signed or must be")
        return LEGACY_UNSIGNED
    try:
        result = eval_signing.check(data["signature"], _payload(data, head, length))
    except SigningError as error:
        raise IntegrityError(error.code, str(error)) from error
    if result == KEY_MISSING and eval_signing.required():
        raise IntegrityError(KEY_MISSING, "no ssh-keygen/allowed_signers here and evals.require_signatures is set")
    return result


def require_verified(data: JsonObject, head: str, length: int) -> None:
    """Refuse to re-sign a signature this host could not verify (key_missing would launder a forgery)."""
    if _check_signature(data, head, length) != eval_signing.VERIFIED:
        raise IntegrityError(KEY_MISSING, "existing signature is unverifiable here; refusing to re-sign it")


def verify_suite(data: JsonObject, stamped: bool = False, path: object = None) -> str:
    """Return "verified", LEGACY_UNHASHED, LEGACY_UNSIGNED or KEY_MISSING (degraded), or raise IntegrityError.

    stamped=True (merge/completion readers) also requires grading.suite_hash to equal the current hash,
    which makes an amendment after grading stale until regraded; grade time passes False.
    """
    raw = data.get("grading")
    grading: JsonObject = cast(JsonObject, raw) if isinstance(raw, dict) else {}
    current = suite_hash(data)
    if not data.get("frozen_hash"):
        if data.get("amendment_chain"):
            raise IntegrityError(CHAIN_BROKEN, "amendment_chain present without frozen_hash")
        if grading.get("integrity") == "verified":
            raise IntegrityError(INTEGRITY_STRIPPED, "frozen_hash removed from a suite that was graded with one")
        if stamped and grading.get("suite_hash") not in (None, current):
            raise IntegrityError(SUITE_HASH_MISMATCH, "oracle changed since grading")
        return LEGACY_UNHASHED
    head = _walk(data)
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
    return _check_signature(data, head, len(chain), path)


def append_amendment(
    data: JsonObject, eval_id: str, reason: str, actor: str, regraded_by: str = "", path: object = None
) -> None:
    """Record an already-made oracle edit on the chain and on the legacy amendments array."""
    legacy: JsonObject = {"eval": eval_id, "why": reason, "actor": actor}
    if regraded_by:
        legacy["regraded_by"] = regraded_by
    if data.get("frozen_hash"):
        head = _walk(data)
        chain = _chain(data)
        signed = "signature" in data
        if not signed and _signed_before(data, path):  # a stripped signature must not be laundered by re-signing
            raise IntegrityError(SIGNATURE_MISSING, "signature removed from a suite that was signed or must be")
        if signed:
            require_verified(data, head, len(chain))
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
        if signed:
            sign_suite(data, strict=True)  # re-sign the new head; a stale signature must never survive
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
