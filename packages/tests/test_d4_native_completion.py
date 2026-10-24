"""Exercise D4 orders through each provider's real native completion command."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hooks.scripts.tests.lib import claude_transcript_fixture as claude
from packages.tests.provider_fixture import Provider


class NativeOrdersCompletion(unittest.TestCase):
    """Completion must apply orders after the native graph save and support retry."""

    def setUp(self) -> None:
        """Give each provider its own graph, repository config, and order store."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def orders(self, provider: Provider, *args: str) -> tuple[int, dict[str, Any]]:
        """Call the installed provider's real D4 CLI against its graph owner."""
        process = subprocess.run(
            [
                sys.executable,
                str(provider.plugin / "scripts/lib/orders.py"),
                "--dir",
                str(provider.path.parent.parent),
                "--session",
                provider.session,
                *args,
            ],
            cwd=provider.home,
            env=provider.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        return process.returncode, json.loads(process.stdout)

    def ready(self, provider: Provider) -> None:
        """Create real native completion evidence and one prepared D4 observation."""
        provider.finish_wave()
        provider.artifacts()
        retro = provider.read("retro.json")
        provider.write({**retro, "schema_version": 2}, "retro.json")
        code, record = self.orders(
            provider,
            "record",
            "--failure-mode",
            "d4-native-case",
            "--lesson",
            "Keep the cited lesson.",
            "--loop",
            "fixture-loop",
        )
        self.assertEqual(code, 0, record)

    def verify(self, provider: Provider) -> subprocess.CompletedProcess[str]:
        """Run the provider's native read-only completion verifier."""
        args = ["--session", provider.session]
        if provider.name == "codex":
            for name in ("evals", "proof", "retro"):
                args.extend(["--" + name, str(provider.path.with_name(name + ".json"))])
            args.extend(["--transcript", str(provider.parent)])
        return provider.call("verify-completion", *args)

    @staticmethod
    def _fault_script() -> str:
        return """
import json
import sys
from pathlib import Path
from unittest import mock
plugin, name, source, session, transcript, kind = sys.argv[1:]
path = Path(source)
sys.path.insert(0, plugin)
sys.path.insert(0, str(Path(plugin) / 'skills/agentic-loop/scripts'))
if name == 'claude':
    from hooks.scripts.lib import graph_dispatch as completion
    orders = completion.orders_completion
    target = 'hooks.scripts.lib.loop_state_common.os.replace'
    def invoke():
        return completion.complete(path, session)
else:
    import graph_completion as completion
    orders = completion._orders()
    target = 'graph_completion._write'
    def invoke():
        return completion.complete(path, session, path.with_name('evals.json'), path.with_name('proof.json'),
                                   path.with_name('retro.json'), Path(transcript))
if kind == 'save':
    context = mock.patch(target, side_effect=OSError('disk-full'))
elif kind == 'render_old':
    original = orders._call
    def degraded(path, session, command, loop):
        if command == 'render':
            return 3, {'degraded': 'muninn_old_ledger'}
        return original(path, session, command, loop)
    context = mock.patch.object(orders, '_call', side_effect=degraded)
elif kind == 'render_race':
    from scripts.lib import orders_ledger as ol
    original = orders._call
    def raced(path, session, command, loop):
        code, payload = original(path, session, command, loop)
        if command == 'render' and code == 0:
            repo = path.parent.parent
            with orders.order_cli.locked(repo):
                ledger = ol.open_ledger(repo)
                advanced = ol.tick(ledger, 'another-loop', ol.now_iso(), session_id='another-session')
                ol.save(repo / 'orders.json', advanced['ledger'])
        return code, payload
    context = mock.patch.object(orders, '_call', side_effect=raced)
elif kind == 'render_again':
    import argparse
    from scripts.lib import orders_ledger as ol
    original = orders._call
    def raced(path, session, command, loop):
        code, payload = original(path, session, command, loop)
        if command == 'render' and code == 0:
            repo = path.parent.parent
            cli = orders.order_cli
            ledger = ol.open_ledger(repo)
            current = cli.lessons.joined(ledger, include_decayed=True, session=session)
            current['lessons'][0]['text'] = 'A second current lesson.'
            with mock.patch.object(cli.lessons, 'joined', return_value=current):
                _, second = cli.cmd_render(argparse.Namespace(session=session), repo)
            assert second == 0
        return code, payload
    context = mock.patch.object(orders, '_call', side_effect=raced)
else:
    original = orders.prepare
    def changed(*args):
        digest = original(*args)
        prepared = orders.lifecycle.preparation_path(path.parent, args[2])
        value = json.loads(prepared.read_text())
        value['binding']['progress_sha256'] = '0' * 64
        prepared.write_text(json.dumps(value))
        return digest
    context = mock.patch.object(orders, 'prepare', side_effect=changed)
with context:
    try:
        result = invoke()
        if kind in ('render_old', 'render_race', 'render_again'):
            print(json.dumps(result))
            sys.exit(0)
    except Exception as error:
        print(type(error).__name__, str(error))
        sys.exit(0)
sys.exit(1)
"""

    def fault(self, provider: Provider, kind: str) -> subprocess.CompletedProcess[str]:
        """Inject one file failure or post-prepare mutation into the actual native function."""
        return subprocess.run(
            [
                sys.executable,
                "-c",
                self._fault_script(),
                str(provider.plugin),
                provider.name,
                str(provider.path),
                provider.session,
                str(provider.parent),
                kind,
            ],
            cwd=provider.home,
            env=provider.environment,
            capture_output=True,
            text=True,
            check=False,
        )

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
                self.assertIn("order_source_mismatch", changed.stdout)
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
                    cycle.path = repo_dir / cycle.session / "progress.json"
                    cycle.path.parent.mkdir(exist_ok=True)
                    state = cycle.state()
                    state["loop_id"] = f"logical-cycle-{number}"
                    cycle.write(state)
                    cycle.freeze()
                    cycle.finish_wave()
                    cycle.artifacts()
                    retro = cycle.read("retro.json")
                    cycle.write({**retro, "schema_version": 2}, "retro.json")
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
