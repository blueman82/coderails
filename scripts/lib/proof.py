#!/usr/bin/env python3
"""Controller-run proofs: freeze proof.json, execute each frozen cmd verbatim, record chained results.

Usage:
  proof.py freeze <state-dir>
  proof.py run <state-dir> [--id ID | --all]
  proof.py status <state-dir>
  proof.py disposition <state-dir> --none --reason-code CODE --reason TEXT

<state-dir> holds proof.json (and progress.json); rows go to proof_results.jsonl beside it. The frozen cmd runs
through pinned sandbox-runtime with read-only host paths and no network. Exit 0 ok, 1 unsatisfied, 2 refused.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.destructive_patterns import permanent_pattern, secret_path  # noqa: E402
from scripts.lib import proof_results as pr  # noqa: E402

DEFAULT_TIMEOUT_S = 600
EXCERPT_CAP = 2000
SRT_VERSION = "0.0.65"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise SystemExit(f"proof.py: {path.name} is unreadable: {error}") from error
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _identity(state_dir: Path, doc: dict[str, Any]) -> tuple[Any, Any]:
    progress = _load(state_dir / "progress.json")
    return progress.get("session_id", doc.get("session_id")), progress.get("loop_id", doc.get("loop_id"))


def items(doc: dict[str, Any]) -> list[tuple[dict[str, Any], bool]]:
    """Return every (entry, is_withdrawn) of a proof document."""
    out: list[tuple[dict[str, Any], bool]] = []
    for key, withdrawn in (("proofs", False), ("withdrawn_proofs", True)):
        for entry in cast(list[object], doc.get(key) or []):
            out.append((cast(dict[str, Any], entry) if isinstance(entry, dict) else {}, withdrawn))
    return out


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in cast(list[object], value))


def validate(doc: dict[str, Any]) -> list[str]:
    """Return freeze-time schema errors for a proof document (empty when valid)."""
    if doc.get("schema_version") != 2 or type(doc.get("schema_version")) is not int:
        return ["schema_version must be 2 (schema 1 ignores structured expect and is refused)"]
    errors: list[str] = []
    seen: set[str] = set()
    for key in ("proofs", "withdrawn_proofs"):
        if not isinstance(doc.get(key) or [], list):
            errors.append(f"{key} must be an array")
    if errors:
        return errors
    has_live = any(not withdrawn for _, withdrawn in items(doc))
    for entry, _ in items(doc):
        identifier, cmd = entry.get("id"), entry.get("cmd")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            errors.append(f"id {identifier!r} is blank or not unique")
        seen.add(str(identifier))
        if not isinstance(cmd, str) or not cmd.strip():
            errors.append(f"{identifier}: cmd is blank")
        timeout = entry.get("timeout_s")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
            errors.append(f"{identifier}: timeout_s must be a positive number")
        expect = entry.get("expect")
        shaped = isinstance(expect, dict)
        spec = cast(dict[str, Any], expect) if shaped else {}
        code = spec.get("exit_code", 0)
        if not shaped or isinstance(code, bool) or not isinstance(code, int):
            errors.append(f"{identifier}: expect must be an object with an integer exit_code")
        if not all(_is_str_list(spec.get(k, [])) for k in ("stdout_contains", "stdout_not_contains")):
            errors.append(f"{identifier}: stdout_contains/stdout_not_contains must be string arrays")
    return errors + (["no non-withdrawn proofs (record `proof.py disposition` instead)"] if not has_live else [])


def _destructive(cmd: str, cwd: str) -> bool:
    return bool(permanent_pattern(cmd, cwd)[0]) or secret_path(cmd)


def _execute(cmd: str, timeout: float) -> tuple[int | None, str, str, bool, bool]:
    """Return exit, stdout, stderr, timeout, and proof that the sandbox started."""
    with tempfile.TemporaryDirectory(prefix="coderails-proof.", dir="/tmp") as temporary:
        scratch = Path(temporary)
        settings = scratch / "settings.json"
        home = Path.home()
        settings.write_text(
            json.dumps(
                {
                    "filesystem": {
                        "denyRead": [],
                        "allowWrite": [temporary],
                        "denyWrite": [
                            str(settings),
                            "/tmp/claude",
                            "/private/tmp/claude",
                            str(home / ".npm/_logs"),
                            str(home / ".claude/debug"),
                        ],
                    },
                    "network": {"allowedDomains": [], "deniedDomains": ["*"], "strictAllowlist": True},
                }
            )
        )
        marker = f"CODERAILS_PROOF_SANDBOX_{secrets.token_hex(16)}"
        wrapped = f"printf '%s\\n' '{marker}'\n{cmd}"
        environment = os.environ.copy()
        environment.update(
            TMPDIR=temporary,
            CLAUDE_CODE_TMPDIR=temporary,
            XDG_CACHE_HOME=temporary,
            PYTHONDONTWRITEBYTECODE="1",
        )
        environment.pop("CLAUDE_TMPDIR", None)
        try:
            process = subprocess.Popen(
                [
                    "npx",
                    "--offline",
                    "--yes",
                    f"@anthropic-ai/sandbox-runtime@{SRT_VERSION}",
                    "--settings",
                    str(settings),
                    "-c",
                    wrapped,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=True,
                env=environment,
            )
        except OSError as error:
            return None, "", str(error), False, False
        try:
            out, err = process.communicate(timeout=timeout)
            prefix = marker + "\n"
            return (
                process.returncode,
                out[len(prefix) :] if out.startswith(prefix) else out,
                err,
                False,
                out.startswith(prefix),
            )
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            try:
                out, err = process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                out, err = "", ""
            return None, out or "", err or "", True, False


def _judge(entry: dict[str, Any], code: int | None, out: str, timed_out: bool) -> tuple[str, bool]:
    """Evaluate expect against a finished run; returns (verdict, expect_matched)."""
    if timed_out:
        return "timeout", False
    expect = cast(dict[str, Any], entry["expect"])
    if code != expect.get("exit_code", 0):
        return "failed", False
    if any(t not in out for t in expect.get("stdout_contains", [])) or any(
        t in out for t in expect.get("stdout_not_contains", [])
    ):
        return "expect_mismatch", False
    return "satisfied", True


def _run_one(entry: dict[str, Any], freeze_sha: str, who: tuple[Any, Any], path: Path) -> str:
    cmd, cwd = cast(str, entry["cmd"]), os.getcwd()
    base: dict[str, Any] = {
        "kind": "run",
        "proof_id": entry["id"],
        "cmd_sha256": pr.sha(cmd.strip()),
        "proof_json_sha256": freeze_sha,
        "session_id": who[0],
        "loop_id": who[1],
        "cwd": cwd,
        "head_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        or None,
        "started": _now(),
    }
    if _destructive(cmd, cwd):
        pr.append(path, **base, ended=_now(), verdict="refused", expect_matched=False)
        pr.trace("proof.run", "refused", "proof_cmd_destructive", who[0], who[1])
        return "refused"
    try:
        code, out, err, timed_out, started = _execute(cmd, float(entry.get("timeout_s") or DEFAULT_TIMEOUT_S))
    except OSError as error:
        code, out, err, timed_out, started = None, "", str(error), False, False
    if timed_out:
        verdict, matched = "timeout", False
    else:
        verdict, matched = _judge(entry, code, out, False) if started else ("sandbox_unavailable", False)
    pr.append(
        path,
        **base,
        ended=_now(),
        exit_code=code,
        stdout_sha256=pr.sha(out),
        stderr_sha256=pr.sha(err),
        excerpt=(out + err)[:EXCERPT_CAP],
        expect_matched=matched,
        verdict=verdict,
    )
    pr.trace(
        "proof.run", verdict, "" if verdict == "satisfied" else pr.VERDICT_REASON.get(verdict, "proof_failed"), *who
    )
    return verdict


def cmd_freeze(state_dir: Path) -> int:
    """Validate proof.json and append a freeze row."""
    doc = _load(state_dir / "proof.json")
    errors = validate(doc)
    who = _identity(state_dir, doc)
    if errors:
        print("proof.py freeze refused: " + "; ".join(errors), file=sys.stderr)
        pr.trace("proof.freeze", "refused", "proof_stale_cmd", *who)
        return 2
    pr.append(
        state_dir / pr.RESULTS_NAME,
        kind="freeze",
        proof_json_sha256=pr.doc_sha(doc),
        session_id=who[0],
        loop_id=who[1],
        started=_now(),
        ended=_now(),
    )
    pr.trace("proof.freeze", "frozen", "", *who)
    print(json.dumps({"frozen": pr.doc_sha(doc)}))
    return 0


def cmd_run(state_dir: Path, wanted: str | None) -> int:
    """Execute frozen proofs (one id, or all) and append run rows."""
    doc = _load(state_dir / "proof.json")
    who = _identity(state_dir, doc)
    path = state_dir / pr.RESULTS_NAME
    try:
        freezes = [r for r in pr.read_rows(path) if r["kind"] == "freeze"]
    except pr.ChainError as error:
        print(f"proof.py run refused: proof_chain_broken ({error})", file=sys.stderr)
        return 2
    if not freezes or freezes[-1]["proof_json_sha256"] != pr.doc_sha(doc) or validate(doc):
        print("proof.py run refused: proof_stale_cmd (run `proof.py freeze` first)", file=sys.stderr)
        return 2
    chosen = [(e, w) for e, w in items(doc) if wanted in (None, e["id"])]
    if not chosen:
        print(f"proof.py run: no proof with id {wanted}", file=sys.stderr)
        return 2
    status = 0
    for entry, withdrawn in chosen:
        verdict = _run_one(entry, freezes[-1]["proof_json_sha256"], who, path)
        print(json.dumps({"id": entry["id"], "verdict": verdict}))
        if verdict != "satisfied" and not withdrawn:
            status = 1
    return status


def cmd_status(state_dir: Path) -> int:
    """Print the latest verdict per proof."""
    try:
        rows = pr.read_rows(state_dir / pr.RESULTS_NAME)
    except pr.ChainError as error:
        print(f"proof_chain_broken: {error}", file=sys.stderr)
        return 2
    latest = {r["proof_id"]: r["verdict"] for r in rows if r["kind"] == "run"}
    for entry, _ in items(_load(state_dir / "proof.json")):
        print(f"{entry.get('id')}\t{latest.get(entry.get('id'), 'unexecuted')}")
    return 0


def cmd_disposition(state_dir: Path, code: str, reason: str) -> int:
    """Record a typed no-proof disposition row."""
    if code.strip() not in pr.DISPOSITION_CODES or not reason.strip():
        print(
            f"proof.py disposition refused: proof_disposition_no_reason (code must be one of {pr.DISPOSITION_CODES})",
            file=sys.stderr,
        )
        return 2
    who = _identity(state_dir, {})
    pr.append(
        state_dir / pr.RESULTS_NAME,
        kind="disposition",
        session_id=who[0],
        loop_id=who[1],
        verdict=code.strip(),
        excerpt=reason.strip()[:EXCERPT_CAP],
        started=_now(),
        ended=_now(),
    )
    pr.trace("proof.freeze", "disposition", "", *who)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the proof.py subcommands."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "run", "status", "disposition"):
        sub.add_parser(name).add_argument("state_dir", type=Path)
    sub.choices["run"].add_argument("--id")
    sub.choices["run"].add_argument("--all", action="store_true")
    sub.choices["disposition"].add_argument("--none", action="store_true", required=True)
    sub.choices["disposition"].add_argument("--reason-code", required=True)
    sub.choices["disposition"].add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        return cmd_freeze(args.state_dir)
    if args.command == "run":
        return cmd_run(args.state_dir, None if args.all or not args.id else args.id)
    if args.command == "status":
        return cmd_status(args.state_dir)
    return cmd_disposition(args.state_dir, args.reason_code, args.reason)


if __name__ == "__main__":
    sys.exit(main())
