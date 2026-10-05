"""wiki_lint.py stale: wiki_stale_days is read by code, sources resolve by the skill's rules, dates come from git."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/wiki_lint.py"
TODAY = "2026-10-05"


def git(cwd: Path, *args: str, date: str = "") -> None:
    """Run git in a temp repo with a fixed identity and optional commit date."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{date}T12:00:00+00:00"
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def page(updated: str, sources: str) -> str:
    """A wiki page with the standard frontmatter."""
    head = f"title: P\ntype: hook\ncreated: 2026-01-01\nlast_updated: {updated}\nsources: {sources}\ntags: []"
    return f"---\n{head}\n---\nbody\n"


class WikiLintCase(unittest.TestCase):
    """A code repo whose source file was last committed on a chosen day, plus a vault of pages."""

    def setUp(self) -> None:
        """Create the repo, vault and the helper that runs the script."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.vault = Path(self.tmp.name) / "vault"
        (self.repo / "hooks").mkdir(parents=True)
        (self.repo / "skills/foo").mkdir(parents=True)
        (self.vault / "hooks").mkdir(parents=True)
        (self.vault / "sources").mkdir()
        git(self.repo, "init", "-q")

    def commit_source(self, relative: str, day: str) -> None:
        """Commit one repo file on a given day."""
        path = self.repo / relative
        path.write_text(day)
        git(self.repo, "add", relative)
        git(self.repo, "commit", "-q", "-m", day, date=day)

    def write_page(self, name: str, updated: str, sources: str, directory: str = "hooks") -> None:
        """Write one vault page."""
        (self.vault / directory / name).write_text(page(updated, sources))

    def config(self, days: int | None) -> None:
        """Set (or remove) wiki_stale_days in the repo's workflow config."""
        target = self.repo / ".coderails/workflow.config.yaml"
        target.parent.mkdir(exist_ok=True)
        target.write_text("project: x\n" if days is None else f"project: x\nwiki_stale_days: {days}\n")

    def run_stale(self) -> dict[str, Any]:
        """Run the CLI and return its JSON."""
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "stale",
                "--repo",
                str(self.repo),
                "--vault",
                str(self.vault),
                "--today",
                TODAY,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data: dict[str, Any] = json.loads(result.stdout)
        return data

    def stale_pages(self, data: dict[str, Any]) -> list[str]:
        """Names of the pages reported stale."""
        stale: list[dict[str, Any]] = data["stale"]
        return [Path(item["page"]).name for item in stale]


class StaleTests(WikiLintCase):
    """The staleness rule from skills/wiki-lint/SKILL.md Step 2, run by code."""

    def test_old_page_with_moved_source_is_stale_and_unmoved_is_not(self) -> None:
        """Candidate age plus a source commit more than 7 days after last_updated is stale; otherwise not."""
        self.commit_source("hooks/moved.py", "2026-09-20")
        self.commit_source("hooks/still.py", "2026-06-01")
        self.write_page("moved.md", "2026-08-01", "[hooks/moved.py]")
        self.write_page("still.md", "2026-08-01", "[hooks/still.py]")
        self.config(None)
        data = self.run_stale()
        self.assertEqual(self.stale_pages(data), ["moved.md"])
        self.assertEqual(sorted(Path(c).name for c in data["candidates"]), ["moved.md", "still.md"])

    def test_config_value_changes_the_result_and_default_is_30(self) -> None:
        """A 10-day-old page with a moved source flips on wiki_stale_days; no key means the default 30 (control)."""
        self.commit_source("hooks/moved.py", "2026-09-30")
        self.write_page("fresh.md", "2026-09-25", "[hooks/moved.py]")
        self.write_page("moved.md", "2026-09-10", "[hooks/moved.py]")
        self.config(None)
        self.assertEqual(self.stale_pages(self.run_stale()), [])
        self.config(1)
        self.assertEqual(self.stale_pages(self.run_stale()), ["moved.md"])
        self.config(100)
        self.assertEqual(self.stale_pages(self.run_stale()), [])
        self.config(None)
        self.assertEqual(self.run_stale()["stale_days"], 30)

    def test_grace_window_and_skill_shorthand_and_vault_entries(self) -> None:
        """A 3-day gap is authoring lag; `skills/foo.md` resolves to skills/foo/SKILL.md; a vault entry is skipped."""
        self.commit_source("hooks/lag.py", "2026-08-04")
        self.commit_source("skills/foo/SKILL.md", "2026-09-20")
        self.write_page("lag.md", "2026-08-01", "[hooks/lag.py]")
        self.write_page("short.md", "2026-08-01", "[skills/foo.md]")
        self.write_page("vaultonly.md", "2026-08-01", "[sources/pr_1_x.md]")
        (self.vault / "sources/pr_1_x.md").write_text(page("2026-01-01", "[]"))
        self.config(None)
        data = self.run_stale()
        self.assertEqual(sorted(self.stale_pages(data)), ["short.md", "vaultonly.md"])
        by_name = {Path(s["page"]).name: s for s in data["stale"]}
        self.assertEqual(by_name["short.md"]["basis"], "sources")
        self.assertEqual(by_name["vaultonly.md"]["basis"], "date-only")

    def test_unresolvable_source_is_a_data_gap_not_unchanged(self) -> None:
        """An entry that resolves nowhere is reported as a gap and does not clear the page."""
        self.commit_source("hooks/moved.py", "2026-09-20")
        self.write_page("gap.md", "2026-08-01", "[hooks/moved.py, nowhere/x.py]")
        self.config(None)
        data = self.run_stale()
        self.assertEqual(self.stale_pages(data), ["gap.md"])
        self.assertEqual([g["source"] for g in data["data_gaps"]], ["nowhere/x.py"])

    def test_point_in_time_pages_are_excluded(self) -> None:
        """sources/ pages are never candidates."""
        self.write_page("pr_1_x.md", "2026-01-01", "[]", directory="sources")
        self.config(None)
        self.assertEqual(self.run_stale()["candidates"], [])


if __name__ == "__main__":
    unittest.main()
