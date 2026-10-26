"""Keep the prepared source timestamp stable through graph completion."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from packages.tests.provider_fixture import Provider

OLD_TIME = "2000-01-01T00:00:00+00:00"


class CompletionTimestamp(unittest.TestCase):
    """Exercise native completion with a timestamp bound to its prepared source."""

    def setUp(self) -> None:
        """Create one isolated graph for each provider."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def test_native_completion_crosses_progress_timestamp(self) -> None:
        """A completion save retains the timestamp bound to its prepared source."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.finish_wave()
                provider.artifacts()
                provider.write({**provider.read("retro.json"), "schema_version": 2}, "retro.json")
                provider.write({**provider.read(), "updated_at": OLD_TIME})
                record = subprocess.run(
                    [
                        sys.executable,
                        str(provider.plugin / "scripts/lib/orders.py"),
                        "--dir",
                        str(provider.path.parent.parent),
                        "--session",
                        provider.session,
                        "record",
                        "--failure-mode",
                        "timestamp-probe",
                        "--lesson",
                        "Keep this lesson.",
                        "--loop",
                        "fixture-loop",
                    ],
                    cwd=provider.home,
                    env=provider.environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(record.returncode, 0, record.stdout + record.stderr)
                complete = provider.complete()
                self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
                self.assertEqual(provider.read()["updated_at"], OLD_TIME)
                arguments = ["--session", provider.session]
                if provider.name == "codex":
                    for name in ("evals", "proof", "retro"):
                        arguments.extend(["--" + name, str(provider.path.with_name(name + ".json"))])
                    arguments.extend(["--transcript", str(provider.parent)])
                verify = provider.call("verify-completion", *arguments)
                self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_prepared_source_rejects_timestamp_rollback(self) -> None:
        """A prepared receipt cannot be used after the source timestamp changes."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.finish_wave()
                provider.artifacts()
                provider.write({**provider.read("retro.json"), "schema_version": 2}, "retro.json")
                command = [
                    sys.executable,
                    str(provider.plugin / "scripts/lib/orders.py"),
                    "--dir",
                    str(provider.path.parent.parent),
                    "--session",
                    provider.session,
                    "prepare",
                    "--loop",
                    "fixture-loop",
                ]
                first = subprocess.run(
                    command, cwd=provider.home, env=provider.environment, capture_output=True, text=True
                )
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                prepared = next(provider.path.parent.glob("orders-prepared-*.json"))
                before = prepared.read_bytes()
                provider.write({**provider.read(), "updated_at": OLD_TIME})
                second = subprocess.run(
                    command, cwd=provider.home, env=provider.environment, capture_output=True, text=True
                )
                self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("order_source_mismatch", second.stdout)
                self.assertEqual(prepared.read_bytes(), before)

    def test_explicit_fixture_path_rejects_foreign_graph(self) -> None:
        """The fixture path override still checks session and active wave identity."""
        from packages.tests import codex_fixture as codex

        provider = next(item for item in self.providers if item.name == "codex")
        provider.success("begin-wave")
        state = provider.read()
        foreign = provider.path.with_name("foreign-progress.json")
        foreign.write_text(json.dumps({**state, "session_id": "foreign"}))
        before = foreign.read_bytes()
        node_id = state["graph"]["active_wave"]["nodes"][0]
        with self.assertRaisesRegex(AssertionError, "one owned progress.json"):
            codex.dispatch_message(provider.parent, state, node_id, "foreign-probe", foreign)
        self.assertEqual(foreign.read_bytes(), before)
