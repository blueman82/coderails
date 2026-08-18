from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))

from runtime.graph import (  # noqa: E402
    PARALLEL_REVIEW_GATE,
    REQUIRED_GATES,
    StateConflict,
    apply_work_unit_disposition,
    build_graph,
    evaluate_parallel_review_join,
    execute,
    load_contract,
    prepare_implementations,
    ready,
)
from runtime.codex_exec import invoke  # noqa: E402


PASS = [sys.executable, "-c", "print('ok')"]


class GraphRuntimeTests(unittest.TestCase):
    def test_parallel_review_is_not_a_required_gate_kind(self) -> None:
        self.assertNotIn(PARALLEL_REVIEW_GATE, REQUIRED_GATES)

    def test_parallel_review_join_requires_both_fresh_matching_approvals(self) -> None:
        canonical = {"digest": "digest-1"}
        run = {"run_id": "run-1", "revision": "rev-1", "head": "head-1"}

        def record(provider: str, *, digest: str = "digest-1", outcome: str = "approve", **overrides):
            return {
                "schema_version": 1,
                "gate": PARALLEL_REVIEW_GATE,
                "provider": provider,
                **run,
                "frozen_input_digest": digest,
                "verdict": {"outcome": outcome, "reasoning": f"{provider} observed evidence"},
                "route": f"{provider}/reviewer.md",
                "provenance": {"provider": provider},
                **overrides,
            }

        good = evaluate_parallel_review_join(canonical, {"claude": record("claude"), "codex": record("codex")}, expected_run=run)
        self.assertEqual(good["outcome"], "pass")
        self.assertIsNone(good["hard_stop_reason"])

        self.assertEqual(
            evaluate_parallel_review_join(canonical, {}, reviewer_outcomes={"claude": "skipped", "codex": "skipped"})["outcome"],
            "skipped",
        )
        missing = evaluate_parallel_review_join(canonical, {"claude": record("claude")}, reviewer_outcomes={"claude": "done", "codex": "skipped"}, expected_run=run)
        self.assertEqual(missing["hard_stop_reason"], "missing-evidence")
        stale = evaluate_parallel_review_join(canonical, {"claude": record("claude", run_id="old"), "codex": record("codex")}, expected_run=run)
        self.assertEqual(stale["hard_stop_reason"], "stale-evidence")
        mismatched = evaluate_parallel_review_join(canonical, {"claude": record("claude", digest="other"), "codex": record("codex")}, expected_run=run)
        self.assertEqual(mismatched["hard_stop_reason"], "mismatched-evidence")
        conflict = evaluate_parallel_review_join(canonical, {"claude": record("claude"), "codex": record("codex", outcome="reject")}, expected_run=run)
        self.assertEqual(conflict["hard_stop_reason"], "conflicting-verdicts")

    def test_codex_parallel_review_artifact_uses_native_invocation_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "codex.json"
            run = {"run_id": "run-1", "revision": "rev-1", "head": "head-1"}
            artifact.write_text(json.dumps({
                "schema_version": 1,
                "gate": PARALLEL_REVIEW_GATE,
                "provider": "codex",
                **run,
                "frozen_input_digest": "digest-1",
                "verdict": {"outcome": "approve", "reasoning": "reviewed"},
            }))
            graph = build_graph(("A",))
            import runtime.graph as graph_module
            original = graph_module.codex_exec
            try:
                graph_module.codex_exec = lambda _prompt, _cwd: ("done", "native codex result")
                execute(graph, {"SA": {
                    "adapter": "codex-exec", "prompt": "review frozen artifact", "provider": "codex",
                    "skill_id": "review.parallel", "implementation_path": "codex/runtime/graph.py",
                    "gate": PARALLEL_REVIEW_GATE, "mode": "live", "artifact_path": str(artifact),
                    "frozen_input_digest": "digest-1", "provenance": {"provider": "codex", "route": "codex/agents/spec-reviewer.md", **run}, "_run": run,
                }})
            finally:
                graph_module.codex_exec = original
            self.assertEqual(graph["nodes"]["SA"]["outcome"], "done")
            self.assertEqual(graph["nodes"]["SA"]["evidence"][-1]["invocation"], "codex exec")

    def test_codex_exec_adapter_uses_documented_cli_and_preserves_live_evidence(self) -> None:
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed"}\n', stderr="")

        outcome, output = invoke("run node", "/tmp/worktree", runner=runner)
        self.assertEqual(outcome, "done")
        self.assertIn("turn.completed", output)
        self.assertEqual(calls[0][0], ["codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "-C", "/tmp/worktree", "-"])
        self.assertEqual(calls[0][1]["input"], "run node")

    def test_codex_exec_adapter_rejects_empty_and_provider_error_output(self) -> None:
        empty = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr="")
        error = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"type":"item.completed","item":{"type":"error","message":"auth failed"}}\n', stderr="")
        self.assertEqual(invoke("run", "/tmp/worktree", runner=empty)[0], "failed")
        self.assertEqual(invoke("run", "/tmp/worktree", runner=error)[0], "failed")

    def test_graph_node_routes_through_codex_exec_adapter(self) -> None:
        graph = build_graph(("A",))
        import runtime.graph as graph_module
        original = graph_module.codex_exec
        try:
            graph_module.codex_exec = lambda prompt, cwd: ("done", f"live:{prompt}:{cwd}")
            execute(graph, {"SA": {"adapter": "codex-exec", "prompt": "do A", "cwd": "/tmp/worktree", "provider": "codex", "skill_id": "node.A", "implementation_path": "codex/runtime/codex_exec.py"}})
        finally:
            graph_module.codex_exec = original
        evidence = graph["nodes"]["SA"]["evidence"][-1]
        self.assertEqual(graph["nodes"]["SA"]["outcome"], "done")
        self.assertEqual(evidence["invocation"], "codex exec")
        self.assertEqual(evidence["mode"], "live")
    def test_contract_parser_preserves_only_declared_nodes_edges_and_join(self) -> None:
        contract = """# contract

| ID | Node / true prerequisites | Ready when | Conditional skip or join |
|---|---|---|---|
| `root` | Stub state | ready | never |
| `left` | `root` | ready | never |
| `right` | `root` | ready | never |
| `join` | `left` and `right` | ready | explicit join |

```text
root -> left
root -> right
left -> join
right -> join
```
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution-graph.md"
            path.write_text(contract)
            graph = build_graph(contract_path=path)
        self.assertEqual(set(graph["nodes"]), {"root", "left", "right", "join"})
        self.assertNotIn("J12-all", graph["nodes"])
        self.assertEqual(graph["joins"]["join"]["inputs"], ["left", "right"])
        self.assertFalse(ready(graph, "left"))

    def test_contract_template_expands_only_from_explicit_work_units(self) -> None:
        contract = """| ID | Node / true prerequisites | Ready when | Conditional skip or join |
