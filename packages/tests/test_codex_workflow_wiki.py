"""Reuse local vault scenarios against the independent Codex wiki-debt implementation."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex"))
from scripts.lib import git_common, wiki_debt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.tests import merge_wiki_debt_test, workflow_wiki_fixture


class CodexWikiDebtTests(merge_wiki_debt_test.WikiDebtTests):
    """Apply the same real local Git fixtures to the separately installed provider copy."""

    def setUp(self) -> None:
        """Bind fixture command and gate calls to Codex's independent modules."""
        super().setUp()
        provider = Path(__file__).resolve().parents[1] / "codex"
        self.assertTrue(Path(wiki_debt.__file__).resolve().is_relative_to(provider))
        self.assertTrue(Path(git_common.__file__).resolve().is_relative_to(provider))
        self.enter_provider("wiki_debt", wiki_debt)
        self.enter_provider("git_common", git_common)

    def enter_provider(self, name: str, module: object) -> None:
        """Restore the fixture binding after every case, including failures."""
        binding = patch.object(workflow_wiki_fixture, name, module)
        binding.start()
        self.addCleanup(binding.stop)


if __name__ == "__main__":
    unittest.main(defaultTest="CodexWikiDebtTests")
