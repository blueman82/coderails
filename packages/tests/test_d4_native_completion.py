"""Exercise D4 orders through each provider's real native completion command."""

from __future__ import annotations

import json
import subprocess
import sys

from hooks.scripts.tests.lib import assembled_retro
from hooks.scripts.tests.lib import claude_transcript_fixture as claude
from packages.tests.d4_completion_fixture import NativeOrdersFixture
from packages.tests.provider_fixture import Provider


class NativeOrdersCompletion(NativeOrdersFixture):
    """Completion must apply orders after the native graph save and support retry."""

    def test_completion_ticks_renders_and_retries_once(self) -> None:
        """Both native commands apply one completed loop, then resume without a second tick."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                self.assertEqual(self.orders(provider, "tick", "--loop", "fixture-loop")[0], 2)
                complete = provider.complete()
                self.assertEqual(complete.returncode, 0, complete.stderr)
                ledger_path = provider.path.parent.parent / "orders.json"
                ledger = json.loads(ledger_path.read_text())
                self.assertEqual(len(ledger["ticked_loops"]), 1)
                self.assertEqual(len(ledger["orders"][0]["evidence"]), 1)
                self.assertTrue((provider.path.parent.parent / "standing-orders.md").is_file())
                retry = provider.complete()
                self.assertEqual(retry.returncode, 0, retry.stderr)
                after = json.loads(ledger_path.read_text())
                self.assertEqual(after["ticked_loops"], ledger["ticked_loops"])
                self.assertEqual(after["orders"][0]["evidence"], ledger["orders"][0]["evidence"])
                self.assertEqual(self.verify(provider).returncode, 0)

    def test_missing_or_stale_teardown_blocks_native_verify(self) -> None:
        """Both providers refuse missing preparation and a changed generated view after completion."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                self.assertEqual(provider.complete().returncode, 0)
                self.assertEqual(self.verify(provider).returncode, 0)
                view = provider.path.parent.parent / "standing-orders.md"
                original = view.read_bytes()
                view.chmod(0o644)
                view.write_text("stale generated view")
                view.chmod(0o444)
                self.assertNotEqual(self.verify(provider).returncode, 0)
                view.chmod(0o644)
                view.write_bytes(original)
                view.chmod(0o444)
                self.assertEqual(self.verify(provider).returncode, 0)
                prepared = next(provider.path.parent.glob("orders-prepared-*.json"))
                prepared.unlink()
                self.assertNotEqual(self.verify(provider).returncode, 0)

    def test_failed_native_save_never_ticks(self) -> None:
        """A failed graph replacement leaves both provider ledgers without any completion tick."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                before = provider.path.read_bytes()
                failed = self.fault(provider, "save")
                self.assertEqual(failed.returncode, 0, failed.stderr)
                expected = "graph lock or atomic update failed" if provider.name == "claude" else "disk-full"
                self.assertIn(expected, failed.stdout)
                self.assertEqual(provider.path.read_bytes(), before)
                self.assertEqual(self.orders(provider, "tick", "--loop", "fixture-loop")[0], 2)

    def test_changed_preparation_refuses_before_native_save(self) -> None:
        """Each provider rechecks staged source under its graph lock and leaves ages unchanged."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                before = provider.path.read_bytes()
                changed = self.fault(provider, "race")
                self.assertEqual(changed.returncode, 0, changed.stderr)
                self.assertTrue(
                    "order_source_mismatch" in changed.stdout or "retro_steps_missing" in changed.stdout,
                    changed.stdout,
                )
                self.assertEqual(provider.path.read_bytes(), before)
                self.assertEqual(self.orders(provider, "tick", "--loop", "fixture-loop")[0], 2)

    def test_stop_guards_block_pending_teardown(self) -> None:
        """Both native Stop paths refuse stale views after validated graph completion."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
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
                    marked = subprocess.run(
                        [
                            sys.executable,
                            str(provider.plugin / "hooks/scripts/lib/loop_state_common.py"),
                            "mark-complete",
                            str(provider.home),
                            provider.session,
                        ],
                        cwd=provider.home,
                        env=provider.environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(marked.returncode, 0, marked.stderr)
                    self.assertEqual(provider.read()["completed_marker"], 1)
                name = "loop_state_guard" if provider.name == "claude" else "graph_completion_guard"
                payload = {
                    "session_id": provider.session,
                    "cwd": str(provider.home),
                    "transcript_path": str(provider.parent),
                    "last_assistant_message": "",
                }
                valid = provider.hook(name, payload)
                self.assertNotIn("block", valid.stdout + valid.stderr)
                view = provider.path.parent.parent / "standing-orders.md"
                view.chmod(0o644)
                view.write_text("stale generated view")
                view.chmod(0o444)
                refused = provider.hook(name, payload)
                if provider.name == "claude":
                    self.assertEqual(refused.returncode, 2)
                    self.assertIn("Standing-orders teardown", refused.stderr)
                else:
                    self.assertEqual(json.loads(refused.stdout)["decision"], "block")

    def test_native_completed_loops_age_and_decay_once(self) -> None:
        """Five distinct native completions decay an old order; retries do not advance it."""
        for initial in self.providers:
            with self.subTest(provider=initial.name):
                self.ready(initial)
                self.assertEqual(initial.complete().returncode, 0)
                repo_dir = initial.path.parent.parent
                for number in range(1, 6):
                    cycle_root = initial.home.parent / f"{initial.name}-cycle-{number}"
                    cycle_root.mkdir()
                    cycle = Provider(cycle_root, initial.name)
                    cycle.checkout = initial.checkout
                    cycle.path = repo_dir / cycle.session / "progress.json"
                    cycle.path.parent.mkdir(exist_ok=True)
                    state = cycle.state()
                    state["loop_id"] = f"logical-cycle-{number}"
                    cycle.write(state)
                    (cycle.path.parent / "teardown.jsonl").unlink(missing_ok=True)
                    cycle.freeze()
                    cycle.finish_wave()
                    cycle.artifacts()
                    code, prepared = self.orders(cycle, "prepare", "--loop", state["loop_id"])
                    self.assertEqual(code, 0, prepared)
                    assembled_retro.write(cycle.path.parent, cycle.session)
                    self.assertEqual(cycle.complete().returncode, 0)
                    self.assertEqual(cycle.complete().returncode, 0)
                    ledger = json.loads((repo_dir / "orders.json").read_text())
                    row = ledger["orders"][0]
                    self.assertEqual(row["loops_since_recurrence"], number)
                    self.assertEqual(row["status"], "decayed" if number == 5 else "active")
                    self.assertEqual(len(ledger["ticked_loops"]), number + 1)

    def test_degraded_memory_keeps_completed_graph_pending(self) -> None:
        """An unsupported store mode cannot turn ledger text into a current cited lesson."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                (provider.home / ".coderails/workflow.config.yaml").write_text("memory:\n  backend: invalid\n")
                completion = provider.complete()
                self.assertEqual(completion.returncode, 3, completion.stderr)
                payload = json.loads(completion.stdout)
                self.assertTrue(payload["pending_teardown"])
                self.assertEqual(payload["reason_code"], "memory_backend_invalid")
                self.assertEqual(provider.read()["status"], "complete")
                ledger = json.loads((provider.path.parent.parent / "orders.json").read_text())
                self.assertEqual(len(ledger["ticked_loops"]), 1)
                verified = self.verify(provider)
                self.assertNotEqual(verified.returncode, 0)
                self.assertIn("memory_backend_invalid", verified.stdout + verified.stderr)
                (provider.home / ".coderails/workflow.config.yaml").write_text("memory:\n  backend: off\n")
                self.assertEqual(provider.complete().returncode, 0)
                self.assertEqual(self.verify(provider).returncode, 0)
                saved = json.loads((provider.path.parent.parent / "orders.json").read_text())
                self.assertEqual(len(saved["ticked_loops"]), 1)

    def test_render_refusal_reason_survives_later_verification(self) -> None:
        """A current retired Muninn API refusal remains visible after native completion."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                failed = self.fault(provider, "render_old")
                self.assertEqual(failed.returncode, 0, failed.stderr)
                self.assertEqual(json.loads(failed.stdout)["reason_code"], "muninn_old_ledger")
                self.assertEqual(provider.read()["status"], "complete")
                verified = self.verify(provider)
                self.assertNotEqual(verified.returncode, 0)
                self.assertIn("muninn_old_ledger", verified.stdout + verified.stderr)

    def test_render_input_change_blocks_receipt_until_retry(self) -> None:
        """A ledger update after rendering cannot certify old views for the new ledger."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                raced = self.fault(provider, "render_race")
                self.assertEqual(raced.returncode, 0, raced.stderr)
                result = json.loads(raced.stdout)
                self.assertEqual(result["exit_code"], 3)
                self.assertEqual(result["reason_code"], "order_source_mismatch")
                teardown = provider.path.with_name("teardown.jsonl")
                rows = [json.loads(line) for line in teardown.read_text().splitlines()]
                rendered = [row for row in rows if row["step"] == "orders_rendered"]
                self.assertEqual(rendered, [])
                self.assertNotEqual(self.verify(provider).returncode, 0)
                self.assertEqual(provider.complete().returncode, 0)
                self.assertEqual(self.verify(provider).returncode, 0)
                rows = [json.loads(line) for line in teardown.read_text().splitlines()]
                self.assertEqual(len([row for row in rows if row["step"] == "orders_rendered"]), 1)

    def test_second_render_blocks_first_receipt(self) -> None:
        """A second render from changed currentness cannot certify the first render."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.ready(provider)
                raced = self.fault(provider, "render_again")
                self.assertEqual(raced.returncode, 0, raced.stderr)
                result = json.loads(raced.stdout)
                self.assertEqual(result["exit_code"], 3, result)
                self.assertEqual(result["reason_code"], "order_source_mismatch")
                teardown = provider.path.with_name("teardown.jsonl")
                rows = [json.loads(line) for line in teardown.read_text().splitlines()]
                self.assertFalse(any(row["step"] == "orders_rendered" for row in rows))
                self.assertEqual(provider.complete().returncode, 0)
                self.assertEqual(self.verify(provider).returncode, 0)
                rows = [json.loads(line) for line in teardown.read_text().splitlines()]
                self.assertEqual(sum(row["step"] == "orders_rendered" for row in rows), 1)
