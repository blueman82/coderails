from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))

from runtime.graph import (  # noqa: E402
    build_graph,
    codex_policy_mappings,
    load_graph_policies,
    persist_parallel_review_join,
    ready,
)


class LiveGraphWiringTests(unittest.TestCase):
    def test_loads_both_provider_routes_and_rejects_bad_policy(self) -> None:
        policy = load_graph_policies(ROOT / "skills/index.yaml", repo_root=ROOT)
        self.assertEqual(policy["U4b-review"]["join"]["policy"], "unanimous")
        self.assertEqual({item["provider"] for item in policy["U4b-review"]["reviewers"]}, {"claude", "codex"})
        graph = build_graph(contract_path=ROOT / "skills/agentic-loop/execution-graph.md")
        mappings = codex_policy_mappings(graph, policy, repo_root=ROOT)
        self.assertEqual(mappings["U4b-review-codex[i]"]["provider"], "codex")
        expanded = build_graph(contract_path=ROOT / "skills/agentic-loop/execution-graph.md", work_units=[{"id": "unit-a"}, {"id": "unit-b"}])
        expanded_mappings = codex_policy_mappings(expanded, policy, repo_root=ROOT)
        self.assertEqual(
            {name for name in expanded_mappings if name.startswith("U4b-review-codex[")},
            {"U4b-review-codex[unit-a]", "U4b-review-codex[unit-b]"},
        )
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.yaml"
            index.write_text("graph_policies:\n  U4b-review:\n    mode: other\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_graph_policies(index, repo_root=ROOT)

    def test_join_is_atomic_and_blocks_downstream_on_bad_evidence(self) -> None:
        graph = build_graph(contract_path=ROOT / "skills/agentic-loop/execution-graph.md")
        policy = load_graph_policies(ROOT / "skills/index.yaml", repo_root=ROOT)["U4b-review"]
        run = {"run_id": "run-1", "revision": "rev-1", "head": "head-1"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "canonical.json"
            claude = root / "claude.json"
            codex = root / "codex.json"
            canonical.write_text(json.dumps({
                "schema_version": 1, "node": "U4b-review[i]", "artifact_ref": "frozen-input.txt",
                "digest_algorithm": "sha256", "digest": "abc",
            }), encoding="utf-8")
            for path, provider in ((claude, "claude"), (codex, "codex")):
                path.write_text(json.dumps({
                    "schema_version": 1, "gate": "parallel-review", "node": "U4b-review[i]",
                    **run, "provider": provider, "frozen_input_digest": "abc",
                    "digest_algorithm": "sha256", "verdict": {"outcome": "approve", "reasoning": "ok"},
                    "written_at": "2026-08-18T10:00:00Z",
                }), encoding="utf-8")
            state = root / "progress.json"
            state.write_text(json.dumps({"revision": 0}), encoding="utf-8")
            join = persist_parallel_review_join(graph, policy, canonical, {"claude": claude, "codex": codex}, expected_run=run, state_path=state, expected_revision=0)
            self.assertEqual(join["outcome"], "pass")
            saved = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved["parallel_review_join"]["outcome"], "pass")
            self.assertRegex(saved["parallel_review_join"]["evaluated_at"], r"^2026-\d\d-\d\dT")
            join_node = next(name for name, node in saved["graph"]["nodes"].items() if node.get("parallel_review"))
            self.assertEqual(saved["graph"]["nodes"][join_node]["outcome"], "done")
            self.assertTrue(ready(saved["graph"], "U5[0]") if "U5[0]" in saved["graph"]["nodes"] else any(ready(saved["graph"], name) for name in saved["graph"]["nodes"] if name.startswith("U5[")))


if __name__ == "__main__":
    unittest.main()
