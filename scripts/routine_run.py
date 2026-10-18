#!/usr/bin/env python3
"""The one state machine for the docs-sync and loop-retro-promotion routines; needs no hooks, so it works headless.

    routine_run.py [--log PATH] ROUTINE begin | stage NAME | run-gate STAGE -- ARGV... | abort CODE | refuse GATE
                                      | finish ok|no_drift

`begin` writes the state file and a provisional run_incomplete row. `stage` and `run-gate` enforce the spec's stage
order (an out-of-order call aborts the run: stage_out_of_order). `stage manifest_check` runs diff_manifest.py with the
spec's policy and aborts on any violation. `run-gate` runs a gate command and maps any non-zero exit to run_refused for
that gate. `abort` and `refuse` end the run and clean up with git and gh only (close the PR and delete the current
local branch, never the remote or default branch), once. `finish` emits run_ok. Exit: 0 ok; 1 abort/refused; 2 refused.
Events go through routine_log.emit; the human log is the JSONL path with a .log suffix.
"""

from __future__ import annotations

import argparse
import fcntl
import json
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
from scripts.lib import artifact_io  # noqa: E402
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

    def load(self) -> bool:
        """Load the active run's state; False (with a message) when there is none."""
        try:
            self.state = artifact_io.read_object(self.state_path)
        except (OSError, ValueError):
            print("no_active_run: call begin first", file=sys.stderr)
            return False
        if self.state.get("routine") != self.routine:
            print("routine_mismatch: use this routine's own log", file=sys.stderr)
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
        """Emit the terminal row, persist the ended state, then clean up (once, because the state is already ended)."""
        refusal = self.emit(stage, outcome, code)
        if refusal:
            return refusal
        self.state["ended"], self.state["outcome"] = True, outcome
        self.save()
        if outcome != "run_ok":
            self.cleanup()
        return ""

    def cleanup(self) -> None:
        """Close the PR and delete only this run's current local branch; report failures."""
        branch = str(self.state.get("branch", ""))
        default = git.main()
        if not branch or branch != git.branch() or branch in (default, "main", "master"):
            return
        steps = cast(list[str], self.spec.get("cleanup", []))
        if "close_pr" in steps:
            listing = ("gh", "pr", "list", "--head", branch, "--state", "open")
            for number in git.run(*listing, "--json", "number", "--jq", ".[].number").stdout.split():
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


def manifest_code(run: Run) -> str:
    """Run diff_manifest.py with the spec's policy over a clean tree; '' when it passes, else the reason code."""
    if git.output("git", "status", "--porcelain"):
        return "dirty_worktree"
    policy = ROOT / str(run.spec.get("policy", ""))
    done = git.run(sys.executable, str(Path(__file__).with_name("diff_manifest.py")), "--policy", str(policy))
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
    """Start a run: write the state and the provisional run_incomplete row; print the run id.

    Refused while a run is open, or after a same-day abort/refusal, unless --new closes the previous run.
    """
    human = run.human
    if run.state_path.exists():
        if not run.load():
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
    run.state = {"v": 1, "run_id": uuid.uuid4().hex[:12], "next": 0, "branch": "", "ended": False}
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
    try:
        code = subprocess.run(argv, check=False).returncode
    except OSError as error:
        print(f"gate_spawn_failed: {error}", file=sys.stderr)
        code = 127
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
