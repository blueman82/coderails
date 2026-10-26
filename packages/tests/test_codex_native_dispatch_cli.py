"""Exercise native v3 dispatch through the real hook and graph CLI."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/codex/skills/agentic-loop/scripts"))
import graph_contract

ROOT = Path(__file__).resolve().parents[2]
TASK = "loop_worker_6c6f6f70_55335b375d"


def seeded_state(progress: Path) -> dict[str, Any]:
    """A running U3[7] wave with its unused begin-wave dispatch record."""
    node: dict[str, Any] = {
        "label": "Build unit 7",
        "status": "running",
        "outcome": "running",
        "retry": {"attempts": 0, "max": 2},
        "respawn": {"generation": 0, "intent": None},
        "evidence": [],
    }
    state: dict[str, Any] = {
        "schema_version": 3,
        "session_id": "parent",
        "loop_id": "loop",
        "revision": 2,
        "status": "in-progress",
        "state_minor": 2,
        "graph": {
            "nodes": {"U3[7]": node},
            "edges": [],
            "joins": {},
            "hard_stop": None,
            "active_wave": {"wave_id": "wave-2", "revision": 2, "nodes": ["U3[7]"]},
            "dispatches": {},
            "contract_from_revision": 1,
        },
    }
    contract = graph_contract.build_contract(state, "U3[7]", "main", progress, ROOT / "packages/codex/scripts/push.py")
    identifier, record = graph_contract.make_record(state, "U3[7]", "wave-2", 1, contract, "native")
    record["task_name"] = TASK
    state["graph"]["dispatches"][identifier] = record
    return state


def message_for(state: dict[str, Any]) -> str:
    """The pasted prompt for the seeded record."""
    identifier, record = next(iter(state["graph"]["dispatches"].items()))
    return (
        graph_contract.prompt_prefix(state, identifier, record)
        + "\n"
        + graph_contract.render_sections(record["contract"])
        + "\nImplement."
    )


class NativeDispatchCliTests(unittest.TestCase):
    """Require v3 ownership, a begin-wave record and frozen evals for every spawn in a graph-bound session."""

    def test_native_hook_traces_invalid_identity_without_using_it_as_a_path(self) -> None:
        """Malformed harness identity is denied with a stable code and a safe audit record."""
        plugin = ROOT / "packages/codex"
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            audit = directory / "discipline.log"
            base: dict[str, object] = {
                "tool_name": "collaborationspawn_agent",
                "tool_input": {"task_name": "ordinary", "message": "ordinary task"},
                "session_id": "parent",
                "cwd": scratch,
            }
            env = os.environ | {
                "PLUGIN_ROOT": str(plugin),
                "PLUGIN_DATA": str(directory / "data"),
                "CODERAILS_DISCIPLINE_LOG": str(audit),
                "CODERAILS_AGENTIC_LOOP_DIR": str(directory / "loops"),
            }
            cases: list[tuple[dict[str, object], str]] = [
                ({"session_id": ...}, "dispatch_session_required"),
                ({"session_id": None}, "dispatch_session_required"),
                ({"session_id": 7}, "dispatch_session_required"),
                ({"session_id": []}, "dispatch_session_required"),
                ({"session_id": "  "}, "dispatch_session_required"),
                ({"cwd": ...}, "dispatch_cwd_required"),
                ({"cwd": None}, "dispatch_cwd_required"),
                ({"cwd": 7}, "dispatch_cwd_required"),
                ({"cwd": []}, "dispatch_cwd_required"),
                ({"cwd": "  "}, "dispatch_cwd_required"),
                ({"session_id": ".."}, "dispatch_unsafe_session"),
                ({"session_id": "a/b"}, "dispatch_unsafe_session"),
                ({"session_id": "a..b"}, "dispatch_unsafe_session"),
            ]
            for graph_task in (False, True):
                for mutation, code in cases:
                    with self.subTest(graph_task=graph_task, mutation=mutation):
                        payload = base | mutation
                        for field, value in mutation.items():
                            if value is ...:
                                payload.pop(field)
                        if graph_task:
                            payload["tool_input"] = {"task_name": TASK, "message": "graph task"}
                        before = audit.read_text() if audit.exists() else ""
                        trace_owner = "parent" if payload.get("session_id") == "parent" else "invalid-dispatch"
                        trace = directory / "loops" / trace_owner / "trace.jsonl"
                        trace_before = len(trace.read_text().splitlines()) if trace.exists() else 0
                        result = subprocess.run(
                            [sys.executable, str(plugin / "hooks/scripts/loop_dispatch_guard.py")],
                            input=json.dumps(payload),
                            capture_output=True,
                            text=True,
                            env=env,
                            check=False,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        decision = json.loads(result.stdout)["hookSpecificOutput"]
                        self.assertEqual(decision["permissionDecision"], "deny")
                        self.assertIn(code, decision["permissionDecisionReason"])
                        added = audit.read_text()[len(before) :]
                        self.assertIn(f"reason_code={code}", added)
                        self.assertNotIn(f"session={mutation.get('session_id', '..')}", added)
                        rows = trace.read_text().splitlines()
                        self.assertEqual(len(rows), trace_before + 1)
                        self.assertEqual(json.loads(rows[-1])["reason_code"], code)
                        if code == "dispatch_unsafe_session":
                            self.assertNotIn(str(payload["session_id"]), rows[-1])
            self.assertFalse((directory / "loops" / "a").exists())
            ordinary = subprocess.run(
                [sys.executable, str(plugin / "hooks/scripts/loop_dispatch_guard.py")],
                input=json.dumps(base),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
            self.assertEqual(ordinary.stdout, "")

    def test_native_hook_denies_when_authorization_lock_is_held(self) -> None:
        """One blocked flock cannot outlive the host's ten-second hook budget without a denial."""
        plugin = ROOT / "packages/codex"
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            state_path = directory / "loops/project/parent/progress.json"
            state_path.parent.mkdir(parents=True)
            state = seeded_state(state_path)
            state_path.write_text(json.dumps(state))
            lock = Path(f"{state_path}.lock")
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import fcntl,sys,time; f=open(sys.argv[1],'a+'); "
                    "fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(12)",
                    str(lock),
                ],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                assert holder.stdout is not None
                self.assertEqual(holder.stdout.readline().strip(), "ready")
                payload = {
                    "tool_name": "collaborationspawn_agent",
                    "tool_use_id": "call_lock_probe",
                    "session_id": "parent",
                    "cwd": scratch,
                    "tool_input": {"task_name": TASK, "message": message_for(state)},
                }
                start = time.monotonic()
                result = subprocess.run(
                    [sys.executable, str(plugin / "hooks/scripts/loop_dispatch_guard.py")],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    env=os.environ
                    | {
                        "CODERAILS_AGENTIC_LOOP_DIR": str(directory / "loops"),
                        "PLUGIN_ROOT": str(plugin),
                        "PLUGIN_DATA": str(directory / "data"),
                    },
                    timeout=9.5,
                    check=False,
                )
                self.assertLess(time.monotonic() - start, 9.5)
                self.assertEqual(result.returncode, 0, result.stderr)
                denial = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(denial["permissionDecision"], "deny")
                self.assertIn("dispatch_graph_timeout", denial["permissionDecisionReason"])
                trace = directory / "loops/parent/trace.jsonl"
                self.assertEqual(
                    json.loads(trace.read_text().splitlines()[-1])["reason_code"], "dispatch_graph_timeout"
                )
            finally:
                holder.terminate()
                holder.wait(timeout=3)
                assert holder.stdout is not None
                holder.stdout.close()

    def test_opaque_native_message_is_refused_without_consuming_dispatch(self) -> None:
        """Visible task and ciphertext hash cannot prove the hidden prompt instructions."""
        plugin = ROOT / "packages/codex"
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            state_path = directory / "loops/project/parent/progress.json"
            state_path.parent.mkdir(parents=True)
            state = seeded_state(state_path)
            state_path.write_text(json.dumps(state))
            state_path.with_name("evals.json").write_text(
                json.dumps(
                    {
                        "session_id": "parent",
                        "loop_id": "loop",
                        "scope": "loop",
                        "task_ref": "loop",
                        "verification_justification": "Native dispatch fixture",
                        "verification_level": 1,
                        "frozen_sha": "fixture-sha",
                        "result": None,
                        "grading": None,
                        "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
                    }
                )
            )
            environment = os.environ | {
                "CODERAILS_AGENTIC_LOOP_DIR": str(directory / "loops"),
                "PLUGIN_ROOT": str(plugin),
                "PLUGIN_DATA": str(directory / "data"),
            }
            token = base64.urlsafe_b64encode(bytes([128]) + bytes(8 + 16 + 16 + 32)).decode()
            tool_input: dict[str, str] = {"task_name": TASK, "message": token}
            payload = {
                "tool_name": "collaborationspawn_agent",
                "tool_use_id": "call_native_1",
                "session_id": "parent",
                "cwd": scratch,
                "tool_input": tool_input,
            }

            def run() -> tuple[bool, str]:
                result = subprocess.run(
                    [sys.executable, str(plugin / "hooks/scripts/loop_dispatch_guard.py")],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if not result.stdout:
                    return False, ""
                output = json.loads(result.stdout)["hookSpecificOutput"]
                return output["permissionDecision"] == "deny", str(output["permissionDecisionReason"])

            before = state_path.read_bytes()
            altered = base64.urlsafe_b64encode(bytes([128, 1]) + bytes(71)).decode()
            for message in (token, altered, token):
                tool_input["message"] = message
                denied, reason = run()
                self.assertTrue(denied)
                self.assertIn("dispatch_prompt_unverifiable", reason)
                self.assertIn("Codex OAuth graph driver", reason)
                self.assertIn("Do not retry native spawn", reason)
                self.assertEqual(state_path.read_bytes(), before)
                record = next(iter(json.loads(state_path.read_text())["graph"]["dispatches"].values()))
                self.assertIsNone(record["authorized"])
                trace = json.loads(state_path.with_name("recovery-trace.jsonl").read_text().splitlines()[-1])
                self.assertEqual(trace["reason_code"], "dispatch_prompt_unverifiable")
            tool_input["message"] = message_for(state)
            denied, _reason = run()
            self.assertFalse(denied)
            record = next(iter(json.loads(state_path.read_text())["graph"]["dispatches"].values()))
            self.assertEqual(record["authorized"], {"tool_use_id": None})
            state_path.unlink()
            self.assertTrue(run()[0], "a graph-shaped task name cannot bypass a missing graph")

    def test_v3_native_dispatch_authority(self) -> None:
        """Allow an owned dispatch once; deny replay, missing evals, foreign session, task and bare spawns."""
        plugin = ROOT / "packages/codex"
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            state_path = directory / "loops/project/parent/progress.json"
            state_path.parent.mkdir(parents=True)
            evals = {
                "session_id": "parent",
                "loop_id": "loop",
                "scope": "loop",
                "task_ref": "loop",
                "verification_justification": "Native dispatch fixture",
                "verification_level": 1,
                "frozen_sha": "fixture-sha",
                "result": None,
                "grading": None,
                "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
            }
            evals_path = state_path.with_name("evals.json")
            environment = os.environ | {
                "CODERAILS_AGENTIC_LOOP_DIR": str(directory / "loops"),
                "PLUGIN_ROOT": str(plugin),
                "PLUGIN_DATA": str(directory / "data"),
            }
            hook = plugin / "hooks/scripts/loop_dispatch_guard.py"

            def seed() -> dict[str, Any]:
                state = seeded_state(state_path)
                state_path.write_text(json.dumps(state), encoding="utf-8")
                evals_path.write_text(json.dumps(evals), encoding="utf-8")
                return state

            def run(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, str(hook)],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )

            def denied(result: subprocess.CompletedProcess[str]) -> bool:
                self.assertEqual(result.returncode, 0, result.stderr)
                return (
                    bool(result.stdout)
                    and json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
                )

            base = seed()
            payload: dict[str, Any] = {
                "tool_name": "collaborationspawn_agent",
                "tool_use_id": "call_501f6560969348d29d04eeef99cb2650",
                "session_id": "parent",
                "cwd": scratch,
                "tool_input": {"task_name": TASK, "message": message_for(base)},
            }
            for role in (None,):
                seed()
                if role is not None:
                    payload["tool_input"]["agent_type"] = role
                self.assertFalse(denied(run(payload)), role)
            for role in ("worker", "general-purpose", "explorer"):
                seed()
                payload["tool_input"]["agent_type"] = role
                self.assertTrue(denied(run(payload)), role)
            payload["tool_input"].pop("agent_type", None)
            seed()
            self.assertFalse(denied(run(payload)))
            after = state_path.read_bytes()
            self.assertTrue(denied(run(payload)), "a second spawn with the same envelope is a replay")
            self.assertEqual(state_path.read_bytes(), after)
            for mutation in ("task", "session", "evals", "bare", "foreign role"):
                state = seed()
                altered = json.loads(json.dumps(payload))
                altered["tool_input"].pop("agent_type", None)
                if mutation == "task":
                    altered["tool_input"]["task_name"] = "loop_worker_6c6f6f70_55335b385d"
                elif mutation == "session":
                    altered["session_id"] = "other"
                elif mutation == "bare":
                    altered["tool_input"].update(
                        task_name=TASK, message="CODERAILS_GRAPH_TASK=" + TASK + "\nImplement."
                    )
                elif mutation == "foreign role":
                    altered["tool_input"]["agent_type"] = "source-auditor"
                else:
                    evals_path.unlink()
                self.assertTrue(denied(run(altered)), mutation)
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state, mutation)


if __name__ == "__main__":
    unittest.main()
