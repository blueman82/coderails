#!/usr/bin/env python3
"""Pin the worker containment gate: in-process loop-worker dispatch when a sandboxed launch is available."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_evidence import ENVELOPE_KEY
from hooks.scripts.tests.receipt_hook_case import ReceiptHookCase
from hooks.scripts.tests.receipt_test_support import signed_receipt, store
from scripts import action_receipt_cli
from scripts.lib import action_receipt as ar
from scripts.sandbox import containment

HOOK = "worker_containment_gate"
HOOKS_JSON = Path(__file__).resolve().parents[2] / "hooks.json"
SRT = ".npm/_npx/abc/node_modules/@anthropic-ai/sandbox-runtime/package.json"


class GateCase(ReceiptHookCase):
    """A repo, an owner key, a graph-bound session and a fully provisioned sandbox (all under temp dirs)."""

    def setUp(self) -> None:
        """Provision tools on a private PATH, the pinned srt cache and the worker credential."""
        super().setUp()
        tools = self.directory / "tools"
        tools.mkdir()
        for name in ("sandbox-exec", "bwrap", "rg", "npx"):
            (tools / name).write_text("#!/bin/sh\n")
            (tools / name).chmod(0o755)
        for name in ("git", "ssh-keygen"):  # the only real binaries the gate needs besides the faked sandbox tools
            (tools / name).symlink_to(shutil.which(name) or name)
        self.tools = tools
        self.environment = self.environment | {"PATH": str(tools)}
        home = self.directory / "home"
        (home / SRT).parent.mkdir(parents=True)
        (home / SRT).write_text(json.dumps({"version": containment.SRT_VERSION}))
        self.credential = home / ".coderails/worker_credential"
        self.credential.parent.mkdir(parents=True, exist_ok=True)
        self.credential.write_text("ANTHROPIC_API_KEY=sk-fixture\n")
        self.credential.chmod(0o600)
        self.state(["src/**"])

    def state(self, manifest: list[str] | None, graph: bool = True, session: str = "s1") -> None:
        """Write progress.json for unit 4 with the given manifest."""
        unit: dict[str, Any] = {"status": "pending"}
        if manifest is not None:
            unit["manifest"] = manifest
        path = self.loop / "-fixture" / session / "progress.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"session_id": session, "work_units": {"4": unit}, **({"graph": {}} if graph else {})})
        )

    def dispatch(self, role: str = "coderails:loop-worker") -> dict[str, Any]:
        """An Agent PreToolUse payload carrying a graph envelope for unit 4."""
        owner = {"session_id": "s1", "loop_id": "l1", "revision": 1, "wave_id": "w1", "node_id": "U3[4]"}
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "cwd": str(self.repo),
            "tool_name": "Agent",
            "tool_input": {"subagent_type": role, "prompt": f"{ENVELOPE_KEY}={json.dumps(owner)}\nbuild"},
        }

    def ack(self, rid: str = "ack1", **over: object) -> None:
        """Store an owner-signed worker_fallback receipt for unit 4 on the fixture repo."""
        bind = containment.fallback_binding(str(self.repo))
        store(
            self.loop,
            signed_receipt(
                self.key,
                containment.ACK_KIND,
                containment.ack_command("4"),
                str(self.repo),
                "main",
                bind,
                "s1",
                None,
                receipt_id=rid,
                **over,
            ),
            "s1",
        )


class GateTests(GateCase):
    """Allow low risk, deny high risk without an owner acknowledgement, leave everything else alone."""

    def test_low_risk_unit_is_allowed_and_traced(self) -> None:
        """(d) Sandbox ON, loop-worker in process, manifest avoids the protected trees: allowed with a trace row."""
        self.assertFalse(self.denied(HOOK, self.dispatch()))
        self.assertEqual(self.reasons(), ["containment_fallback_low_risk"])

    def test_high_risk_needs_acknowledgement_then_replay_is_denied(self) -> None:
        """(d) A manifest touching hooks/ is denied; a signed worker_fallback receipt allows exactly once."""
        self.state(["hooks/scripts/x.py"])
        self.assertTrue(self.denied(HOOK, self.dispatch()))
        self.ack()
        self.assertFalse(self.denied(HOOK, self.dispatch()))
        self.assertTrue(self.denied(HOOK, self.dispatch()))
        self.assertEqual(
            self.reasons(), ["containment_ack_required", "containment_ack_receipt", "containment_ack_required"]
        )

    def test_unknown_manifest_is_high_risk_and_foreign_receipts_do_not_ack(self) -> None:
        """No manifest cannot prove low risk; an agent-signed, unsigned or other-unit receipt does not acknowledge."""
        self.state(None)
        self.assertTrue(self.denied(HOOK, self.dispatch()))
        self.ack("agent", signature=None)
        self.assertTrue(self.denied(HOOK, self.dispatch()))
        bind = containment.fallback_binding(str(self.repo))
        store(
            self.loop,
            signed_receipt(
                self.agent_key,
                containment.ACK_KIND,
                containment.ack_command("4"),
                str(self.repo),
                "main",
                bind,
                "s1",
                None,
                receipt_id="mine",
            ),
            "s1",
        )
        store(
            self.loop,
            signed_receipt(
                self.key,
                containment.ACK_KIND,
                containment.ack_command("9"),
                str(self.repo),
                "main",
                bind,
                "s1",
                None,
                receipt_id="unit9",
            ),
            "s1",
        )
        self.assertTrue(self.denied(HOOK, self.dispatch()))

    def test_untouched_cases(self) -> None:
        """Non-graph session, sandbox_workers false, fallback mode, another role or tool: no verdict and no trace."""
        self.state(["hooks/x.py"], graph=False)
        self.assertFalse(self.denied(HOOK, self.dispatch()))
        self.state(["hooks/x.py"])
        self.assertFalse(self.denied(HOOK, self.dispatch("coderails:spec-reviewer")))
        self.assertFalse(self.denied(HOOK, self.dispatch() | {"tool_name": "Bash"}))
        self.credential.unlink()  # mode fallback: worker_credential_missing
        self.assertFalse(self.denied(HOOK, self.dispatch()))
        self.credential.parent.joinpath("worker_credential").write_text("ANTHROPIC_API_KEY=sk\n")
        self.credential.chmod(0o600)
        self.assertTrue(self.denied(HOOK, self.dispatch()))  # control: provisioned again, denied
        (self.repo / ".coderails").mkdir(exist_ok=True)
        (self.repo / ".coderails/workflow.config.yaml").write_text("sandbox_workers: false\n")
        self.assertFalse(self.denied(HOOK, self.dispatch()))
        self.assertEqual(self.reasons(), ["containment_ack_required"])

    def test_gate_is_registered_so_the_denial_reaches_the_session(self) -> None:
        """Without the hooks.json entry the denial above never runs and the dispatch is allowed."""
        hooks = json.loads((HOOKS_JSON).read_text())["hooks"]["PreToolUse"]
        registered = [item["command"] for group in hooks if group["matcher"] == "Agent" for item in group["hooks"]]
        self.assertTrue(any(f"{HOOK}.py" in command for command in registered), registered)

    def test_own_error_fails_open(self) -> None:
        """A torn progress.json never blocks a session."""
        path = next(self.loop.glob("*/s1/progress.json"))
        path.write_text("{")
        self.assertFalse(self.denied(HOOK, self.dispatch()))


class AckCliTests(GateCase):
    """The owner mints the acknowledgement with the existing receipt CLI (new kind worker_fallback)."""

    def test_cli_mints_a_receipt_the_gate_accepts(self) -> None:
        """approve-action --kind worker_fallback binds repository + branch + base sha and the gate consumes it."""
        self.state(["hooks/x.py"])
        signers = self.directory / "home/.coderails/keys/receipt_signers"
        with (
            mock.patch.dict(
                os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop), "HOME": str(self.directory / "home")}
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = action_receipt_cli.main(
                [
                    "approve-action",
                    "--session",
                    "s1",
                    "--kind",
                    containment.ACK_KIND,
                    "--command",
                    containment.ack_command("4"),
                    "--cwd",
                    str(self.repo),
                    "--key",
                    str(self.key),
                    "--signers",
                    str(signers),
                ],
                tty_ok=lambda: True,
            )
        self.assertEqual(code, 0)
        receipt = json.loads(next((self.loop / "s1/receipts").glob("*.json")).read_text())
        self.assertEqual(receipt["action"], "worker_fallback")
        bind = containment.fallback_binding(str(self.repo))
        self.assertEqual(receipt["artifact_sha"], (bind or {}).get("sha"))
        self.assertIn(receipt["receipt_id"], [p.stem for p in (self.loop / "s1/receipts").glob("*.json")])
        self.assertFalse(self.denied(HOOK, self.dispatch()))
        self.assertTrue(ar.is_consumed(next((self.loop / "s1/receipts").glob("*.json"))))
