"""The machine-readable graph spec and policy: validation, enforcement, instantiate, plan skip_when, add-unit wiring."""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_semantics  # noqa: E402
import graph_spec  # noqa: E402

from packages.tests.test_provider_controller_commands import LOOP, SESSION, Controller  # noqa: E402
from scripts.lib.spec_counters import count_reasons  # noqa: E402

PROVIDERS = ("claude", "codex")


def spec_copy() -> dict[str, Any]:
    """A mutable copy of the committed spec."""
    return copy.deepcopy(graph_spec.load_spec())


def write_state(controller: Controller, state: dict[str, Any]) -> None:
    """Replace the controller's progress.json with a hand-edited state."""
    controller.path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def inject_join(state: dict[str, Any], with_edge: bool) -> dict[str, Any]:
    """Add an S2.8 -> J2.8 prerequisite pair beside U3[1]; the J2.8 -> U3[1] edge only when asked."""
    graph = state["graph"]
    template = graph["nodes"]["U3[1]"]
    done = {**copy.deepcopy(template), "label": "Assign model roles", "status": "done", "outcome": "done"}
    gate = {**copy.deepcopy(template), "label": "Implementation ready"}
    graph["nodes"]["S2.8"], graph["nodes"]["J2.8"] = done, gate
    graph["joins"]["J2.8"] = {"id": "J2.8", "mode": "all", "inputs": ["S2.8"], "released": False}
    graph["edges"] = [e for e in graph["edges"] if e["to"] != "U3[1]"]
    if with_edge:
        graph["edges"].append({"from": "J2.8", "to": "U3[1]"})
    return state


def instantiate_loop(name: str, scratch: str, profile: str, *units: str) -> tuple[Controller, dict[str, Any]]:
    """Start a loop through one provider's CLI and instantiate it; return the controller and the CLI answer."""
    controller = Controller(Path(scratch), name)
    start = controller.start()
    if start.returncode:
        raise AssertionError(start.stderr)
    tail = ["--session", SESSION, "--loop-id", LOOP, "--profile", profile]
    for unit in units:
        tail += ["--unit", unit]
    result = controller.run("instantiate", *tail)
    if result.returncode:
        raise AssertionError(result.stderr)
    return controller, json.loads(result.stdout)


