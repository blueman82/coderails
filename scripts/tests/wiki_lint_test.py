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
CODEX_SCRIPT = REPO / "packages/codex/scripts/wiki_lint.py"
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

    def run_stale(self, script: Path = SCRIPT) -> dict[str, Any]:
        """Run the CLI and return its JSON."""
        result = subprocess.run(
            [
                sys.executable,
                str(script),
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

    def test_source_commit_grace_boundary_in_both_providers(self) -> None:
        """A day-seven commit is still in grace; a day-eight commit is drift."""
        self.write_page("grace.md", "2026-08-01", "[hooks/moved.py]")
        for script in (SCRIPT, CODEX_SCRIPT):
            with self.subTest(script=script, day=7):
                self.commit_source("hooks/moved.py", "2026-08-08")
                report = self.run_stale(script)
                self.assertEqual(report["candidates"], ["hooks/grace.md"])
                self.assertEqual(self.stale_pages(report), [])
            with self.subTest(script=script, day=8):
                self.commit_source("hooks/moved.py", "2026-08-09")
                self.assertEqual(self.stale_pages(self.run_stale(script)), ["grace.md"])

    def test_zero_threshold_and_eighth_day_source_change(self) -> None:
        """Zero is a typed threshold; an eighth-day source commit counts as moved."""
        self.commit_source("hooks/moved.py", "2026-09-28")
        self.write_page("recent.md", "2026-09-20", "[hooks/moved.py]")
        self.config(0)
        report = self.run_stale()
        self.assertEqual(report["stale_days"], 0)
        self.assertEqual(self.stale_pages(report), ["recent.md"])

    def test_source_change_one_day_after_an_old_page_is_in_grace(self) -> None:
        """The source grace period applies to an old candidate page too."""
        self.commit_source("hooks/moved.py", "2026-08-02")
        self.write_page("old.md", "2026-08-01", "[hooks/moved.py]")
        self.assertEqual(self.stale_pages(self.run_stale()), [])

    def test_old_pages_without_comparable_sources_are_only_data_gaps(self) -> None:
        """Missing, untracked and vault-only sources cannot prove source drift."""
        (self.repo / "hooks/untracked.py").write_text("untracked\n")
        (self.vault / "sources/reference.md").write_text(page("2026-01-01", "[]"))
        for name, sources in (
            ("empty.md", "[]"),
            ("missing.md", "[nowhere.py]"),
            ("untracked.md", "[hooks/untracked.py]"),
            ("vault.md", "[sources/reference.md]"),
        ):
            self.write_page(name, "2026-01-01", sources)
        report = self.run_stale()
        self.assertEqual(self.stale_pages(report), [])
        self.assertEqual(
            {Path(g["page"]).name for g in report["data_gaps"]}, {"empty.md", "missing.md", "untracked.md", "vault.md"}
        )

    def test_missing_vault_is_unavailable_instead_of_an_empty_report(self) -> None:
        """A nonexistent input directory must not look like a healthy empty vault."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "stale", "--repo", str(self.repo), "--vault", str(self.vault / "absent")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("vault_unavailable", result.stderr)

    def test_old_page_with_moved_source_is_stale_and_unmoved_is_not(self) -> None:
        """Candidate age plus a source commit past grace is stale; otherwise not."""
        self.commit_source("hooks/moved.py", "2026-09-20")
        self.commit_source("hooks/still.py", "2026-06-01")
        self.write_page("moved.md", "2026-08-01", "[hooks/moved.py]")
        self.write_page("still.md", "2026-08-01", "[hooks/still.py]")
        self.config(None)
        data = self.run_stale()
        self.assertEqual(self.stale_pages(data), ["moved.md"])
        self.assertEqual(sorted(Path(c).name for c in data["candidates"]), ["moved.md", "still.md"])

    def test_config_value_changes_the_result_and_default_is_30(self) -> None:
        """Page age controls candidacy; no key means the default 30 (control)."""
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

    def test_skill_shorthand_and_vault_entries(self) -> None:
        """Shorthand resolves to SKILL.md; commits within grace are excluded; vault sources are gaps."""
        self.commit_source("hooks/lag.py", "2026-08-04")
        self.commit_source("skills/foo/SKILL.md", "2026-09-20")
        self.write_page("lag.md", "2026-08-01", "[hooks/lag.py]")
        self.write_page("short.md", "2026-08-01", "[skills/foo.md]")
        self.write_page("vaultonly.md", "2026-08-01", "[sources/pr_1_x.md]")
        (self.vault / "sources/pr_1_x.md").write_text(page("2026-01-01", "[]"))
        self.config(None)
        data = self.run_stale()
        self.assertEqual(sorted(self.stale_pages(data)), ["short.md"])
        by_name = {Path(s["page"]).name: s for s in data["stale"]}
        self.assertEqual(by_name["short.md"]["basis"], "sources")
        self.assertEqual(data["data_gaps"], [{"page": "hooks/vaultonly.md", "source": "", "reason": "no_repo_sources"}])

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
