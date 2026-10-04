"""Build-time drift guards: generated config docs and the wiki page-type tables follow their schemas."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.config import wiki_page_types
from scripts.lib.config_schema_docs import START, splice, table

ROOT = Path(__file__).resolve().parents[3]


def section_tables(text: str) -> list[list[str]]:
    """Backticked directory names in the Directory column of each table under '## Page types'."""
    match = re.search(r"^## Page types\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if match is None:
        raise AssertionError("AGENTS.md has no '## Page types' heading: wiki.schema.json and the doc have drifted")
    tables: list[list[str]] = []
    previous = False
    for line in match[1].splitlines():
        found = re.search(r"`([A-Za-z0-9_-]+)/`", line) if line.startswith("|") else None
        if line.startswith("|") and not previous:
            tables.append([])
        previous = line.startswith("|")
        if found:
            tables[-1].append(found[1])
    return tables


class DriftTests(unittest.TestCase):
    """Fail the build, not the runtime hook."""

    def test_config_table_is_current(self) -> None:
        """docs/REFERENCE.md carries exactly the table rendered from config.schema.json."""
        document = (ROOT / "docs/REFERENCE.md").read_text()
        self.assertIn(START, document)
        self.assertEqual(splice(document, table()), document, "run: python3 scripts/lib/config_schema_docs.py --write")
        # negative control: a stale block is detected
        stale = document.replace("| `sandbox_workers` |", "| `sandbox_worker` |")
        self.assertNotEqual(splice(stale, table()), stale)

    def test_agents_page_types_match_wiki_schema(self) -> None:
        """AGENTS.md page-type and structural tables equal wiki.schema.json; a renamed heading fails."""
        schema = json.loads((ROOT / "wiki.schema.json").read_text())
        text = (ROOT / "AGENTS.md").read_text()
        types, structural = section_tables(text)[:2]
        self.assertEqual(types, schema["page_types"])
        self.assertEqual(structural, schema["structural_dirs"])
        self.assertEqual(wiki_page_types(ROOT / "wiki.schema.json")[1], "")
        with self.assertRaises(AssertionError):
            section_tables(text.replace("## Page types", "## Page kinds"))

    def test_single_wiki_schema_source(self) -> None:
        """Both gates read wiki.schema.json; the divergent AGENTS-wiki-schema.md source is gone."""
        self.assertTrue((ROOT / "wiki.schema.json").is_file())
        self.assertFalse((ROOT / "AGENTS-wiki-schema.md").exists())


if __name__ == "__main__":
    unittest.main()
