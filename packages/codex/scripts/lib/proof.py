#!/usr/bin/env python3
"""Run frozen proofs with SHA-bound results; exit 0 satisfied, 1 unsatisfied, 2 refused."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import secrets
import selectors
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.destructive_patterns import permanent_pattern, secret_path  # noqa: E402
from scripts.lib import proof_results as pr  # noqa: E402
from scripts.lib import proof_suite as suite  # noqa: E402
from scripts.lib import teardown_steps  # noqa: E402
from scripts.lib.proof_runtime import git_environment, runtime_argv, source_snapshot, trusted_executable  # noqa: E402
from scripts.lib.proof_suite import items, validate  # noqa: E402

DEFAULT_TIMEOUT_S = 600
EXCERPT_CAP = 2000
MAX_OUTPUT_BYTES = 1_048_576


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


def _capture(process: subprocess.Popen[bytes], timeout: float) -> tuple[bytes, bytes, bool, bool]:
    """Read both pipes up to a shared byte cap; stop the process group on overflow or timeout."""
    output = [bytearray(), bytearray()]
    deadline = time.monotonic() + timeout
    timed_out = overflow = False
    try:
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate((process.stdout, process.stderr)):
                if stream is not None:
                    selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    budget = MAX_OUTPUT_BYTES - sum(map(len, output))
                    chunk = os.read(key.fd, min(65536, budget + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output[cast(int, key.data)].extend(chunk[:budget])
                    if len(chunk) > budget:
                        overflow = True
                        break
                if overflow:
                    break
    finally:
        if timed_out or overflow or process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    return bytes(output[0]), bytes(output[1]), timed_out, overflow


def _execute(cmd: str, timeout: float, head: str | None) -> tuple[int | None, str, str, bool, bool, bool, str | None]:
    """Return exit, stdout, stderr, timeout, and proof that the sandbox started."""
    with tempfile.TemporaryDirectory(prefix="coderails-proof.", dir="/tmp") as temporary:
        scratch = Path(temporary)
        runner = scratch / "runner"
        runner.mkdir()
        runtime = runtime_argv(Path.cwd().resolve())
        if not head:
            raise OSError("proof source HEAD is unavailable")
        source_cwd, source_root, source_tree = source_snapshot(Path.cwd(), head, scratch)
        settings = runner / "settings.json"
        home = Path.home()
        settings.write_text(
            json.dumps(
                {
                    "filesystem": {
                        "denyRead": [str(source_root)],
                        "allowWrite": [str(runner)],
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
        wrapped = f"cd {shlex.quote(str(source_cwd))} || exit 1\nprintf '%s\\n' '{marker}'\n{cmd}"
        environment = os.environ.copy()
        environment.update(
            TMPDIR=str(runner),
            CLAUDE_CODE_TMPDIR=str(runner),
            XDG_CACHE_HOME=str(runner),
            PYTHONDONTWRITEBYTECODE="1",
        )
        for key in ("CLAUDE_TMPDIR", "NODE_OPTIONS", "NODE_PATH"):
            environment.pop(key, None)
        try:
            process = subprocess.Popen(
                [
                    *runtime,
                    "--settings",
                    str(settings),
                    "-c",
                    wrapped,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=environment,
                cwd=runner,
            )
        except OSError as error:
            return None, "", str(error), False, False, False, None
        stdout, stderr, timed_out, overflow = _capture(process, timeout)
        git = trusted_executable("git", Path.cwd())
        unchanged = subprocess.run(
            [git, "-C", str(source_cwd), "status", "--porcelain=v1", "--untracked-files=all"],
            env=git_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        identity = subprocess.run(
            [git, "-C", str(source_cwd), "rev-parse", "HEAD", "HEAD^{tree}"],
            env=git_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if (
            unchanged.returncode
            or unchanged.stdout
            or identity.returncode
            or identity.stdout.splitlines() != [head, source_tree]
        ):
            return None, "", "proof source snapshot changed", False, False, False, None
        out, err = stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")
        prefix = marker + "\n"
        started = out.startswith(prefix)
        return (
            None if timed_out or overflow else process.returncode,
            out[len(prefix) :] if started else out,
            err,
            timed_out,
            started,
            overflow,
            source_tree,
        )


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
    context = pr.git_context(Path.cwd())
    base: dict[str, Any] = {
        "kind": "run",
        "proof_id": entry["id"],
        "cmd_sha256": pr.sha(cmd.strip()),
        "proof_json_sha256": freeze_sha,
        "session_id": who[0],
        "loop_id": who[1],
        "cwd": cwd,
        "head_sha": context[1] if context else None,
        "started": _now(),
    }
    if permanent_pattern(cmd, cwd, proof_only=True)[0] or secret_path(cmd):
        pr.append(path, **base, ended=_now(), verdict="refused", expect_matched=False)
        pr.trace("proof.run", "refused", "proof_cmd_destructive", who[0], who[1])
        return "refused"
    try:
        code, out, err, timed_out, started, overflow, source_tree = _execute(
            cmd, float(entry.get("timeout_s") or DEFAULT_TIMEOUT_S), cast("str | None", base["head_sha"])
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        code, out, err, timed_out, started, overflow, source_tree = None, "", str(error), False, False, False, None
    if overflow:
        verdict, matched = "output_limit", False
    elif timed_out:
        verdict, matched = "timeout", False
    else:
        verdict, matched = _judge(entry, code, out, False) if started else ("sandbox_unavailable", False)
    note = f"[partial output: exceeded {MAX_OUTPUT_BYTES}-byte limit]\n" if overflow else ""
    pr.append(
        path,
        **base,
        ended=_now(),
        exit_code=code,
        stdout_sha256=pr.sha(out),
        stderr_sha256=pr.sha(err),
        source_tree_sha=source_tree,
        excerpt=note + (out + err)[: EXCERPT_CAP - len(note)],
        expect_matched=matched,
        verdict=verdict,
    )
    pr.trace(
        "proof.run", verdict, "" if verdict == "satisfied" else pr.VERDICT_REASON.get(verdict, "proof_failed"), *who
    )
    return verdict


def cmd_freeze(state_dir: Path) -> int:
    """Validate proof.json and append a freeze row."""
    try:
        selected, _, _ = suite.active_suite(state_dir / "proof.json", _load(state_dir / "progress.json"))
    except (pr.ChainError, suite.SuiteError) as error:
        print(f"proof.py freeze refused: {error}", file=sys.stderr)
        return 2
    doc = selected or {}
    errors = validate(doc)
    who = _identity(state_dir, doc)
    if who != (doc.get("session_id"), doc.get("loop_id")):
        errors.append("proof identity does not match progress.json")
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
    try:
        selected, rows, cutoff = suite.active_suite(state_dir / "proof.json", _load(state_dir / "progress.json"))
    except (pr.ChainError, suite.SuiteError) as error:
        print(f"proof.py run refused: {error}", file=sys.stderr)
        return 2
    doc = selected or {}
    who = _identity(state_dir, doc)
    path = state_dir / pr.RESULTS_NAME
    freezes = [
        r for r in rows if r["kind"] == "freeze" and r["seq"] > cutoff and (r["session_id"], r["loop_id"]) == who
    ]
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
    if wanted is None and status == 0:  # a full, clean run is the teardown step; `--id` runs and failures are not
        teardown_steps.record(
            state_dir, "proof_run", str(who[0]), cast("str | None", who[1]), teardown_steps.file_sha(path)
        )
    return status


def cmd_status(state_dir: Path) -> int:
    """Print the latest verdict per proof."""
    try:
        selected, rows, cutoff = suite.active_suite(state_dir / "proof.json", _load(state_dir / "progress.json"))
    except (pr.ChainError, suite.SuiteError) as error:
        print(f"proof.py status refused: {error}", file=sys.stderr)
        return 2
    latest = {r["proof_id"]: r["verdict"] for r in rows if r["kind"] == "run" and r["seq"] > cutoff}
    for entry, _ in items(selected or {}):
        print(f"{entry.get('id')}\t{latest.get(entry.get('id'), 'unexecuted')}")
    return 0


def cmd_supersede(state_dir: Path, candidate: Path, reason: str, original_sha256: str, evidence: Path) -> int:
    """Bind one independently authored candidate to this graph without editing proof.json."""
    try:
        row = suite.supersede(state_dir, candidate, reason, original_sha256, evidence)
    except (pr.ChainError, suite.SuiteError) as error:
        print(f"proof.py supersede refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"candidate_sha256": row["candidate_raw_sha256"], "sequence": row["seq"]}))
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
    result_path = state_dir / pr.RESULTS_NAME
    pr.append(
        result_path,
        kind="disposition",
        session_id=who[0],
        loop_id=who[1],
        verdict=code.strip(),
        excerpt=reason.strip()[:EXCERPT_CAP],
        started=_now(),
        ended=_now(),
    )
    pr.trace("proof.freeze", "disposition", "", *who)
    teardown_steps.record(
        state_dir, "proof_run", str(who[0]), cast("str | None", who[1]), teardown_steps.file_sha(result_path)
    )  # the typed disposition resolves the proof stage
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the proof.py subcommands."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "run", "status", "disposition", "supersede"):
        sub.add_parser(name).add_argument("state_dir", type=Path)
    sub.choices["run"].add_argument("--id")
    sub.choices["run"].add_argument("--all", action="store_true")
    sub.choices["disposition"].add_argument("--none", action="store_true", required=True)
    sub.choices["disposition"].add_argument("--reason-code", required=True)
    sub.choices["disposition"].add_argument("--reason", required=True)
    for flag in ("candidate", "reason", "original-sha256", "author-evidence"):
        sub.choices["supersede"].add_argument(f"--{flag}", required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        return cmd_freeze(args.state_dir)
    if args.command == "run":
        return cmd_run(args.state_dir, None if args.all or not args.id else args.id)
    if args.command == "status":
        return cmd_status(args.state_dir)
    if args.command == "supersede":
        return cmd_supersede(
            args.state_dir, Path(args.candidate), args.reason, args.original_sha256, Path(args.author_evidence)
        )
    return cmd_disposition(args.state_dir, args.reason_code, args.reason)


if __name__ == "__main__":
    sys.exit(main())
