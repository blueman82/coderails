#!/usr/bin/env python3
"""Pin the fail-closed identity hook: Bash from a subagent with no agent_type in a graph-bound session is denied."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import resolve_path  # noqa: E402
from hooks.scripts.tests.native_hook_test_support import HookCase  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
HOOK = "subagent_identity_gate"
SESSION = "s_identity"
CODE = "bash_agent_type_absent"


def request(session: str = SESSION, **identity: object) -> dict[str, Any]:
    """A native Bash PreToolUse payload; `identity` adds agent_id / agent_type exactly as given."""
    body: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "cwd": "/x",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }
    body.update(identity)
    return body


class SubagentIdentityGateTests(HookCase):
    """agent_id without a usable agent_type is the one shape a typed role can hide behind; it fails closed."""

    def bind(self, state: dict[str, Any]) -> None:
        """Write progress.json where the hook will resolve it for cwd /x and the test session."""
        with patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}):
            path = resolve_path("/x", SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))

    def graph_bound(self) -> None:
        """A progress.json for this session that carries a graph."""
        self.bind({"session_id": SESSION, "graph": {"nodes": {}}})

    def rows(self) -> list[dict[str, Any]]:
        """Trace rows written for the session."""
        path = self.loop / SESSION / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def test_agent_id_without_agent_type_in_graph_session_is_denied_and_traced(self) -> None:
        """The core case: deny, name the reason, write a discipline-log line and one trace row."""
        self.graph_bound()
        out = self.output(HOOK, request(agent_id="a1"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(CODE, out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn(CODE, self.log.read_text())
        rows = [(r["command"], r["outcome"], r["reason_code"]) for r in self.rows()]
        self.assertEqual(rows, [(HOOK, "denied", CODE)])

    def test_blank_or_non_string_agent_type_is_absent(self) -> None:
        """Empty, whitespace and non-string agent_type values are treated as absent, not as a role."""
        self.graph_bound()
        for value in ("", "   ", None, 7, ["design-scout"]):
            with self.subTest(agent_type=value):
                self.assertTrue(self.denied(HOOK, request(agent_id="a1", agent_type=value)))

    def test_allowed_shapes(self) -> None:
        """No progress.json, a named agent_type, no agent_id and a foreign session's state are all untouched."""
        self.assertFalse(self.denied(HOOK, request(agent_id="a1")))  # no progress.json at all
        self.graph_bound()
        self.assertFalse(self.denied(HOOK, request(agent_id="a1", agent_type="design-scout")))
        self.assertFalse(self.denied(HOOK, request()))  # orchestrator: no agent_id
        self.assertFalse(self.denied(HOOK, request(agent_id="", agent_type="")))  # blank id is the orchestrator too
        self.bind({"session_id": "someone-else", "graph": {"nodes": {}}})
        self.assertFalse(self.denied(HOOK, request(agent_id="a1")))
        self.bind({"session_id": SESSION})  # this session's state, but no graph
        self.assertFalse(self.denied(HOOK, request(agent_id="a1")))
        self.assertEqual(self.rows(), [])

    def test_non_bash_tool_is_untouched(self) -> None:
        """Only Bash is in scope; the typed MCP tools and Read carry no shell."""
        self.graph_bound()
        self.assertFalse(self.denied(HOOK, request(agent_id="a1") | {"tool_name": "Read"}))

    def test_config_off_switch_disables_the_gate(self) -> None:
        """`subagent_identity_gate: off` in the repo config lets the call through; unset or any other value stays ON."""
        import subprocess

        repo = self.directory / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        (repo / ".coderails").mkdir()
        body = request(agent_id="a1") | {"cwd": str(repo)}
        with patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}):
            path = resolve_path(str(repo), SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": SESSION, "graph": {"nodes": {}}}))
        config = repo / ".coderails/workflow.config.yaml"
        cases = (("", True), ("subagent_identity_gate: on\n", True), ("subagent_identity_gate: off\n", False))
        for line, expect in cases:
            with self.subTest(config=line):
                config.write_text(line)
                self.assertEqual(self.denied(HOOK, body), expect)

    def test_malformed_payload_does_not_crash(self) -> None:
        """A non-object or garbage payload exits 0 with no decision (the harness treats a crash as allow anyway)."""
        for raw in ("", "not json", "[]"):
            with self.subTest(raw=raw):
                self.assertEqual(self.output(HOOK, raw), {})

    def test_registered_identity_chain_denies_end_to_end(self) -> None:
        """Run the Bash identity hooks as hooks.json registers them: with the gate unregistered nothing denies."""
        group = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]
        chain = [Path(h["command"].strip('"')).stem for h in group["hooks"]]
        chain = [name for name in chain if name in {"reviewer_bash_allowlist", "subagent_identity_gate"}]
        self.graph_bound()
        verdicts = [self.denied(name, request(agent_id="a1")) for name in chain]
        self.assertIn("subagent_identity_gate", chain)
        self.assertEqual(verdicts, [False, True])  # the allowlist has no agent_type to key on; the gate catches it
        chain.remove("subagent_identity_gate")  # negative control: the same chain minus the gate denies nothing
        self.assertFalse(any(self.denied(name, request(agent_id="a1")) for name in chain))


if __name__ == "__main__":
    unittest.main()
