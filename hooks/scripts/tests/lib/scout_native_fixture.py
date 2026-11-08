"""Synthetic native scout results and refusal-to-fallback source controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hooks.scripts.tests.lib.scout_skip_fixture import ROLES, ScoutFixture


class NativeScoutFixture(ScoutFixture):
    """Add provider-shaped native child and refusal inputs to the public-CLI fixture."""

    def native_result(self, node_id: str) -> None:
        """Represent one authorized scout child and its successful native terminal."""
        self.consume(node_id)
        item = next(item for item in self.opened["dispatches"] if item["node_id"] == node_id)
        prompt = item["prompt_prefix"] + "\n" + item["prompt_sections"] + "\nRead scout instructions."
        child, tool, role = "child-" + node_id.replace(".", "_"), "call-" + node_id, ROLES[node_id]
        if self.provider == "claude":
            path, rows = self.claude_result(node_id, prompt, child, tool, role)
        else:
            path, rows = self.codex_result(node_id, item["task_name"], prompt, child, tool, role)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def claude_result(
        self, node_id: str, prompt: str, child: str, tool: str, role: str
    ) -> tuple[Path, list[dict[str, Any]]]:
        """Write Claude parent events and describe the matching child transcript."""
        self.append(
            {
                "type": "assistant",
                "sessionId": "parent",
                "uuid": "spawn-" + node_id,
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Agent",
                            "id": tool,
                            "input": {"subagent_type": "coderails:" + role, "prompt": prompt},
                        }
                    ]
                },
            }
        )
        self.append(
            {
                "type": "user",
                "sessionId": "parent",
                "message": {"content": [{"type": "tool_result", "tool_use_id": tool}]},
                "toolUseResult": {"status": "async_launched", "agentId": child},
            }
        )
        self.append(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "sessionId": "parent",
                "content": f"<task-notification><tool-use-id>{tool}</tool-use-id><task-id>{child}</task-id>"
                "<status>completed</status><result>Scout complete</result></task-notification>",
            }
        )
        path = self.transcript.with_suffix("") / "subagents" / f"agent-{child}.jsonl"
        common = {"sessionId": "parent", "isSidechain": True, "agentId": child, "timestamp": "2026-09-21T00:00:02Z"}
        rows = [
            {**common, "type": "user", "message": {"role": "user", "content": prompt}},
            {
                **common,
                "type": "assistant",
                "attributionAgent": "coderails:" + role,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Scout complete"}],
                    "stop_reason": "end_turn",
                },
            },
        ]
        return path, rows

    def codex_result(
        self, node_id: str, task: str, prompt: str, child: str, tool: str, role: str
    ) -> tuple[Path, list[dict[str, Any]]]:
        """Write Codex parent events and describe the matching child transcript."""
        self.append(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "spawn_agent",
                    "namespace": "collaboration",
                    "call_id": tool,
                    "arguments": json.dumps({"task_name": task, "agent_type": role, "message": prompt}),
                },
            }
        )
        self.append(
            {
                "type": "event_msg",
                "payload": {
                    "item": {
                        "type": "SubAgentActivity",
                        "kind": "started",
                        "id": tool,
                        "agent_thread_id": child,
                        "agent_path": "/root/" + task,
                    }
                },
            }
        )
        path = self.transcript.with_name(f"fixture-{child}.jsonl")
        spawn = {"parent_thread_id": "parent", "depth": 1, "agent_role": role, "agent_path": "/root/" + task}
        rows = [
            {
                "timestamp": "2026-09-21T00:00:01Z",
                "type": "session_meta",
                "payload": {
                    "id": child,
                    "parent_thread_id": "parent",
                    "session_id": "parent",
                    "thread_source": "subagent",
                    "agent_role": role,
                    "agent_path": "/root/" + task,
                    "source": {"subagent": {"thread_spawn": spawn}},
                },
            },
            {
                "timestamp": "2026-09-21T00:00:02Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-" + node_id},
            },
            {
                "timestamp": "2026-09-21T00:00:03Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": "turn-" + node_id},
            },
        ]
        return path, rows

    def fallback(self) -> dict[str, Any]:
        """Record a consumed native refusal, then issue a fresh approved fallback wave."""
        self.consume("S2.5")
        item = next(item for item in self.opened["dispatches"] if item["node_id"] == "S2.5")
        prompt = item["prompt_prefix"] + "\n" + item["prompt_sections"] + "\nRead scout instructions."
        self.append(
            {
                "type": "assistant",
                "sessionId": "parent",
                "uuid": "failed-spawn",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Agent",
                            "id": "call-S2.5",
                            "input": {"subagent_type": "coderails:design-scout", "prompt": prompt},
                        }
                    ]
                },
            }
        )
        self.append(
            {
                "type": "user",
                "sessionId": "parent",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "call-S2.5", "is_error": True}]},
                "toolUseResult": {"is_error": True},
            }
        )
        report = self.report()
        report["results"]["S2.5"] = {"outcome": "failed", "evidence": "native scout launch refused"}
        result = self.record(report)
        if result.returncode:
            raise AssertionError(result.stderr)
        request = (
            "Coderails: Approve a non-independent design-scout fallback for loop loop, "
            "node S2.5, attempt 2? Reply approve or deny."
        )
        self.append(
            {
                "type": "assistant",
                "sessionId": "parent",
                "message": {"role": "assistant", "content": [{"type": "text", "text": request}]},
            }
        )
        self.append({"type": "user", "sessionId": "parent", "message": {"role": "user", "content": "approve"}})
        self.opened = self.accept("begin-wave", str(self.path))
        return {
            "wave_id": self.opened["wave_id"],
            "results": {"S2.5": {"outcome": "skipped", "evidence": "non_independent: human approved design fallback"}},
        }
