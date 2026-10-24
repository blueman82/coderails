"""The legacy import archive and ledger describe the same captured source."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.tests.fake_muninn_case import SESSION
from scripts.tests.orders_legacy_test import BODY, REPO

CHANGED = BODY.replace("Keep the whole lesson.", "Keep the changed lesson.")
PROBE = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders, orders_ledger as ol, orders_legacy_import as legacy
source, mode = Path(sys.argv[2]), sys.argv[3]
changed = sys.argv[4]
real_save = ol.save
def save(path, ledger):
    if mode == 'inplace':
        with source.open('r+b') as handle:
            handle.seek(0)
            handle.write(changed.encode())
            handle.truncate()
    if mode == 'recreate':
        source.write_text(changed)
    if mode == 'after':
        real_save(path, ledger)
    if mode in ('before', 'recreate', 'after'):
        raise OSError('injected ledger save result')
    return real_save(path, ledger)
ol.save = save
raise SystemExit(orders.main(sys.argv[5:]))
"""


class ImportCapture(unittest.TestCase):
    """Check the native import command on both independent provider packages."""

    def test_crlf_source_keeps_exact_archived_bytes(self) -> None:
        """The parser can normalize line endings while the archive retains the original bytes."""
        raw = BODY.replace("\n", "\r\n").encode()
        for codex in (False, True):
            with self.subTest(codex=codex), tempfile.TemporaryDirectory() as tmp:
                root = REPO / "packages/codex" if codex else REPO
                repo = Path(tmp)
                (repo / "standing-orders.md").write_bytes(raw)
                got = subprocess.run(
                    [sys.executable, str(root / "scripts/lib/orders.py"), "--dir", str(repo),
                     "--session", SESSION, "import-legacy"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )  # fmt: skip
                self.assertEqual(got.stderr, "")
                self.assertEqual(got.returncode, 0, got.stdout)
                self.assertEqual((repo / "standing-orders.legacy.md").read_bytes(), raw)
                self.assertEqual((repo / "standing-orders.md").read_bytes(), raw)
                self.assertEqual(json.loads(got.stdout)["source_retained"], True)
                self.assertEqual(json.loads(got.stdout)["archived_to"], str(repo / "standing-orders.legacy.md"))
                self.assertIn("Keep the whole lesson.", (repo / "orders.json").read_text())

    def test_capture_and_save_failure_boundaries(self) -> None:
        """Later source edits do not alter the archive; failed saves keep both files."""
        for codex in (False, True):
            root = REPO / "packages/codex" if codex else REPO
            for mode in ("inplace", "before", "recreate", "after"):
                with self.subTest(codex=codex, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    source = repo / "standing-orders.md"
                    backup = repo / "standing-orders.legacy.md"
                    source.write_text(BODY)
                    got = subprocess.run(
                        [sys.executable, "-c", PROBE, str(root), str(source), mode, CHANGED,
                         "--dir", str(repo), "--session", SESSION, "import-legacy"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )  # fmt: skip
                    self.assertEqual(got.stderr, "")
                    payload = json.loads(got.stdout)
                    if mode in ("inplace", "after"):
                        self.assertEqual((got.returncode, payload["imported"]), (0, 1))
                        self.assertEqual(backup.read_text(), BODY)
                        self.assertEqual(source.read_text(), CHANGED if mode == "inplace" else BODY)
                        self.assertIn("Keep the whole lesson.", (repo / "orders.json").read_text())
                    else:
                        self.assertEqual((got.returncode, payload["reason_code"]), (2, "order_state_error"))
                        self.assertFalse((repo / "orders.json").exists())
                        self.assertEqual(source.read_text(), BODY if mode == "before" else CHANGED)
                        self.assertEqual(backup.read_text(), BODY)

    def test_occupied_archive_name_is_never_replaced(self) -> None:
        """A writer claiming the first archive name during publication cannot lose its bytes."""
        probe = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders, orders_legacy_import as legacy
repo = Path(sys.argv[2])
real_link = legacy.os.link
def link(src, dst):
    if Path(dst).name == 'standing-orders.legacy.md':
        Path(dst).write_text('Concurrent archive.\n')
    return real_link(src, dst)
legacy.os.link = link
raise SystemExit(orders.main(sys.argv[3:]))
"""
        for codex in (False, True):
            with self.subTest(codex=codex), tempfile.TemporaryDirectory() as tmp:
                root = REPO / "packages/codex" if codex else REPO
                repo = Path(tmp)
                (repo / "standing-orders.md").write_text(BODY)
                got = subprocess.run(
                    [sys.executable, "-c", probe, str(root), str(repo), "--dir", str(repo),
                     "--session", SESSION, "import-legacy"], capture_output=True, text=True, timeout=15,
                )  # fmt: skip
                self.assertEqual(got.stderr, "")
                self.assertEqual(got.returncode, 0, got.stdout)
                self.assertEqual((repo / "standing-orders.legacy.md").read_text(), "Concurrent archive.\n")
                self.assertEqual((repo / "standing-orders.legacy.2.md").read_text(), BODY)
                self.assertEqual((repo / "standing-orders.md").read_text(), BODY)
                self.assertEqual(
                    json.loads((repo / "orders.json").read_text())["orders"][0]["legacy_source_sha256"],
                    hashlib.sha256(BODY.encode()).hexdigest(),
                )

    def test_retry_refuses_changed_raw_bytes_with_equal_parsed_lesson(self) -> None:
        """A saved source hash blocks a retry that changes only legacy whitespace."""
        for codex in (False, True):
            with self.subTest(codex=codex), tempfile.TemporaryDirectory() as tmp:
                root = REPO / "packages/codex" if codex else REPO
                repo = Path(tmp)
                source = repo / "standing-orders.md"
                source.write_text(BODY)
                command = [
                    sys.executable,
                    str(root / "scripts/lib/orders.py"),
                    "--dir",
                    str(repo),
                    "--session",
                    SESSION,
                    "import-legacy",
                ]
                first = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertEqual(first.returncode, 0, first.stdout)
                saved = (repo / "orders.json").read_bytes()
                source.write_text(BODY.replace("Keep the whole lesson.", "    Keep the whole lesson."))
                retry = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertEqual((retry.returncode, json.loads(retry.stdout)["reason_code"]), (2, "legacy_parse_error"))
                self.assertEqual((repo / "orders.json").read_bytes(), saved)
                self.assertEqual((repo / "standing-orders.legacy.md").read_text(), BODY)
                self.assertEqual(len(list(repo.glob("standing-orders.legacy*.md"))), 1)
