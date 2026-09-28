"""Mechanical integrity attestation controls using an entirely local fake client."""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/integrity-gate"))
from integrity_http import JsonObject
from integrity_policy import gate_pr, should_gate, valid_evidence

ROOT = Path(__file__).resolve().parents[3]

SHA = "a" * 40


def artifact() -> str:
    """Construct exact SHA-bound reviewable fixture evidence."""
    data: JsonObject = {"schema_version": 1, "task_ref": "fixture", "frozen_sha": SHA, "head_sha": SHA, "evals": []}
    return f"<!-- coderails-eval-summary v1 pr=7 head_sha={SHA} result=GO -->\n```json\n{json.dumps(data)}\n```"


class IntegrityRunnerTests(unittest.TestCase):
    """Exercise status reuse, evidence binding, policy and bounded inputs."""

    def test_status_parity(self) -> None:
        """Consider a fresh head and recheck only expired pending statuses."""
        self.assertTrue(should_gate([], 720))
        self.assertFalse(should_gate([{"state": "success"}], 720))
        self.assertFalse(should_gate([{"state": "failure"}], 720))
        self.assertFalse(should_gate([{"state": "error"}], 720))
        self.assertFalse(should_gate([{"state": "pending", "created_at": "invalid"}], 720))
        self.assertFalse(
            should_gate(
                [{"state": "pending", "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}], 720
            )
        )
        self.assertTrue(should_gate([{"state": "pending", "created_at": "2020-01-01T00:00:00Z"}], 720))

    def test_evidence_exact_sha_and_schema(self) -> None:
        """Malformed JSON or stale identity never counts as attested evidence."""
        self.assertTrue(valid_evidence(artifact(), SHA))
        self.assertFalse(valid_evidence(artifact(), "b" * 40))
        self.assertFalse(valid_evidence("```json\n[]\n```", SHA))
        self.assertFalse(valid_evidence(artifact().replace('"evals": []', '"evals": {}'), SHA))

    def test_gate_controls(self) -> None:
        """Success requires live review, allowed paths, bounded diff and status writes."""
        client = Mock()
        client.get_object.return_value = {"head": {"sha": SHA}}
        client.comments.return_value = [artifact(), f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->"]

        def safe_response(target: str) -> list[JsonObject]:
            """Return an unattested fresh head and an allowed file."""
            return [] if "statuses" in target else [{"filename": "src/example.py"}]

        client.get_array.side_effect = safe_response
        client.get.return_value = "safe diff"
        self.assertEqual(gate_pr(client, 7, 204800, 720), 0)
        self.assertEqual(client.post_status.call_args.args[1], "success")
        client.comments.return_value = [artifact()]
        self.assertEqual(gate_pr(client, 7, 204800, 720), 1)
        self.assertIn("review_evidence_missing", client.post_status.call_args.args[2])
        client.comments.return_value.append(f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->")
        self.assertEqual(gate_pr(client, 7, 2, 720), 0)
        self.assertIn("diff_invalid_or_oversize", client.post_status.call_args.args[2])

        def denied_response(target: str) -> list[JsonObject]:
            """Return an unattested head with a denied policy file."""
            return [] if "statuses" in target else [{"filename": "launchd/unsafe.py"}]

        client.get_array.side_effect = denied_response
        self.assertEqual(gate_pr(client, 7, 204800, 720), 0)
        self.assertIn("policy_path_launchd/unsafe.py", client.post_status.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
