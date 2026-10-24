"""The legacy import archive and ledger describe the same captured source."""

from __future__ import annotations

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
if mode == 'capture':
    real_replace = legacy.os.replace
    def replace(src, dst):
        if Path(src) == source:
            replacement = source.with_name('replacement.md')
            replacement.write_text(changed)
            real_replace(replacement, source)
        return real_replace(src, dst)
    legacy.os.replace = replace
else:
    real_save = ol.save
    def save(path, ledger):
        if mode == 'recreate':
            source.write_text(changed)
        if mode == 'after':
            real_save(path, ledger)
        raise OSError('injected ledger save result')
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
                self.assertIn("Keep the whole lesson.", (repo / "orders.json").read_text())

    def test_capture_and_save_failure_boundaries(self) -> None:
        """Changed input refuses; failed save restores safely or retains a truthful archive."""
        for codex in (False, True):
            root = REPO / "packages/codex" if codex else REPO
            for mode in ("capture", "before", "recreate", "after"):
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
                    if mode == "after":
                        self.assertEqual((got.returncode, payload["imported"]), (0, 1))
                        self.assertFalse(source.exists())
                        self.assertEqual(backup.read_text(), BODY)
                        self.assertIn("Keep the whole lesson.", (repo / "orders.json").read_text())
                    else:
                        reason = "legacy_parse_error" if mode == "capture" else "order_state_error"
                        self.assertEqual((got.returncode, payload["reason_code"]), (2, reason))
                        self.assertFalse((repo / "orders.json").exists())
                        self.assertEqual(source.read_text(), BODY if mode == "before" else CHANGED)
                        self.assertEqual(backup.exists(), mode == "recreate")
                        if backup.exists():
                            self.assertEqual(backup.read_text(), BODY)
