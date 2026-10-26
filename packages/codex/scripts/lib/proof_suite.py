"""Validate and select one frozen proof suite without changing the original proof.json."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

from scripts.lib import proof_results as pr
from scripts.lib.proof_runtime import git_environment, trusted_executable

MAX_TIMEOUT_S = 3600
STORE = "proof_candidates"


class SuiteError(ValueError):
    """A proof replacement is missing, invalid, or bound to different evidence."""


def items(doc: dict[str, Any]) -> list[tuple[dict[str, Any], bool]]:
    """Return every proof and withdrawal in the document."""
    out: list[tuple[dict[str, Any], bool]] = []
    for key, withdrawn in (("proofs", False), ("withdrawn_proofs", True)):
        for entry in cast(list[object], doc.get(key) or []):
            out.append((cast(dict[str, Any], entry) if isinstance(entry, dict) else {}, withdrawn))
    return out


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in cast(list[object], value))


def validate(doc: dict[str, Any]) -> list[str]:
    """Return freeze-time schema errors for a schema-2 proof document."""
    if doc.get("schema_version") != 2 or type(doc.get("schema_version")) is not int:
        return ["schema_version must be 2 (schema 1 ignores structured expect and is refused)"]
    errors: list[str] = []
    seen: set[str] = set()
    for key in ("session_id", "loop_id"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            errors.append(f"{key} must be a nonblank string")
    for key in ("proofs", "withdrawn_proofs"):
        if not isinstance(doc.get(key, []), list):
            errors.append(f"{key} must be an array")
    if errors:
        return errors
    if len(doc.get("proofs", [])) + len(doc.get("withdrawn_proofs", [])) > 100:
        errors.append("proofs+withdrawn_proofs exceeds cap of 100")
    has_live = any(not withdrawn for _, withdrawn in items(doc))
    for entry, _ in items(doc):
        identifier, cmd = entry.get("id"), entry.get("cmd")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            errors.append(f"id {identifier!r} is blank or not unique")
        seen.add(str(identifier))
        if not isinstance(cmd, str) or not cmd.strip():
            errors.append(f"{identifier}: cmd is blank")
        timeout = entry.get("timeout_s")
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not (0 < timeout <= MAX_TIMEOUT_S and math.isfinite(timeout))
        ):
            errors.append(f"{identifier}: timeout_s must be finite, greater than 0, and at most {MAX_TIMEOUT_S}")
        expect = entry.get("expect")
        shaped = isinstance(expect, dict)
        spec = cast(dict[str, Any], expect) if shaped else {}
        code = spec.get("exit_code", 0)
        if not shaped or isinstance(code, bool) or not isinstance(code, int):
            errors.append(f"{identifier}: expect must be an object with an integer exit_code")
        if not all(_is_str_list(spec.get(key, [])) for key in ("stdout_contains", "stdout_not_contains")):
            errors.append(f"{identifier}: stdout_contains/stdout_not_contains must be string arrays")
    return errors + (["no non-withdrawn proofs (record `proof.py disposition` instead)"] if not has_live else [])


def candidate_errors(doc: dict[str, Any]) -> list[str]:
    """Require a fresh pending suite with no amendment history."""
    errors = validate(doc)
    if errors:
        return errors
    if doc.get("amendments") != []:
        errors.append("amendments must be an empty array")
    if any(entry.get("status") != "pending" for entry, _ in items(doc)):
        errors.append("each proof status must be pending")
    return errors


def _regular_bytes(path: Path, reason: str) -> bytes:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise SuiteError(reason)
        return path.read_bytes()
    except OSError as error:
        raise SuiteError(reason) from error


def _document(raw: bytes, reason: str) -> dict[str, Any]:
    try:
        value: object = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise SuiteError(reason) from error
    if not isinstance(value, dict):
        raise SuiteError(reason)
    return cast(dict[str, Any], value)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def active_suite(proof_path: Path, state: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    """Select the original or its only chained replacement; return its row cutoff."""
    rows = pr.read_rows(proof_path.with_name(pr.RESULTS_NAME))
    replacements = [row for row in rows if row["kind"] == "supersede"]
    if len(replacements) > 1:
        raise SuiteError("proof_supersession_duplicate")
    if not proof_path.exists():
        if replacements:
            raise SuiteError("proof_supersession_invalid: original is missing")
        return None, rows, 0
    original_raw = _regular_bytes(proof_path, "proof_supersession_invalid: original is not a regular file")
    original = _document(original_raw, "proof.json is malformed")
    if not replacements:
        return original, rows, 0
    row = replacements[0]
    if (row["session_id"], row["loop_id"]) != (state.get("session_id"), state.get("loop_id")):
        raise SuiteError("proof_supersession_invalid: loop identity changed")
    if row["original_raw_sha256"] != _sha(original_raw) or row["original_canonical_sha256"] != pr.doc_sha(original):
        raise SuiteError("proof_supersession_invalid: original changed")
    relative = f"{STORE}/{row['candidate_raw_sha256']}.json"
    if row["candidate_path"] != relative:
        raise SuiteError("proof_supersession_invalid: candidate path changed")
    if not Path(row["author_evidence_path"]).is_absolute():
        raise SuiteError("proof_supersession_invalid: author evidence path is relative")
    if (proof_path.parent / STORE).is_symlink():
        raise SuiteError("proof_supersession_invalid: candidate store is a symlink")
    candidate_raw = _regular_bytes(proof_path.parent / relative, "proof_supersession_invalid: candidate missing")
    candidate = _document(candidate_raw, "proof_supersession_invalid: candidate is not JSON")
    if _sha(candidate_raw) != row["candidate_raw_sha256"] or pr.doc_sha(candidate) != row["candidate_canonical_sha256"]:
        raise SuiteError("proof_supersession_invalid: candidate changed")
    if candidate_errors(candidate) or (candidate.get("session_id"), candidate.get("loop_id")) != (
        state.get("session_id"),
        state.get("loop_id"),
    ):
        raise SuiteError("proof_supersession_invalid: candidate schema or identity changed")
    evidence = _regular_bytes(Path(row["author_evidence_path"]), "proof_supersession_invalid: author evidence missing")
    if not evidence or _sha(evidence) != row["author_evidence_sha256"]:
        raise SuiteError("proof_supersession_invalid: author evidence changed")
    return candidate, rows, cast(int, row["seq"])


def supersede(
    state_dir: Path, candidate_path: Path, reason: str, original_sha256: str, author_evidence_path: Path
) -> dict[str, Any]:
    """Store one valid replacement and append its binding after every input passes validation."""
    progress = _document(
        _regular_bytes(state_dir / "progress.json", "proof_supersession_invalid: graph missing"),
        "proof_supersession_invalid: graph is not JSON",
    )
    original_path = state_dir / "proof.json"
    current, rows, _ = active_suite(original_path, progress)
    if current is None or any(row["kind"] == "supersede" for row in rows):
        raise SuiteError("proof_supersession_duplicate_or_missing_original")
    original_raw = _regular_bytes(original_path, "proof_supersession_invalid: original missing")
    if _sha(original_raw) != original_sha256:
        raise SuiteError("proof_supersession_original_hash_mismatch")
    if candidate_path.resolve().is_relative_to(state_dir.resolve()):
        raise SuiteError("proof_supersession_candidate_invalid: source is inside the active graph")
    candidate_raw = _regular_bytes(candidate_path, "proof_supersession_candidate_invalid")
    candidate = _document(candidate_raw, "proof_supersession_candidate_invalid")
    if candidate_errors(candidate) or (candidate.get("session_id"), candidate.get("loop_id")) != (
        progress.get("session_id"),
        progress.get("loop_id"),
    ):
        raise SuiteError("proof_supersession_candidate_invalid: schema or identity")
    if not reason.strip():
        raise SuiteError("proof_supersession_reason_missing")
    if author_evidence_path.resolve().is_relative_to(state_dir.resolve()):
        raise SuiteError("proof_author_evidence_missing: report is inside the active graph")
    evidence = _regular_bytes(author_evidence_path, "proof_author_evidence_missing")
    if not evidence:
        raise SuiteError("proof_author_evidence_missing")
    try:
        head = subprocess.run(
            [trusted_executable("git", Path.cwd()), "rev-parse", "HEAD"],
            env=git_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SuiteError("proof_supersession_head_missing") from error
    if head.returncode or len(head.stdout.strip()) not in (40, 64):
        raise SuiteError("proof_supersession_head_missing")
    digest = _sha(candidate_raw)
    directory = state_dir / STORE
    if directory.is_symlink():
        raise SuiteError("proof_supersession_candidate_invalid: store is a symlink")
    try:
        directory.mkdir(exist_ok=True)
    except OSError as error:
        raise SuiteError("proof_supersession_candidate_invalid: store unavailable") from error
    destination = directory / f"{digest}.json"
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise SuiteError("proof_supersession_candidate_invalid: nofollow is unavailable")
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
    except FileExistsError:
        if _regular_bytes(destination, "proof_supersession_candidate_invalid") != candidate_raw:
            raise SuiteError("proof_supersession_candidate_invalid: store collision") from None
    except OSError as error:
        raise SuiteError("proof_supersession_candidate_invalid: store write failed") from error
    else:
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(candidate_raw)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise SuiteError("proof_supersession_candidate_invalid: store write failed") from error
    try:
        row = pr.append(
            state_dir / pr.RESULTS_NAME,
            kind="supersede",
            session_id=progress["session_id"],
            loop_id=progress["loop_id"],
            head_sha=head.stdout.strip(),
            cwd=str(Path.cwd()),
            original_raw_sha256=_sha(original_raw),
            original_canonical_sha256=pr.doc_sha(current),
            candidate_raw_sha256=digest,
            candidate_canonical_sha256=pr.doc_sha(candidate),
            candidate_path=f"{STORE}/{digest}.json",
            author_evidence_sha256=_sha(evidence),
            author_evidence_path=str(author_evidence_path.resolve()),
            reason=reason.strip(),
        )
    except (pr.ChainError, OSError) as error:
        raise SuiteError(str(error)) from error
    return row
