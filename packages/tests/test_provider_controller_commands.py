"""`start` and `add-unit` behave identically through both providers' real CLIs, with coded refusals and a trace."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))
import graph_completion  # noqa: E402
import graph_controller as codex_controller  # noqa: E402
import graph_io  # noqa: E402
from graph_identity import GraphError  # noqa: E402

from hooks.scripts.lib import graph_controller as claude_controller  # noqa: E402
from hooks.scripts.lib import loop_completion  # noqa: E402
from hooks.scripts.lib.graph_executor import load as claude_load  # noqa: E402
from hooks.scripts.lib.loop_state_common import LoopState  # noqa: E402

SESSION, LOOP, PROMPT = "sess-1", "loop-a", 'Ship it.\n  "quoted" ☃ end\n'
CLI = {
    "claude": ROOT / "skills/agentic-loop/scripts/graph.py",
    "codex": ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py",
}


class Controller:
    """One provider's CLI over an isolated state directory."""

    def __init__(self, root: Path, name: str) -> None:
        """Isolate HOME, state dir and lock timing so contenders wait rather than fail."""
        self.name, self.root = name, root / name
        self.root.mkdir()
        self.path = self.root / "state/proj" / SESSION / "progress.json"
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text(PROMPT, encoding="utf-8")
        self.env = {
            **os.environ,
            "HOME": str(self.root),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.root / "state"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.root / "state"),
            "CLAUDE_DISCIPLINE_LOG": str(self.root / "log"),
            "CODERAILS_DISCIPLINE_LOG": str(self.root / "log"),
            "CLAUDE_HOOK_MAX_ATTEMPTS": "400",
            "CLAUDE_HOOK_SLEEP_S": "0.01",
        }

    def argv(self, command: str, *rest: str, path: Path | None = None) -> list[str]:
        """Build the CLI line."""
        return [sys.executable, str(CLI[self.name]), command, str(path or self.path), *rest]

    def run(self, command: str, *rest: str, path: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run one CLI command to completion."""
        return subprocess.run(
            self.argv(command, *rest, path=path), capture_output=True, text=True, check=False, env=self.env
        )

    def start(
        self, loop: str = LOOP, session: str = SESSION, path: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run `start` with the shared defaults."""
        return self.run("start", "--session", session, "--loop-id", loop, "--prompt-file", str(self.prompt), path=path)

    def add(self, unit: str, *extra: str, loop: str = LOOP, session: str = SESSION) -> subprocess.CompletedProcess[str]:
        """Run `add-unit`."""
        return self.run("add-unit", "--session", session, "--loop-id", loop, "--unit", unit, *extra)

    def read(self) -> dict[str, Any]:
        """Current state."""
        return cast(dict[str, Any], json.loads(self.path.read_text(encoding="utf-8")))

    def trace(self) -> list[dict[str, Any]]:
        """Sidecar rows."""
        sidecar = self.path.with_name("recovery-trace.jsonl")
        return [json.loads(line) for line in sidecar.read_text().splitlines()] if sidecar.is_file() else []

    def codes(self, command: str) -> list[str]:
        """Reason codes the sidecar holds for one command."""
        return [row["reason_code"] for row in self.trace() if row["command"] == command]


class ControllerCase(unittest.TestCase):
    """Run every case against both providers and require the same observable result."""

    def setUp(self) -> None:
        """One Controller per provider."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.controllers = [Controller(Path(temporary.name), name) for name in ("claude", "codex")]

    def each(self) -> Iterator[Controller]:
        """Iterate providers under subTest."""
        for controller in self.controllers:
            with self.subTest(provider=controller.name):
                yield controller

    def refused(self, result: subprocess.CompletedProcess[str], code: str) -> None:
        """A refusal exits 1 and names its reason code."""
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"[reason_code={code}]", result.stderr)


class StartTests(ControllerCase):
    """Creation, idempotence, rearming and every refusal."""

    def test_start_writes_the_in_progress_stub_with_the_prompt_verbatim(self) -> None:
        """The stub is schema v3, in-progress, empty graph, prompt unchanged; the trace says created."""
        for c in self.each():
            result = c.start()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "start_created")
            state = c.read()
            self.assertEqual(
                (state["schema_version"], state["session_id"], state["loop_id"], state["revision"], state["status"]),
                (3, SESSION, LOOP, 1, "in-progress"),
            )
            self.assertEqual(state["authorising_prompt_raw"], PROMPT)
            self.assertEqual(state["work_units"], {})
            self.assertEqual(
                state["graph"], {"nodes": {}, "edges": [], "joins": {}, "active_wave": None, "hard_stop": None}
            )
            self.assertEqual(("completed_marker" in state), c.name == "claude")
            self.assertEqual(c.codes("start"), ["start_created"])

    def test_start_is_an_idempotent_retry_for_the_same_loop(self) -> None:
        """A second start for the same loop exits 0, writes nothing and traces start_noop."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            result = c.start()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "start_noop")
            self.assertEqual(c.path.read_bytes(), before)
            self.assertEqual(c.codes("start"), ["start_created", "start_noop"])

    def test_start_on_a_completed_loop_with_the_same_id_is_refused_with_a_code(self) -> None:
        """Same loop id over a complete loop must not noop (the guard then demands start forever)."""
        for c in self.each():
            c.start()
            state = c.read()
            state.update(status="complete")
            c.path.write_text(json.dumps(state))
            before = c.path.read_bytes()
            self.refused(c.start(), "start_refused_loop_complete")
            self.assertEqual(c.path.read_bytes(), before)
            self.assertEqual(c.start(loop="loop-b").returncode, 0)

    def test_a_live_loop_is_never_restubbed(self) -> None:
        """A different loop id over an unfinished loop is refused; resume is the answer."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            self.refused(c.start(loop="loop-b"), "start_refused_active_loop")
            self.assertEqual(c.path.read_bytes(), before)
            self.assertEqual(c.codes("start")[-1], "start_refused_active_loop")

    def test_a_completed_loop_is_rearmed_with_a_fresh_loop_id(self) -> None:
        """Revision resets to 1, loop_stop_counts is dropped, and Claude carries completed_marker forward."""
        for c in self.each():
            c.start()
            state = c.read()
            state.update(status="complete", loop_stop_counts={"x": 2}, revision=9)
            if c.name == "claude":
                state["completed_marker"] = 7
            c.path.write_text(json.dumps(state))
            result = c.start(loop="loop-b")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "start_rearmed")
            fresh = c.read()
            self.assertEqual((fresh["loop_id"], fresh["revision"], fresh["status"]), ("loop-b", 1, "in-progress"))
            self.assertNotIn("loop_stop_counts", fresh)
            self.assertEqual(fresh.get("completed_marker"), 7 if c.name == "claude" else None)

    def test_foreign_session_blank_session_and_wrong_path_are_refused_without_a_write(self) -> None:
        """Another session's file, a blank or ? session, and a path not keyed by the session all refuse."""
        for c in self.each():
            c.start()
            foreign = {**c.read(), "session_id": "someone-else"}
            c.path.write_text(json.dumps(foreign))
            before = c.path.read_bytes()
            self.refused(c.start(loop="loop-b"), "start_refused_session")
            self.assertEqual(c.path.read_bytes(), before)
            fresh = c.root / "state/proj"
            for bad in ("", "  ", "?"):
                self.refused(c.start(session=bad, path=fresh / "x" / "progress.json"), "start_refused_session")
            self.refused(c.start(path=fresh / "other-dir" / "progress.json"), "start_refused_path")
            self.refused(c.start(path=fresh / SESSION / "notes.json"), "start_refused_path")
            self.assertFalse((fresh / "other-dir").exists() or (fresh / "x").exists())

    def test_competing_starters_produce_exactly_one_created(self) -> None:
        """Four processes race a different loop id each: one wins, three are refused, the file is the winner's."""
        for c in self.each():
            procs = [
                subprocess.Popen(
                    c.argv("start", "--session", SESSION, "--loop-id", f"loop-{i}", "--prompt-file", str(c.prompt)),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=c.env,
                )
                for i in range(4)
            ]
            results = [(p.communicate()[1], p.returncode) for p in procs]
            self.assertEqual(sorted(code for _, code in results), [0, 1, 1, 1], results)
            self.assertEqual(c.codes("start").count("start_created"), 1)
            self.assertEqual(c.codes("start").count("start_refused_active_loop"), 3)
            self.assertIn(c.read()["loop_id"], {f"loop-{i}" for i in range(4)})

    def test_a_torn_write_leaves_no_file_and_the_old_file_intact(self) -> None:
        """os.replace failing mid-start: no progress.json on a fresh start, original bytes on a rearm."""
        for module in (claude_controller, codex_controller):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / SESSION / "progress.json"
                prompt = Path(raw) / "p.txt"
                prompt.write_text(PROMPT)
                with patch("os.replace", side_effect=OSError("torn")), self.assertRaises(ValueError):
                    module.start(path, SESSION, LOOP, prompt)
                debris = {"progress.json.lock", "recovery-trace.jsonl", "lock-events.jsonl"}
                self.assertEqual([p.name for p in path.parent.iterdir() if p.name not in debris], [])
                module.start(path, SESSION, LOOP, prompt)
                state = json.loads(path.read_text())
                path.write_text(json.dumps({**state, "status": "complete"}))
                before = path.read_bytes()
                with patch("os.replace", side_effect=OSError("torn")), self.assertRaises(ValueError):
                    module.start(path, SESSION, "loop-b", prompt)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(
                    [p.name for p in path.parent.iterdir() if p.name not in debris | {"progress.json"}], []
                )


class AddUnitTests(ControllerCase):
    """Registration, refusals, one lock one write."""

    def setUp(self) -> None:
        """Each provider starts a loop."""
        super().setUp()
        for c in self.controllers:
            c.start()

    def test_add_unit_registers_unit_node_edge_and_join_together(self) -> None:
        """work_units stays separate from nodes; edges and the J12 join are written in the same save."""
        for c in self.each():
            self.assertEqual(c.add("1", "--join").returncode, 0)
            result = c.add("2", "--depends-on", "1", "--join")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["reason_code"], "add_unit_registered")
            state = c.read()
            self.assertEqual(state["work_units"], {"1": {"status": "pending"}, "2": {"status": "pending"}})
            self.assertEqual(sorted(state["graph"]["nodes"]), ["J12-all-units", "U3[1]", "U3[2]"])
            node = state["graph"]["nodes"]["U3[2]"]
            self.assertEqual(
                (node["label"], node["status"], node["outcome"], node["retry"], node["respawn"], node["evidence"]),
                (
                    "Build unit 2",
                    "pending",
                    "pending",
                    {"attempts": 0, "max": 5},
                    {"generation": 0, "intent": None},
                    [],
                ),
            )
            self.assertEqual(state["graph"]["edges"], [{"from": "U3[1]", "to": "U3[2]"}])
            self.assertEqual(
                state["graph"]["joins"]["J12-all-units"],
                {"id": "J12-all-units", "mode": "all", "inputs": ["U3[1]", "U3[2]"], "released": False},
            )
            self.assertEqual(c.codes("add-unit"), ["add_unit_registered"] * 2)
            self.assertEqual(state["revision"], 3)

    def test_a_repeated_dependency_is_reported_once_matching_the_single_edge(self) -> None:
        """The reply must describe what was written: one edge, one depends_on entry."""
        for c in self.each():
            c.add("1")
            reply = json.loads(c.add("2", "--depends-on", "1", "--depends-on", "1").stdout)
            self.assertEqual(reply["depends_on"], ["1"])
            self.assertEqual(c.read()["graph"]["edges"], [{"from": "U3[1]", "to": "U3[2]"}])

    def test_each_add_unit_bumps_revision_so_frozen_evals_go_stale(self) -> None:
        """Evals bind (session, loop, revision): a unit added after freezing must break that binding."""
        for c in self.each():
            frozen = {"session_id": SESSION, "loop_id": LOOP, "revision": c.read()["revision"]}
            self.assertEqual(c.add("1").returncode, 0)
            state = c.read()
            self.assertNotEqual(frozen["revision"], state["revision"])
            self.assertTrue(any(frozen[k] != state[k] for k in frozen))

    def test_duplicate_blank_bad_and_unknown_dependency_are_refused_unchanged(self) -> None:
        """Each refusal carries its code and leaves the file byte-identical."""
        for c in self.each():
            c.add("1")
            before = c.path.read_bytes()
            self.refused(c.add("1"), "add_unit_refused_duplicate")
            for bad in ("", "  ", "0", "01", "a", "1.5", "U3[1]"):
                self.refused(c.add(bad), "add_unit_refused_bad_id")
            self.refused(c.add("2", "--depends-on", "9"), "add_unit_refused_unknown_dep")
            self.refused(c.add("2", "--depends-on", "2"), "add_unit_refused_unknown_dep")
            self.assertEqual(c.path.read_bytes(), before)

    def test_a_dependency_cycle_through_the_join_is_rejected_by_the_kernel(self) -> None:
        """U1 -> U3 -> J12 -> U1 is a cycle only the kernel validate sees; nothing is written."""
        for c in self.each():
            c.add("1")
            c.add("2", "--join")
            state = c.read()
            state["graph"]["edges"].append({"from": "J12-all-units", "to": "U3[1]"})
            c.path.write_text(json.dumps(state))
            before = c.path.read_bytes()
            self.refused(c.add("3", "--depends-on", "1", "--join"), "add_unit_refused_cycle")
            self.assertEqual(c.path.read_bytes(), before)

    def test_foreign_loop_session_and_non_in_progress_state_are_refused(self) -> None:
        """Wrong loop id, wrong session, an initialising or complete file, and an active wave all refuse."""
        for c in self.each():
            before = c.path.read_bytes()
            self.refused(c.add("1", loop="loop-z"), "add_unit_refused_foreign")
            self.refused(c.add("1", session="other"), "add_unit_refused_foreign")
            for status in ("initialising", "complete"):
                c.path.write_text(json.dumps({**json.loads(before), "status": status}))
                self.refused(c.add("1"), "add_unit_refused_state")
            wave = {**json.loads(before)}
            wave["graph"]["active_wave"] = {"wave_id": "w", "revision": 1, "nodes": [], "transcript_cursor": 0}
            c.path.write_text(json.dumps(wave))
            self.refused(c.add("1"), "add_unit_refused_state")
            c.path.write_bytes(before)
            self.assertEqual(c.read()["work_units"], {})

    def test_missing_or_corrupt_state_is_refused_and_still_traced(self) -> None:
        """A refusal on an absent or corrupt file writes a trace row (the tolerant-state fix)."""
        for c in self.each():
            c.path.write_text("not-json")
            self.refused(c.add("1"), "add_unit_refused_state")
            self.assertEqual(c.codes("add-unit"), ["add_unit_refused_state"])

    def test_two_writers_for_the_same_unit_register_it_exactly_once(self) -> None:
        """Four processes add unit 1: one registers, three are duplicates, the file has one unit and one node."""
        for c in self.each():
            procs = [
                subprocess.Popen(
                    c.argv("add-unit", "--session", SESSION, "--loop-id", LOOP, "--unit", "1"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=c.env,
                )
                for _ in range(4)
            ]
            for p in procs:
                p.communicate()
            self.assertEqual(sorted(p.returncode for p in procs), [0, 1, 1, 1])
            self.assertEqual(c.codes("add-unit").count("add_unit_registered"), 1)
            self.assertEqual(c.codes("add-unit").count("add_unit_refused_duplicate"), 3)
            self.assertEqual(list(c.read()["work_units"]), ["1"])

    def test_a_torn_write_leaves_no_partial_unit_node_or_edge(self) -> None:
        """os.replace failing mid add-unit leaves the file byte-identical."""
        for module, name in ((claude_controller, "claude"), (codex_controller, "codex")):
            with self.subTest(module=name):
                c = next(item for item in self.controllers if item.name == name)
                c.add("1")
                before = c.path.read_bytes()
                with patch("os.replace", side_effect=OSError("torn")), self.assertRaises(ValueError):
                    module.add_unit(c.path, SESSION, LOOP, "2", ["1"], True)
                self.assertEqual(c.path.read_bytes(), before)

    def test_the_files_the_commands_wrote_satisfy_each_providers_guards(self) -> None:
        """Claude's guard sees an owned, unfinished loop and its predicate blocks the pending unit; Codex loads it."""
        c = self.controllers[0]
        c.add("1")
        data = c.read()
        state = LoopState(c.path, SESSION, 1, data)
        self.assertTrue(state.owned)
        self.assertFalse(state.complete)
        with self.assertRaises(ValueError):
            loop_completion.validate_work_units(data)
        claude_load(c.path)
        x = self.controllers[1]
        x.add("1")
        graph_io.load(x.path)
        with self.assertRaises(GraphError):
            graph_completion.validate_work_units(x.read())


if __name__ == "__main__":
    unittest.main()
