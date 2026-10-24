"""Migrate reviewed pre-D4 complete loops without changing historical progress."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hooks.scripts.tests.lib import claude_transcript_fixture as claude
from packages.tests.provider_fixture import Provider


class LegacyAdmission(unittest.TestCase):
    """Keep old completion evidence separate from the new D4 lifecycle."""

    def setUp(self) -> None:
        """Create independent native provider repos."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def verify(self, provider: Provider) -> subprocess.CompletedProcess[str]:
        """Ask each provider's own native completion verifier."""
        args = ["--session", provider.session]
        if provider.name == "codex":
            for name in ("evals", "proof", "retro"):
                args.extend(["--" + name, str(provider.path.with_name(name + ".json"))])
            args.extend(["--transcript", str(provider.parent)])
        return provider.call("verify-completion", *args)

    def command(self, provider: Provider, reason: str) -> list[str]:
        """Bind one operator command to the exact current completed progress bytes."""
        return [
            sys.executable,
            str(provider.plugin / "scripts/lib/orders_completion.py"),
            "admit-legacy",
            "--dir",
            str(provider.path.parent.parent),
            "--session",
            provider.session,
            "--loop",
            provider.read()["loop_id"],
            "--progress-sha256",
            hashlib.sha256(provider.path.read_bytes()).hexdigest(),
            "--reason",
            reason,
        ]

    def old_complete(self, provider: Provider) -> None:
        """Represent one genuine pre-D4 saved completion with native wave artifacts."""
        provider.finish_wave()
        provider.artifacts()
        state = provider.read()
        state["status"] = "complete"
        if provider.name == "codex":
            state["completion"] = {"revision": state["revision"]}
            state["revision"] += 1
        provider.write(state)

    def test_old_complete_requires_exact_reviewed_admission(self) -> None:
        """Both native guards accept a reviewed old graph without ticking it."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.old_complete(provider)
                original = provider.path.read_bytes()
                self.assertNotEqual(self.verify(provider).returncode, 0)
                self.assertEqual(provider.complete().returncode, 3)
                self.assertEqual(provider.path.read_bytes(), original)
                command = self.command(provider, "Reviewed the pre-D4 completed graph and its retained evidence.")
                wrong = command.copy()
                wrong[wrong.index("--progress-sha256") + 1] = "0" * 64
                refused = subprocess.run(wrong, cwd=provider.home, env=provider.environment, capture_output=True)
                self.assertNotEqual(refused.returncode, 0)
                accepted = subprocess.run(command, cwd=provider.home, env=provider.environment, capture_output=True)
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertEqual(provider.path.read_bytes(), original)
                self.assertEqual(self.verify(provider).returncode, 0)
                self.assertEqual(provider.complete().returncode, 0)
                if provider.name == "claude":
                    claude.append(
                        provider.parent,
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}
                                ]
                            },
                        },
                    )
                guard = "loop_state_guard" if provider.name == "claude" else "graph_completion_guard"
                checked = provider.hook(
                    guard,
                    {
                        "session_id": provider.session,
                        "cwd": str(provider.home),
                        "transcript_path": str(provider.parent),
                        "last_assistant_message": "LOOP-STOP: complete",
                    },
                )
                self.assertNotIn("block", checked.stdout + checked.stderr)
                ledger = provider.path.parent.parent / "orders.json"
                if ledger.exists():
                    self.assertEqual(json.loads(ledger.read_text())["ticked_loops"], [])
                provider.path.write_bytes(original + b" ")
                self.assertNotEqual(self.verify(provider).returncode, 0)

    def test_new_completion_cannot_use_legacy_admission(self) -> None:
        """A prepared new loop cannot claim the historical no-aging exception."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.finish_wave()
                provider.artifacts()
                self.assertEqual(provider.complete().returncode, 0)
                command = self.command(provider, "This must be refused because D4 evidence exists.")
                refused = subprocess.run(command, cwd=provider.home, env=provider.environment, capture_output=True)
                self.assertNotEqual(refused.returncode, 0)

    def test_another_logical_loops_teardown_does_not_block_admission(self) -> None:
        """A session can hold old orders events for a different logical loop."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.old_complete(provider)
                log = provider.path.with_name("teardown.jsonl")
                other = {
                    "step": "orders_prepared",
                    "session_id": provider.session,
                    "loop_id": "later-logical-loop",
                    "binding": {"session_id": provider.session, "loop_id": "later-logical-loop"},
                    "evidence_sha256": "0" * 64,
                }
                log.write_text(json.dumps(other) + "\n")
                command = self.command(provider, "Reviewed the old loop despite a later loop in this session.")
                accepted = subprocess.run(command, cwd=provider.home, env=provider.environment, capture_output=True)
                self.assertEqual(accepted.returncode, 0, accepted.stdout)
                self.assertEqual(self.verify(provider).returncode, 0)
                target = {**other, "loop_id": provider.read()["loop_id"]}
                log.write_text(json.dumps(other) + "\n" + json.dumps(target) + "\n")
                self.assertNotEqual(self.verify(provider).returncode, 0)
