"""`add-unit --manifest` records unit.manifest identically through both providers; absent flag changes nothing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.test_provider_controller_commands import ControllerCase


class AddUnitManifestTests(ControllerCase):
    """The manifest key is written only when the flag is given."""

    def test_manifest_key_only_when_given(self) -> None:
        """Without --manifest a unit is exactly pending; with it the globs are recorded in order."""
        for c in self.each():
            c.start()
            self.assertEqual(c.add("1").returncode, 0)
            result = c.add("2", "--manifest", "src/**", "--manifest", "docs/*.md")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                c.read()["work_units"],
                {"1": {"status": "pending"}, "2": {"status": "pending", "manifest": ["src/**", "docs/*.md"]}},
            )


if __name__ == "__main__":
    unittest.main()
