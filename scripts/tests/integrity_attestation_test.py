"""One attestation parser: mutated descriptions give the same reason code through both callers."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "integrity-gate"))
sys.path.insert(0, str(REPO / "scripts" / "integrity-gate" / "tests"))
from hooks.scripts.lib.pr_merge_gate import integrity_reason  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib.integrity_attestation import format_attestation, parse_attestation  # noqa: E402
from scripts.lib.integrity_status import verify_integrity_status  # noqa: E402
from scripts.lib.state_counters import count_reasons  # noqa: E402

gate_policy_test = importlib.import_module("gate_policy_test")
gate_pr: Any = importlib.import_module("integrity_policy").gate_pr
SHA = "a" * 40
MODULE = "hooks.scripts.lib.pr_merge_gate"
VALID: dict[str, Any] = {"state": "success", "creator": {"login": "machine"}, "description": format_attestation(SHA)}
TABLE: list[tuple[str, list[dict[str, Any]], str]] = [
    ("passed", [{**VALID, "description": f"integrity=passed sha={SHA}"}], "attest_not_bound"),
    ("prefixed", [{**VALID, "description": f"xintegrity=pass sha={SHA}"}], "attest_not_bound"),
    ("other sha", [{**VALID, "description": f"integrity=pass sha={'b' * 40}"}], "attest_not_bound"),
    ("sha suffix", [{**VALID, "description": f"integrity=pass sha={SHA}0"}], "attest_not_bound"),
    ("empty", [{**VALID, "description": ""}], "attest_not_bound"),
    ("wrong creator", [{**VALID, "creator": {"login": "other"}}], "attest_wrong_creator"),
    ("pending", [{**VALID, "state": "pending"}], "attest_not_success"),
    ("no status", [], "attest_missing"),
]


def merge_gate_code(rows: list[object]) -> str:
    """Run pr_merge_gate.integrity_reason against canned statuses; return the code or ''."""
    with (
        patch(MODULE + ".config_path", return_value="config"),
        patch(MODULE + ".integrity_machine_user", return_value="machine"),
        patch(MODULE + ".repo", return_value="owner/repo"),
        patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps(rows))),
    ):
        found = re.search(r"attest_\w+", integrity_reason("1", SHA, "."))
    return found.group(0) if found else ""


def status_code(rows: list[object]) -> str:
    """Run integrity_status.verify_integrity_status against canned statuses; return the code or ''."""
    with (
        patch.object(git, "repo", return_value="owner/repo"),
        patch.object(git, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(rows))),
    ):
        try:
            verify_integrity_status(SHA, "machine")
        except git.WorkflowError as error:
            found = re.search(r"attest_\w+", str(error))
            return found.group(0) if found else "uncoded"
    return ""


class AttestationTests(unittest.TestCase):
    """Both callers render the one parser's closed codes."""

    def test_mutation_table_same_code_through_both_callers(self) -> None:
        """Every mutated attestation yields one closed code through the parser, merge.py and the hook."""
        for name, rows, code in TABLE:
            with self.subTest(name):
                self.assertEqual(parse_attestation(rows[0] if rows else None, SHA, "machine").reason_code, code)
                self.assertEqual(status_code(list(rows)), code)
                self.assertEqual(merge_gate_code(list(rows)), code)

    def test_valid_line_passes_both(self) -> None:
        """A well-formed attestation is accepted by the parser and both callers."""
        self.assertTrue(parse_attestation(VALID, SHA, "machine").ok)
        self.assertEqual(status_code([VALID]), "")
        self.assertEqual(merge_gate_code([VALID]), "")

    def test_denial_writes_a_trace_row_with_the_code(self) -> None:
        """A denial under a session leaves one pr_merge_gate trace row carrying the closed reason code."""
        with tempfile.TemporaryDirectory() as base, patch.dict("os.environ", {"CLAUDE_AGENTIC_LOOP_DIR": base}):
            rows = [{**VALID, "state": "pending"}]
            with (
                patch(MODULE + ".config_path", return_value="config"),
                patch(MODULE + ".integrity_machine_user", return_value="machine"),
                patch(MODULE + ".repo", return_value="owner/repo"),
                patch(MODULE + ".run", return_value=subprocess.CompletedProcess([], 0, json.dumps(rows))),
            ):
                self.assertTrue(integrity_reason("1", SHA, ".", "sess"))
            lines = (Path(base) / "sess" / "trace.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(x)["reason_code"] for x in lines], ["attest_not_success"])
            self.assertEqual(count_reasons(Path(base))["attest_not_success"], 1)

    def test_daemon_description_parses(self) -> None:
        """The root-owned daemon's real success description is accepted by the parser."""
        client: Any = gate_policy_test.EvidenceFixture()
        with redirect_stdout(StringIO()):
            self.assertEqual(gate_pr(client, 7, 204800, 720), 0)
        description: str = client.posts[-1][2]
        daemon_sha: str = gate_policy_test.SHA
        status = {"state": "success", "creator": {"login": "machine"}, "description": description}
        self.assertTrue(parse_attestation(status, daemon_sha, "machine").ok, description)
        self.assertTrue(description.startswith(format_attestation(daemon_sha)))

    def test_only_parser_knows_the_token(self) -> None:
        """No other caller regex-matches the attestation tokens; the Codex mirror is byte-identical."""
        for path in (
            "scripts/lib/integrity_status.py",
            "hooks/scripts/lib/pr_merge_gate.py",
            "packages/codex/scripts/lib/integrity_status.py",
        ):
            text = (REPO / path).read_text()
            self.assertNotIn("integrity=pass", text, path)
            self.assertIn("parse_attestation", text, path)
        mirror = REPO / "packages/codex/scripts/lib/integrity_attestation.py"
        self.assertEqual(mirror.read_bytes(), (REPO / "scripts/lib/integrity_attestation.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
