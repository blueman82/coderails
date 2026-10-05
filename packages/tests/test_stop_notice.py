"""Stop-block notice: state-keyed dedupe, automatic status, one bounded recovery attempt."""

from __future__ import annotations

import filecmp
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import stall_notice  # noqa: E402
from packages.tests.provider_fixture import Provider  # noqa: E402
from packages.tests.stop_notice_fixture import StopNoticeBase  # noqa: E402


class StopNoticeTests(StopNoticeBase):
    """Drive both providers' real Stop hooks."""

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
            with self.subTest(provider=provider.name):
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
            with self.subTest(provider=provider.name):
                provider.success("begin-wave")
                revision = provider.read()["revision"]
                first = self.stop(provider)
                self.assertIn("waiting for worker", first)
                self.assertIn("recover-wave", first)
                self.assertEqual(self.stop(provider), "")
                self.assertEqual(self.recover_rows(provider), 1)
                self.assertEqual(provider.read()["revision"], revision)

    def test_expired_lease_recovers_at_hook_level(self) -> None:
        """Silent workers past the lease are recovered by the hook; the recovered state is not re-notified."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.success("begin-wave")
                provider.launch("stale")
                first = self.stop(provider)
                self.assertIn("recover-wave recovered", first)
                self.assertIsNone(provider.read()["graph"]["active_wave"])
                self.assertEqual(self.stop(provider), "")

    def test_active_wave_change_without_revision_bump_renotifies(self) -> None:
        """Same revision, different active_wave (written directly): the hook notifies again."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.success("begin-wave")
                self.assertIn("waiting for worker", self.stop(provider))
                self.assertEqual(self.stop(provider), "")
                state = provider.read()
                state["graph"]["active_wave"] = {**state["graph"]["active_wave"], "transcript_cursor": 0}
                provider.write(state)
                self.assertIn("waiting for worker", self.stop(provider))
                self.assertEqual(provider.read()["revision"], state["revision"])

    def fake_graph(self, body: str) -> Path:
        """A stand-in graph.py reporting a waiting wave; `body` handles recover-wave."""
        fake = self.providers[0].home / "fake_graph.py"
        fake.write_text(
            "import json, sys, time\n"
            "if sys.argv[1] == 'summarize':\n"
            "    print(json.dumps({'phase': 'waiting for worker', 'detail': 'd', " + self.summary_fields + "}))\n"
            "else:\n"
            "    " + body + "\n"
        )
        return fake

    summary_fields = "'done': [], 'active': [], 'ready': [], 'pending': []"

    def test_recover_wave_timeout_is_unknown_not_refused(self) -> None:
        """A recover-wave that outlives the cap says the outcome is unknown."""
        fake = self.fake_graph("time.sleep(30)")
        provider = self.providers[0]
        with mock.patch.object(stall_notice, "TIMEOUT", 1):
            text = stall_notice.status_notice(fake, provider.path, provider.session)
        self.assertIn("outcome unknown (timed out)", text)
        self.assertNotIn("refused", text)

    def test_summarize_failure_keeps_its_reason(self) -> None:
        """A failing summarize reports its stderr line."""
        fake = self.providers[0].home / "bad_graph.py"
        fake.write_text("import sys\nsys.stderr.write('state is corrupt\\n')\nsys.exit(1)\n")
        text = stall_notice.status_notice(fake, self.providers[0].path, "s")
        self.assertIn("unavailable", text)
        self.assertIn("state is corrupt", text)

    def test_non_list_summarize_fields_do_not_raise(self) -> None:
        """Malformed list fields render as '-' instead of raising."""
        self.summary_fields = "'done': 5, 'active': None, 'ready': {'a': 1}, 'pending': 'x'"
        fake = self.fake_graph("print(json.dumps({'recovered': False, 'reason_code': 'within_lease'}))")
        text = stall_notice.status_notice(fake, self.providers[0].path, "s")
        self.assertIn("done: -; active: -; ready: -; pending: -", text)

    def test_failed_resummarize_is_labelled_stale(self) -> None:
        """If the post-recovery summarize fails, the notice says so rather than reusing the old summary silently."""
        provider = self.providers[0]
        fake = provider.home / "flaky_graph.py"
        fake.write_text(
            "import json, os, sys\n"
            "flag = sys.argv[2] + '.recovered'\n"
            "if sys.argv[1] == 'recover-wave':\n"
            "    open(flag, 'w').close()\n"
            "    print(json.dumps({'recovered': True, 'reason_code': 'recovered'}))\n"
            "elif os.path.exists(flag):\n"
            "    sys.exit(1)\n"
            "else:\n"
            "    print(json.dumps({'phase': 'waiting for worker', 'detail': 'd'}))\n"
        )
        text = stall_notice.status_notice(fake, provider.path, provider.session)
        self.assertIn("post-recovery status unavailable", text)

    def test_failing_notice_leaves_no_marker(self) -> None:
        """If building the notice fails, no dedupe marker exists, so the next Stop re-notifies."""
        claude = (
            "from hooks.scripts import loop_stall_guard as g\n"
            "from hooks.scripts.lib.loop_state_common import LoopState\n"
            "call = lambda p, d, s: g.emit_human_request(LoopState(p, s, 1, d))\n"
        )
        codex = (
            "import graph_completion_guard as g\n"
            "ident = lambda d: {'loop_id': d['loop_id'], 'revision': d['revision']}\n"
            "call = lambda p, d, s: g.request_human_approval(p, s, ident(d))\n"
        )
        roots = (ROOT, ROOT / "packages/codex/hooks/scripts")
        for provider, setup, root in zip(self.providers, (claude, codex), roots):
            with self.subTest(provider=provider.name):
                code = (
                    "import json, sys\nfrom pathlib import Path\nfrom unittest import mock\n"
                    f"sys.path.insert(0, {str(root)!r})\n"
                    + setup
                    + f"p = Path({str(provider.path)!r}); d = json.loads(p.read_text())\n"
                    "with mock.patch.object(g, 'status_notice', side_effect=RuntimeError('boom')):\n"
                    f"    try: call(p, d, {provider.session!r})\n"
                    "    except RuntimeError: pass\n"
                    "print([x.name for x in p.parent.iterdir() if x.name.startswith('.human-approval')])\n"
                )
                done = subprocess.run(
                    [sys.executable, "-c", code], capture_output=True, text=True, env=provider.environment, check=False
                )
                self.assertEqual(done.stdout.strip().splitlines()[-1], "[]", done.stderr)

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

    def test_foreign_session_is_refused(self) -> None:
        """A different session's recover-wave is shown as refused with its reason."""
        for provider in self.providers:
            provider.success("begin-wave")
            os.environ.update(provider.environment)
            text = stall_notice.status_notice(self.graph_cli(provider), provider.path, "intruder")
            self.assertIn("refused", text)
            self.assertIn("does not own", text)

    def test_recovery_premarks_new_state_and_resummarizes(self) -> None:
        """A recovery shows the post-recovery summary; record_notice then consumes the new state's marker."""
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
        self.assertNotIn("Dispatch:", text)  # the recovery line replaces the hint
        stall_notice.record_notice(provider.path, provider.session, ".human-approval-first")
        name = stall_notice.marker_name(provider.read(), provider.session)
        self.assertTrue((provider.path.parent / str(name)).is_dir())


if __name__ == "__main__":
    unittest.main()
