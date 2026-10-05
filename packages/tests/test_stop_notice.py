"""Stop-block notice: state-keyed dedupe, automatic status, one bounded recovery attempt."""

from __future__ import annotations

import filecmp
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import stall_notice  # noqa: E402
from hooks.scripts.tests.lib.claude_transcript_fixture import append  # noqa: E402
from packages.tests.provider_fixture import Provider  # noqa: E402


class StopNoticeTests(unittest.TestCase):
    """Drive both providers' real Stop hooks."""

    def setUp(self) -> None:
        """Isolated claude and codex providers."""
        patch = mock.patch.dict("os.environ", {}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def stop(self, provider: Provider) -> str:
        """Run one Stop and return the systemMessage ('' when deduplicated)."""
        if provider.name == "claude":
            skill = {"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}
            append(provider.parent, {"type": "assistant", "message": {"content": [skill]}})
            append(provider.parent, {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}})
        payload = {
            "session_id": provider.session,
            "cwd": str(provider.home),
            "hook_event_name": "Stop",
            "transcript_path": str(provider.parent),
            "last_assistant_message": "done",
        }
        hook = "loop_stall_guard" if provider.name == "claude" else "graph_completion_guard"
        result = provider.hook(hook, payload)
        output: dict[str, Any] = json.loads(result.stdout) if result.stdout else {}
        return str(output.get("systemMessage", ""))

    def test_helper_copies_identical(self) -> None:
        """Both providers ship the same helper bytes."""
        left = ROOT / "hooks/scripts/lib/stall_notice.py"
        self.assertTrue(filecmp.cmp(left, ROOT / "packages/codex/hooks/scripts/lib/stall_notice.py", shallow=False))

    def test_key_changes_with_session_wave_hard_stop(self) -> None:
        """Each component changes the marker; identical state does not."""
        base = {"loop_id": "l", "revision": 3, "graph": {"active_wave": None, "hard_stop": None}}
        key = stall_notice.marker_name(base, "s")
        self.assertEqual(key, stall_notice.marker_name(json.loads(json.dumps(base)), "s"))
        self.assertNotEqual(key, stall_notice.marker_name(base, "other"))
        wave = {**base, "graph": {"active_wave": {"wave_id": "w1"}, "hard_stop": None}}
        self.assertNotEqual(key, stall_notice.marker_name(wave, "s"))
        stop = {**base, "graph": {"active_wave": None, "hard_stop": {"node": "A", "reason": "r"}}}
        self.assertNotEqual(key, stall_notice.marker_name(stop, "s"))

    def test_hard_stop_change_without_revision_bump_renotifies(self) -> None:
        """Same revision, new hard_stop: notice again; unchanged: silent."""
        for provider in self.providers:
            first = self.stop(provider)
            self.assertIn("ready to dispatch", first)
            self.assertIn("begin-wave", first)
            self.assertEqual(self.stop(provider), "")
            state = provider.read()
            state["graph"]["hard_stop"] = {"node": "U3[1]", "reason": "needs a human decision", "ts": "t"}
            provider.write(state)
            second = self.stop(provider)
            self.assertIn("waiting for human", second)
            self.assertIn("needs a human decision", second)
            self.assertEqual(self.stop(provider), "")

    def test_running_wave_runs_recover_once(self) -> None:
        """A running wave with no worker gets one recover-wave result in the notice."""
        for provider in self.providers:
            provider.success("begin-wave")
            first = self.stop(provider)
            self.assertIn("waiting for worker", first)
            self.assertIn("recover-wave", first)
            self.assertEqual(self.stop(provider), "")

    def graph_cli(self, provider: Provider) -> Path:
        """The provider's real graph.py."""
        return provider.plugin / "skills/agentic-loop/scripts/graph.py"

    def test_large_graph_status_not_truncated(self) -> None:
        """A 60-node graph still yields the compact status (summarize JSON is never cut)."""
        for provider in self.providers:
            value = provider.state()
            base = value["graph"]["nodes"]["U3[1]"]
            value["graph"]["nodes"] = {f"U3[{i}]": {**base, "label": f"Build unit {i}"} for i in range(1, 61)}
            provider.write(value)
            text = stall_notice.status_notice(self.graph_cli(provider), provider.path, provider.session)
            self.assertIn("Graph status:", text)

    def test_missing_graph_is_reported(self) -> None:
        """A missing graph.py never raises and says the status is unavailable."""
        provider = self.providers[0]
        text = stall_notice.status_notice(provider.home / "absent.py", provider.path, provider.session)
        self.assertIn("unavailable", text)

    def test_unexpired_lease_is_not_labelled_applied(self) -> None:
        """A healthy running wave reports that recover-wave did nothing."""
        for provider in self.providers:
            provider.success("begin-wave")
            os.environ.update(provider.environment)
            text = stall_notice.status_notice(self.graph_cli(provider), provider.path, provider.session)
            self.assertIn("did nothing", text)
            self.assertNotIn("applied", text)

    def test_foreign_session_is_refused(self) -> None:
        """A different session's recover-wave is shown as refused with its reason."""
        for provider in self.providers:
            provider.success("begin-wave")
            os.environ.update(provider.environment)
            text = stall_notice.status_notice(self.graph_cli(provider), provider.path, "intruder")
            self.assertIn("refused", text)
            self.assertIn("does not own", text)

    def test_recovery_premarks_new_state_and_resummarizes(self) -> None:
        """An applied recovery shows the post-recovery summary and consumes the new state's marker."""
        provider = self.providers[0]
        provider.success("begin-wave")
        fake = provider.home / "fake_graph.py"
        fake.write_text(
            "import json, sys\n"
            "p = sys.argv[2]\n"
            "s = json.load(open(p))\n"
            "if sys.argv[1] == 'recover-wave':\n"
            "    s['revision'] += 1\n"
            "    s['graph']['active_wave'] = None\n"
            "    json.dump(s, open(p, 'w'))\n"
            "    print(json.dumps({'recovered': True, 'reason_code': 'recovered'}))\n"
            "else:\n"
            "    ph = 'waiting for worker' if s['graph']['active_wave'] else 'ready to dispatch'\n"
            "    print(json.dumps({'phase': ph, 'detail': 'd', 'done': [], 'active': [],\n"
            "                      'ready': [], 'pending': []}))\n"
        )
        text = stall_notice.status_notice(fake, provider.path, provider.session)
        self.assertIn("recover-wave recovered", text)
        self.assertIn("ready to dispatch", text)
        name = stall_notice.marker_name(provider.read(), provider.session)
        self.assertTrue((provider.path.parent / str(name)).is_dir())


if __name__ == "__main__":
    unittest.main()
