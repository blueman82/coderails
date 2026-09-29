"""Replay the canonical semantic corpus across both independent provider installs."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "packages/graph-semantics/fixtures"
COPIES = {
    "shared": ROOT / "packages/graph-semantics/graph_semantics.py",
    "claude": ROOT / "skills/agentic-loop/scripts/graph_semantics.py",
    "codex": ROOT / "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
}


def semantic_copy(name: str, path: Path) -> ModuleType:
    """Load each materialized copy by path so sys.path cannot alias another copy."""
    spec = importlib.util.spec_from_file_location(f"fixture_graph_semantics_{name}", path)
    if spec is None:
        raise AssertionError(f"cannot load {path}")
    loader = cast(object, getattr(spec, "loader", None))
    if not isinstance(loader, SourceFileLoader):
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run_semantic(module: ModuleType, fixture: dict[str, Any]) -> tuple[object, dict[str, Any]]:
    """Keep the fixture input available for the atomicity assertion."""
    state = copy.deepcopy(fixture["state"])
    try:
        result = getattr(module, fixture["operation"])(state, **fixture.get("request", {}))
    except module.GraphSemanticError as error:
        result = {"error": {"code": error.code, "message": error.message}}
    return result, state


def native_state(provider: Provider, fixture: dict[str, Any]) -> dict[str, Any]:
    """Add only the provider owner fields absent from pure semantic fixtures."""
    return {
        **copy.deepcopy(fixture["state"]),
        "session_id": provider.session,
        "loop_id": "fixture-loop",
        "status": "in-progress",
    }


def semantic_graph(state: dict[str, Any]) -> dict[str, Any]:
    """Remove native cursor, wave history and worker references added by adapters."""
    result = copy.deepcopy(state)
    graph = result["graph"]
    graph.pop("wave_history", None)
    wave = graph["active_wave"]
    if wave is not None:
        wave.pop("transcript_cursor", None)
    for node in graph["nodes"].values():
        node["evidence"] = [entry for entry in node["evidence"] if not isinstance(entry, dict)]
    return {key: result[key] for key in ("schema_version", "revision", "graph")}


class ProviderGraphFixtureTests(unittest.TestCase):
    """Compare exact pure outcomes and persisted native transitions."""

    def test_every_fixture_against_each_independent_semantic_copy(self) -> None:
        """All 52 corpus cases retain exact results, errors, and refusal atomicity."""
        paths = sorted(FIXTURES.glob("*.json"))
        self.assertEqual(len(paths), 52, "fixture replay must expand with the canonical corpus")
        for name, path in COPIES.items():
            module = semantic_copy(name, path)
            for fixture_path in paths:
                with self.subTest(copy=name, fixture=fixture_path.name):
                    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                    actual, state = run_semantic(module, fixture)
                    self.assertEqual(actual, fixture["expected"])
                    if fixture.get("unchanged") or "error" in fixture["expected"]:
                        self.assertEqual(state, fixture["state"])

    def test_native_adapters_validate_every_fixture_state(self) -> None:
        """Native readers agree with the corpus on valid states and ready nodes."""
        core = semantic_copy("shared_reader", COPIES["shared"])
        with tempfile.TemporaryDirectory() as directory:
            for index, fixture_path in enumerate(sorted(FIXTURES.glob("*.json"))):
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                fixture_home = Path(directory) / str(index)
                fixture_home.mkdir()
                try:
                    core.validate(copy.deepcopy(fixture["state"]))
                    valid = True
                except core.GraphSemanticError:
                    valid = False
                for name in ("claude", "codex"):
                    with self.subTest(provider=name, fixture=fixture_path.name):
                        provider = Provider(fixture_home, name)
                        provider.write(native_state(provider, fixture))
                        before = provider.path.read_bytes()
                        result = provider.call("inspect")
                        self.assertEqual(result.returncode == 0, valid, result.stderr)
                        self.assertEqual(provider.path.read_bytes(), before)
                        if valid and fixture["operation"] == "ready":
                            self.assertEqual(json.loads(result.stdout)["ready"], fixture["expected"])

    def test_native_adapters_replay_supported_transitions(self) -> None:
        """Provider commands preserve semantic graph results and reject atomically."""
        operations = {"begin_wave", "hard_stop", "respawn_stale"}
        paths = [
            path
            for path in sorted(FIXTURES.glob("*.json"))
            if json.loads(path.read_text(encoding="utf-8"))["operation"] in operations
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, fixture_path in enumerate(paths):
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                fixture_home = Path(directory) / str(index)
                fixture_home.mkdir()
                for name in ("claude", "codex"):
                    with self.subTest(provider=name, fixture=fixture_path.name):
                        provider = Provider(fixture_home, name)
                        provider.write(native_state(provider, fixture))
                        operation = fixture["operation"]
                        request = fixture.get("request", {})
                        arguments = (
                            ()
                            if operation == "begin_wave"
                            else (
                                "--node",
                                request["node_id"],
                                "--session",
                                provider.session,
                                "--reason",
                                request["reason"],
                            )
                        )
                        before = provider.path.read_bytes()
                        result = provider.call(operation.replace("_", "-"), *arguments)
                        expected = fixture["expected"]
                        if "error" in expected:
                            self.assertNotEqual(result.returncode, 0, result.stdout)
                            self.assertEqual(provider.path.read_bytes(), before)
                        else:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(semantic_graph(provider.read()), expected["state"])

    def test_native_record_wave_refusals_preserve_state_bytes(self) -> None:
        """Malformed and incomplete corpus wave reports never write native state."""
        fixtures = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(FIXTURES.glob("*.json"))]
        refusals = [
            (path, fixture)
            for path, fixture in fixtures
            if fixture["operation"] == "record_wave" and "error" in fixture["expected"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (path, fixture) in enumerate(refusals):
                fixture_home = Path(directory) / str(index)
                fixture_home.mkdir()
                for name in ("claude", "codex"):
                    with self.subTest(provider=name, fixture=path.name):
                        provider = Provider(fixture_home, name)
                        provider.write(native_state(provider, fixture))
                        before = provider.path.read_bytes()
                        result = provider.call("record-wave", json.dumps(fixture["request"]))
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertEqual(provider.path.read_bytes(), before)

    def test_native_record_wave_successes_preserve_semantic_results(self) -> None:
        """Bind real fixture transcripts while comparing the core transition."""
        fixtures = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(FIXTURES.glob("*.json"))]
        successes = [
            (path, fixture)
            for path, fixture in fixtures
            if fixture["operation"] == "record_wave" and "error" not in fixture["expected"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (path, fixture) in enumerate(successes):
                fixture_home = Path(directory) / str(index)
                fixture_home.mkdir()
                for name in ("claude", "codex"):
                    # This corpus case starts after a prior failed attempt, represented
                    # only by a semantic string. Codex requires that attempt's native
                    # worker reference and transcript before it can bind the next one.
                    if name == "codex" and path.name == "26-retry-exhaustion.json":
                        continue
                    with self.subTest(provider=name, fixture=path.name):
                        provider = Provider(fixture_home, name)
                        state = native_state(provider, fixture)
                        state["graph"]["active_wave"]["transcript_cursor"] = 0 if name == "claude" else 1
                        provider.write(state)
                        outcomes = {entry["outcome"] for entry in fixture["request"]["results"].values()}
                        provider.launch("stale" if outcomes == {"stale"} else "done")
                        result = provider.call("record-wave", json.dumps(fixture["request"]))
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(semantic_graph(provider.read()), fixture["expected"]["state"])
                        response = json.loads(result.stdout)
                        self.assertEqual(response["revision"], fixture["expected"]["state"]["revision"])
                        for key in ("released_joins", "ready"):
                            self.assertEqual(response[key], fixture["expected"][key])

    def test_native_completion_reports_corpus_blockers(self) -> None:
        """The CLI exposes graph blockers before its provider completion gates."""
        with tempfile.TemporaryDirectory() as directory:
            paths = sorted(FIXTURES.glob("*.json"))
            for index, path in enumerate(paths):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                if fixture["operation"] != "can_complete":
                    continue
                fixture_home = Path(directory) / str(index)
                fixture_home.mkdir()
                for name in ("claude", "codex"):
                    with self.subTest(provider=name, fixture=path.name):
                        provider = Provider(fixture_home, name)
                        state = native_state(provider, fixture)
                        if name == "claude":
                            state["graph"]["wave_history"] = {}
                        provider.write(state)
                        before = provider.path.read_bytes()
                        result = provider.complete()
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(provider.path.read_bytes(), before)
                        for blocker in fixture["expected"]["blockers"]:
                            self.assertIn(blocker, result.stderr)
                        if fixture["expected"]["eligible"]:
                            provider_gate = "native attempt history" if name == "claude" else "work unit"
                            self.assertIn(provider_gate, result.stderr)


if __name__ == "__main__":
    unittest.main()
