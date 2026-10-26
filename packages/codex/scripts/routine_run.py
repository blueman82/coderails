#!/usr/bin/env python3
"""Run the headless state machine for docs-sync and loop-retro-promotion."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import routine_log  # noqa: E402
from scripts.lib import artifact_io, routine_merge  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402


class Run:
    """One routine's spec, log paths and persisted state."""

    def __init__(self, routine: str, log: str | None) -> None:
        """Load the routine's spec and resolve the log, JSONL and state paths."""
        spec = routine_log.load_spec(routine)
        if spec is None:
            raise SystemExit(f"routine_unknown: {routine}")
        template = log or str(spec.get("log", ""))
        if not template or "{repo_key_dir}" in template:
            raise SystemExit("log_path_required: pass --log PATH")
        self.spec, self.routine = spec, routine
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.human = Path(template.replace("{date}", self.today)).expanduser()
        # the state file is keyed by the template, not the date, so a run that crosses midnight keeps its state
        keyed = Path(template.replace("{date}", "active")).expanduser()
        self.jsonl, self.state_path = self.human.with_suffix(".jsonl"), keyed.with_suffix(".state.json")
        self.state: dict[str, Any] = {}

    @property
    def stages(self) -> list[str]:
        """The spec's ordered stage names."""
        return [str(s) for s in cast(list[object], self.spec.get("stages", []))]

    @property
    def gates(self) -> dict[str, str]:
        """The spec's gate stages mapped to the one script each may run."""
        return cast(dict[str, str], self.spec.get("gates", {}))

    def load(self, allow_foreign: bool = False) -> bool:
        """Load the active run's state; False (with a message) when there is none."""
        try:
            self.state = artifact_io.read_object(self.state_path)
        except (OSError, ValueError):
            print("no_active_run: call begin first", file=sys.stderr)
            return False
        if self.state.get("routine") != self.routine:
            print("routine_mismatch: use this routine's own log", file=sys.stderr)
            return False
        if not allow_foreign:
            token, run_id = os.environ.get("CODERAILS_ROUTINE_RUN_ID"), self.state.get("run_id")
            if (
                not isinstance(run_id, str)
                or not re.fullmatch(r"[0-9a-f]{12}([0-9a-f]{4})?", run_id)
                or token != (run_id if len(run_id) == 16 else None)
            ):
                print("run_id_mismatch: active run belongs to another invocation", file=sys.stderr)
                return False
        if self.state.get("human"):  # the log paths pinned at begin
            self.human = Path(str(self.state["human"]))
            self.jsonl = self.human.with_suffix(".jsonl")
        return True

    def save(self) -> None:
        """Persist the state atomically."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_io.write_object(self.state_path, self.state)

    def emit(self, stage: str, outcome: str, code: str = "") -> str:
        """Append one event row for this run; returns '' or the refusal code."""
        run_id = self.state["run_id"]
        return routine_log.emit(self.jsonl, run_id, self.routine, stage, outcome, code, self.human, self.spec)

    def end(self, stage: str, outcome: str, code: str) -> str:
        """Persist success before its marker; persist failures before one cleanup."""
        if outcome in ("run_abort", "run_refused") and self.state.get("merge_attempt"):
            status = self.merge_status()
            if status != "OPEN":
                code = "merged_incomplete" if status == "MERGED" else "merge_state_unknown"
                return self.incomplete(code) or code
        if outcome == "run_ok":
            self.state["ended"], self.state["outcome"] = True, outcome
            self.save()  # never publish a green marker before the terminal state is durable
        refusal = self.emit(stage, outcome, code)
        if refusal:
            return refusal
        if outcome != "run_ok":
            self.state["ended"], self.state["outcome"] = True, outcome
            self.save()
            self.cleanup()
        return ""

    def incomplete(self, code: str) -> str:
        """Leave a red, recoverable run when a merge may already have happened."""
        if self.state.get("blocked_reason") != code:
            if refusal := self.emit("merge", "run_incomplete", code):
                return refusal
            self.state["blocked_reason"] = code
            self.save()
        return ""

    def merge_status(self) -> str:
        """Read only the pinned PR/head; an unknown or changed target cannot authorize cleanup."""
        return routine_merge.status(self.state.get("merge_attempt"))

    def cleanup(self) -> None:
        """Close the PR and delete only this run's current local branch; report failures."""
        if self.state.get("merge_attempt") and self.merge_status() != "OPEN":
            print("cleanup_blocked: merge state is not confirmed OPEN", file=sys.stderr)
            return
        branch = str(self.state.get("branch", ""))
        default = git.main()
        if not branch or branch != git.branch() or branch in (default, "main", "master"):
            return
        steps = cast(list[str], self.spec.get("cleanup", []))
        if "close_pr" in steps:
            for number in routine_merge.cleanup_numbers(branch, self.state.get("merge_attempt")):
                report("close_pr", git.run("gh", "pr", "close", number))
        if "delete_local_branch" in steps:
            if git.branch() == branch:
                switched = git.run("git", "switch", "--detach", f"origin/{default}")
                if switched.returncode:
                    report("switch_to_default", switched)
                    return
            report("delete_local_branch", git.run("git", "branch", "-D", branch))

    def next_stage(self) -> str:
        """The stage the run must perform next, or '' when all are done."""
        done = int(self.state.get("next", 0))
        return self.stages[done] if done < len(self.stages) else ""

    def out_of_order(self, name: str) -> int:
        """Refuse an out-of-order call: abort the run unless it already ended; always exit 2."""
        print(f"stage_out_of_order: {name} (expected {self.next_stage() or 'none'})", file=sys.stderr)
        if not self.state.get("ended"):
            self.end(name, "run_abort", "stage_out_of_order")
        return 2

    def advance(self, name: str) -> int:
        """Record a passed stage."""
        if name == "merge" and (refusal := self.incomplete("merged_incomplete")):
            print(refusal, file=sys.stderr)
            return 2
        refusal = self.emit(name, "stage_ok")
        if refusal:
            print(refusal, file=sys.stderr)
            return 2
        self.state["next"] = int(self.state["next"]) + 1
        self.save()
        return 0


