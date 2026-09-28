"""Run actual native wrapper processes with inert Node executables for seed failure controls."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class SeedAndSweepTests(unittest.TestCase):
    """Both independent provider wrappers must reach the sweep after any seed exit."""

    def test_seed_failure_never_suppresses_sweep(self) -> None:
        """Preserve seed 0/1/2 outcomes and exact single-line failure diagnostics."""
        for provider in (ROOT, ROOT / "packages/codex"):
            for status in (0, 1, 2):
                with self.subTest(provider=provider, status=status), tempfile.TemporaryDirectory() as directory:
                    base = Path(directory)
                    log = base / "calls"
                    node = base / "node"
                    node.write_text(
                        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
                        "with open(os.environ['NODE_LOG'],'a') as stream:\n"
                        " stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
                        "status=int(os.environ['SEED_STATUS']) if sys.argv[1].endswith('seedMain.ts') else 0\n"
                        "raise SystemExit(status)\n"
                    )
                    node.chmod(0o755)
                    wrapper = base / "runner/bin/seed_and_sweep.py"
                    wrapper.parent.mkdir(parents=True)
                    source = provider / "skills/dashboard/runner/bin/seed_and_sweep.py"
                    wrapper.write_text(
                        source.read_text().replace('NODE = "/opt/homebrew/bin/node"', f"NODE = {str(node)!r}")
                    )
                    result = subprocess.run(
                        [sys.executable, str(wrapper)],
                        text=True,
                        capture_output=True,
                        env=dict(os.environ, NODE_LOG=str(log), SEED_STATUS=str(status)),
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertEqual([Path(row[0]).name for row in calls], ["seedMain.ts", "main.ts"])
                    expected = f"seed step failed (exit {status}), continuing to sweep\n" if status else ""
                    self.assertEqual(result.stderr, expected)


if __name__ == "__main__":
    unittest.main()
