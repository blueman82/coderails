"""Prove OS containment with the real pinned runtime and disposable local fixtures (skipped when srt is not cached)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ROOT
from hooks.scripts.tests.lib.sandbox_fixture import SandboxCase

WRITE = "from pathlib import Path; import sys; Path(sys.argv[1]).open('a').write(sys.argv[2])"


class SandboxLiveTests(SandboxCase):
    """Ground truth writes establish both denial and legitimate-write controls."""

    def test_real_probe_and_escape_surface_denials(self) -> None:
        """(e) ~/.claude.json, the primary refs and the real HOME are unwritable; the scratch clone is writable."""
        self.render()
        result = self.sandbox(
            sys.executable,
            str(ROOT / "scripts/sandbox/sandbox_probe.py"),
            str(self.clone),
            "--primary-git",
            str(self.primary),
            "--real-home",
            str(self.home),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.home / ".claude.json").read_text(), "{}")
        main_ref = self.primary / "refs/heads/main"
        before = (main_ref.read_bytes(), (self.primary / "config").read_bytes())
        targets = (
            main_ref,
            self.primary / "hooks/escape-probe",
            self.primary / "config",
            self.home / ".claude.json",
            self.home / "escape-probe",
            self.home / ".coderails/escape-probe",
        )
        for target in targets:
            with self.subTest(target=target):
                result = self.sandbox(sys.executable, "-c", WRITE, str(target), "escape")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not permitted", result.stdout + result.stderr)
        self.assertEqual((main_ref.read_bytes(), (self.primary / "config").read_bytes()), before)
        self.assertEqual((self.home / ".claude.json").read_text(), "{}")
        self.assertFalse((self.home / "escape-probe").exists())
        inside = self.scratch / "home/.claude.json"  # the worker's own config lives in the scratch HOME
        inside.parent.mkdir()
        result = self.sandbox(sys.executable, "-c", WRITE, str(inside), "state")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
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
        """Preserve the pinned launch log, scrubbed child, containment, cache grant and worker exit."""
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
        self.assertEqual((self.home / ".claude.json").read_text(), "{}")
        clones = list(self.scratch.glob("sw.*/clone/inside-probe.txt"))
        self.assertEqual(len(clones), 1)  # "direct" ran inside its own clone; nothing touched the worktree
        self.assertFalse((self.worktree / "inside-probe.txt").exists())
        logs = list(self.scratch.glob("sw.*/worker.log"))
        self.assertEqual(len(logs), 4)
        self.assertTrue(
            all("@anthropic-ai/sandbox-runtime@0.0.65" in path.read_text().splitlines()[0] for path in logs)
        )


if __name__ == "__main__":
    unittest.main()
