"""Audit callable/import modes using an isolated Git index, without staging user work."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "hooks/scripts/tests/fixtures/python_entrypoint_modes.json"


def index_modes(root: Path) -> dict[str, str]:
    """Read the actual index format used by installer mode restoration."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z"], check=True, capture_output=True, text=True
    )
    return {row.split("\t", 1)[1]: row.split(" ", 1)[0] for row in result.stdout.split("\0") if row}


class ExecutableModeTests(unittest.TestCase):
    """Explicit audited modes distinguish import libraries from callable entrypoints."""

    def test_audited_sources_and_private_index_modes(self) -> None:
        """Include every Python production module and preserve its exact mode in an index."""
        expected = json.loads(MANIFEST.read_text())
        for directory in ("scripts", "hooks/scripts", "launchd"):
            for path in (ROOT / directory).rglob("*.py"):
                if any(part in ("tests", "fixtures", "__pycache__") for part in path.parts):
                    continue
                self.assertIn(str(path.relative_to(ROOT)), expected, "new production file needs call-site audit")
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            for relative, mode in expected.items():
                source = ROOT / relative
                self.assertTrue(source.is_file(), relative)
                self.assertEqual(source.stat().st_mode & 0o777, int(mode, 8) & 0o777, relative)
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
            subprocess.run(["git", "init", "-q", str(snapshot)], check=True, env=env)
            subprocess.run(["git", "-C", str(snapshot), "add", "."], check=True, env=env)
            self.assertEqual(index_modes(snapshot), expected)
            subprocess.run(
                ["git", "-C", str(snapshot), "update-index", "--chmod=-x", "install.py"], check=True, env=env
            )
            self.assertNotEqual(index_modes(snapshot), expected, "nonexecutable CLI negative control must fail")
            subprocess.run(
                ["git", "-C", str(snapshot), "update-index", "--chmod=+x", "scripts/lib/git_common.py"],
                check=True,
                env=env,
            )
            self.assertEqual(index_modes(snapshot)["scripts/lib/git_common.py"], "100755")
            self.assertNotEqual(index_modes(snapshot), expected, "executable import library control must fail")


if __name__ == "__main__":
    unittest.main()