class SpecValidationTests(unittest.TestCase):
    """The spec is closed, acyclic, resolves every reference and agrees with the pure core's label registry."""

    def test_committed_spec_and_policy_validate(self) -> None:
        """Loading validates; the expansion of three units is acyclic and every join has inputs."""
        spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
        self.assertEqual(policy["graph"]["profile"], "units-only")
        built = graph_spec.expand(spec, policy, ["1", "2", "3"], "full")
        graph_semantics.validate(
            {
                "schema_version": 3,
                "revision": 1,
                "graph": {
                    "nodes": built["nodes"],
                    "edges": [{"from": a, "to": b} for a, b in built["edges"]],
                    "joins": {
                        j: {"id": j, "mode": "all", "inputs": sorted(i), "released": False}
                        for j, i in built["joins"].items()
                    },
                    "active_wave": None,
                    "hard_stop": None,
                },
            }
        )

    def test_spec_labels_equal_the_core_registry(self) -> None:
        """Every concrete spec label is exactly what the unmodified core demands for that id."""
        spec = graph_spec.load_spec()
        for node in spec["nodes"]:
            concrete = node["id"].replace("[i]", "[7]")
            expected = graph_semantics._label_for(concrete)  # pyright: ignore[reportPrivateUsage]
            self.assertEqual(node["label"].replace("{i}", "7"), expected, node["id"])

    def test_sources_and_roles_exist(self) -> None:
        """Every instruction source and agent role the spec names exists in the plugin."""
        for node in graph_spec.load_spec()["nodes"]:
            if node["source"]:
                self.assertTrue((ROOT / node["source"]).is_file(), node["id"])
            if node["agent_role"]:
                self.assertTrue((ROOT / "agents" / f"{node['agent_role']}.md").is_file(), node["id"])

    def test_closed_vocabulary_and_references_are_refused(self) -> None:
        """Unknown fields, kinds, phases, predicates, dangling requirements and cycles are coded refusals."""
        bad_rule = {"predicate": "work_units_lt", "policy_key": "nope"}
        edits: dict[str, tuple[int, dict[str, Any]]] = {  # code -> (node index, field changes)
            "spec_field": (0, {"extra": 1}),
            "spec_kind": (0, {"kind": "mystery"}),
            "spec_phase": (0, {"phase": "later"}),
            "spec_predicate": (10, {"skip_when": {"predicate": "vibes", "policy_key": None}}),
            "spec_policy_key": (10, {"skip_when": bad_rule}),
            "spec_reference": (1, {"requires": ["S-404"]}),
            "spec_cycle": (0, {"requires": ["S0"]}),
        }
        for code, (index, changes) in edits.items():
            spec = spec_copy()
            spec["nodes"][index].update(changes)
            with self.assertRaises(graph_spec.SpecError, msg=code) as raised:
                graph_spec.validate_spec(spec)
            self.assertEqual(raised.exception.code, code)

    def test_policy_is_validated(self) -> None:
        """A non-integer threshold, an over-large retry bound or an unknown profile is refused."""
        for edit in (
            {"design_doc_min_units": "3"},
            {"retry_max": 6},
            {"graph": {"profile": "huge"}},
            {"surprise": 1},
        ):
            with self.assertRaises(graph_spec.SpecError):
                graph_spec.validate_policy({**graph_spec.load_policy(), **edit})

    def test_before_freeze_comes_from_phase(self) -> None:
        """Preparation and freeze nodes need no frozen evals; unit build nodes do."""
        spec = graph_spec.load_spec()
        by_id = {node["id"]: node for node in spec["nodes"]}
        self.assertEqual(by_id["U3[i]"]["phase"], "build")
        self.assertEqual(by_id["S2.7c"]["phase"], "freeze")
        for identifier, expected in (("S2.7c", True), ("S2", True), ("J2.8", True), ("U3[1]", False), ("U3", False)):
            self.assertIs(graph_spec.before_freeze(spec, identifier), expected, identifier)
        self.assertFalse(graph_spec.before_freeze(spec, "S13-proof"))

    def test_hardcoded_tables_are_gone(self) -> None:
        """The dispatch module carries no instruction table and no id-prefix regex."""
        source = (ROOT / "hooks/scripts/lib/graph_dispatch.py").read_text(encoding="utf-8")
        for name in ("before_freeze", "TARGETS"):
            self.assertNotIn(name + " =", source)
            self.assertIsNone(re.search(rf"def {name}\b", source))
        controller = (ROOT / "hooks/scripts/lib/graph_controller.py").read_text(encoding="utf-8")
        self.assertNotIn('JOIN = "J12', controller)


