"""Drive independent provider CLIs with native local fixture transcripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/codex/skills/agentic-loop/scripts"))
from hooks.scripts.tests.claude_graph_test_support import node
from hooks.scripts.tests.lib import claude_transcript_fixture as claude
from packages.tests import codex_fixture as codex

ROOT = Path(__file__).resolve().parents[2]


class Provider:
    """Keep provider runtime imports and mutable state in separate native CLI processes."""

    def __init__(self, root: Path, name: str) -> None:
        """Initialize isolated state/transcripts without touching any live provider store."""
        self.name = name
        self.home = root / name
        self.home.mkdir()
        self.plugin = ROOT if name == "claude" else ROOT / "packages/codex"
        self.session = "fixture-session" if name == "claude" else "parent"
        self.parent = claude.parent(self.home) if name == "claude" else codex.transcripts(self.home)
        self.path = self.home / "state/fixture" / self.session / "progress.json"
        self.path.parent.mkdir(parents=True)
        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "CLAUDE_PROJECTS_DIR": str(self.home / ".claude/projects"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.home / "state"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.home / "state"),
            "CLAUDE_DISCIPLINE_LOG": str(self.home / "log"),
            "CODERAILS_DISCIPLINE_LOG": str(self.home / "log"),
            "PLUGIN_ROOT": str(self.plugin),
            "CLAUDE_HOOK_MAX_ATTEMPTS": "1",
            "CLAUDE_HOOK_SLEEP_S": "0",
        }
        self.write(self.state())
        self.freeze()

    def state(self, identifiers: tuple[str, ...] = ("U3[1]",)) -> dict[str, Any]:
        """Return a current state using stable semantic IDs and native session identity."""
        value = claude.state(0)
        value.update(session_id=self.session, loop_id="fixture-loop")
        value["graph"]["nodes"] = {identifier: node(identifier) for identifier in identifiers}
        return value

    def write(self, value: object, filename: str = "progress.json") -> None:
        """Write one fixture document beside this provider's own progress file."""
        claude.write_json(self.path.with_name(filename), value)

    def read(self, filename: str = "progress.json") -> dict[str, Any]:
        """Read current persisted fixture state."""
        return cast(dict[str, Any], json.loads(self.path.with_name(filename).read_text()))

    def call(self, operation: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Invoke the actual installed-layout provider graph CLI."""
        return subprocess.run(
            [
                sys.executable,
                str(self.plugin / "skills/agentic-loop/scripts/graph.py"),
                operation,
                str(self.path),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=self.environment,
            cwd=self.home,
        )

    def success(self, operation: str, *arguments: str) -> dict[str, Any]:
        """Require a successful graph command and return its real JSON response."""
        result = self.call(operation, *arguments)
        if result.returncode:
            raise AssertionError(result.stderr)
        return cast(dict[str, Any], json.loads(result.stdout))

    def freeze(self) -> None:
        """Write a stable-identity ungraded suite accepted before implementation."""
        value = claude.frozen_evals()
        value.update(session_id=self.session, loop_id="fixture-loop", task_ref="fixture-loop")
        self.write(value, "evals.json")

    def launch(self, outcome: str = "done") -> dict[str, Any]:
        """Emit actual provider-shaped local fixture authority for every active node."""
        state = self.read()
        for identifier in state["graph"]["active_wave"]["nodes"]:
            if self.name == "claude":
                claude.spawn(self.parent, state, identifier, completed=outcome == "done")
            else:
                codex.spawn(self.parent, state, identifier, terminal=outcome != "stale")
        return claude.report(state, outcome)

    def finish_wave(self, outcome: str = "done") -> dict[str, Any]:
        """Open, launch and collect one complete native wave."""
        self.success("begin-wave")
        return self.success("record-wave", json.dumps(self.launch(outcome)))

    def artifacts(self) -> None:
        """Grade a nonvacuous suite and write identity-matched observed proof and retro."""
        state = self.read()
        identity = {key: state[key] for key in ("session_id", "loop_id")}
        suite = {
            **identity,
            "scope": "loop",
            "task_ref": "fixture-loop",
            "revision": state["revision"],
            "verification_level": 1,
            "verification_justification": "independent provider parity",
            "frozen_sha": "a" * 40,
            "head_sha": "a" * 40,
            "amendments": [],
            "evals": [
                {
                    "id": "E1",
                    "priority": "P0",
                    "mode": "scripted",
                    "cmd": "true",
                    "negative_control": "false",
                    "status": "pass",
                    "evidence": "verified",
                }
            ],
        }
        self.write(suite, "evals.json")
        result = subprocess.run(
            [
                sys.executable,
                str(self.plugin / "scripts/post_evals.py"),
                "grade-loop",
                str(self.path.with_name("evals.json")),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=self.environment,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        self.write(
            {
                **identity,
                "schema_version": 1,
                "proofs": [{"id": "P1", "cmd": "true", "status": "pass", "evidence": "observed"}],
                "withdrawn_proofs": [],
            },
            "proof.json",
        )
        self.write({**identity, "schema_version": 1, "status": "complete"}, "retro.json")
        if self.name == "claude":
            claude.append(
                self.parent,
                {
                    "type": "assistant",
                    "sessionId": self.session,
                    "message": {
                        "content": [{"type": "tool_use", "name": "Bash", "id": "proof-1", "input": {"command": "true"}}]
                    },
                },
            )
            claude.append(
                self.parent,
                {
                    "type": "user",
                    "sessionId": self.session,
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": "proof-1", "is_error": False, "content": "success"}
                        ]
                    },
                },
            )
        else:
            codex.append(
                self.parent,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "proof-1",
                        "arguments": json.dumps({"cmd": "true"}),
                    },
                },
            )
            codex.append(
                self.parent,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "proof-1",
                        "output": json.dumps({"exit_code": 0}),
                    },
                },
            )

    def complete(self) -> subprocess.CompletedProcess[str]:
        """Run each provider's native completion options without sharing runtime code."""
        arguments = ["--session", self.session]
        if self.name == "codex":
            for name in ("evals", "proof", "retro"):
                arguments.extend(["--" + name, str(self.path.with_name(name + ".json"))])
            arguments.extend(["--transcript", str(self.parent)])
        return self.call("complete", *arguments)

    def request(self) -> dict[str, Any]:
        """Build provider-native dispatch labels with a separate graph correlation marker."""
        state = self.read()
        identifier = state["graph"]["active_wave"]["nodes"][0]
        request: dict[str, Any] = {"session_id": self.session, "cwd": str(self.home)}
        if self.name == "claude":
            owner = {key: state[key] for key in ("session_id", "loop_id", "revision")}
            owner.update(wave_id=state["graph"]["active_wave"]["wave_id"], node_id=identifier)
            request.update(
                tool_name="Agent",
                tool_input={
                    "subagent_type": "general-purpose",
                    "prompt": "CODERAILS_GRAPH_DISPATCH=" + json.dumps(owner) + "\nWorker instructions.",
                },
            )
        else:
            task = self.success("inspect")["task_names"][identifier]
            request.update(
                tool_name="spawn_agent",
                tool_input={"task_name": task, "message": "CODERAILS_GRAPH_TASK=" + task + "\nWorker instructions."},
            )
        return request

    def hook(self, name: str, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        """Execute one registered native hook with its provider's environment."""
        return subprocess.run(
            [sys.executable, str(self.plugin / "hooks/scripts" / (name + ".py"))],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env=self.environment,
            cwd=self.home,
        )
