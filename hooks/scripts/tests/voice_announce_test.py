#!/usr/bin/env python3
"""Verify observe-only speech, native-loop detection, and per-kind debounce."""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


class VoiceAnnounceTests(HookTestCase):
    """Keep optional speech asynchronous, deduplicated, and lifecycle-specific."""

    def setUp(self) -> None:
        """Install a Python speech recorder without invoking real system audio."""
        super().setUp()
        self.binary = self.directory / "bin"
        self.binary.mkdir()
        self.say_log = self.directory / "say.log"
        stub = self.binary / "say"
        stub.write_text(
            f"#!{sys.executable}\nimport os,sys,time\n"
            "time.sleep(float(os.environ.get('SAY_DELAY','0')))\n"
            "with open(os.environ['SAY_LOG'],'a') as f:f.write(' '.join(sys.argv[1:])+'\\n')\n"
        )
        stub.chmod(0o755)
        self.environment.update(
            {"PATH": str(self.binary) + os.pathsep + os.environ["PATH"], "SAY_LOG": str(self.say_log)}
        )

    def spoken(self, expected: int = 1) -> list[str]:
        """Poll bounded asynchronous output without hiding unexpected extra calls."""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            lines = self.say_log.read_text().splitlines() if self.say_log.exists() else []
            if len(lines) >= expected:
                return lines
            time.sleep(0.02)
        return []

    def test_all_categories_and_noncategory_stall(self) -> None:
        """Each category uses the original phrase, while unknown declarations mean stall."""
        cases = {
            "complete": "Loop complete.",
            "approval-gate": "Loop is waiting on you.",
            "awaiting-input": "Loop is waiting on you.",
            "hard-stop": "Loop has hit a hard stop.",
            "unknown": "Loop may have stalled.",
            "": "Loop may have stalled.",
        }
        self.progress()
        for category, phrase in cases.items():
            self.say_log.unlink(missing_ok=True)
            payload = self.payload(self.transcript(f"LOOP-STOP: {category}"))
            result = self.run_hook("voice_announce", payload, CLAUDE_VOICE_DEBOUNCE_SECONDS="0")
            self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
            self.assertEqual(self.spoken(), [phrase])

    def test_inactive_and_empty_output_are_silent(self) -> None:
        """Missing transcript, non-loop, completed ownership, loop guard, and no text pass silently."""
        for payload in ({}, self.payload(self.transcript("hello", 0))):
            self.assertEqual(self.run_hook("voice_announce", payload).returncode, 0)
        self.progress("complete", 1)
        payload = self.payload(self.transcript("LOOP-STOP: complete"))
        self.run_hook("voice_announce", payload)
        payload["stop_hook_active"] = True
        self.run_hook("voice_announce", payload)
        self.progress()
        self.run_hook("voice_announce", self.payload(self.transcript()))
        self.assertFalse(self.say_log.exists())
        self.assertIn("reason=extract_failed", (self.directory / "discipline.log").read_text())

    def test_debounce_is_per_kind_and_expiry_releases(self) -> None:
        """Immediate same-kind repetition suppresses while other kinds and expired markers speak."""
        path = self.progress()
        payload = self.payload(self.transcript("LOOP-STOP: complete"))
        self.run_hook("voice_announce", payload)
        self.assertEqual(len(self.spoken()), 1)
        self.run_hook("voice_announce", payload)
        self.assertEqual(len(self.spoken()), 1)
        self.run_hook("voice_announce", self.payload(self.transcript("LOOP-STOP: awaiting-input")))
        self.assertEqual(len(self.spoken(2)), 2)
        (path.parent / "voice_announce_complete.last").write_text("1")
        self.run_hook("voice_announce", self.payload(self.transcript("LOOP-STOP: complete")))
        self.assertEqual(len(self.spoken(3)), 3)

    def test_missing_speech_and_unwritable_marker_still_allow(self) -> None:
        """Infrastructure failure does not prevent stop and is attributed in the audit log."""
        path = self.progress()
        payload = self.payload(self.transcript("LOOP-STOP: complete"))
        self.assertEqual(self.run_hook("voice_announce", payload, PATH="/nonexistent").returncode, 0)
        self.assertIn("reason=no_say_binary", (self.directory / "discipline.log").read_text())
        marker = path.parent / "voice_announce_waiting.last"
        marker.mkdir()
        self.run_hook("voice_announce", self.payload(self.transcript("LOOP-STOP: awaiting-input")))
        self.assertEqual(self.spoken(), ["Loop is waiting on you."])
        self.assertIn("debounce_write_failed", (self.directory / "discipline.log").read_text())

    def test_native_asynchronous_child_and_malformed_transcript(self) -> None:
        """Speech is detached and malformed trailing records do not hide a valid declaration."""
        path = self.transcript("LOOP-STOP: complete")
        path.write_text(path.read_text() + '{"broken"\n' + json.dumps("scalar") + "\n")
        self.progress()
        start = time.monotonic()
        result = self.run_hook("voice_announce", self.payload(path), SAY_DELAY="1")
        self.assertEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - start, 0.9)
        self.assertEqual(self.spoken(), ["Loop complete."])


if __name__ == "__main__":
    unittest.main()