class SpecEnforcementTests(unittest.TestCase):
    """A spec edge whose endpoints both exist but whose edge is absent is refused on every load."""

    def run_provider(self, name: str, scratch: str) -> Controller:
        """A controller with one started loop and unit 1."""
        controller = Controller(Path(scratch), name)
        self.assertEqual(controller.start().returncode, 0)
        self.assertEqual(controller.add("1").returncode, 0)
        return controller

    def test_missing_spec_edge_is_refused_everywhere(self) -> None:
        """inspect, begin-wave and add-unit refuse; restoring the edge restores them."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = self.run_provider(name, scratch)
                write_state(controller, inject_join(controller.read(), with_edge=False))
                before = controller.path.read_bytes()
                for result in (controller.run("inspect"), controller.run("begin-wave"), controller.add("2")):
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("spec_edge_missing", result.stderr)
                self.assertEqual(controller.path.read_bytes(), before)
                self.assertGreaterEqual(count_reasons(controller.root / "state")["spec_edge_missing"], 3)
                write_state(controller, inject_join(controller.read(), with_edge=True))
                self.assertEqual(controller.run("inspect").returncode, 0)

    def test_legacy_units_only_graph_still_loads(self) -> None:
        """A markerless graph made by start and add-unit loads and keeps adding units."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = self.run_provider(name, scratch)
                self.assertEqual(controller.add("2", "--depends-on", "1", "--join").returncode, 0)
                self.assertEqual(controller.run("inspect").returncode, 0)
                self.assertNotIn("spec_sha256", controller.read()["graph"])

    def test_add_unit_wires_the_prerequisite_join_from_the_spec(self) -> None:
        """With J2.8 present a new unit is wired behind it; without, no extra edge appears."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = self.run_provider(name, scratch)
                self.assertEqual(controller.read()["graph"]["edges"], [])
                write_state(controller, inject_join(controller.read(), with_edge=True))
                self.assertEqual(controller.add("2").returncode, 0)
                edges = controller.read()["graph"]["edges"]
                self.assertIn({"from": "J2.8", "to": "U3[2]"}, edges)

    def test_stamped_graph_rejects_drift(self) -> None:
        """A forged spec hash, an unknown node and a removed spec node are each refused with their code."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = Controller(Path(scratch), name)
                self.assertEqual(controller.start().returncode, 0)
                self.assertEqual(controller.run("instantiate", *self.args("full", "1")).returncode, 0)
                good = controller.read()
                forged = copy.deepcopy(good)
                forged["graph"]["spec_sha256"] = "0" * 64
                missing = copy.deepcopy(good)
                missing["graph"]["nodes"].pop("S9-docs")
                missing["graph"]["edges"] = [e for e in missing["graph"]["edges"] if "S9-docs" not in e.values()]
                unknown = copy.deepcopy(good)
                unknown["graph"]["nodes"]["S2.7d[9]"] = copy.deepcopy(unknown["graph"]["nodes"]["S2.7d[1]"])
                unknown["graph"]["nodes"]["S2.7d[9]"]["label"] = "Freeze unit 9 evaluation"
                for code, state in (
                    ("spec_hash_mismatch", forged),
                    ("spec_node_missing", missing),
                    ("spec_unknown_node", unknown),
                ):
                    write_state(controller, state)
                    result = controller.run("inspect")
                    self.assertEqual(result.returncode, 1, code)
                    self.assertIn(code, result.stderr)

    def test_dropped_join_input_is_refused_on_a_stamped_graph(self) -> None:
        """Leaving a unit out of the all-units join, or removing the join, is refused with spec_join_inputs."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = Controller(Path(scratch), name)
                self.assertEqual(controller.start().returncode, 0)
                self.assertEqual(controller.run("instantiate", *self.args("units-only", "1", "2")).returncode, 0)
                good = controller.read()
                short = copy.deepcopy(good)
                short["graph"]["joins"]["J12-all-units"]["inputs"].remove("U3[2]")
                gone = copy.deepcopy(good)
                del gone["graph"]["joins"]["J12-all-units"]
                for state in (short, gone):
                    write_state(controller, state)
                    result = controller.run("inspect")
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("spec_join_inputs", result.stderr)

    def test_stamped_profile_cannot_fall_below_the_policy_floor(self) -> None:
        """A units-only stamp under a full policy is refused; a full stamp under units-only is fine."""
        with tempfile.TemporaryDirectory() as scratch:
            controller = Controller(Path(scratch), "claude")
            self.assertEqual(controller.start().returncode, 0)
            self.assertEqual(controller.run("instantiate", *self.args("units-only", "1")).returncode, 0)
            state = controller.read()
            floor = {**graph_spec.load_policy(), "graph": {"profile": "full"}}
            with patch.object(graph_spec, "load_policy", return_value=floor):
                self.assertRaisesRegex(graph_spec.SpecError, "spec_profile_downgrade", graph_spec.check, state)
            graph_spec.check(state)

    def test_env_off_switch_skips_the_check(self) -> None:
        """CODERAILS_GRAPH_SPEC=off lets a spec-violating graph load on both providers; unset refuses again."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = self.run_provider(name, scratch)
                write_state(controller, inject_join(controller.read(), with_edge=False))
                self.assertEqual(controller.run("inspect").returncode, 1)
                controller.env["CODERAILS_GRAPH_SPEC"] = "off"
                self.assertEqual(controller.run("inspect").returncode, 0)

    @staticmethod
    def args(profile: str, *units: str) -> list[str]:
        """The shared instantiate argument tail."""
        tail = ["--session", SESSION, "--loop-id", LOOP, "--profile", profile]
        for unit in units:
            tail += ["--unit", unit]
        return tail


