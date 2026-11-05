"""Independent E3 canaries for complete context and bounded inspection records."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import review_na, review_passes  # noqa: E402
from scripts.tests import review_na_test as fixture  # noqa: E402


class ContextCoverageTests(fixture.WikiNaTests):
    """Use real inert Git objects; never load fixture programs as Python."""

    def add_context(self) -> None:
        """Add two known unchanged inputs below the authored page change."""
        old_head = self.head
        self.git("checkout", "-q", "main")
        for path, text in {
            "notes/index.md": "A plain index.\n",
            "tools/access.py": "INERT_ACCESS_INPUT = 'page'\n",
        }.items():
            target = self.directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", ".")
        self.git("commit", "-qm", "context baseline")
        self.base = self.live_base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "context-pages")
        self.git("cherry-pick", old_head)
        self.head = self.git("rev-parse", "HEAD").strip()

    def test_partial_omission_fails_while_the_complete_mixed_context_passes(self) -> None:
        """Two correct retained paths cannot conceal an omitted third consumer."""
        self.add_context()
        claim = self.scope()
        group = claim["consumer_scope"]["references"][0]
        group["paths"] += ["notes/index.md", "tools/access.py"]
        try:
            review_na.validate(claim, "7", self.head)
        except ValueError as error:
            self.fail(f"complete v2 sibling refused: {error}")
        facts = review_na.prepare("7", self.head)
        self.assertEqual(
            {row["path"] for row in facts["context_inventory"]},
            {".obsidian/plugins/view/main.js", "notes/index.md", "tools/access.py"},
        )
        group["paths"].remove("tools/access.py")
        with self.assertRaisesRegex(ValueError, "context.*coverage"):
            review_na.validate(claim, "7", self.head)

    def test_duplicate_foreign_pattern_and_empty_groups_refuse(self) -> None:
        """Coverage is an exact set, rather than a count or a nonempty-array check."""
        claim = self.scope()
        review_na.validate(claim, "7", self.head)
        for paths in ([], ["*"], ["elsewhere.md"], [".obsidian/plugins/view/main.js"] * 2):
            bad = copy.deepcopy(claim)
            bad["consumer_scope"]["references"][0]["paths"] = paths
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                review_na.validate(bad, "7", self.head)

    def test_context_digest_and_base_change_groups_bind_actual_entries(self) -> None:
        """A group cannot mix an unchanged entry with a base-only changed entry."""
        self.add_context()
        original = self.scope()
        original["consumer_scope"]["references"][0]["paths"] += ["notes/index.md", "tools/access.py"]
        review_na.validate(original, "7", self.head)
        bad = copy.deepcopy(original)
        bad["binding"]["context_inventory_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "stale"):
            review_na.validate(bad, "7", self.head)
        self.git("checkout", "-q", "main")
        (self.directory / "notes/index.md").write_text("New plain index.\n")
        self.git("commit", "-qam", "new base index")
        self.live_base = self.git("rev-parse", "HEAD").strip()
        fresh = self.scope()
        group = fresh["consumer_scope"]["references"][0]
        group["paths"] += ["notes/index.md", "tools/access.py"]
        for reasoning in (None, "Inspected base change; only display wording changed."):
            group["base_change_assessment"] = reasoning
            with self.assertRaisesRegex(ValueError, "base change"):
                review_na.validate(fresh, "7", self.head)
        group["paths"].remove("notes/index.md")
        group["base_change_assessment"] = None
        fresh["consumer_scope"]["references"].append(
            {
                "paths": ["notes/index.md"],
                "base_change_assessment": "Inspected base change; only display wording changed.",
                "assessment": "Actual base/head entries display prose only.",
            }
        )
        review_na.validate(fresh, "7", self.head)

    def test_403_path_context_fits_comment_and_uses_bounded_git_processes(self) -> None:
        """The real 426-entry shape needs a fixed number of object processes, not one for each path."""
        old_head = self.head
        self.git("checkout", "-q", "main")
        paths = [".obsidian/plugins/view/main.js"]
        lengths = [42] * 402
        lengths[0] = 84
        for index in range(1, 143):
            lengths[index] += 1
        for index, length in enumerate(lengths):
            prefix, suffix = f"notes/item-{index:03d}/", "/page.md"
            path = prefix + "x" * (length - len(prefix) - len(suffix)) + suffix
            paths.append(path)
            target = self.directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"Unique inert context {index}.\n")
        for index in range(20):
            (self.directory / f"hooks/extra-{index:02d}.md").write_text(f"Before {index}.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "large context baseline")
        self.base = self.live_base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "large-pages")
        self.git("cherry-pick", old_head)
        for index in range(18):
            (self.directory / f"hooks/extra-{index:02d}.md").write_text(f"After {index}.\n")
        for index in (18, 19):
            (self.directory / f"hooks/extra-{index:02d}.md").unlink()
            (self.directory / f"commands/added-{index}.md").write_text("New prose.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "large authored prose change")
        self.head = self.git("rev-parse", "HEAD").strip()
        claim = self.scope()
        claim["consumer_scope"]["references"][0]["paths"] = paths
        self.assertEqual(len(json.dumps(paths, separators=(",", ":"))), 18308)
        self.assertEqual(max(map(len, paths)), 84)
        real_run = subprocess.run
        with mock.patch.object(subprocess, "run", wraps=real_run) as observed:
            review_na.validate(claim, "7", self.head)
        commands = [list(call.args[0]) for call in observed.call_args_list]
        self.assertLessEqual(sum("ls-tree" in argv for argv in commands), 3)
        self.assertEqual(sum("--batch-check" in argv for argv in commands), 1)
        prepared = review_na.prepare("7", self.head)
        self.assertEqual(len(prepared["inventory"]), 26)
        self.assertEqual(len(prepared["context_inventory"]), 403)
        self.assertEqual(len(self.git("ls-tree", "-r", self.head).splitlines()), 426)
        text = fixture.na_summary(claim)
        body = review_passes.tail([("review-pr", "## No findings\n"), ("security-review", text)])
        self.assertLess(len(body) + 1024, 65536)
        review_na.check_comment_bodies(body)
        with self.assertRaises(ValueError):
            review_na.check_comment_bodies(body + "x" * 65536)
        self.assertLess(len(review_na.preparation_json("7").encode()), 131072)

    def test_input_limits_refuse_instead_of_truncating(self) -> None:
        """Oversized structured input and complete metadata cannot silently lose coverage."""
        claim = self.scope()
        claim["repository_purpose"] = "x" * 131072
        with self.assertRaisesRegex(ValueError, "input byte limit"):
            review_passes.validate_summary_text(fixture.na_summary(claim), name="security-review")
        with (
            mock.patch.object(review_na, "prepare", return_value={"context_inventory": ["x" * 131072]}),
            self.assertRaisesRegex(ValueError, "input byte limit"),
        ):
            review_na.preparation_json("7")


if __name__ == "__main__":
    import unittest

    unittest.main()
