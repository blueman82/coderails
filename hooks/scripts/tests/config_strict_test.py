#!/usr/bin/env python3
"""Strict typed config: controls default ON, rejected config denies only the guarded action, sandbox mode is read."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.claude_graph_test_support import GraphCase, dispatch
from hooks.scripts.tests.native_hook_test_support import HookCase
from scripts.lib.config import load_config, require_signatures
from scripts.lib.config_strict import ConfigRejected, controls_resolved, sandbox_mode, strict_settings

ROOT = Path(__file__).resolve().parents[3]
CODEX = ROOT / "packages/codex"
REAL = """project: coderails
wiki_path: /tmp/vault
sandbox_workers: true
action_authority: advisory
diff_manifest: enforce
diff_manifest_policy: .coderails/manifest-policy.json
evals:
  require_signatures: true
"""


def controls(properties: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    """Dotted key to spec for every property flagged control:true."""
    found: dict[str, dict[str, Any]] = {}
    for key, spec in properties.items():
        if spec.get("control"):
            found[prefix + key] = spec
        found |= controls(spec.get("properties", {}), prefix + key + ".")
    return found


class ScratchCase(unittest.TestCase):
    """Throwaway config files; the findings' stderr line and trace rows stay out of the test output."""

    def setUp(self) -> None:
        """Mute stderr and point trace rows at a scratch loop dir."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        for patcher in (
            patch("sys.stderr", io.StringIO()),
            patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": scratch.name}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, text: str) -> Path:
        """Path holding text."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "workflow.config.yaml"
        path.write_text(text)
        return path


class ControlsTests(ScratchCase):
    """(a) An empty valid config turns every control ON."""

    def test_empty_config_resolves_every_control_to_on_value(self) -> None:
        """Every control resolves to on_value once its prerequisite stack is present."""
        schema = json.loads((ROOT / "config.schema.json").read_text())
        found = controls(schema["properties"])
        self.assertGreaterEqual(len(found), 4)
        values, findings = load_config(self.write(""))
        self.assertEqual(findings, [])
        resolved = controls_resolved(values)
        self.assertEqual(sorted(resolved), sorted(found))
        for key, spec in found.items():
            self.assertIn("on_value", spec, key)
            self.assertEqual(resolved[key], spec["on_value"], key)
            self.assertNotIn("blocked_on", spec, f"{key} is ON but still claims to be blocked")

    def test_defaults_that_were_off_are_on(self) -> None:
        """Schema defaults for sandbox_workers, action_authority, evals.require_signatures and diff_manifest."""
        resolved = controls_resolved(load_config(self.write(""))[0])
        self.assertIs(resolved["sandbox_workers"], True)
        self.assertEqual(resolved["action_authority"], "enforce")
        self.assertIs(resolved["evals.require_signatures"], True)
        self.assertEqual(resolved["diff_manifest"], "enforce")


