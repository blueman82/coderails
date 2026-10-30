"""The native Codex hook trace carries the same typed decision fields."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hooks.scripts.lib.hook_decision import FALLBACK_REMEDIATION

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"


class CodexHookDecisionTests(unittest.TestCase):
    """The native Codex trace includes the shared decision record."""

    def test_native_trace_has_typed_record_and_hashed_params(self) -> None:
        """The Codex hook writes only hashed params and catalog recovery text."""
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            catalog = base / "messages.json"
            catalog.write_text(
                json.dumps(
                    {
                        "hooks": {"crack_on_gate": {"reason_code": "authority_deny", "remediation": "Retry."}},
                        "aliases": {"crack_on": "crack_on_gate"},
                        "reasons": {"stop_row_missing": {"remediation": "Record the current Stop result."}},
                        "fallback": {"remediation": "Read the hook reason."},
                    }
                )
            )
            code = (
                "from pathlib import Path\n"
                "from hooks.scripts import hook_common\n"
                "from hooks.scripts.lib import hook_decision\n"
                "hook_decision.CATALOG = Path(sys.argv[1])\n"
                "assert hook_common.append_trace_row('crack_on', 'blocked', 'stop_row_missing', 's1', "
                "{'inputs': {'cmd': 'SECRET'}})\n"
            )
            env = {
                **os.environ,
                "HOME": str(base),
                "CODERAILS_AGENTIC_LOOP_DIR": str(base),
                "PYTHONPATH": os.pathsep.join((str(CODEX), str(CODEX / "hooks/scripts"))),
            }
            result = subprocess.run(
                [sys.executable, "-c", "import sys\n" + code, str(catalog)],
                cwd=base,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = (base / "s1" / "trace.jsonl").read_text()
            self.assertNotIn("SECRET", raw)
            row = json.loads(raw)
            self.assertEqual(row["inputs"]["cmd"], hashlib.sha256(b"SECRET").hexdigest())
            self.assertEqual(row["decision_record"]["remediation"], "Record the current Stop result.")
            self.assertEqual(row["decision_record"]["reason_code"], "stop_row_missing")

    def test_bad_catalog_still_writes_native_decision_record(self) -> None:
        """The native trace has typed fields when the catalog is absent or malformed."""
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            code = (
                "from pathlib import Path\n"
                "from hooks.scripts import hook_common\n"
                "from hooks.scripts.lib import hook_decision\n"
                "hook_decision.CATALOG = Path('messages.json')\n"
                "assert hook_common.append_trace_row('gate', 'blocked', 'bad_state', 's1')\n"
            )
            env = {
                **os.environ,
                "HOME": str(base),
                "CODERAILS_AGENTIC_LOOP_DIR": str(base),
                "PYTHONPATH": os.pathsep.join((str(CODEX), str(CODEX / "hooks/scripts"))),
            }
            for malformed in (False, True):
                with self.subTest(malformed=malformed):
                    if malformed:
                        (base / "messages.json").write_text("{")
                    result = subprocess.run(
                        [sys.executable, "-c", code], cwd=base, env=env, capture_output=True, text=True, check=False
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    row = json.loads((base / "s1" / "trace.jsonl").read_text().splitlines()[-1])
                    self.assertEqual(row["decision_record"]["reason_code"], "bad_state")
                    self.assertEqual(row["decision_record"]["remediation"], FALLBACK_REMEDIATION)

    def test_native_malformed_decision_is_not_emitted(self) -> None:
        """The native trace writer refuses unknown decisions and empty reasons."""
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            env = {
                **os.environ,
                "HOME": str(base),
                "CODERAILS_AGENTIC_LOOP_DIR": str(base),
                "PYTHONPATH": os.pathsep.join((str(CODEX), str(CODEX / "hooks/scripts"))),
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from hook_common import append_trace_row; "
                    "assert not append_trace_row('gate', 'made_up_decision', 'reason', 's1'); "
                    "assert not append_trace_row('gate', 'blocked', '', 's1')",
                ],
                cwd=base,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((base / "s1" / "trace.jsonl").exists())

    def test_helpers_are_mirrored(self) -> None:
        """Both standalone plugins ship the same typed helper and trace writer."""
        for filename in ("trace_row.py", "hook_decision.py"):
            self.assertEqual(
                (ROOT / "hooks/scripts/lib" / filename).read_bytes(),
                (CODEX / "hooks/scripts/lib" / filename).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
