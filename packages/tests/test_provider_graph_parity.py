"""Require equivalent safety transitions through independently installed provider CLIs."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import ROOT, Provider


class ProviderParityTests(unittest.TestCase):
    """Compare common outcomes while asserting distinct native identity field names."""

    def setUp(self) -> None:
        """Give each provider isolated HOME and durable state for every test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def test_malformed_legacy_unknown_and_exact_wave_atomicity(self) -> None:
        """No provider mutates state on malformed graphs or partial/extra wave results."""
        for provider in self.providers:
            baseline = provider.state(("U3[1]", "U3[2]"))
            for state in ({**baseline, "schema_version": 2}, {**baseline, "revision": None}):
                provider.write(state)
                before = provider.path.read_bytes()
                self.assertNotEqual(provider.call("begin-wave").returncode, 0)
                self.assertEqual(before, provider.path.read_bytes())
            provider.path.write_text("not-json")
            self.assertNotEqual(provider.call("begin-wave").returncode, 0)
            state = copy.deepcopy(baseline)
            state["graph"]["edges"] = [{"from": "UNKNOWN", "to": "U3[1]"}]
            provider.write(state)
            self.assertNotEqual(provider.call("begin-wave").returncode, 0)
            provider.write(baseline)
            wave = provider.success("begin-wave")
            self.assertEqual(wave["nodes"], ["U3[1]", "U3[2]"])
            report = provider.launch()
            for results in (
                {"U3[1]": report["results"]["U3[1]"]},
                {**report["results"], "U4[1]": {"outcome": "done", "evidence": "extra"}},
            ):
                before = provider.path.read_bytes()
                self.assertNotEqual(
                    provider.call("record-wave", json.dumps({**report, "results": results})).returncode, 0
                )
                self.assertEqual(before, provider.path.read_bytes())

    def test_fanout_join_next_wave_and_retry_identity(self) -> None:
        """Both providers release joins and retain native references for each failed attempt."""
        for provider in self.providers:
            state = provider.state(("U3[1]", "U3[2]", "J12-all-units", "S9-wiki"))
            state["graph"]["edges"] = [{"from": "J12-all-units", "to": "S9-wiki"}]
            state["graph"]["joins"] = {
                "J12-all-units": {"id": "J12-all-units", "mode": "all", "inputs": ["U3[1]", "U3[2]"], "released": False}
            }
            provider.write(state)
            result = provider.finish_wave()
            self.assertEqual(result["released_joins"], ["J12-all-units"])
            self.assertEqual(provider.success("begin-wave")["nodes"], ["S9-wiki"])
            provider.success("record-wave", json.dumps(provider.launch()))
        for provider in self.providers:
            provider.parent.write_text("")
            if provider.name == "codex":
                provider.parent.write_text(json.dumps({"type": "session_meta", "payload": {"id": "parent"}}) + "\n")
                for path in provider.parent.parent.glob("fixture-child-*.jsonl"):
                    path.unlink()
            state = provider.state()
            state["graph"]["nodes"]["U3[1]"]["retry"]["max"] = 2
            provider.write(state)
            for attempt in (1, 2):
                provider.finish_wave("failed")
                saved = provider.read()["graph"]["nodes"]["U3[1]"]
                self.assertEqual(saved["retry"]["attempts"], attempt)
            saved = provider.read()["graph"]["nodes"]["U3[1]"]
            refs: list[dict[str, Any]] = [entry for entry in saved["evidence"] if isinstance(entry, dict)]
            self.assertEqual([entry["attempt"] for entry in refs], [1, 2])
            fields = (
                ("tool_use_id", "record_uuid")
                if provider.name == "claude"
                else ("spawn_call_id", "agent_thread_id", "task_complete_turn_id")
            )
            for field in fields:
                self.assertEqual(len({entry[field] for entry in refs}), 2)
                self.assertTrue(all(isinstance(entry[field], str) and entry[field] for entry in refs))
            inspected = provider.success("inspect")
            self.assertEqual(inspected["session_id"], provider.session)
            self.assertEqual(inspected["ready"], [])
            self.assertIsNotNone(inspected["hard_stop"])

    def test_completion_identity_teardown_and_graph_refusals(self) -> None:
        """Completed nodes cannot bypass stale evals, missing teardown or unfinished peers."""
        for provider in self.providers:
            provider.finish_wave()
            provider.artifacts()
            original = provider.read()
            result = provider.complete()
            self.assertEqual(result.returncode, 0, result.stderr)
            provider.write(original)
            for changes in ({"status": "pending", "outcome": "pending"},):
                altered = copy.deepcopy(original)
                altered["graph"]["nodes"]["U3[1]"].update(changes)
                provider.write(altered)
                before = provider.path.read_bytes()
                self.assertNotEqual(provider.complete().returncode, 0)
                self.assertEqual(before, provider.path.read_bytes())
            provider.write(original)
            suite = provider.read("evals.json")
            provider.write({**suite, "loop_id": "stale"}, "evals.json")
            self.assertNotEqual(provider.complete().returncode, 0)
            provider.write(suite, "evals.json")
            provider.path.with_name("retro.json").write_text("")
            self.assertNotEqual(provider.complete().returncode, 0)

    def test_native_dispatch_ownership_and_frozen_gates(self) -> None:
        """Provider-native worker labels require matching predispatch state and frozen evals."""
        for provider in self.providers:
            state = provider.state()
            state["work_units"] = {"unit": {"status": "pending"}}
            provider.write(state)
            provider.success("begin-wave")
            request = provider.request()
            result = provider.hook("loop_dispatch_guard", request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            original = provider.read()
            suite = provider.read("evals.json")
            for artifact in ({**suite, "loop_id": "stale"}, {}):
                provider.write(artifact, "evals.json")
                before = provider.path.read_bytes()
                result = provider.hook("loop_dispatch_guard", request)
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
                self.assertEqual(before, provider.path.read_bytes())
            provider.write(suite, "evals.json")
            for key in ("loop_id", "revision"):
                altered = copy.deepcopy(original)
                del altered[key]
                provider.write(altered)
                result = provider.hook("loop_dispatch_guard", request)
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
            provider.write(original)
            for session in ("foreign", provider.session):
                if session == provider.session:
                    provider.path.unlink()
                result = provider.hook("loop_dispatch_guard", {**request, "session_id": session})
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_recover_wave_is_equivalent_and_bounded(self) -> None:
        """Both CLIs report, recover once, refuse past retry.max and trace the same reason codes."""
        for provider in self.providers:
            state = provider.state()
            state["graph"]["nodes"]["U3[1]"]["retry"]["max"] = 1
            provider.write(state)
            args = ("--session", provider.session, "--lease-seconds", "600")
            provider.success("begin-wave")
            before = provider.path.read_bytes()
            self.assertEqual(provider.success("recover-wave", *args)["reason_code"], "no_spawn_dispatch")
            provider.launch("stale")
            self.assertEqual(provider.success("recover-wave", *args, "--report-only")["recovered"], False)
            foreign = provider.call("recover-wave", "--session", "foreign", "--lease-seconds", "600")
            self.assertNotEqual(foreign.returncode, 0)
            self.assertEqual(before, provider.path.read_bytes())
            self.assertEqual(provider.success("recover-wave", *args)["reason_code"], "recovered")
            recovered = provider.read()["graph"]
            self.assertIsNone(recovered["active_wave"])
            self.assertEqual(recovered["nodes"]["U3[1]"]["respawn"]["generation"], 1)
            provider.success("begin-wave")
            provider.launch("stale")
            before = provider.path.read_bytes()
            refused = provider.call("recover-wave", *args)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("recovery budget", refused.stderr)
            self.assertEqual(before, provider.path.read_bytes())
            rows = [
                json.loads(line) for line in provider.path.with_name("recovery-trace.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                [row["reason_code"] for row in rows],
                [
                    "no_spawn_dispatch",
                    "stalled_report_only",
                    "foreign_session",
                    "recovered",
                    "recovery_budget_exhausted",
                ],
            )
            self.assertEqual(provider.success("summarize")["phase"], "waiting for worker")

    def test_controller_commands_return_the_same_reason_codes_for_the_same_inputs(self) -> None:
        """Start and add-unit refuse identically: same exit status and reason code on both providers."""
        outcomes: dict[str, list[tuple[int, str]]] = {}
        for provider in self.providers:
            provider.path.unlink()
            session, loop = provider.session, "parity-loop"
            prompt = provider.home / "prompt.txt"
            prompt.write_text("go")
            start = ("--session", session, "--loop-id", loop, "--prompt-file", str(prompt))
            add = ("--session", session, "--loop-id", loop, "--unit")
            calls = [
                ("add-unit", *add, "1"),  # no state yet
                ("start", *start),
                ("start", *start),
                ("start", "--session", session, "--loop-id", "other", "--prompt-file", str(prompt)),
                ("add-unit", *add, "1"),
                ("add-unit", *add, "1"),
                ("add-unit", *add, " "),
                ("add-unit", *add, "2", "--depends-on", "7"),
            ]
            outcomes[provider.name] = []
            for command, *arguments in calls:
                result = provider.call(command, *arguments)
                found = re.search(r"reason_code=(\w+)", result.stderr) or re.search(
                    r'"reason_code": "(\w+)"', result.stdout
                )
                outcomes[provider.name].append((result.returncode, found.group(1) if found else ""))
        self.assertEqual(outcomes["claude"], outcomes["codex"])
        self.assertEqual(
            [code for _, code in outcomes["claude"]],
            [
                "add_unit_refused_state",
                "start_created",
                "start_noop",
                "start_refused_active_loop",
                "add_unit_registered",
                "add_unit_refused_duplicate",
                "add_unit_refused_bad_id",
                "add_unit_refused_unknown_dep",
            ],
        )

    def test_skill_prose_names_the_controller_commands_and_embeds_no_stub_json(self) -> None:
        """No document tells the model to hand-write the stub: each names `start`/`add-unit` and carries no stub."""
        named = (ROOT / "skills/agentic-loop/SKILL.md", ROOT / "packages/codex/skills/agentic-loop/SKILL.md")
        stubbed = (
            *named,
            ROOT / "skills/agentic-loop/phases-setup.md",
            ROOT / "skills/agentic-loop/loop-state.md",
            ROOT / "commands/prep.md",
        )
        for path in named:
            text = path.read_text()
            for command in ("start", "add-unit"):
                self.assertRegex(text, rf'graph\.py"? {command}\b', f"{path.name} must name graph.py {command}")
        for path in stubbed:
            text = path.read_text()
            with self.subTest(document=str(path.relative_to(ROOT))):
                self.assertNotIn('"schema_version": 3', text)
                self.assertNotIn('"status": "initialising"', text)
        for path in (ROOT / "skills/agentic-loop/phases-setup.md", ROOT / "commands/prep.md"):
            self.assertRegex(path.read_text(), r'graph\.py"? start\b', path.name)

    def test_prose_only_directs_commands_the_cli_has(self) -> None:
        """Every `graph.py <word>` the skill prose names is a real subcommand on both providers; no `status` command."""
        for provider, base in (
            ("claude", ROOT / "skills/agentic-loop"),
            ("codex", ROOT / "packages/codex/skills/agentic-loop"),
        ):
            usage = subprocess.run(
                [sys.executable, str(base / "scripts/graph.py"), "-h"], capture_output=True, text=True, check=True
            ).stdout
            real = set(re.search(r"\{([a-z,-]+)\}", usage).group(1).split(","))  # type: ignore[union-attr]
            for doc in sorted(base.glob("*.md")):
                text = doc.read_text()
                with self.subTest(provider=provider, doc=doc.name):
                    named = set(re.findall(r'graph\.py"? ([a-z][a-z-]+)\b', text))
                    self.assertLessEqual(named, real, f"{doc.name} names a command graph.py lacks")
                    self.assertIsNone(re.search(r"`status`[^.;)]*commands", text), "`status` is not a graph.py command")

    def test_native_provider_boundaries(self) -> None:
        """Skills dispatch only their native provider and no retired shared scheduler exists."""
        claude = (ROOT / "skills/agentic-loop/SKILL.md").read_text()
        codex = (ROOT / "packages/codex/skills/agentic-loop/SKILL.md").read_text()
        self.assertIn("Agent", claude)
        self.assertNotIn("spawn_agent", claude)
        self.assertIn("spawn_agent", codex)
        for text in (claude, codex):
            self.assertNotIn("codex exec", text)
            self.assertNotIn("claude -p", text)
        for path in (
            "skills/index.yaml",
            "packages/codex/runtime",
            "packages/codex/skills/agentic-loop/scripts/scheduler.sh",
            "packages/codex/skills/agentic-loop/scripts/daemon.sh",
        ):
            self.assertFalse((ROOT / path).exists())


if __name__ == "__main__":
    unittest.main()
