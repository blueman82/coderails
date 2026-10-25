"""Exercise source-bound order preparation through both provider entrypoints."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PROVIDERS = (REPO / "scripts/lib/orders.py", REPO / "packages/codex/scripts/lib/orders.py")
sys.path.insert(0, str(REPO))
from scripts.lib import teardown_steps  # noqa: E402

SESSION = "prepared-session"
LOOP = "separate-logical-loop"


class PreparedCli(unittest.TestCase):
    """Run the CLI against isolated owner-bound progress and teardown files."""

    def setUp(self) -> None:
        """Create one eligible schema-v3 loop in a temporary repo-key directory."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo-key"
        self.repo.mkdir()
        self.state_dir = self.repo / SESSION
        self.state_dir.mkdir()
        self.path = self.state_dir / "progress.json"
        self.state: dict[str, Any] = {
            "schema_version": 3,
            "session_id": SESSION,
            "loop_id": LOOP,
            "revision": 1,
            "status": "in-progress",
            "created": "2026-10-19T10:00:00+00:00",
            "authorising_prompt_raw": "Prepare this bounded loop.",
            "work_units": {},
            "graph": {"nodes": {}, "edges": [], "joins": {}, "active_wave": None, "hard_stop": None},
        }
        self.path.write_text(json.dumps(self.state), encoding="utf-8")

    def cli(self, script: Path, *args: str) -> tuple[int, dict[str, Any]]:
        """Run a provider entrypoint and decode its JSON result."""
        result = subprocess.run(
            [sys.executable, str(script), "--dir", str(self.repo), "--session", SESSION, *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.stderr, "", result.stderr)
        return result.returncode, json.loads(result.stdout)

    def artifact(self) -> Path:
        """Path of the logical-loop preparation artifact."""
        digest = hashlib.sha256(LOOP.encode()).hexdigest()
        return self.state_dir / f"orders-prepared-{digest}.json"

    def test_both_providers_write_idempotent_source_bound_receipts(self) -> None:
        """Exact owner binding and evidence are recorded without ticking orders."""
        source = {k: v for k, v in self.state.items() if k not in {"status", "completion", "completed_marker"}}
        binding = {
            "repo_dir": str(self.repo.resolve()),
            "state_dir": str(self.state_dir.resolve()),
            "session_id": SESSION,
            "loop_id": LOOP,
            "revision": 1,
            "progress_sha256": teardown_steps.sha_json(source),
        }
        for script in PROVIDERS:
            with self.subTest(script=script):
                rc, out = self.cli(script, "prepare", "--loop", LOOP)
                self.assertEqual(rc, 0, out)
                prepared = json.loads(self.artifact().read_text(encoding="utf-8"))
                self.assertEqual(prepared, {"schema": 1, "binding": binding, "records": []})
                evidence = teardown_steps.sha_json(prepared)
                self.assertEqual(out["evidence_sha256"], evidence)
                rows = teardown_steps.read_rows(self.state_dir)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["binding"], rows[0]["evidence_sha256"]), (binding, evidence))
                before = (self.state_dir / teardown_steps.NAME).read_bytes()
                rc, again = self.cli(script, "prepare", "--loop", LOOP)
                self.assertEqual((rc, again["evidence_sha256"]), (0, evidence))
                self.assertEqual((self.state_dir / teardown_steps.NAME).read_bytes(), before)
        self.assertFalse((self.repo / "orders.json").exists())

    def test_foreign_or_changed_source_is_refused_without_replacing_artifact(self) -> None:
        """Ownership mismatch and source drift cannot create or replace prepared evidence."""
        script = PROVIDERS[1]
        rc, out = self.cli(script, "prepare", "--loop", "foreign-loop")
        self.assertEqual(rc, 2, out)
        self.assertFalse(self.artifact().exists())
        self.assertFalse((self.state_dir / teardown_steps.NAME).exists())
        self.assertEqual(self.cli(script, "prepare", "--loop", LOOP)[0], 0)
        before = self.artifact().read_bytes()
        tampered = json.loads(before)
        tampered["records"].append({"id": "invented"})
        self.artifact().write_text(json.dumps(tampered), encoding="utf-8")
        tampered_bytes = self.artifact().read_bytes()
        rc, out = self.cli(script, "prepare", "--loop", LOOP)
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.artifact().read_bytes(), tampered_bytes)
        self.artifact().write_bytes(before)
        self.path.write_text(json.dumps({**self.state, "authorising_prompt_raw": "changed"}), encoding="utf-8")
        rc, out = self.cli(script, "prepare", "--loop", LOOP)
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.artifact().read_bytes(), before)

    def test_ineligible_work_units_are_refused_before_writing(self) -> None:
        """Pending work cannot receive a teardown preparation receipt."""
        self.state["work_units"] = {"1": {"status": "pending"}}
        self.path.write_text(json.dumps(self.state), encoding="utf-8")
        rc, out = self.cli(PROVIDERS[0], "prepare", "--loop", LOOP)
        self.assertEqual(rc, 2, out)
        self.assertFalse(self.artifact().exists())
        self.assertFalse((self.state_dir / teardown_steps.NAME).exists())


if __name__ == "__main__":
    unittest.main()