def report(step: str, done: subprocess.CompletedProcess[str]) -> None:
    """Print a cleanup step that failed."""
    if done.returncode:
        print(f"cleanup_failed: {step}: {done.stderr.strip()}", file=sys.stderr)


def manifest_code(run: Run, base: str = "", head: str = "") -> str:
    """Run diff_manifest.py with the spec's policy over a clean tree; '' when it passes, else the reason code."""
    if git.output("git", "status", "--porcelain"):
        return "dirty_worktree"
    policy = ROOT / str(run.spec.get("policy", ""))
    command = [sys.executable, str(Path(__file__).with_name("diff_manifest.py")), "--policy", str(policy)]
    if base and head:
        command += ["--base", base, "--head", head]
    done = git.run(*command)
    code, ok = "", False
    try:
        verdict = cast(dict[str, Any], json.loads(done.stdout.strip().splitlines()[-1]))
        violations = cast(list[dict[str, Any]], verdict.get("violations") or [])
        code = str(violations[0]["code"]) if violations else str(verdict.get("reason_code", ""))
        ok = done.returncode == 0 and verdict.get("ok") is True and not code
    except (ValueError, IndexError, KeyError, TypeError, AttributeError):
        pass
    if ok:
        return ""
    print(done.stdout.strip(), file=sys.stderr)
    return code if code in cast(list[str], run.spec.get("reason_codes", [])) else "manifest_internal_error"


def manifest_check(run: Run, stage: str) -> int:
    """Check the manifest at `stage`; a violation aborts the run, a pass at manifest_check advances it."""
    code = manifest_code(run)
    if code:
        run.end(stage, "run_abort", code)
        return 1
    return run.advance(stage) if stage == "manifest_check" else 0


def cmd_begin(run: Run, args: argparse.Namespace) -> int:
    """Start a run with state and a provisional event; --new replaces an old run."""
    run_id = os.environ.get("CODERAILS_ROUTINE_RUN_ID")
    if run_id is not None and not re.fullmatch(r"[0-9a-f]{16}", run_id):
        print("run_id_invalid: expected 16 lowercase hex characters", file=sys.stderr)
        return 2
    human = run.human
    if run.state_path.exists():
        if not run.load(allow_foreign=True):
            return 2
        old = run.state
        failed = old.get("outcome") in ("run_abort", "run_refused")
        if not args.new and (not old.get("ended") or (old.get("date") == run.today and failed)):
            print("run_in_progress_or_failed: pass --new to start over", file=sys.stderr)
            return 2
        if not old.get("ended"):
            refusal = run.end("begin", "run_abort", "incomplete-run")
            if refusal:
                print(refusal, file=sys.stderr)
                return 2
    run.human, run.jsonl = human, human.with_suffix(".jsonl")
    run.state = {"v": 1, "run_id": run_id or uuid.uuid4().hex[:12], "next": 0, "branch": "", "ended": False}
    run.state |= {"routine": run.routine, "date": run.today, "human": str(run.human)}
    run.save()
    refusal = run.emit("begin", "run_incomplete", "incomplete-run")
    print(refusal or run.state["run_id"], file=sys.stderr if refusal else sys.stdout)
    return 2 if refusal else 0


def cmd_stage(run: Run, args: argparse.Namespace) -> int:
    """Perform a non-gate stage in order; manifest_check runs the policy."""
    if not run.load():
        return 2
    if run.state.get("ended") or run.next_stage() != args.name:
        return run.out_of_order(args.name)
    if args.name == "fetch_branch":
        run.state["branch"] = git.branch()
    if args.name in run.gates:
        print(f"{args.name} is a gate: use run-gate", file=sys.stderr)
        return run.out_of_order(args.name)
    return manifest_check(run, args.name) if args.name == "manifest_check" else run.advance(args.name)


def gate_allowed(script: str, argv: list[str]) -> bool:
    """Accept only the shipped gate script, invoked directly or by this Python interpreter."""
    expected = (ROOT / "scripts" / script).resolve()
    if not script or not expected.is_file() or not argv:
        return False
    command = Path(argv[0])
    executable = Path(shutil.which(argv[0]) or argv[0]).resolve()
    if command.name == script and executable == expected:
        return True
    interpreter = Path(shutil.which("python3") or "").resolve()
    return (
        executable in {Path(sys.executable).resolve(), interpreter}
        and len(argv) > 1
        and Path(argv[1]).resolve() == expected
    )