class InstantiateTests(unittest.TestCase):
    """`instantiate` builds exactly the spec, stamps it, no-ops on a re-run and is identical on both providers."""

    def instantiate(self, name: str, scratch: str, profile: str, *units: str) -> tuple[Controller, dict[str, Any]]:
        """Start a loop and instantiate it; return the controller and the CLI answer."""
        return instantiate_loop(name, scratch, profile, *units)

    def test_full_profile_is_set_equal_to_expand(self) -> None:
        """Nodes, edges, joins and labels equal graph_spec.expand and the core registry; the stamp is present."""
        spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
        want = graph_spec.expand(spec, policy, ["1", "2"], "full")
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, answer = self.instantiate(name, scratch, "full", "1", "2")
                self.assertEqual(answer["reason_code"], "instantiate_ok")
                graph = controller.read()["graph"]
                self.assertEqual(set(graph["nodes"]), set(want["nodes"]))
                self.assertEqual({(e["from"], e["to"]) for e in graph["edges"]}, set(want["edges"]))
                self.assertEqual({k: set(v["inputs"]) for k, v in graph["joins"].items()}, want["joins"])
                for identifier, node in graph["nodes"].items():
                    self.assertEqual(node["label"], graph_semantics._label_for(identifier))  # pyright: ignore
                    self.assertEqual(node["retry"]["max"], 5)
                self.assertEqual(graph["spec_sha256"], graph_spec.spec_sha256(spec))
                self.assertEqual(graph["spec_profile"], "full")
                self.assertEqual(controller.run("inspect").returncode, 0)
                self.assertEqual(count_reasons(controller.root / "state")["instantiate_ok"], 1)

    def test_default_profile_comes_from_policy(self) -> None:
        """Without --profile the policy's units-only profile builds only the unit lane and its join."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller = Controller(Path(scratch), name)
                self.assertEqual(controller.start().returncode, 0)
                args = ["--session", SESSION, "--loop-id", LOOP, "--unit", "1"]
                self.assertEqual(controller.run("instantiate", *args).returncode, 0, name)
                self.assertEqual(set(controller.read()["graph"]["nodes"]), {"U3[1]", "J12-all-units"})

    def test_rerun_is_a_noop_and_foreign_graphs_are_refused(self) -> None:
        """An identical re-run writes nothing; a hand-built graph is refused with a coded reason."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, _ = self.instantiate(name, scratch, "full", "1")
                before = controller.path.read_bytes()
                again = controller.run("instantiate", *SpecEnforcementTests.args("full", "1"))
                self.assertEqual(json.loads(again.stdout)["reason_code"], "instantiate_noop")
                self.assertEqual(controller.path.read_bytes(), before)
            with self.subTest(name + "-foreign"), tempfile.TemporaryDirectory() as scratch:
                controller = Controller(Path(scratch), name)
                self.assertEqual(controller.start().returncode, 0)
                self.assertEqual(controller.add("1").returncode, 0)
                refused = controller.run("instantiate", *SpecEnforcementTests.args("full", "2"))
                self.assertEqual(refused.returncode, 1)
                self.assertIn("instantiate_refused_nonempty", refused.stderr)

    def test_add_unit_extends_a_stamped_full_graph_from_the_spec(self) -> None:
        """A stamped full graph grows by a whole unit lane and still loads."""
        for name in PROVIDERS:
            with self.subTest(name), tempfile.TemporaryDirectory() as scratch:
                controller, _ = self.instantiate(name, scratch, "full", "1")
                self.assertEqual(controller.add("2").returncode, 0)
                state = controller.read()
                spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
                want = graph_spec.expand(spec, policy, ["1", "2"], "full")
                self.assertEqual(set(state["graph"]["nodes"]), set(want["nodes"]))
                self.assertTrue(want["edges"] <= {(e["from"], e["to"]) for e in state["graph"]["edges"]})
                self.assertEqual(controller.run("inspect").returncode, 0)

    def test_both_providers_write_the_same_graph(self) -> None:
        """Identical input yields identical graph and identical stdout apart from clock-derived fields."""
        seen: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for name in PROVIDERS:
            with tempfile.TemporaryDirectory() as scratch:
                controller, answer = self.instantiate(name, scratch, "full", "1", "2")
                state = controller.read()
                seen.append((state["graph"], {k: state["work_units"][k] for k in sorted(state["work_units"])}))
                self.assertEqual(answer["revision"], state["revision"])
        self.assertEqual(seen[0], seen[1])


