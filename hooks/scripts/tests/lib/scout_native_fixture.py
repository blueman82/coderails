"""Synthetic native scout results and refusal-to-fallback source controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

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

    def refuse(self, authorize: bool = True) -> None:
        """Record an actual issued wave with a synthetic childless native failure."""
        state = self.load()
        attempt = state["graph"]["nodes"]["S2.5"]["retry"]["attempts"] + 1
        call = "call-S2.5" + (f"-a{attempt}" if attempt > 1 else "")
        if authorize:
            self.consume("S2.5", call)
        item = next(item for item in self.opened["dispatches"] if item["node_id"] == "S2.5")
        prompt = item["prompt_prefix"] + "\n" + item["prompt_sections"] + "\nRead scout instructions."
        if self.provider == "claude":
            self.append(
                {
                    "type": "assistant",
                    "sessionId": "parent",
                    "uuid": "failed-spawn-" + str(attempt),
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Agent",
                                "id": call,
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
                    "message": {"content": [{"type": "tool_result", "tool_use_id": call, "is_error": True}]},
                    "toolUseResult": {"is_error": True},
                }
            )
        else:
            self.append(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "spawn_agent",
                        "namespace": "collaboration",
                        "call_id": call,
                        "arguments": json.dumps(
                            {"task_name": item["task_name"], "agent_type": "design-scout", "message": prompt}
                        ),
                    },
                }
            )
            self.append(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": call,
                        "output": "agent thread limit reached",
                    },
                }
            )
        report = self.report()
        report["results"]["S2.5"] = {"outcome": "failed", "evidence": "native scout launch refused"}
        result = self.record(report)
        if result.returncode:
            raise AssertionError(result.stderr)

    def approve(self) -> None:
        """Append the exact request and next direct owner reply, without a live approval."""
        attempt = self.load()["graph"]["nodes"]["S2.5"]["retry"]["attempts"] + 1
        request = (
            "Coderails: Approve a non-independent design-scout fallback for loop loop, "
            f"node S2.5, attempt {attempt}? Reply approve or deny."
        )
        if self.provider == "claude":
            self.append(
                {
                    "type": "assistant",
                    "sessionId": "parent",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": request}]},
                }
            )
            self.append({"type": "user", "sessionId": "parent", "message": {"role": "user", "content": "approve"}})
        else:
            self.append(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": request}],
                    },
                }
            )
            self.append(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "approve"}],
                    },
                }
            )

    def fallback(self, approval_after_issue: bool = False) -> dict[str, Any]:
        """Issue a fresh fallback after an authorized, recorded native refusal."""
        self.refuse()
        if approval_after_issue:
            self.append({"type": "fixture_observation", "content": "failed result recorded"})
            self.opened = self.accept("begin-wave", str(self.path))
            self.approve()
        else:
            self.approve()
            self.opened = self.accept("begin-wave", str(self.path))
        return {
            "wave_id": self.opened["wave_id"],
            "results": {"S2.5": {"outcome": "skipped", "evidence": "non_independent: human approved design fallback"}},
        }

    def change_prior(self, state: dict[str, Any], rows: list[dict[str, Any]], change: str) -> None:
        """Corrupt one prior-proof relation, keeping the current issue and approval intact."""
        graph = state["graph"]
        key, record = next(
            (key, record)
            for key, record in graph["dispatches"].items()
            if record["node_id"] == "S2.5" and record["attempt"] == 1
        )
        ref = next(cast(dict[str, Any], item) for item in graph["nodes"]["S2.5"]["evidence"] if isinstance(item, dict))
        if change == "missing-issue":
            del graph["dispatches"][key]
        elif change == "duplicate-issue":
            graph["dispatches"]["duplicate"] = dict(record)
        elif change in {"unused-auth", "null-id", "foreign-id", "malformed-auth"}:
            record["authorized"] = {
                "unused-auth": None,
                "null-id": {"tool_use_id": None},
                "foreign-id": {"tool_use_id": "foreign-call"},
                "malformed-auth": {},
            }[change]
        elif change in {"bool-try", "float-try", "zero-try"}:
            ref["attempt"] = {"bool-try": True, "float-try": 1.0, "zero-try": 0}[change]
        elif change == "duplicate-reference":
            graph["nodes"]["S2.5"]["evidence"].append(dict(ref))
        elif change == "missing-history":
            del graph["wave_history"]["wave-2"]
        elif change == "old-cursor":
            graph["wave_history"]["wave-2"]["cursor"] = 2
        elif change == "late-result":
            graph["wave_history"]["wave-4"]["cursor"] = 3
            if graph["active_wave"]:
                graph["active_wave"]["transcript_cursor"] = 3
            else:
                next(
                    cast(dict[str, Any], item)
                    for item in graph["nodes"]["S2.5"]["evidence"]
                    if isinstance(item, dict) and cast(dict[str, Any], item).get("kind") == "graph_skip"
                )["cursor"] = 3
        elif change == "duplicate-call":
            rows.append(rows[1])
        elif change == "duplicate-result":
            rows.insert(3, rows[2])
        elif change == "missing-result":
            rows.pop(2)
        elif change == "approval-before-result":
            rows[:] = [rows[index] for index in (0, 1, 3, 4, 2)]
        elif change == "request-before-result":
            rows[:] = [rows[index] for index in (0, 1, 3, 2, 4)]
        else:
            arguments = (
                rows[1]["message"]["content"][0]["input"]
                if self.provider == "claude"
                else json.loads(rows[1]["payload"]["arguments"])
            )
            message_key, role_key = (
                ("prompt", "subagent_type") if self.provider == "claude" else ("message", "agent_type")
            )
            message = arguments[message_key]
            if change == "wrong-role":
                arguments[role_key] = "general-purpose" if self.provider == "claude" else "worker"
            elif change == "missing-envelope":
                arguments[message_key] = "Read scout instructions."
            elif change == "missing-sections":
                arguments[message_key] = message.split("\n", 1)[0] + "\nRead scout instructions."
            elif change == "foreign-envelope":
                header, rest = message.split("\n", 1)
                envelope = json.loads(header.split("=", 1)[1])
                envelope["loop_id"] = "foreign-loop"
                arguments[message_key] = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(envelope) + "\n" + rest
            elif change == "success-result":
                if self.provider == "claude":
                    rows[2]["toolUseResult"] = {"agentId": "successful-child", "status": "async_launched"}
                    rows[2]["message"]["content"][0]["is_error"] = False
                else:
                    rows[2]["payload"]["output"] = json.dumps({"agent_id": "successful-child"})
            if self.provider == "codex":
                rows[1]["payload"]["arguments"] = json.dumps(arguments)