def cmd_run_gate(run: Run, args: argparse.Namespace) -> int:
    """Run a gate command in order; any non-zero exit is a refusal for that gate."""
    argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not argv:
        print("run-gate needs a command after --", file=sys.stderr)
        return 2
    if not run.load():
        return 2
    if run.state.get("ended") or run.next_stage() != args.stage:
        return run.out_of_order(args.stage)
    if not gate_allowed(run.gates.get(args.stage, ""), argv):
        pinned = run.gates.get(args.stage) or "no command"
        print(f"gate_argv_not_allowed: {args.stage} runs only {pinned}", file=sys.stderr)
        run.end(args.stage, "run_abort", "gate_argv_not_allowed")
        return 2
    if args.stage == "push" and manifest_check(run, "push"):  # a late edit is caught before it is pushed
        return 1
    if args.stage == "merge":
        if run.state.get("merge_attempt"):
            status = run.merge_status()
            if status == "MERGED":
                return run.advance(args.stage)
            if status != "OPEN":
                run.incomplete("merge_state_unknown")
                return 2
            print("merge_not_confirmed: previous attempt is still OPEN", file=sys.stderr)
            run.end(args.stage, "run_abort", "merge_not_confirmed")
            return 2
        scope_code, attempt = routine_merge.scope_attempt(
            argv, str(run.state.get("branch", "")), lambda base, head: manifest_code(run, base, head)
        )
        if scope_code:
            print(f"merge_scope_refused: {scope_code}", file=sys.stderr)
            run.end(args.stage, "run_abort", scope_code)
            return 2
        run.state["merge_attempt"] = attempt
        run.save()
    try:
        code = subprocess.run(argv, check=False).returncode
    except OSError as error:
        print(f"gate_spawn_failed: {error}", file=sys.stderr)
        code = 127
    if args.stage == "merge":
        status = run.merge_status()
        if status == "MERGED":
            return run.advance(args.stage)
        if status != "OPEN":
            run.incomplete("merge_state_unknown")
            return 2
        if code == 0:
            print("merge_not_confirmed: PR remains OPEN", file=sys.stderr)
            run.end(args.stage, "run_abort", "merge_not_confirmed")
            return 2
    if code == 0:
        return run.advance(args.stage)
    print(f"refused: gate {args.stage} exited {code}", file=sys.stderr)
    if run.end(args.stage, "run_refused", args.stage):  # code not in the spec: still end the run, never swallow it
        run.end(args.stage, "run_abort", "runner_exit_no_terminal")
    return 1


def cmd_end(run: Run, args: argparse.Namespace) -> int:
    """Abort with CODE or refuse GATE explicitly."""
    if not run.load():
        return 2
    if run.state.get("ended"):
        print("already_terminal", file=sys.stderr)
        return 2
    outcome = "run_abort" if args.command == "abort" else "run_refused"
    refusal = run.end(run.next_stage() or "end", outcome, args.code)
    if refusal:
        print(refusal, file=sys.stderr)
    return 2 if refusal else 0


def cmd_finish(run: Run, args: argparse.Namespace) -> int:
    """Finish ok (all stages done) or no_drift (none started) by emitting run_ok."""
    if not run.load():
        return 2
    delivered = int(run.state.get("next", 0))
    complete = delivered == len(run.stages) if args.result == "ok" else delivered == 0
    if run.state.get("ended") or not complete:
        return run.out_of_order(f"finish {args.result}")
    if args.result == "ok" and run.merge_status() != "MERGED":
        run.incomplete("merge_state_unknown")
        return 2
    refusal = run.end("merge" if args.result == "ok" else "no_drift", "run_ok", "")
    if refusal:
        print(refusal, file=sys.stderr)
    return 2 if refusal else 0


@contextmanager
def locked(run: Run) -> Generator[None]:
    """Serialise load..save across concurrent calls on one routine's state."""
    run.state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(run.state_path.with_suffix(".lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def main(arguments: list[str] | None = None) -> int:
    """CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", help="human run log path; default is the spec's log with {date} expanded")
    parser.add_argument("routine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("begin").add_argument("--new", action="store_true")
    sub.add_parser("stage").add_argument("name")
    gate = sub.add_parser("run-gate")
    gate.add_argument("stage")
    gate.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("abort").add_argument("code")
    sub.add_parser("refuse").add_argument("code")
    sub.add_parser("finish").add_argument("result", choices=("ok", "no_drift"))
    args = parser.parse_args(arguments)
    handlers = {
        "begin": cmd_begin,
        "stage": cmd_stage,
        "run-gate": cmd_run_gate,
        "abort": cmd_end,
        "refuse": cmd_end,
        "finish": cmd_finish,
    }
    run = Run(args.routine, args.log)
    with locked(run):
        return handlers[args.command](run, args)


if __name__ == "__main__":
    raise SystemExit(main())
