"""Validate eval structures, freeze ancestry and explicit discriminating fixtures."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import cast

from .artifact_io import JsonObject, array_value, object_value, read_object
from .eval_artifact import parse_verification_level
from .eval_execution import is_environmental_rc, run_recorded, scripted_evals, validate_smoke, verify_execution


def git_output(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run Git with captured diagnostics without interpreting argument text."""
    return subprocess.run(["git", "-C", str(directory), *arguments], capture_output=True, text=True, check=False)


def validate_freeze(path: str | Path) -> None:
    """Require a resolvable pre-branch freeze or an explicit late-freeze disclosure."""
    data = read_object(path)
    frozen = str(data.get("frozen_sha") or "").strip()
    directory = Path(path).resolve().parent
    if not frozen or git_output(directory, "rev-parse", "--is-inside-work-tree").returncode:
        return
    if git_output(directory, "cat-file", "-e", f"{frozen}^{{commit}}").returncode:
        raise ValueError(f"frozen_sha {frozen} does not resolve to a commit in this repository")
    base = ""
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        if git_output(directory, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
            result = git_output(directory, "merge-base", "HEAD", ref)
            if result.returncode == 0 and result.stdout.strip():
                base = result.stdout.strip()
                break
    if not base or git_output(directory, "merge-base", "--is-ancestor", frozen, base).returncode == 0:
        return
    disclosure = " ".join(
        [str(data.get("verification_justification", ""))]
        + [str(item.get("why", "")) for item in data.get("amendments", [])]
    ).lower()
    if "freeze" not in disclosure and "frozen" not in disclosure:
        raise ValueError(f"frozen_sha {frozen} is not an ancestor of the branch base {base} — disclose the late freeze")


def validate_structure(path: str | Path, pr: str = "", current_head_sha: str = "", scope: str = "pr") -> None:
    """Apply structural, evidence, freeze and execution refusals to an artifact."""
    del pr
    data = read_object(path)
    level = str(data.get("verification_level", ""))
    justification = data.get("verification_justification")
    if not isinstance(justification, str) or not justification.strip():
        raise ValueError(f"verification_level {level} requires a non-blank verification_justification")
    evals = [object_value(item) for item in array_value(data.get("evals", []))]
    for item in evals:
        validate_entry(item, level)
    sha = data.get("head_sha", "")
    if scope == "loop":
        if not sha:
            raise ValueError("evals.json head_sha must be non-blank (loop scope)")
    elif sha != current_head_sha:
        raise ValueError(f"evals.json head_sha ({sha}) does not match current PR head ({current_head_sha})")
    if level != "0" and not any(item.get("priority") == "P0" for item in evals):
        raise ValueError("verification_level>=1 requires at least one P0 eval in .evals")
    if scope != "loop":
        validate_freeze(path)
        validate_smoke(data)
        verify_execution(data)
    new_cases = data.get("new_cases", [])
    if not isinstance(new_cases, list):
        raise ValueError("new_cases is not a JSON array (malformed)")
    new_cases = [object_value(item) for item in array_value(cast(object, new_cases))]
    ids = [item.get("id") for item in evals]
    if any(not item.get("id") or item["id"] not in ids for item in new_cases):
        raise ValueError("new_cases[] entry has no matching .evals[].id")


def validate_entry(item: JsonObject, level: str) -> None:
    """Reject vacuous controls and missing mandatory evidence."""
    if item.get("mode") == "scripted":
        command = " ".join(str(item.get("cmd") or "").split())
        control = " ".join(str(item.get("negative_control") or "").split())
        if level != "0" and not control:
            raise ValueError(f"scripted eval {item.get('id')} has empty negative_control")
        if command and control and re.search(r"(^|[\s;&|])" + re.escape(command) + r"($|[\s;&|])", control):
            raise ValueError(f"eval {item.get('id')} negative_control is identical to cmd")
    if item.get("priority") == "P0" and not item.get("evidence"):
        raise ValueError(f"P0 eval {item.get('id')} has empty evidence")


def extract_json_block(body: str) -> str:
    """Extract the first fenced JSON block, preserving its content."""
    inside = False
    lines: list[str] = []
    for line in body.splitlines():
        if re.fullmatch(r"```json\s*", line):
            inside = True
            continue
        if inside and re.fullmatch(r"```\s*", line):
            break
        if inside:
            lines.append(line)
    return "\n".join(lines)


def validate_embed(path: str | Path, body_path: str | Path) -> None:
    """Validate the verification-level-zero comment embed against its source artifact."""
    body = Path(body_path).read_text()
    level = parse_verification_level(body.splitlines()[0] if body else "")
    if not level:
        raise ValueError("body marker line does not parse (missing or malformed marker)")
    if level != "0":
        return
    if len(re.findall(r"^```json\s*$", body, re.MULTILINE)) != 1:
        raise ValueError("verification_level-0 body must contain exactly one fenced json block")
    block: object = json.loads(extract_json_block(body))
    block = object_value(block)
    if str(block.get("verification_level", "")) != level:
        raise ValueError("embedded block verification_level does not match marker verification_level")
    if not block.get("task_ref") or block["task_ref"] != read_object(path).get("task_ref"):
        raise ValueError("embedded block task_ref does not match source evals.json task_ref")


def validate_discriminating(path: str | Path) -> None:
    """Prove optional explicit fixtures produce a pass and a content failure."""
    for item in scripted_evals(read_object(path)):
        fixtures = item.get("fixtures")
        if fixtures is None:
            continue
        identity = f"eval {item.get('id')}"
        if not isinstance(fixtures, dict):
            raise ValueError(f"{identity} has malformed fixtures (must be an object)")
        fixtures = object_value(cast(object, fixtures))
        good, bad = fixtures.get("good"), fixtures.get("bad")
        if not isinstance(good, str) or not good or not isinstance(bad, str) or not bad:
            raise ValueError(f"{identity} fixtures present but good and bad are both required")
        formula = fixtures.get("formula")
        if not formula:
            command = str(item.get("cmd") or "")
            if "|" not in command:
                raise ValueError(
                    f"{identity} has fixtures but no derivable formula — supply fixtures.formula explicitly"
                )
            formula = command.rsplit("|", 1)[1].strip()
        if not isinstance(formula, str):
            raise ValueError(f"{identity} fixtures.formula must be a string")
        good_rc, _ = run_recorded(formula, input_text=good)
        bad_rc, _ = run_recorded(formula, input_text=bad)
        outcomes = f"good exit={good_rc}, bad exit={bad_rc}"
        if 127 in (good_rc, bad_rc):
            raise ValueError(f"{identity} formula execution failed (command not found) — {outcomes}")
        if 142 in (good_rc, bad_rc):
            raise ValueError(f"{identity} formula execution timed out (10s) — {outcomes}")
        if is_environmental_rc(good_rc) or is_environmental_rc(bad_rc):
            raise ValueError(f"{identity} formula execution crashed (environmental) — {outcomes}")
        if good_rc == 0 and bad_rc != 0:
            continue
        if good_rc == bad_rc:
            raise ValueError(f"{identity} formula is non-discriminating — good and bad fixtures both exit {good_rc}")
        raise ValueError(f"{identity} formula did not discriminate as required — {outcomes}")
