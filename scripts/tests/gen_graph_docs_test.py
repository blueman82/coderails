"""`scripts/gen_graph_docs.py --check` keeps the generated doc regions equal to what the spec and policy render."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_spec  # noqa: E402

SCRIPT = ROOT / "scripts/gen_graph_docs.py"
FILES = (
    "skills/agentic-loop/execution-graph.md",
    "skills/agentic-loop/phases-setup.md",
    "packages/graph-semantics/graph-spec.yaml",
    "packages/graph-semantics/policy.yaml",
)


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the generator."""
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, check=False)


class GenGraphDocsTests(unittest.TestCase):
    """The committed docs are current; hand edits and unregenerated spec edits are caught."""

    def copy_tree(self) -> Path:
        """A scratch root holding only the files the generator reads and writes."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        for relative in FILES:
            (Path(scratch.name) / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, Path(scratch.name) / relative)
        return Path(scratch.name)

    def test_committed_docs_are_current(self) -> None:
        """`--check` exits 0 on the committed docs and writes nothing."""
        result = run("--check")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_hand_edited_row_fails_check(self) -> None:
        """Editing one generated table row is detected, and regenerating restores it."""
        root = self.copy_tree()
        document = root / FILES[0]
        document.write_text(document.read_text().replace("never skipped", "sometimes skipped", 1), encoding="utf-8")
        failed = run("--check", "--root", str(root))
        self.assertEqual(failed.returncode, 1)
        self.assertIn("execution-graph.md", failed.stdout)
        self.assertEqual(run("--root", str(root)).returncode, 0)
        self.assertEqual(run("--check", "--root", str(root)).returncode, 0)

    def test_spec_edit_without_regenerating_fails_check(self) -> None:
        """A changed spec text or policy threshold no longer matches the committed docs."""
        for relative, old, new in (
            (FILES[2], "durable `spec.md` exists", "durable spec exists"),
            (FILES[3], '"design_doc_min_units": 3', '"design_doc_min_units": 4'),
        ):
            with self.subTest(relative):
                root = self.copy_tree()
                edited = root / relative
                edited.write_text(edited.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
                self.assertEqual(run("--check", "--root", str(root)).returncode, 1)

    def test_worker_status_path_is_rendered_without_changing_spec(self) -> None:
        """The public table has a usable provider path; its source spec retains its digest."""
        root = self.copy_tree()
        spec_path = root / FILES[2]
        original_bytes = spec_path.read_bytes()
        original_spec = graph_spec.load_spec(spec_path)
        document = root / FILES[0]
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`skills/agentic-loop/scripts/worker_status.py`", "`missing-worker-status.py`", 1
            ),
            encoding="utf-8",
        )
        self.assertEqual(run("--check", "--root", str(root)).returncode, 1)
        regenerated = run("--root", str(root))
        self.assertEqual(regenerated.returncode, 0, regenerated.stderr)
        table = document.read_text(encoding="utf-8")
        row = next(line for line in table.splitlines() if line.startswith("| `U4[i]` |"))
        self.assertIn("`skills/agentic-loop/scripts/worker_status.py`", row)
        self.assertNotIn("`scripts/worker_status.py`", row)
        self.assertEqual(spec_path.read_bytes(), original_bytes)
        self.assertEqual(graph_spec.load_spec(spec_path), original_spec)
        self.assertEqual(graph_spec.spec_sha256(graph_spec.load_spec(spec_path)), graph_spec.spec_sha256(original_spec))
        self.assertEqual(run("--check", "--root", str(root)).returncode, 0)

    def test_missing_marker_is_an_error(self) -> None:
        """A document that lost its region markers refuses instead of silently skipping."""
        root = self.copy_tree()
        document = root / FILES[1]
        document.write_text(document.read_text().replace("<!-- END GENERATED graph-spec:thresholds -->", ""))
        failed = run("--check", "--root", str(root))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("graph-spec:thresholds", failed.stderr)


if __name__ == "__main__":
    unittest.main()
