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
MOVE_PROBE = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders, orders_ledger as ol
source = Path(sys.argv[2])
real_replace, moves, saved_rows = orders.os.replace, 0, 0
def replace(src, dst):
    global moves, saved_rows
    if Path(src) == source:
        moves += 1
        saved_rows = len(ol.open_ledger(source.parent)['orders'])
        raise OSError('injected move failure after durable ledger save')
    return real_replace(src, dst)
orders.os.replace = replace
rc = orders.main(sys.argv[3:])
print(json.dumps({'moves': moves, 'saved_rows': saved_rows}))
raise SystemExit(rc)
"""


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

    def test_retry_after_own_ledger_save_and_failed_source_move_resumes_exact_import(self) -> None:
        """The move fault occurs after real publication; a normal retry neither duplicates nor drops evidence."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                root = REPO / "packages/codex" if codex else REPO
                repo = self.tmp / ("resume-" + str(codex))
                repo.mkdir()
                (repo / "orders.json").write_bytes(self.prior)
                source, backup = repo / "standing-orders.md", repo / "standing-orders.legacy.md"
                source.write_text(BODY)
                backup.write_text("Prior backup\n")
                args = ["--dir", str(repo), "--session", SESSION, "import-legacy"]
                first = subprocess.run(
                    [sys.executable, "-c", MOVE_PROBE, str(root), str(source), *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(first.stderr, "")
                out, probe = map(json.loads, first.stdout.splitlines())
                self.assertEqual((first.returncode, out.get("reason_code")), (2, "order_state_error"))
                self.assertEqual(probe, {"moves": 1, "saved_rows": 2})
                self.assertEqual(source.read_text(), BODY)
                self.assertEqual(backup.read_text(), "Prior backup\n")
                saved = (repo / "orders.json").read_bytes()
                retried = subprocess.run(
                    [sys.executable, str(root / "scripts/lib/orders.py"), *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(retried.stderr, "")
                out = json.loads(retried.stdout)
                self.assertEqual(retried.returncode, 0, out)
                self.assertFalse(source.exists())
                self.assertEqual(Path(out["moved_to"]).read_text(), BODY)
                self.assertEqual(backup.read_text(), "Prior backup\n")
                self.assertEqual((repo / "orders.json").read_bytes(), saved)
                self.assertEqual(len(ol.open_ledger(repo)["orders"]), 2)

    def test_unrelated_colliding_legacy_row_is_not_a_resume_receipt(self) -> None:
        """Matching ids alone never authorize accepting different imported content on retry."""
        self.source.write_text(BODY)
        ledger = ol.open_ledger(self.repo)
        row = ol.parse_legacy(BODY, "2026-10-01")[0]
        row["lesson"] = "Unrelated colliding lesson."
        ledger["orders"].append(row)
        ol.save(self.repo / "orders.json", ol.seal(ledger))
        before = (self.repo / "orders.json").read_bytes()
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual((self.repo / "orders.json").read_bytes(), before)
        self.assertEqual(self.source.read_text(), BODY)

    def test_interrupted_two_row_cohort_with_raw_body_divergence_refuses_resume(self) -> None:
        """One unchanged row cannot authorize a second changed raw body with the same normalized lesson."""
        for codex in (False, True):
            with self.subTest(codex=codex):
                root = REPO / "packages/codex" if codex else REPO
                repo = self.tmp / ("divergent-" + str(codex))
                repo.mkdir()
                (repo / "orders.json").write_bytes(self.prior)
                source, backup = repo / "standing-orders.md", repo / "standing-orders.legacy.md"
                body = BODY + BODY.replace("Keep source text", "Second source text")
                source.write_text(body)
                backup.write_text("Prior backup\n")
                args = ["--dir", str(repo), "--session", SESSION, "import-legacy"]
                failed = subprocess.run(
                    [sys.executable, "-c", MOVE_PROBE, str(root), str(source), *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(failed.stderr, "")
                self.assertEqual(failed.returncode, 2)
                self.assertEqual(json.loads(failed.stdout.splitlines()[1]), {"moves": 1, "saved_rows": 3})
                saved = (repo / "orders.json").read_bytes()
                changed = body.rsplit("Keep the whole lesson.", 1)
                text = "    Keep the whole lesson.".join(changed)
                self.assertEqual(
                    [o["lesson"] for o in ol.parse_legacy(body, "same")],
                    [o["lesson"] for o in ol.parse_legacy(text, "same")],
                )
                source.write_text(text)
                retry = subprocess.run(
                    [sys.executable, str(root / "scripts/lib/orders.py"), *args],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(retry.stderr, "")
                self.assertEqual(
                    (retry.returncode, json.loads(retry.stdout).get("reason_code")), (2, "legacy_parse_error")
                )
                self.assertEqual((repo / "orders.json").read_bytes(), saved)
                self.assertEqual(source.read_text(), text)
                self.assertEqual(backup.read_text(), "Prior backup\n")
                self.assertEqual(list(repo.glob("standing-orders.legacy*.md")), [backup])


if __name__ == "__main__":
    unittest.main()
