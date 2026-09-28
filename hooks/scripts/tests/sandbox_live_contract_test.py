"""Prove OS containment with the real pinned runtime and disposable local fixtures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ROOT
from hooks.scripts.tests.lib.sandbox_fixture import SandboxCase


class SandboxLiveTests(SandboxCase):
    """Ground truth writes establish both denial and legitimate-write controls."""

    def test_real_probe_and_primary_exec_surface_denials(self) -> None:
        """The probe discriminates and the primary Git execution surfaces remain unchanged."""
        self.render()
        result = self.sandbox(sys.executable, str(ROOT / "scripts/sandbox/sandbox_probe.py"), str(self.worktree))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / ".sandbox-escape-probe").exists())
        self.assertFalse((self.directory.parent / "escape-probe").exists())
        config = self.primary / "config"
        before = config.read_bytes()
        targets = (
            self.primary / "hooks/escape-probe",
            config,
            self.home / ".claude/hooks/escape-probe.py",
            self.home / ".claude/plugins/escape-probe.json",
        )
        for target in targets:
            with self.subTest(target=target):
                result = self.sandbox(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).open('a').write('escape')",
                    str(target),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not permitted", result.stdout + result.stderr)
                if target != config:
                    self.assertFalse(target.exists())
        self.assertEqual(config.read_bytes(), before)
        allowed = self.home / ".claude/legitimate-state"
        result = self.sandbox(
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('state')",
            str(allowed),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(allowed.read_text(), "state")
        result = self.sandbox(
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "--allow-empty",
            "-m",
            "sandbox write control",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_launcher_worker_descendant_cache_and_exit_status(self) -> None:
        """Preserve the pinned launch log, child containment, cache grant and worker exit."""
        for mode, code in (("direct", 0), ("child", 0), ("cache", 0), ("exit", 42)):
            with self.subTest(mode=mode):
                result = self.spawn(mode)
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, code, output)
                self.assertIn("npx --yes @anthropic-ai/sandbox-runtime@0.0.65", output)
                self.assertFalse((self.home / "escape-probe").exists())
                if mode in ("direct", "child"):
                    self.assertIn("not permitted", output)
                if mode == "cache":
                    self.assertIn("xdg-cache-ok:", output)
        self.assertEqual((self.worktree / "inside-probe.txt").read_text(), "inside")
        logs = list(self.scratch.glob("sandbox-worker.*/worker.log"))
        self.assertEqual(len(logs), 4)
        self.assertTrue(
            all("@anthropic-ai/sandbox-runtime@0.0.65" in path.read_text().splitlines()[0] for path in logs)
        )


if __name__ == "__main__":
    unittest.main()