class PlanSkipWhenTests(unittest.TestCase):
    """`plan` computes skip_when_met from policy in code, not from a constant."""

    def ready_plan(self, units: tuple[str, ...]) -> list[dict[str, Any]]:
        """Instantiate a full graph with its early prep done so S2.7a is ready, then run plan in-process."""
        from hooks.scripts.lib import graph_dispatch

        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        controller, _ = instantiate_loop("claude", scratch.name, "full", *units)
        state = controller.read()
        for identifier in ("S-2", "S-1", "S0", "S0.4", "S0.5", "S1", "S2", "S2.5", "S2.6", "J2"):
            state["graph"]["nodes"][identifier].update(status="done", outcome="done")
        state["graph"]["joins"]["J2"]["released"] = True
        write_state(controller, state)
        return graph_dispatch.plan(controller.path)

    def test_skip_when_met_follows_the_unit_count_and_the_policy(self) -> None:
        """True at two units and false at three; flipping design_doc_min_units flips it."""
        by_id = {item["node_id"]: item for item in self.ready_plan(("1", "2"))}
        self.assertIs(by_id["S2.7a"]["skip_when_met"], True)
        self.assertNotIn("skip_when_met", by_id["S2.7c"])
        self.assertEqual(by_id["S2.7a"]["path"], "agents/spec-reviewer.md")
        self.assertEqual(by_id["S2.7c"]["path"], "skills/task-evals/SKILL.md")
        self.assertIs({i["node_id"]: i for i in self.ready_plan(("1", "2", "3"))}["S2.7a"]["skip_when_met"], False)
        with tempfile.TemporaryDirectory() as scratch:
            flipped = Path(scratch) / "policy.yaml"
            flipped.write_text(json.dumps({**graph_spec.load_policy(), "design_doc_min_units": 2}), encoding="utf-8")
            with patch.object(graph_spec, "POLICY_FILE", flipped):
                self.assertIs({i["node_id"]: i for i in self.ready_plan(("1", "2"))}["S2.7a"]["skip_when_met"], False)

    def test_cross_unit_dependency_prevents_the_skip(self) -> None:
        """Two units with a dependency edge still need the design docs."""
        spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
        units: dict[str, Any] = {"1": {}, "2": {}}
        chained: dict[str, Any] = {"work_units": units, "graph": {"edges": [{"from": "U3[1]", "to": "U3[2]"}]}}
        free: dict[str, Any] = {"work_units": units, "graph": {"edges": []}}
        self.assertFalse(graph_spec.skip_when_met(chained, spec, policy, "S2.7a"))
        self.assertTrue(graph_spec.skip_when_met(free, spec, policy, "S2.7a"))


if __name__ == "__main__":
    unittest.main()
