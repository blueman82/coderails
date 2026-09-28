"""Resolve native runner target constants against real source files for both providers."""

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class RunnerTargetTests(unittest.TestCase):
    """Every runner entrypoint has an audited target contract; unknown wrappers fail."""

    def test_real_targets_and_missing_target_control(self) -> None:
        """Keep nonexistent dist targets from silently reaching production launchd jobs."""
        for prefix in ("skills.dashboard", "packages.codex.skills.dashboard"):
            base = ROOT / prefix.replace(".", "/")
            actual = {path.name for path in (base / "runner/bin").glob("*.py")}
            self.assertEqual(actual, {"dashboard_server.py", "seed_and_sweep.py", "sweeper.py"})
            for name in ("seed_and_sweep", "sweeper"):
                module = importlib.import_module(f"{prefix}.runner.bin.{name}")
                self.assertEqual(module.NODE, "/opt/homebrew/bin/node")
                self.assertTrue(module.TARGET.is_file(), str(module.TARGET))
                self.assertEqual(module.TARGET, base / "runner/src/main.ts")
                if name == "seed_and_sweep":
                    self.assertTrue(module.SEED.is_file())
                    self.assertEqual(module.SEED, base / "runner/src/seedMain.ts")
            self.assertFalse((base / "runner/dist/nonexistent-regression-control.js").is_file())


if __name__ == "__main__":
    unittest.main()
