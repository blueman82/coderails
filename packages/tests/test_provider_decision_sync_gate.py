"""A D decision in its first locked save blocks both native provider continuations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from packages.tests.provider_fixture import Provider
from scripts.lib import decision_record

NODE = "U3[1]"


class DecisionSyncGateTests(unittest.TestCase):
    """Use one authentic hashed D row with Muninn still marked syncing."""

    def setUp(self) -> None:
        """Give each real CLI an isolated graph and repository."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def provider(self, name: str, suffix: str) -> Provider:
        """Create one native provider fixture without sharing a state file."""
        root = self.root / suffix
        root.mkdir()
        return Provider(root, name)

    def pending(self, provider: Provider, state: dict[str, Any]) -> None:
        """Persist exactly D's reachable state between its local append and Muninn sync."""
        result = decision_record.add_decision(
            state,
            provider.session,
            "implementation",
            "answer",
            state["loop_id"],
            state["revision"],
        )
        provider.write(result["state"])
        current = provider.read()
        self.assertEqual(current["decisions_absorbed"][0]["muninn"]["state"], "syncing")
        self.assertEqual(decision_record.verify_chain(current["decisions_absorbed"], 1), [])

    def finalized(self, provider: Provider, state: str) -> None:
        """Apply D's second locked transform to the isolated fixture."""
        current = provider.read()
        row = current["decisions_absorbed"][0]
        provider.write(
            decision_record.mark_synced(
                current,
                provider.session,
                current["loop_id"],
                row["row_sha256"],
                {"state": state, "reason_code": "ok", "id": "K1" if state == "written" else None},
            )
        )

    def test_pending_sync_refuses_authorization_without_mutation(self) -> None:
        """Normal and off-mode dispatch both refuse the issued native request."""
        for name in ("claude", "codex"):
            for mode in ("normal", "off"):
                with self.subTest(provider=name, mode=mode):
                    provider = self.provider(name, f"{name}-{mode}")
                    wave = provider.success("begin-wave")
                    dispatch = wave["dispatches"][0]
                    prompt = dispatch["prompt_prefix"] + "\n" + dispatch["prompt_sections"]
                    if mode == "off":
                        provider.environment["CODERAILS_GRAPH_DISPATCH"] = "off"
                    self.pending(provider, provider.read())
                    before = provider.path.read_bytes()
                    args: tuple[str, ...]
                    if name == "claude":
                        args = ("--prompt", prompt, "--subagent-type", "coderails:loop-worker")
                    else:
                        message = provider.home / "message.txt"
                        message.write_text(prompt, encoding="utf-8")
                        args = (
                            "--dispatch-id",
                            dispatch["dispatch_id"],
                            "--message-file",
                            str(message),
                            "--agent-type",
                            "loop-worker",
                            "--task-name",
                            dispatch["task_name"],
                        )
                    result = provider.call("authorize-dispatch", "--session", provider.session, *args)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("decision", result.stderr)
                    self.assertEqual(provider.path.read_bytes(), before)

    def test_pending_sync_refuses_stale_retry_without_mutation(self) -> None:
        """A stale node cannot consume another attempt before the D sync result is known."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.provider(name, name + "-retry")
                state = provider.read()
                state["graph"]["nodes"][NODE].update(
                    status="stale",
                    outcome="stale",
                    stale_check={"checked": True, "method": "inspection", "result": "absent"},
                )
                self.pending(provider, state)
                self.assertEqual(provider.success("inspect")["ready"], [])
                before = provider.path.read_bytes()
                result = provider.call(
                    "respawn-stale", "--session", provider.session, "--node", NODE, "--reason", "retry after check"
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("decision", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_final_sync_releases_stale_retry(self) -> None:
        """A final written or disabled D row permits the same retry."""
        for name in ("claude", "codex"):
            for final in ("written", "disabled"):
                with self.subTest(provider=name, final=final):
                    provider = self.provider(name, name + "-" + final)
                    state = provider.read()
                    state["graph"]["nodes"][NODE].update(
                        status="stale",
                        outcome="stale",
                        stale_check={"checked": True, "method": "inspection", "result": "absent"},
                    )
                    self.pending(provider, state)
                    self.finalized(provider, final)
                    result = provider.call(
                        "respawn-stale", "--session", provider.session, "--node", NODE, "--reason", "retry after check"
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