class StrictTests(ScratchCase):
    """(b)(c) strict_settings raises on a bad file and stays quiet on every documented shape."""

    def test_typo_key_raises_naming_the_correct_key(self) -> None:
        """Negative control target: returning findings instead of raising breaks this."""
        with self.assertRaises(ConfigRejected) as caught:
            strict_settings(self.write("sandbox_workerz: true\n"))
        self.assertEqual(caught.exception.findings[0]["code"], "config_unknown_key")
        self.assertEqual(caught.exception.findings[0]["hint"], "sandbox_workers")
        self.assertIn("sandbox_workers", str(caught.exception))

    def test_bad_type_enum_and_unreadable_raise(self) -> None:
        """Each finding class rejects; the enum finding hints the closest allowed value."""
        for text, code in (
            ("sandbox_workers: maybe\n", "config_bad_type"),
            ("action_authority: enforse\n", "config_bad_value"),
            ("diff_manifest: strict\n", "config_bad_value"),
        ):
            with self.subTest(text), self.assertRaises(ConfigRejected) as caught:
                strict_settings(self.write(text))
            self.assertEqual(caught.exception.findings[0]["code"], code)
        with self.assertRaises(ConfigRejected) as caught:
            strict_settings(Path("/nonexistent/workflow.config.yaml"))
        self.assertEqual(caught.exception.findings[0]["code"], "config_unreadable")
        with self.assertRaises(ConfigRejected) as caught:
            strict_settings(self.write("action_authority: enforse\n"))
        self.assertEqual(caught.exception.findings[0]["hint"], "enforce")

    def test_missing_or_corrupt_schema_cannot_resolve_controls_to_off(self) -> None:
        """A missing schema is a typed refusal, never an empty controls table."""
        with (
            patch("scripts.lib.config.SCHEMA_PATH", Path("/not/a/schema.json")),
            self.assertRaises(ConfigRejected) as caught,
        ):
            strict_settings(self.write("sandbox_workers: true\n"))
        self.assertEqual(caught.exception.findings[0]["code"], "config_schema_unreadable")
        with patch("scripts.lib.config_strict.SCHEMA_PATH", Path("/not/a/schema.json")):
            with self.assertRaises(ConfigRejected) as caught:
                controls_resolved({"sandbox_workers": True})
            self.assertEqual(caught.exception.findings[0]["code"], "config_schema_unreadable")
            with self.assertRaises(ConfigRejected):
                sandbox_mode({"sandbox_workers": True})

    def test_documented_shapes_stay_clean(self) -> None:
        """Negative control target: deleting action_authority from the schema makes REAL an unknown_key."""
        init = (ROOT / "commands/init.md").read_text()
        blocks = re.findall(r"```yaml\n(.*?)```", init, re.S)
        self.assertTrue(blocks)
        texts = [("example", (ROOT / "examples/workflow.config.yaml").read_text()), ("real", REAL)]
        texts += [(f"init{i}", block) for i, block in enumerate(blocks)]
        for name, text in texts:
            with self.subTest(name):
                strict_settings(self.write(text))

    def test_malformed_or_repeated_lines_are_findings(self) -> None:
        """A typo in syntax or a repeated key cannot silently disable a control."""
        for text, code in (
            ("action_authority : enforce\n", "config_unparseable_line"),
            ('"action_authority": enforce\n', "config_unparseable_line"),
            ("  action_authority: enforce\n", "config_unparseable_line"),
            ("evals:\n  require_signatures: true\n    nested: 1\n", "config_unparseable_line"),
            ("action_authority: enforce\naction_authority: off\n", "config_duplicate_key"),
            ("evals:\n  require_signatures: true\n  require_signatures: false\n", "config_duplicate_key"),
        ):
            with self.subTest(text), self.assertRaises(ConfigRejected) as caught:
                strict_settings(self.write(text))
            self.assertEqual(caught.exception.findings[0]["code"], code)

    def test_require_signatures_fails_closed(self) -> None:
        """Only an explicit false is OFF; null, a bad type and a rejected config keep signing ON."""
        for text, expected in (
            ("evals:\n  require_signatures:\n", True),
            ("evals:\n  require_signatures: no\n", True),
            ("evals:\n  require_signatures: false\n", False),
            ("evals:\n  require_signatures: false\n  require_signaturez: x\n", True),
        ):
            with self.subTest(text):
                self.assertIs(require_signatures(self.write(text)), expected)

    def test_real_shape_values(self) -> None:
        """Typed values come back for the real-shaped file."""
        values = strict_settings(self.write(REAL))
        self.assertEqual(values["action_authority"], "advisory")
        self.assertEqual(values["diff_manifest_policy"], ".coderails/manifest-policy.json")