|---|---|---|---|
| `start` | Stub state | ready | never |
| `U3[i]` | `start` | ready | per work unit |
| `join` | `U3[i]` | ready | explicit join |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution-graph.md"
            path.write_text(contract)
            graph = build_graph(contract_path=path, work_units=[{"id": "one"}, {"id": "two"}])
        self.assertEqual(set(graph["nodes"]), {"start", "U3[one]", "U3[two]", "join"})

    def test_guard_nodes_are_metadata_only_and_no_work_units_skip_templates(self) -> None:
        graph = build_graph(contract_path=ROOT / "skills/agentic-loop/execution-graph.md")
        for name in ("G10", "G11", "G12"):
            self.assertFalse(graph["nodes"][name]["dispatch"])
        apply_work_unit_disposition(graph, None)
        self.assertTrue(all(graph["nodes"][name]["outcome"] == "skipped" for name in graph["nodes"] if "[i]" in name))

    def test_gate_configuration_is_explicit_and_complete(self) -> None:
        graph = build_graph(("root", "review", "eval", "proof", "integrity", "wiki", "teardown"))
        config = {"mode": "fixture", "nodes": {}, "gates": {}}
        nodes = list(graph["nodes"])
        for name in nodes:
            config["nodes"][name] = {"command": PASS, "provider": "codex", "skill_id": f"fixture.{name}", "implementation_path": "codex/tests"}
        for kind, node in zip(REQUIRED_GATES, nodes[1:]):
            config["gates"][kind] = {"node": node, "command": PASS, "provider": "codex", "skill_id": f"gate.{kind}", "implementation_path": "codex/tests"}
        mappings, errors = prepare_implementations(graph, config)
        self.assertEqual(errors, [])
        self.assertEqual(set(REQUIRED_GATES), {mappings[node]["gate"] for node in nodes[1:]})
        _, errors = prepare_implementations(graph, {"mode": "fixture", "nodes": config["nodes"], "gates": {"review": config["gates"]["review"]}})
        self.assertTrue(any("missing gate" in error for error in errors))

    def test_catalog_route_must_resolve_to_declared_codex_path(self) -> None:
        graph = build_graph(("A", "review", "eval", "proof", "integrity", "wiki", "teardown"))
        record = {"command": PASS, "provider": "codex", "skill_id": "cite-check", "implementation_path": ".codex/skills/cite-check/SKILL.md", "catalog_route": "cite-check", "catalog_kind": "skills"}
        node_records = {name: {"command": PASS, "provider": "codex", "skill_id": "test." + name, "implementation_path": "codex/tests"} for name in graph["nodes"]}
        node_records["SA"] = record
        gates = {kind: {"node": node, **node_records[node]} for kind, node in zip(REQUIRED_GATES, list(graph["nodes"])[1:])}
        mappings, errors = prepare_implementations(graph, {"mode": "fixture", "nodes": node_records, "gates": gates}, catalog_root=ROOT)
        self.assertEqual(errors, [])
        record["catalog_route"] = "missing-route"
        _, errors = prepare_implementations(graph, {"mode": "fixture", "nodes": node_records, "gates": gates}, catalog_root=ROOT)
        self.assertTrue(any("catalog" in error for error in errors))

    def test_stale_revision_cannot_overwrite_newer_state(self) -> None:
        graph = build_graph(("A",))
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            execute(graph, {"SA": {"command": PASS, "provider": "codex", "skill_id": "test.a", "implementation_path": "codex/tests"}}, state_path=state, expected_revision=0)
            before = state.read_text()
            with self.assertRaises(StateConflict):
                execute(build_graph(("A",)), {"SA": {"command": PASS, "provider": "codex", "skill_id": "test.a", "implementation_path": "codex/tests"}}, state_path=state, expected_revision=0)
            self.assertEqual(state.read_text(), before)

    def test_live_gate_requires_specific_marker_and_provenance(self) -> None:
        graph = build_graph(("A",))
        record = {
            "command": ["sh", "-c", "printf 'coderails-gate kind=review provider=codex artifact=synthetic provenance=synthetic'"],
            "provider": "codex", "skill_id": "gate.review", "implementation_path": "codex/tests",
            "gate": "review", "mode": "live", "artifact_path": "missing-review.json",
            "provenance": {"provider": "codex", "route": "review-route", "run_id": "run-1", "revision": "1", "head": "head-1"},
            "_run": {"run_id": "run-1", "revision": "1", "head": "head-1"},
        }
        execute(graph, {"SA": record})
        self.assertEqual(graph["nodes"]["SA"]["outcome"], "hard-stop")
        self.assertTrue(any("artifact validation failed" in evidence["output"] for evidence in graph["nodes"]["SA"]["evidence"]))

    def test_all_done_live_gate_outcomes_cannot_bypass_missing_artifacts(self) -> None:
        graph = build_graph(("root", "review", "eval", "proof", "integrity", "wiki", "teardown"))
        run = {"run_id": "run-1", "revision": "1", "head": "head-1"}
        mappings = {"Sroot": {"command": PASS, "provider": "codex", "skill_id": "node.root", "implementation_path": "codex/tests"}}
        for kind, node in zip(REQUIRED_GATES, list(graph["nodes"])[1:]):
            mappings[node] = {"command": PASS, "outcome": "done", "provider": "codex", "skill_id": "gate." + kind, "implementation_path": "codex/tests", "gate": kind, "mode": "live", "artifact_path": "missing-" + kind + ".json", "provenance": {"provider": "codex", "route": "test-route", **run}, "_run": run}
        execute(graph, mappings)
        self.assertEqual(graph["nodes"]["Sroot"]["outcome"], "done")
        self.assertTrue(all(graph["nodes"][node]["outcome"] == "hard-stop" for node in list(graph["nodes"])[1:]))
        self.assertTrue(all(any("artifact validation failed" in item["output"] or "blocked by hard-stop" in item["output"] for item in graph["nodes"][node]["evidence"]) for node in list(graph["nodes"])[1:]))

    def test_final_state_cas_rejects_stale_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            state.write_text(json.dumps({"revision": 3}))
            with self.assertRaises(StateConflict):
                from runtime.graph import write_json
                write_json(state, {"revision": 4}, expected_revision=2)
            self.assertEqual(json.loads(state.read_text())["revision"], 3)

    def test_loads_nodes_from_canonical_contract(self) -> None:
        nodes = load_contract(ROOT / "skills/agentic-loop/execution-graph.md")
        ids = {node["id"] for node in nodes}
        self.assertIn("S-2", ids)
        self.assertIn("S13-complete", ids)
        self.assertNotIn("PHASES", ids)
        self.assertEqual(set(build_graph(contract_path=ROOT / "skills/agentic-loop/execution-graph.md")["nodes"]), ids)

    def test_vertical_contract_edges_block_late_join_until_predecessor(self) -> None:
        graph = build_graph(contract_path=ROOT / "skills/agentic-loop/execution-graph.md")
        self.assertFalse(ready(graph, "J12-all-units"))

    def test_dispatches_independent_wave_then_join_and_persists(self) -> None:
        graph = build_graph(("P", "A", "B", "C"), joins={"C": ["A", "B"]}, edges=[("P", "A"), ("P", "B")])
        snapshots = []
        implementations = {
            node: {"command": PASS, "provider": "codex", "skill_id": f"skill-{node}", "implementation_path": f"codex/{node}.md"}
            for node in graph["nodes"]
        }
        execute(graph, implementations, persist=lambda value: snapshots.append(json.loads(json.dumps(value))))
        self.assertEqual(graph["nodes"]["C"]["outcome"], "done")
        self.assertTrue(all(snapshot["nodes"]["C"]["outcome"] == "pending" for snapshot in snapshots[:1]))
        self.assertGreaterEqual(len(snapshots), 3)

    def test_independent_ready_nodes_run_concurrently_before_one_wave_persist(self) -> None:
        graph = build_graph(("root", "A", "B", "C"), joins={"C": ["A", "B"]}, edges=[("root", "A"), ("root", "B")])
        barrier = threading.Barrier(2)
        calls = []
        def work(name):
            if name in {"A", "B"}:
                barrier.wait(timeout=2)
            calls.append(name)
            return "done"
        implementations = {name: {"provider": "codex", "skill_id": name, "implementation_path": "codex/tests", "test_only": True, "outcome": lambda name=name: work(name)} for name in graph["nodes"]}
        snapshots = []
        execute(graph, implementations, persist=lambda value: snapshots.append(json.loads(json.dumps(value))))
        self.assertEqual(graph["nodes"]["C"]["outcome"], "done")
        self.assertEqual(calls.count("A"), 1)
        self.assertEqual(calls.count("B"), 1)
        self.assertEqual(len(snapshots), 3)

    def test_resume_retries_and_failure_are_durable(self) -> None:
        graph = build_graph(("A",))
        graph["nodes"]["SA"]["retry"]["max"] = 2
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            outcomes = iter(["failed", "done"])
            execute(graph, {"SA": {"provider": "codex", "skill_id": "test.retry", "implementation_path": "codex/tests", "test_only": True, "outcome": lambda: next(outcomes)}}, state_path=state)
            self.assertEqual(graph["nodes"]["SA"]["retry"]["attempts"], 2)
            resumed = json.loads(state.read_text())
            execute(resumed["graph"], {"SA": {"command": PASS, "provider": "codex", "skill_id": "test.resume", "implementation_path": "codex/tests"}}, state_path=state)
            self.assertEqual(resumed["graph"]["nodes"]["SA"]["outcome"], "done")

        failed = build_graph(("A",))
        execute(failed, {"SA": {"provider": "codex", "skill_id": "test.failed", "implementation_path": "codex/tests", "test_only": True, "outcome": "failed"}})
        self.assertEqual(failed["nodes"]["SA"]["outcome"], "hard-stop")

    def test_resume_after_interruption_keeps_completed_wave(self) -> None:
        graph = build_graph(("A", "B", "C"), joins={"C": ["A", "B"]}, edges=[("A", "C"), ("B", "C")])
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "progress.json"
            interrupted = {"provider": "codex", "skill_id": "test.c", "implementation_path": "codex/tests", "test_only": True, "outcome": lambda: (_ for _ in ()).throw(KeyboardInterrupt())}
            with self.assertRaises(KeyboardInterrupt):
                execute(graph, {"A": {"command": PASS, "provider": "codex", "skill_id": "test.a", "implementation_path": "codex/tests"}, "B": {"command": PASS, "provider": "codex", "skill_id": "test.b", "implementation_path": "codex/tests"}, "C": interrupted}, state_path=state)
            saved = json.loads(state.read_text())
            self.assertEqual(saved["graph"]["nodes"]["A"]["outcome"], "done")
            resumed = saved["graph"]
            execute(resumed, {"C": {"command": PASS, "provider": "codex", "skill_id": "test.c.resume", "implementation_path": "codex/tests"}, "A": {}, "B": {}}, state_path=state, expected_revision=saved["revision"])
            self.assertEqual(resumed["nodes"]["C"]["outcome"], "done")
            self.assertEqual(resumed["nodes"]["A"]["retry"]["attempts"], 1)

    def test_missing_implementation_and_gate_unavailability_fail_closed(self) -> None:
        graph = build_graph(("U4b-review",), joins={"U4b-review": []})
        execute(graph, {})
        node = graph["nodes"]["U4b-review"]
        self.assertEqual(node["outcome"], "hard-stop")
        self.assertIn("missing implementation", node["evidence"][-1]["output"])

    def test_invalid_metadata_and_blocked_dependents_are_hard_stop(self) -> None:
        graph = build_graph(("A", "B"))
        execute(graph, {"SA": {"command": [sys.executable, "-c", "exit(1)"]}})
        self.assertEqual(graph["nodes"]["SA"]["outcome"], "hard-stop")
        self.assertEqual(graph["nodes"]["SB"]["outcome"], "hard-stop")
        self.assertIn("blocked by", graph["nodes"]["SB"]["evidence"][-1]["output"])

    def test_invalid_mapping_metadata_is_durable(self) -> None:
        graph = build_graph(("A",))
        execute(graph, {"SA": {"command": PASS, "provider": "claude", "skill_id": "x", "path": "x"}})
        self.assertEqual(graph["nodes"]["SA"]["outcome"], "hard-stop")
        self.assertIn("provider", graph["nodes"]["SA"]["evidence"][-1]["output"])

    def test_completion_requires_all_nodes_done_or_skipped(self) -> None:
        graph = build_graph(("A", "B"))
        execute(graph, {"SA": {"command": PASS, "provider": "codex", "skill_id": "test.a", "implementation_path": "codex/tests"}, "SB": {"provider": "codex", "skill_id": "test.b", "implementation_path": "codex/tests", "test_only": True, "outcome": "skipped", "evidence": "not in scope"}})
        self.assertEqual({node["outcome"] for node in graph["nodes"].values()}, {"done", "skipped"})


if __name__ == "__main__":
    unittest.main()
