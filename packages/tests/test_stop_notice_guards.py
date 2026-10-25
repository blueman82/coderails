"""Stop-block notice: lease-aged dedupe, pruning, delivery failures and helper branches."""

from __future__ import annotations

import json
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


class StopNoticeGuardTests(StopNoticeBase):
    """Both providers' guards under lease expiry and failure."""

    def test_key_ignores_time(self) -> None:
        """The key carries no clock bucket; freshness comes from the marker age."""
        running = {"loop_id": "l", "revision": 1, "graph": {"active_wave": {"wave_id": "w"}, "hard_stop": None}}
        with mock.patch("time.time", return_value=1000.0):
            first = stall_notice.marker_name(running, "s")
        with mock.patch("time.time", return_value=1000.0 + 5 * stall_notice.LEASE_SECONDS):
            self.assertEqual(first, stall_notice.marker_name(running, "s"))

    def test_unreadable_marker_counts_as_unseen(self) -> None:
        """A marker that vanishes or cannot be stat'd re-notifies instead of silencing the stop."""
        provider = self.providers[0]
        with mock.patch.object(Path, "is_dir", return_value=True), mock.patch.object(Path, "stat", side_effect=OSError):
            self.assertFalse(stall_notice.seen(provider.path, ".human-approval-l-1-aaaaaaaaaaaa"))
        self.assertFalse(stall_notice.seen(provider.path, ".human-approval-absent"))

    def test_persistent_stall_renotifies_per_lease(self) -> None:
        """Silent inside the lease, full status again once the marker is a lease old."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                self.assertIn("Graph status:", self.stop(provider))
                self.age(provider, stall_notice.LEASE_SECONDS - 60)
                self.assertEqual(self.stop(provider), "")
                self.age(provider, 120)
                self.assertIn("Graph status:", self.stop(provider))
                self.assertEqual(self.stop(provider), "")

    def test_wave_retries_recovery_one_lease_after_first_notice(self) -> None:
        """A running wave's recover-wave is retried once the marker is a lease old."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.success("begin-wave")
                self.stop(provider)
                self.assertEqual(self.recover_rows(provider), 1)
                self.age(provider, stall_notice.LEASE_SECONDS + 1)
                self.assertIn("recover-wave", self.stop(provider))
                self.assertEqual(self.recover_rows(provider), 2)

    def test_older_revisions_are_pruned_on_record(self) -> None:
        """Recording a marker removes older revisions of the same loop only."""
        provider = self.providers[0]
        folder = provider.path.parent
        keep = [".human-approval-l-3-bbbbbbbbbbbb", ".human-approval-other-1-cccccccccccc", ".human-approval-l-x-1"]
        gone = [".human-approval-l-1-aaaaaaaaaaaa", ".human-approval-l-2-aaaaaaaaaaaa"]
        for name in [*gone, *keep]:
            (folder / name).mkdir()
        stall_notice.record_notice(provider.path, provider.session, ".human-approval-l-3-dddddddddddd")
        names = {item.name for item in folder.glob(".human-approval-*")}
        self.assertIn(".human-approval-l-3-dddddddddddd", names)
        self.assertTrue(set(keep) <= names)
        self.assertFalse(set(gone) & names)

    def test_markers_stay_bounded_across_revisions(self) -> None:
        """Real hook runs across revision bumps leave one marker."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                for _ in range(3):
                    self.stop(provider)
                    state = provider.read()
                    state["revision"] += 1
                    provider.write(state)
                self.stop(provider)
                self.assertEqual(len(list(provider.path.parent.glob(".human-approval-*"))), 1)

    def guard(self, provider: Provider, body: str, data: str = "d") -> subprocess.CompletedProcess[str]:
        """Run `body` in a child with `g` (the guard module), `call(p, d, s)`, `p`, `d`, `s` and `names()` defined."""
        claude = (
            "from hooks.scripts import loop_stall_guard as g\n"
            "from hooks.scripts.lib.loop_state_common import LoopState\n"
            "def call(p, d, s):\n    return g.emit_human_request(LoopState(p, s, 1, d))\n"
        )
        codex = (
            "import graph_completion_guard as g\n"
            "def call(p, d, s):\n"
            "    graph = d.get('graph', {})\n"
            "    return g.request_human_approval(p, s, {'loop_id': d.get('loop_id'), 'revision': d.get('revision'),\n"
            "        'active_wave': graph.get('active_wave'), 'hard_stop': graph.get('hard_stop')})\n"
        )
        root = ROOT if provider.name == "claude" else ROOT / "packages/codex/hooks/scripts"
        code = (
            "import io, json, sys\nfrom pathlib import Path\nfrom unittest import mock\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            + (claude if provider.name == "claude" else codex)
            + f"p = Path({str(provider.path)!r}); d = json.loads(p.read_text()) if {data == 'd'} else {{}}\n"
            f"s = {provider.session!r}\n"
            "names = lambda: sorted(x.name for x in p.parent.iterdir() if x.name.startswith('.human-approval'))\n"
            + body
        )
        return subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=provider.environment, check=False
        )

    def test_no_key_emits_base_notice_and_logs_on_both(self) -> None:
        """A state with no loop id still gets the base notice and a log line on both providers."""
        body = (
            "logged = []\n"
            "with mock.patch.object(g, 'log', side_effect=logged.append):\n"
            "    call(p, d, s)\n"
            "    call(p, d, s)\n"
            "print(json.dumps([sum('no_marker_key' in x for x in logged), names()]))\n"
        )
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                done = self.guard(provider, body, data="empty")
                lines = done.stdout.strip().splitlines()
                self.assertEqual(json.loads(lines[-1]), [2, []], done.stderr)
                self.assertEqual(len(lines), 3)
                for line in lines[:-1]:
                    self.assertTrue(json.loads(line)["systemMessage"].startswith("Human approval required"))

    def test_codex_corrupt_state_still_emits_notice(self) -> None:
        """An unreadable progress.json no longer drops the approval message: the key comes from the inspection."""
        body = "p.write_text('{not json')\ncall(p, d, s)\n"
        done = self.guard(self.providers[1], body)
        message = json.loads(done.stdout.strip().splitlines()[0])
        self.assertEqual(message["decision"], "block")
        self.assertTrue(message["systemMessage"].startswith("Human approval required"))
        self.assertIn("Graph status unavailable", message["reason"])

    def test_codex_blocked_log_precedes_dedupe(self) -> None:
        """blocked=1 is logged on the first and on the deduplicated call."""
        body = (
            "logged = []\n"
            "with mock.patch.object(g, 'log', side_effect=logged.append):\n"
            "    call(p, d, s)\n"
            "    call(p, d, s)\n"
            "print(sum('blocked=1' in x for x in logged))\n"
        )
        done = self.guard(self.providers[1], body)
        self.assertEqual(done.stdout.strip().splitlines()[-1], "2", done.stderr)

    def test_failed_delivery_leaves_no_marker_on_both(self) -> None:
        """A write or flush failure raises (exit 2 upstream) and leaves no dedupe marker."""
        template = (
            "class Out(io.StringIO):\n"
            "    def {fail}(self, *a): raise BrokenPipeError('pipe')\n"
            "sys.stdout = Out()\n"
            "try: call(p, d, s)\n"
            "except (OSError, ValueError) as e: caught = type(e).__name__\n"
            "else: caught = 'none'\n"
            "sys.stdout = sys.__stdout__\n"
            "print(json.dumps([caught, names()]))\n"
        )
        for provider in self.providers:
            for fail in ("write", "flush"):
                for data in ("d", "empty"):  # keyed notice and no-key notice
                    with self.subTest(provider=provider.name, fail=fail, data=data):
                        done = self.guard(provider, template.format(fail=fail), data=data)
                        caught, markers = json.loads(done.stdout.strip().splitlines()[-1])
                        self.assertEqual(markers, [], done.stderr)
                        self.assertNotEqual(caught, "none")
                        if provider.name == "claude":  # its main() only turns ValueError into exit 2
                            self.assertEqual(caught, "ValueError")

    def test_broken_stdout_exits_2_on_both(self) -> None:
        """End to end: with stdout gone the Stop still blocks (exit 2), never a non-blocking exit 1."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                hook = "loop_stall_guard" if provider.name == "claude" else "graph_completion_guard"
                path = provider.plugin / "hooks/scripts" / (hook + ".py")
                code = (
                    "import io, json, runpy, sys\n"
                    f"sys.path.insert(0, {str(path.parent)!r})\n"
                    "class Out(io.StringIO):\n"
                    "    def write(self, *a): raise BrokenPipeError('pipe')\n"
                    "sys.stdout = Out()\n"
                    f"try: runpy.run_path({str(path)!r}, run_name='__main__')\n"
                    "except SystemExit as e: code = e.code\n"
                    "except BaseException as e: code = type(e).__name__\n"
                    "sys.__stdout__.write(json.dumps(code))\n"
                )
                done = subprocess.run(
                    [sys.executable, "-c", code],
                    input=json.dumps(self.payload(provider)),
                    capture_output=True,
                    text=True,
                    env=provider.environment,
                    check=False,
                    cwd=provider.home,
                )
                self.assertEqual(done.stdout.strip(), "2", done.stderr)
                self.assertEqual(list(provider.path.parent.glob(".human-approval-*")), [])

    def test_notice_reaches_model_channel_on_both(self) -> None:
        """Claude's stderr and Codex's reason both carry the status and the dispatch hint."""
        claude, codex = self.providers
        self.assertIn("Graph status:", self.stop(claude))
        self.assertEqual(self.last.returncode, 2)
        self.assertIn("Graph status:", self.last.stderr)
        self.assertIn("Dispatch: python3", self.last.stderr)
        self.stop(codex)
        reason = json.loads(self.last.stdout)["reason"]
        self.assertIn("Graph status:", reason)
        self.assertIn("Dispatch: python3", reason)

    def test_complete_declaration_with_unresolved_graph_notifies(self) -> None:
        """The LOOP-STOP: complete call site also emits the status notice and blocks."""
        message = self.stop(self.providers[0], "LOOP-STOP: complete — all done")
        self.assertEqual(self.last.returncode, 2, self.last.stderr)
        self.assertIn("Graph status:", message)
        self.assertIn("Graph status:", self.last.stderr)

    def recording_graph(self, phase: str, recover: str = "{'recovered': False, 'reason_code': 'within_lease'}") -> Path:
        """A stand-in graph.py that logs its argv beside itself and reports `phase`."""
        fake = self.providers[0].home / "recording_graph.py"
        fake.write_text(
            "import json, sys\n"
            "open(sys.argv[0] + '.log', 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1] == 'summarize':\n"
            f"    print(json.dumps({{'phase': {phase!r}, 'detail': 'd', 'done': [], 'active': [],\n"
            "                      'ready': [], 'pending': []}))\n"
            "else:\n"
            f"    print(json.dumps({recover}))\n"
        )
        Path(str(fake) + ".log").unlink(missing_ok=True)
        return fake

    def calls(self, fake: Path) -> list[list[str]]:
        """Recorded argv lists."""
        log = Path(str(fake) + ".log")
        return [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []

    def test_recover_wave_only_for_waiting_phase_with_lease(self) -> None:
        """recover-wave runs only while a worker is awaited, with the session and the explicit lease."""
        provider = self.providers[0]
        idle = self.recording_graph("ready to dispatch")
        text = stall_notice.status_notice(idle, provider.path, provider.session)
        self.assertEqual([call[0] for call in self.calls(idle)], ["summarize"])
        self.assertIn("Dispatch: python3", text)
        self.assertNotIn("recover-wave", text)
        busy = self.recording_graph("waiting for worker")
        text = stall_notice.status_notice(busy, provider.path, provider.session)
        recover = [call for call in self.calls(busy) if call[0] == "recover-wave"]
        self.assertEqual(
            recover,
            [["recover-wave", str(provider.path), "--session", provider.session, "--lease-seconds", "900"]],
        )
        self.assertNotIn("Dispatch:", text)

    def test_dispatch_hint_absent_when_not_ready(self) -> None:
        """The hint appears only for a ready-to-dispatch phase."""
        provider = self.providers[0]
        other = self.recording_graph("waiting for human")
        self.assertNotIn("Dispatch:", stall_notice.status_notice(other, provider.path, "s"))

    def test_status_deadline_skips_recovery(self) -> None:
        """Once the overall deadline is spent, recover-wave is not attempted and the label says so."""
        provider = self.providers[0]
        busy = self.recording_graph("waiting for worker")
        ticks = iter([0.0, 0.0])

        def monotonic() -> float:
            return next(ticks, 100.0)

        clock = mock.Mock(monotonic=monotonic)
        with mock.patch.object(stall_notice, "time", clock):
            text = stall_notice.status_notice(busy, provider.path, provider.session)
        self.assertEqual([call[0] for call in self.calls(busy)], ["summarize"])
        self.assertIn("not attempted (status deadline reached)", text)

    def test_json_guard(self) -> None:
        """Only a successful object payload decodes."""
        self.assertEqual(stall_notice.json_object(True, '{"a": 1}'), {"a": 1})
        self.assertIsNone(stall_notice.json_object(False, '{"a": 1}'))
        self.assertIsNone(stall_notice.json_object(True, "[1]"))
        self.assertIsNone(stall_notice.json_object(True, "not json"))

    def test_non_object_outputs_are_reported(self) -> None:
        """Non-object summarize or recover-wave output is labelled, not trusted."""
        provider = self.providers[0]
        fake = provider.home / "odd_graph.py"
        fake.write_text("print('[1]')\n")
        self.assertIn("unreadable output", stall_notice.status_notice(fake, provider.path, "s"))
        busy = self.recording_graph("waiting for worker", recover="[1]")
        self.assertIn("recover-wave refused", stall_notice.status_notice(busy, provider.path, "s"))

    def test_status_notice_never_raises(self) -> None:
        """An unexpected internal error becomes a notice line and a log entry."""
        logged: list[str] = []
        with mock.patch.object(stall_notice, "_status", side_effect=RuntimeError("boom")):
            text = stall_notice.status_notice(Path("x"), Path("y"), "s", logged.append)
        self.assertIn("internal error", text)
        self.assertTrue(any("status_failed=RuntimeError" in line for line in logged))

    def test_agents_table_rows_are_closed(self) -> None:
        """Every markdown table row in AGENTS.md ends with a pipe, so appended prose cannot fall out of the table."""
        rows = [line for line in (ROOT / "AGENTS.md").read_text().splitlines() if line.startswith("|")]
        self.assertTrue(rows)
        self.assertEqual([line[-40:] for line in rows if not line.rstrip().endswith("|")], [])


if __name__ == "__main__":
    unittest.main()
