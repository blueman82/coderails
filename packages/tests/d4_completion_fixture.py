"""Exercise D4 orders through each provider's real native completion command."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hooks.scripts.tests.lib import assembled_retro
from packages.tests.provider_fixture import Provider


class NativeOrdersFixture(unittest.TestCase):
    """Provide isolated provider checkouts and real orders commands."""

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
            cwd=provider.checkout,
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
        code, prepared = self.orders(provider, "prepare", "--loop", "fixture-loop")
        self.assertEqual(code, 0, prepared)
        assembled_retro.write(provider.path.parent, provider.session)

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