class SandboxModeTests(GraphCase):
    """(d) sandbox_workers has a code reader: plan() carries dispatch_mode for U3 nodes."""

    def modes(self) -> dict[str, Any]:
        """dispatch_mode per planned node."""
        return {item["node_id"]: item.get("dispatch_mode") for item in dispatch.plan(self.path)}

    def test_sandbox_mode_values(self) -> None:
        """Off is in-process; on is sandboxed or names the missing executable."""
        self.assertEqual(sandbox_mode({"sandbox_workers": False}), "in-process")
        with patch("scripts.lib.config_strict.shutil.which", return_value="/bin/x"):
            self.assertEqual(sandbox_mode({"sandbox_workers": True}), "sandboxed")

        def no_npx(name: str) -> str | None:
            return None if name == "npx" else "/bin/x"

        with patch("scripts.lib.config_strict.shutil.which", side_effect=no_npx):
            self.assertEqual(sandbox_mode({"sandbox_workers": True}), "in-process-fallback:npx_missing")

    def test_plan_carries_dispatch_mode(self) -> None:
        """Negative control target: removing the plan() line leaves U3[1] with no dispatch_mode."""
        with patch("scripts.lib.config_strict.shutil.which", return_value="/bin/x"):
            self.assertEqual(self.modes()["U3[1]"], "sandboxed")
        with patch("scripts.lib.config_strict.shutil.which", return_value=None):
            self.assertEqual(self.modes()["U3[1]"], "in-process-fallback:npx_missing")


class GuardedActionTests(HookCase):
    """(b) a rejected config denies the guarded action with config_rejected and nothing else."""

    def setUp(self) -> None:
        """Repo on main with a typo'd config."""
        super().setUp()
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / ".coderails").mkdir()
        self.config = self.repo / ".coderails/workflow.config.yaml"
        self.config.write_text("sandbox_workerz: true\n")

    def payload(self, command: str) -> dict[str, Any]:
        """A Bash PreToolUse payload."""
        return {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Bash", "tool_input": {"command": command}}

    def reasons(self) -> list[str]:
        """Trace reasons for s1."""
        path = self.loop / "s1/trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_rejected_config_denies_guarded_action_only(self) -> None:
        """Invalid config is denied for guarded actions; unrelated commands do not trigger the config gate."""
        result = self.invoke("action_authority_gate", self.payload("gh pr merge 12 --squash"))
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("config_rejected", out["permissionDecisionReason"])
        self.assertIn("sandbox_workers", out["permissionDecisionReason"])
        self.assertIn("config_rejected", self.reasons())
        self.assertEqual(self.invoke("action_authority_gate", self.payload("ls -la")).stdout, "")
        self.config.unlink()
        absent = self.invoke("action_authority_gate", self.payload("gh pr merge 12"))
        self.assertEqual(json.loads(absent.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("config_rejected", absent.stdout)


class ParityTests(unittest.TestCase):
    """(f) Claude and Codex ship the same strict module and schema and agree on findings."""

    def test_byte_identical(self) -> None:
        """Module and schema copies must not drift."""
        for relative in ("scripts/lib/config_strict.py", "config.schema.json", "scripts/lib/manifest_policy.py"):
            with self.subTest(relative):
                self.assertEqual((ROOT / relative).read_bytes(), (CODEX / relative).read_bytes())

    def test_same_findings_for_same_file(self) -> None:
        """Run each package's own module on the same bad file."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.config.yaml"
            path.write_text("sandbox_workerz: true\naction_authority: enforse\nsandbox_workers: maybe\n")
            code = (
                "import json,sys\nfrom scripts.lib.config_strict import ConfigRejected, strict_settings\n"
                "try:\n    strict_settings(sys.argv[1])\n"
                "except ConfigRejected as e:\n    print(json.dumps(e.findings))\n"
            )
            out = [
                subprocess.run([sys.executable, "-c", code, str(path)], cwd=root, capture_output=True, text=True).stdout
                for root in (ROOT, CODEX)
            ]
        self.assertTrue(out[0].strip())
        self.assertEqual(out[0], out[1])
        self.assertEqual(len(json.loads(out[0])), 3)


if __name__ == "__main__":
    unittest.main()
