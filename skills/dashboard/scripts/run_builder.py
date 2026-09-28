#!/usr/bin/env python3
"""Own the provider-local approved builder lock, validation, watchdog and terminal artifacts."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
if not __package__:
    __package__ = "skills.dashboard.scripts"
from .canonical_json import dumps, loads

PROVIDER = "claude"
PROVIDER_HOME = ".claude"
IDENTITY = ".claude-plugin/plugin.json"
PLUGIN_NAME = "coderails"


def read_object(path: Path) -> dict[str, object]:
    """Read an object artifact, leaving malformed input to explicit state validation."""
    try:
        value = json.loads(path.read_text())
        return cast(dict[str, object], value) if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def process_alive(pid: str) -> bool:
    """Probe the recorded lock PID with the same stale-owner semantics as kill -0."""
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


class BuildError(Exception):
    """A known terminal failure carrying its public reason string."""


class Builder:
    """Keep each provider's state and process evidence independent."""

    def __init__(self, directory: Path) -> None:
        """Bind paths and timing limits without touching the filesystem."""
        self.directory = directory.resolve()
        locks = os.environ.get("CODERAILS_BUILDER_LOCKS_DIR")
        self.lock = (
            Path(locks) if locks else Path.home() / PROVIDER_HOME / "coderails-dashboard/locks"
        ) / "builder.lock"
        self.held = False
        self.finished = False
        self.timeout = False
        self.child: subprocess.Popen[bytes] | None = None
        self.heartbeat_stop = threading.Event()
        self.heartbeat_thread: threading.Thread | None = None
        self.hash = str(read_object(self.directory / "state.json").get("hash") or "unknown")
        self.stored_hash = ""
        self.version = "unknown"
        self.worktree = Path()

    def write(self, state: str, **fields: object) -> None:
        """Replace the state artifact atomically while retaining its stable hash identity."""
        value = {"schemaVersion": 1, "hash": self.hash, "state": state, **fields}
        temporary = self.directory / "state.json.tmp"
        temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n")
        os.replace(temporary, self.directory / "state.json")

    def acquire(self) -> None:
        """Use exclusive creation, stale PID reclamation and original queue timing limits."""
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        if self.lock.is_file():
            pid = self.lock.read_text().strip()
            if pid and not process_alive(pid):
                self.lock.unlink(missing_ok=True)
        waited = 0
        limit = int(os.environ.get("BUILDER_QUEUE_TIMEOUT_SECS", "14400"))
        interval = int(os.environ.get("BUILDER_POLL_INTERVAL_SECS", "15"))
        while True:
            try:
                with self.lock.open("x") as stream:
                    stream.write(f"{os.getpid()}\n")
                self.held = True
                return
            except FileExistsError:
                self.write("queued")
                if waited >= limit:
                    raise BuildError("queue_timeout") from None
                time.sleep(interval)
                waited += interval

    def validate(self) -> object:
        """Reassert frozen hash, approval, tool identity and safe proposed name before spawn."""
        snapshot_path = self.directory / "snapshot.json"
        snapshot = read_object(snapshot_path)
        stored = snapshot.get("hash")
        if not stored:
            raise BuildError("unparseable_entry:snapshot.json")
        canonical = loads(snapshot_path.read_text())
        tool_input = canonical.get("toolInput") if isinstance(canonical, dict) else None
        computed = hashlib.sha256(dumps(tool_input).encode()).hexdigest()
        if computed != stored:
            raise BuildError(f"hash_mismatch:{stored}")
        if snapshot.get("status") != "approved" or snapshot.get("toolName") != "workflow-audit:propose-skill":
            raise BuildError("filter_mismatch")
        name = tool_input.get("proposed_name") if isinstance(tool_input, dict) else None
        self.stored_hash = str(stored)
        return name

    def setup_worktree(self, name: object) -> None:
        """Check primary checkout identity and report the exact failed Git setup stage."""
        path = os.environ.get("CODERAILS_BUILDER_REPO_PATH")
        if not path:
            raise BuildError("unexpected_exit:1")
        root = Path(path)
        if not (root / ".git").is_dir():
            raise BuildError("bad_repo_path:no_git")
        identity = root / IDENTITY
        if not identity.is_file() or identity.is_symlink() or identity.parent.is_symlink():
            raise BuildError("bad_repo_path:no_identity_file")
        if read_object(identity).get("name") != PLUGIN_NAME:
            raise BuildError("bad_repo_path:wrong_identity")
        if not isinstance(name, str) or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name) is None:
            raise BuildError("invalid_proposed_name")
        self.worktree = root / PROVIDER_HOME / "worktrees" / f"skill-build-{self.stored_hash[:8]}"
        commands = (
            ("fetch", ["fetch", "origin"]),
            ("add", ["worktree", "add", str(self.worktree), "-b", f"workflow-audit/skill-{name}", "origin/main"]),
        )
        for stage, arguments in commands:
            try:
                result = subprocess.run(["git", "-C", str(root), *arguments])
            except OSError as error:
                raise BuildError(f"worktree_setup_failed:{stage}") from error
            if result.returncode:
                raise BuildError(f"worktree_setup_failed:{stage}")
        if not self.worktree.is_dir():
            raise BuildError("worktree_setup_failed:cd")

    def heartbeat(self) -> None:
        """Touch immediately and on the configured interval until cleanup cancels ownership."""
        interval = float(os.environ.get("BUILDER_HEARTBEAT_SECS", "30"))
        while not self.heartbeat_stop.is_set():
            with contextlib.suppress(OSError):
                (self.directory / "heartbeat").touch()
            self.heartbeat_stop.wait(interval)

    def command(self, prompt: str) -> list[str]:
        """Keep the provider-native budget and mechanical merge prohibitions intact."""
        return [
            "claude",
            "-p",
            prompt,
            "--dangerously-skip-permissions",
            "--disallowedTools",
            "Skill(coderails:merge)",
            "Bash(gh pr merge*)",
            "Bash(*merge.py*)",
            "--max-budget-usd",
            "25",
            "--output-format",
            "json",
        ]

    def execute(self) -> int:
        """Run the native child with heartbeat and a wall-clock deadline on that child PID."""
        with contextlib.suppress(OSError):
            version = subprocess.run([PROVIDER, "--version"], capture_output=True, text=True)
            if version.returncode == 0:
                self.version = version.stdout.rstrip("\n")
        self.hash = self.stored_hash
        self.write(
            "running", **{f"{PROVIDER}Version": self.version, "startedAt": int(time.time()) * 1000, "pid": os.getpid()}
        )
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.heartbeat_thread.start()
        prompt_path = self.directory / "prompt.md"
        prompt = prompt_path.read_text().rstrip("\n") if prompt_path.is_file() else ""
        with (self.directory / "result.json").open("wb") as output, (self.directory / "build.log").open("wb") as error:
            try:
                self.child = subprocess.Popen(self.command(prompt), cwd=self.worktree, stdout=output, stderr=error)
            except OSError as failure:
                error.write((str(failure) + "\n").encode())
                return 127
            try:
                status = self.child.wait(timeout=float(os.environ.get("BUILDER_WALL_CLOCK_SECS", "2700")))
            except subprocess.TimeoutExpired:
                self.child.terminate()
                self.timeout = True
                status = self.child.wait()
        if status < 0 or status > 128:
            self.timeout = True
        return status

    def terminal(self, status: int) -> int:
        """Preserve provider completion ownership and prioritize timeout/budget/flag failures."""
        pr = self.directory / "pr_url"
        if status == 0 and pr.is_file():
            self.write("pr_open", claudeVersion=self.version, prUrl=pr.read_text().rstrip("\n"))
            self.finished = True
            return 0
        log_path, result_path = self.directory / "build.log", self.directory / "result.json"
        log = log_path.read_text(errors="replace") if log_path.is_file() else ""
        result = result_path.read_text(errors="replace") if result_path.is_file() else ""
        reason = "nonzero_exit"
        if self.timeout:
            reason = "timeout"
        elif "error_max_budget_usd" in result:
            reason = "budget_exceeded"
        elif "unknown option" in log:
            reason = f"{PROVIDER}_cli_flag_rejected"
        self.write("failed", failureReason=reason, stderrTail="\n".join(log.splitlines()[-20:]))
        self.finished = True
        return 1

    def terminate(self, _number: int, _frame: FrameType | None) -> None:
        """Translate an external TERM into a timeout terminal state before cleanup."""
        self.timeout = True
        raise SystemExit(143)

    def run(self) -> int:
        """Never leave an owned lock or nonterminal state after a failed execution."""
        code = 1
        try:
            self.acquire()
            signal.signal(signal.SIGTERM, self.terminate)
            self.setup_worktree(self.validate())
            code = self.terminal(self.execute())
            return code
        except BuildError as error:
            self.write("failed", failureReason=str(error))
            self.finished = True
            return 1
        except (OSError, ValueError) as error:
            print(error, file=sys.stderr)
            return 1
        finally:
            self.heartbeat_stop.set()
            if self.heartbeat_thread:
                self.heartbeat_thread.join(timeout=1)
            if not self.finished:
                self.write("failed", failureReason="timeout" if self.timeout else f"unexpected_exit:{code}")
            if self.held:
                self.lock.unlink(missing_ok=True)


def main() -> int:
    """Accept the claimed build directory; state validation precedes any native worker."""
    if len(sys.argv) < 2:
        print("run_builder.py requires a build directory", file=sys.stderr)
        return 1
    return Builder(Path(sys.argv[1])).run()


if __name__ == "__main__":
    raise SystemExit(main())
