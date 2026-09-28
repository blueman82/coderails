"""Catch known gh field, review invocation and nullable jq projection regressions."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW_FIELD = re.compile(r"(-f |--raw-field )[a-zA-Z0-9_]+=@")
PROJECTION = re.compile(r"[|] *(first|\.\[[0-9]+\]) *[|].*\{url:")
BARE_REVIEW = "`/pr-review-toolkit:review-pr all`"


def sources() -> list[Path]:
    """Scan command and runtime source while leaving fixture test strings out."""
    paths = list((ROOT / "commands").rglob("*.md"))
    for directory in (ROOT / "scripts", ROOT / "hooks/scripts"):
        for suffix in ("*.sh", "*.py"):
            paths.extend(path for path in directory.rglob(suffix) if "tests" not in path.relative_to(directory).parts)
    return paths


class CliAntipatternTests(unittest.TestCase):
    """Retain nonvacuous negative controls for every lint predicate."""

    def test_raw_fields_control(self) -> None:
        """Reject short and long literal-file fields including names with digits."""
        for text in (
            "gh api graphql -f body=@/tmp/comment.md",
            "gh api -f key1=@/tmp/x.txt",
            "gh api --raw-field body=@/tmp/x.md",
        ):
            self.assertIsNotNone(RAW_FIELD.search(text))
        self.assertIsNone(RAW_FIELD.search("gh api -F body=@/tmp/comment.md"))

    def test_nullable_projection_control(self) -> None:
        """Detect both first and numeric-index projection traps without a null guard."""
        for selector in ("first", ".[0]"):
            line = f'--jq "[.[] | select(.merged)] | {selector} | {{url:.html_url,id:.id}}"'
            self.assertIsNotNone(PROJECTION.search(line))
            self.assertNotIn("select(. != null)", line)
            guarded = line.replace(f"{selector} |", f"{selector} | select(. != null) |")
            self.assertIn("select(. != null)", guarded)
        self.assertIn(BARE_REVIEW, f"Run {BARE_REVIEW} to review.")

    def test_repository_has_no_known_cli_antipatterns(self) -> None:
        """Require all scanned source to avoid the three previously shipped mistakes."""
        paths = sources()
        self.assertTrue(paths)
        violations: list[str] = []
        for path in paths:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if RAW_FIELD.search(line) or (PROJECTION.search(line) and "select(. != null)" not in line):
                    violations.append(f"{path.relative_to(ROOT)}:{number}: {line}")
        self.assertEqual(violations, [])
        self.assertNotIn(BARE_REVIEW, (ROOT / "commands/workflow.md").read_text())


if __name__ == "__main__":
    unittest.main()
