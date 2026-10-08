"""Legacy import preserves source text and every prior backup, including refusal paths."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib.memory_adapter import MARKER  # noqa: E402
from scripts.tests.fake_muninn_case import SESSION, StoreCase  # noqa: E402

BODY = "### Keep source text\n**loops_since_recurrence:** 5\n**First seen:** session old\nKeep the whole lesson.\n"


class LegacyPreservation(StoreCase):
    """Only private legacy files and orders ledger files are read or written."""

    def setUp(self) -> None:
        """Create the local import boundary and a genuine already sealed unrelated order."""
        super().setUp()
        self.repo = self.tmp / "repo-key"
        self.repo.mkdir()
        self.source = self.repo / "standing-orders.md"
        ledger = ol.record(
            ol.empty(), "existing", "Keep the prior order.", session_id="prior", loop_id="prior-loop", now="2026-10-05"
        )["ledger"]
        ol.save(self.repo / "orders.json", ledger)
        self.prior = (self.repo / "orders.json").read_bytes()

    def cli(self) -> tuple[int, dict[str, Any]]:
        """Call the real import command, with explicit private directory and provider session."""
        got = subprocess.run(
            [sys.executable, str(REPO / "scripts/lib/orders.py"), "--dir", str(self.repo), "--session", SESSION,
             "import-legacy"], capture_output=True, text=True, timeout=15,
        )  # fmt: skip
        self.assertEqual(got.stderr, "")
        return got.returncode, json.loads(got.stdout)

    def test_nonempty_unrecognized_or_ambiguous_input_refuses_without_moving(self) -> None:
        """No parsed entry is not an import; malformed or ambiguous structure cannot silently lose a record."""
        for n, body in enumerate(
            (
                "# Standing Orders\nNo recognizable entry structure.\n",
                BODY.replace("### Keep source text", "#### Keep source text"),
                BODY.replace("### Keep source text", "### "),
                BODY.replace("### Keep source text", "###    "),
                BODY + BODY,
                BODY + "#### Other entry\n**loops_since_recurrence:** 1\n**First seen:** other\nOther lesson.\n",
            )
        ):
            with self.subTest(body=body):
                self.repo = self.tmp / f"case-{n}"
                self.repo.mkdir()
                self.source = self.repo / "standing-orders.md"
                (self.repo / "orders.json").write_bytes(self.prior)
                self.source.write_text(body)
                rc, out = self.cli()
                self.assertEqual((rc, out.get("reason_code")), (2, "legacy_parse_error"), out)
                self.assertEqual(self.source.read_text(), body)
                self.assertEqual((self.repo / "orders.json").read_bytes(), self.prior)
                self.assertEqual(list(self.repo.glob("standing-orders.legacy*.md")), [])

    def test_empty_absent_and_generated_input_is_not_imported(self) -> None:
        """Legitimate empty and generated cases remain explicit legacy_missing refusals without writes."""
        self.assertEqual(self.cli(), (2, {"reason_code": "legacy_missing"}))
        for body in ("", " \n", MARKER + "\n# Generated view\n"):
            self.source.write_text(body)
            self.assertEqual(self.cli(), (2, {"reason_code": "legacy_missing"}))
            self.assertEqual(self.source.read_text(), body)
        self.assertEqual((self.repo / "orders.json").read_bytes(), self.prior)

    def test_existing_two_hash_heading_format_remains_supported(self) -> None:
        """The established parser accepts both ## and ###; preserve this legitimate legacy format."""
        self.source.write_text(BODY.replace("### Keep source text", "## Keep source text"))
        rc, out = self.cli()
        self.assertEqual((rc, out["imported"]), (0, 1))
        self.assertEqual(ol.open_ledger(self.repo)["orders"][1]["failure_mode"], "Keep source text")

    def test_backup_exhaustion_refuses_before_any_ledger_or_source_change(self) -> None:
        """Exhausting the existing bounded backup namespace cannot overwrite its final file or commit an import."""
        backups = [self.repo / "standing-orders.legacy.md"]
        backups += [self.repo / f"standing-orders.legacy.{n}.md" for n in range(2, 1000)]
        for path in backups:
            path.write_text(f"Prior backup {path.name}\n")
        self.source.write_text(BODY)
        rc, out = self.cli()
        self.assertEqual((rc, out.get("reason_code")), (2, "legacy_parse_error"), out)
        self.assertEqual(self.source.read_text(), BODY)
        self.assertEqual((self.repo / "orders.json").read_bytes(), self.prior)
        for path in backups:
            self.assertEqual(path.read_text(), f"Prior backup {path.name}\n")

    def test_legitimate_import_preserves_decay_text_and_prior_backup(self) -> None:
        """A real entry is saved as a tombstone with full provenance, and the original moves to a fresh backup."""
        old = self.repo / "standing-orders.legacy.md"
        old.write_text("Prior backup\n")
        self.source.write_text(BODY)
        rc, out = self.cli()
        self.assertEqual((rc, out["imported"], out["skipped"]), (0, 1, 0))
        self.assertFalse(self.source.exists())
        self.assertEqual(old.read_text(), "Prior backup\n")
        self.assertEqual(Path(out["moved_to"]).read_text(), BODY)
        imported = ol.open_ledger(self.repo)["orders"][1]
        self.assertEqual((imported["status"], imported["loops_since_recurrence"]), ("decayed", 5))
        self.assertEqual((imported["legacy_first_seen"], imported["lesson"]), ("session old", "Keep the whole lesson."))
        self.assertEqual(imported["legacy_text"], "\n".join(BODY.splitlines()[1:]))


if __name__ == "__main__":
    unittest.main()
