#!/usr/bin/env python3
"""Execute both providers' documented safe YAML validator against real positive and negative fixtures."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import ROOT, HookTestCase

PROGRAM = 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], aliases: false)'


class InitYamlValidationTests(HookTestCase):
    """Malformed YAML, aliases, object tags, and missing files must never pass the documented validator."""

    def test_shared_documented_validator_rejects_unsafe_input(self) -> None:
        """Both docs name the same safe command, which really rejects every unsafe fixture."""
        for relative in ("commands/init.md", "packages/codex/skills/init/SKILL.md"):
            commands = re.findall(r"ruby -e '([^']*)' <path>", (ROOT / relative).read_text())
            self.assertEqual(commands, [PROGRAM])
        cases = {
            "valid.yaml": ("project: example\n", True),
            "malformed.yaml": ("project: [\n", False),
            "alias.yaml": ("defaults: &defaults\n  project: example\ncopy: *defaults\n", False),
            "unsafe.yaml": ("!ruby/object:Object {}\n", False),
            "missing.yaml": (None, False),
        }
        for name, (contents, accepted) in cases.items():
            path = self.directory / name
            if contents is not None:
                path.write_text(contents)
            result = subprocess.run(["ruby", "-e", PROGRAM, str(path)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode == 0, accepted, name)


if __name__ == "__main__":
    unittest.main()
