"""Malformed capability policy cannot select an ordinary Codex worker route."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
import graph_driver_codex

CODEX = Path(__file__).resolve().parents[1] / "codex"


class CodexPolicyTests(unittest.TestCase):
    """Use the actual command builder with disposable installed-role inputs and no client execution."""

    def fixture(self, base: Path) -> tuple[Path, Path]:
        """Copy only public role policy and metadata into a private fake install."""
        plugin = base / "plugin"
        (plugin / "capabilities").mkdir(parents=True)
        (plugin / "capabilities/profiles.json").write_bytes((CODEX / "capabilities/profiles.json").read_bytes())
        (plugin / "agents").mkdir()
        for role in ("security-reviewer", "loop-worker", "spec-reviewer"):
            (plugin / "agents" / f"{role}.toml").write_bytes((CODEX / "agents" / f"{role}.toml").read_bytes())
        (plugin / "scripts").mkdir()
        (plugin / "scripts/codex_role_session.py").touch()
        prompt = base / "prompt.txt"
        prompt.write_text("inert private policy probe\n")
        return plugin, prompt

    def test_guarded_role_cannot_fall_back_on_malformed_or_worker_grants(self) -> None:
        """An empty or contradictory security policy must fail before returning launch argv."""
        for grants in (None, [], ["shell.raw"], ["worktree.write"], ["shell.raw", "worktree.write"], "repo.inspect"):
            with self.subTest(grants=grants), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                plugin, prompt = self.fixture(base)
                policy = plugin / "capabilities/profiles.json"
                profiles: dict[str, Any] = json.loads(policy.read_text())
                if grants is None:
                    profiles["agents"].pop("security-reviewer")
                else:
                    profiles["agents"]["security-reviewer"] = grants
                policy.write_text(json.dumps(profiles))
                with (
                    patch.object(
                        graph_driver_codex,
                        "__file__",
                        str(plugin / "skills/agentic-loop/scripts/graph_driver_codex.py"),
                    ),
                    patch.dict(
                        os.environ, {"HOME": temporary, "CODEX_HOME": temporary, "PATH": "/never/run"}, clear=True
                    ),
                    self.assertRaisesRegex(ValueError, "driver role capability (profile|policy)"),
                ):
                    graph_driver_codex.command(prompt, base, cli="/never/run/codex", role="security-reviewer")

    def test_spec_and_implementation_roles_keep_their_existing_sandboxes(self) -> None:
        """Intentional empty spec grants remain read-only; a normal implementation worker retains writes."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            plugin, prompt = self.fixture(base)
            for role, sandbox in (("spec-reviewer", "read-only"), ("loop-worker", "workspace-write")):
                with (
                    self.subTest(role=role),
                    patch.object(
                        graph_driver_codex,
                        "__file__",
                        str(plugin / "skills/agentic-loop/scripts/graph_driver_codex.py"),
                    ),
                    patch.dict(
                        os.environ, {"HOME": temporary, "CODEX_HOME": temporary, "PATH": "/never/run"}, clear=True
                    ),
                ):
                    argv, _, _ = graph_driver_codex.command(prompt, base, cli="/never/run/codex", role=role)
                    self.assertEqual(argv[argv.index("--sandbox") + 1], sandbox)


if __name__ == "__main__":
    unittest.main()
