"""A hand-built eval artifact comment for gh shims, independent of scripts.lib (no import of the scripts package).

The suite hash is recomputed here from the documented definition (skills/task-evals/SKILL.md "Tamper-evidence"):
sha256 of the canonical JSON of task_ref, scope, verification_level and the per-eval oracle keys.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def suite_hash(level: int, evals: list[object], frozen_sha: str = "", frozen_at: str = "") -> str:
    """Hash the independent wire-format fixture, with v2 freeze metadata when supplied."""
    body = {"task_ref": "1", "scope": None, "verification_level": level, "evals": evals}
    if frozen_at:
        body.update(integrity_version=2, frozen_sha=frozen_sha or None, frozen_at=frozen_at)
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def eval_comment(
    sha: str, level: int, late: bool = False, pr: str = "7", frozen_sha: str = "", tamper: bool = False
) -> str:
    """The comment body post_evals.py post writes: v1 marker, facts line, summary, one fenced embed.

    tamper=True adds an eval to the embed after the freeze hash was taken (an oracle edit without amend).
    """
    data: dict[str, object] = {"verification_level": level, "head_sha": sha, "task_ref": "1", "evals": []}
    if tamper:
        data["evals"] = [
            {"id": "E1", "priority": "P0", "mode": "scripted", "status": "pass",
             "cmd": "true", "negative_control": "false"}
        ]  # fmt: skip
    if frozen_sha:
        data["frozen_sha"] = frozen_sha
    frozen_at = "2026-10-07T00:00:00Z" if level else ""
    if level:
        data.update(integrity_version=2, frozen_at=frozen_at)
    digest = suite_hash(level, [], frozen_sha, frozen_at)
    if level:
        data["frozen_hash"] = digest
    marker = f"<!-- coderails-eval-summary v1 pr={pr} head_sha={sha} result=GO verification_level={level} -->"
    late = late or (level != 0 and not frozen_sha)  # at level >= 1 a missing frozen_sha is stamped late
    facts = f"<!-- coderails-eval-facts v1 derived_min_level={level} late_freeze={int(late)} suite={digest[:16]} -->"
    return "\n".join([marker, facts, "## Eval summary", "", "```json", json.dumps(data), "```", ""])


def sign_comment(path: Path, keys: Path) -> None:
    """Sign an independently built v2 fixture with an isolated test key."""
    body = path.read_text()
    prefix, fenced = body.split("```json\n", 1)
    blob, suffix = fenced.split("\n```", 1)
    data = json.loads(blob)
    if data["verification_level"] == 0:
        return
    keys.mkdir(exist_ok=True)
    private = keys / "evals_ed25519"
    if not private.exists():
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)],
            check=True,
            capture_output=True,
            text=True,
        )
        public = private.with_name(private.name + ".pub").read_text().strip()
        (keys / "allowed_signers").write_text(f'coderails-evals namespaces="coderails-evals" {public}\n')
    digest = data["frozen_hash"]
    payload = json.dumps(
        {"chain_head": digest, "chain_len": 0, "frozen_hash": digest, "loop_id": None, "session_id": None},
        sort_keys=True,
        separators=(",", ":"),
    )
    signed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(private), "-n", "coderails-evals"],
        input=payload,
        check=True,
        capture_output=True,
        text=True,
    )
    data["signature"] = {"signer": "coderails-evals", "payload": payload, "sig": signed.stdout}
    path.write_text(prefix + "```json\n" + json.dumps(data) + "\n```" + suffix)


def write_comment(directory: Path, sha: str, level: int, signing_keys: Path | None = None, **kwargs: object) -> Path:
    """Write eval_comment to directory/eval-comment.md for the shim's FAKE_EVAL_FILE."""
    path = directory / "eval-comment.md"
    path.write_text(eval_comment(sha, level, **kwargs))  # type: ignore[arg-type]
    if signing_keys is not None:
        sign_comment(path, signing_keys)
    return path


# appended to a shim's `api repos/` branch: print the eval comment as one more base64 line
SHIM_EVAL_LINES = """    [ -n "$FAKE_EVAL_FILE" ] && { base64 < "$FAKE_EVAL_FILE" | tr -d '\\n'; echo; }
"""
