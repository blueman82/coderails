"""Preserve native Stop-hook escalation and fail-closed repair distinctions."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, suppress
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/codex/hooks/scripts"))
import graph_completion_guard as codex_stop

from hooks.scripts import loop_stall_guard
from hooks.scripts.lib.loop_state_common import LoopState
from hooks.scripts.tests.lib.claude_transcript_fixture import append
from packages.tests.provider_fixture import Provider


class StopEscalationTests(unittest.TestCase):
    """Drive genuine native Stop processes without weakening provider response contracts."""

    def setUp(self) -> None:
        """Keep tests independent from real HOME and session state."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def stop(self, provider: Provider, message: str = "I am done") -> dict[str, Any]:
        """Append native Claude final text or use Codex direct final text and require block."""
        if provider.name == "claude":
            append(
                provider.parent,
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}]
                    },
                },
            )
            append(provider.parent, {"type": "assistant", "message": {"content": [{"type": "text", "text": message}]}})
        payload = {
            "session_id": provider.session,
            "cwd": str(provider.home),
            "hook_event_name": "Stop",
            "transcript_path": str(provider.parent),
            "last_assistant_message": message,
        }
        hook = "loop_stall_guard" if provider.name == "claude" else "graph_completion_guard"
        result = provider.hook(hook, payload)
        output: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
        if provider.name == "claude":
            self.assertEqual(result.returncode, 2, result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.get("decision"), "block", output)
        return output

    def test_unresolved_first_repeat_and_marker_failure(self) -> None:
        """First notice explains human approval; repeat stays blocked without another notice."""
        for provider in self.providers:
            output = self.stop(provider)
            self.assertIn("human approval", output.get("systemMessage", "").lower())
            self.assertNotIn("systemMessage", self.stop(provider))
            marker = next(provider.path.parent.glob(".human-approval-*"))
            marker.rmdir()
            marker.touch()
            output = self.stop(provider)
            self.assertIn("human approval", output.get("systemMessage", "").lower())

    def test_complete_declaration_still_escalates_unresolved_work(self) -> None:
        """A premature completion declaration cannot hide unfinished native work."""
        for provider in self.providers:
            provider.artifacts()
            output = self.stop(provider, "LOOP-STOP: complete — please stop")
            self.assertIn("human approval", output.get("systemMessage", "").lower())

    def test_valid_unresolved_statuses_and_invalid_shape_repair(self) -> None:
        """Valid unfinished graphs escalate; malformed graphs ask for repair instead."""
        for provider in self.providers:
            baseline = provider.state()
            for status in ("pending", "ready", "blocked"):
                state = copy.deepcopy(baseline)
                state["graph"]["nodes"]["U3[1]"].update(status=status, outcome=status)
                provider.write(state)
                for marker in provider.path.parent.glob(".human-approval-*"):
                    marker.rmdir()
                self.assertIn("systemMessage", self.stop(provider))
            variants: list[dict[str, Any]] = []
            malformed: tuple[tuple[str, object], ...] = (
                ("edges", {}),
                ("edges", "bad"),
                ("joins", []),
                ("joins", "bad"),
                ("nodes", {"U3[1]": "bad"}),
                ("edges", [{"from": "U3[1]", "to": "unknown"}]),
                ("edges", [{"from": "U3[1]", "to": "U3[1]"}]),
                ("joins", {"unknown": {"mode": "all", "inputs": ["U3[1]"], "released": False}}),
            )
            for key, value in malformed:
                state = copy.deepcopy(baseline)
                state["graph"][key] = value
                variants.append(state)
            for key in ("active_wave", "hard_stop"):
                state = copy.deepcopy(baseline)
                del state["graph"][key]
                variants.append(state)
            state = copy.deepcopy(baseline)
            state["session_id"] = "foreign"
            variants.append(state)
            for state in variants:
                provider.write(state)
                self.assertNotIn("systemMessage", self.stop(provider))

    def test_notice_serialization_failure_keeps_retry_possible(self) -> None:
        """Failed notice serialization must never consume the human-request dedupe slot."""
        provider = self.providers[0]
        state = LoopState(provider.path, provider.session, 1, provider.read())
        with (
            patch.dict("os.environ", provider.environment),
            patch("hooks.scripts.loop_stall_guard.json.dumps", side_effect=ValueError("output unavailable")),
            suppress(ValueError),
        ):
            loop_stall_guard.emit_human_request(state)
        self.assertEqual(list(provider.path.parent.glob(".human-approval-*")), [])
        output = io.StringIO()
        with redirect_stdout(output):
            loop_stall_guard.emit_human_request(state)
        self.assertIn("human approval", json.loads(output.getvalue())["systemMessage"].lower())

    def test_codex_notice_failure_does_not_consume_retry(self) -> None:
        """Native Codex must retain the first notice after output generation fails."""
        provider = self.providers[1]
        with (
            patch.dict("os.environ", provider.environment),
            patch("graph_completion_guard.json.dumps", side_effect=ValueError("output unavailable")),
            suppress(ValueError),
        ):
            codex_stop.request_human_approval(provider.path, provider.session, provider.read())
        self.assertEqual(list(provider.path.parent.glob(".human-approval-*")), [])
        self.assertIn("systemMessage", self.stop(provider))

    def test_print_failure_rolls_back_only_new_notice_stamp(self) -> None:
        """A failed write leaves no new stamp and never removes another caller's stamp."""
        for provider in self.providers:
            target = (
                "hooks.scripts.loop_stall_guard.print" if provider.name == "claude" else "graph_completion_guard.print"
            )
            with (
                patch.dict("os.environ", provider.environment),
                patch(target, side_effect=OSError("output lost")),
                redirect_stdout(io.StringIO()),
                suppress(OSError, ValueError),
            ):
                if provider.name == "claude":
                    loop_stall_guard.emit_human_request(LoopState(provider.path, provider.session, 1, provider.read()))
                else:
                    codex_stop.request_human_approval(provider.path, provider.session, provider.read())
            self.assertEqual(list(provider.path.parent.glob(".human-approval-*")), [])
            self.assertIn("systemMessage", self.stop(provider))
            marker = next(provider.path.parent.glob(".human-approval-*"))
            with (
                patch.dict("os.environ", provider.environment),
                patch(target, side_effect=OSError("output lost")),
                redirect_stdout(io.StringIO()),
                suppress(OSError, ValueError),
            ):
                if provider.name == "claude":
                    loop_stall_guard.emit_human_request(LoopState(provider.path, provider.session, 1, provider.read()))
                else:
                    codex_stop.request_human_approval(provider.path, provider.session, provider.read())
            self.assertTrue(marker.is_dir())

    def test_running_stale_and_connected_work_escalate(self) -> None:
        """Actual active waves, stale children and downstream work stay visibly unresolved."""
        for provider in self.providers:
            provider.success("begin-wave")
            self.assertIn("systemMessage", self.stop(provider))
            provider.success("record-wave", json.dumps(provider.launch("stale")))
            self.assertIn("systemMessage", self.stop(provider))

    def test_completed_graph_artifact_failure_is_repair_not_escalation(self) -> None:
        """Completion evidence failures stay blocked without an unrelated approval request."""
        for provider in self.providers:
            provider.finish_wave()
            provider.artifacts()
            provider.path.with_name("evals.json").unlink()
            self.assertNotIn("systemMessage", self.stop(provider, "LOOP-STOP: complete"))


if __name__ == "__main__":
    unittest.main()
