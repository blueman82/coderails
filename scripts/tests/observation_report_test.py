"""Source-bound tests for the descriptive native trace report."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "observation_report.py"


def digest(data: bytes) -> str:
    """Hash fixture bytes."""
    return hashlib.sha256(data).hexdigest()


class ObservationReportTests(unittest.TestCase):
    """Use small native-shaped files with known source bytes."""

    def setUp(self) -> None:
        """Create one bound native source and derived trace event."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        (self.root / "workflow.config.yaml").write_text("memory:\n  backend: off\n")
        self.source = self.root / "native.jsonl"
        self.source.write_bytes(b'{"message":"SECRET BODY"}\n')
        self.event: dict[str, Any] = {
            "schemaVersion": 1,
            "eventId": "event-1",
            "traceId": digest(b"claude:s1")[:32],
            "spanId": "span-1",
            "parentSpanId": None,
            "name": "tool_result",
            "kind": "internal",
            "status": {"value": "ok", "basis": "source"},
            "startTimeUnixNano": None,
            "endTimeUnixNano": None,
            "events": [],
            "attributes": {
                "coderails.start_time.basis": "unavailable",
                "coderails.end_time.basis": "unavailable",
                "coderails.observation.kind": "read",
                "coderails.observation.target_kind": "skill",
                "coderails.observation.target_sha256": "a" * 64,
                "coderails.observation.bytes": 11,
                "coderails.native.call_id": "call-1",
                "coderails.usage.semantics": "cumulative",
                "gen_ai.usage.input_tokens": 42,
            },
            "provenance": {
                "provider": "claude",
                "nativeSessionId": "s1",
                "sourceId": "native.jsonl",
                "sourceOrdinal": 1,
                "basis": "observed",
                "sourceRef": {"kind": "claude_parent_record", "recordId": "native.jsonl:1", "ordinal": 1},
            },
        }
        self.manifest_path = self.root / "manifest.json"
        self.config_path = self.root / "cohorts.json"
        self.write_inputs()

    def write_inputs(self, rows: list[dict[str, Any]] | None = None) -> None:
        """Refresh cohort hashes after a fixture change."""
        rows = rows if rows is not None else [self.event]
        events = ("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)).encode()
        self.events_path = self.root / f"events.{digest(events)}.jsonl"
        self.events_path.write_bytes(events)
        manifest = {
            "schemaVersion": 1,
            "parserVersion": 5,
            "provider": "claude",
            "nativeSessionId": "s1",
            "loopId": None,
            "sources": [
                {
                    "sourceId": "native.jsonl",
                    "fingerprint": f"sha256:{digest(self.source.read_bytes())};identity:1:2:3:4",
                    "cursor": "1",
                }
            ],
            "generatedAt": "2026-10-25T00:00:00Z",
            "complete": True,
            "errors": [],
            "eventCount": len(rows),
            "eventFile": self.events_path.name,
        }
        self.manifest_path.write_text(json.dumps(manifest))
        self.session: dict[str, Any] = {
            "provider": "claude",
            "native_session_id": "s1",
            "parser_version": 5,
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": digest(self.manifest_path.read_bytes()),
            "events_path": str(self.events_path),
            "events_sha256": digest(self.events_path.read_bytes()),
            "source_files": [
                {"source_id": "native.jsonl", "path": str(self.source), "sha256": digest(self.source.read_bytes())}
            ],
            "eligible": True,
            "excluded_reason": None,
            "retry_of": None,
        }
        self.config: dict[str, Any] = {"schema_version": 1, "cohorts": {"baseline": [self.session], "comparison": []}}
        self.config_path.write_text(json.dumps(self.config))

    def run_report(self) -> subprocess.CompletedProcess[str]:
        """Run the CLI without copying its source files to stdout."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.config_path)],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_report_counts_bound_observations_without_bodies_or_token_sums(self) -> None:
        """Count observations while keeping source text and paths out of the report."""
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        cohort = report["cohorts"]["baseline"]
        self.assertEqual(cohort["eligible_sessions"], 1)
        self.assertEqual(cohort["observations"]["read"], 1)
        self.assertEqual(cohort["coverage"], {"complete": 1, "eligible": 1})
        self.assertEqual(cohort["usage_records"], 1)
        self.assertNotIn("token_total", result.stdout)
        self.assertNotIn("SECRET BODY", result.stdout)
        self.assertNotIn(str(self.root), result.stdout)

    def test_usage_counts_native_records_once_across_tool_events(self) -> None:
        """Several tool events from one message share one native usage record."""
        first = copy.deepcopy(self.event)
        first["name"] = "tool_use"
        first["attributes"] = {"coderails.usage.semantics": "incremental", "gen_ai.usage.input_tokens": 8}
        first["provenance"]["sourceRef"]["recordId"] = "native.jsonl:1:item:0"
        second = copy.deepcopy(first)
        second.update(eventId="event-2", spanId="span-2")
        second["provenance"]["sourceRef"]["recordId"] = "native.jsonl:1:item:1"
        third = copy.deepcopy(first)
        third.update(eventId="event-3", spanId="span-3")
        third["provenance"]["sourceOrdinal"] = 2
        third["provenance"]["sourceRef"].update(recordId="native.jsonl:2:item:0", ordinal=2)
        self.write_inputs([first, second, third])
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["cohorts"]["baseline"]["usage_records"], 2)

    def test_usage_deduplicates_native_message_identity_across_rows(self) -> None:
        """Repeated Claude message snapshots count once, distinct identities remain distinct."""
        first = copy.deepcopy(self.event)
        first["attributes"] = {
            "coderails.usage.semantics": "incremental",
            "coderails.usage.identity_sha256": "b" * 64,
            "gen_ai.usage.input_tokens": 8,
        }
        second = copy.deepcopy(first)
        second.update(eventId="event-2", spanId="span-2")
        second["provenance"]["sourceOrdinal"] = 2
        second["provenance"]["sourceRef"].update(recordId="native.jsonl:2", ordinal=2)
        third = copy.deepcopy(second)
        third.update(eventId="event-3", spanId="span-3")
        third["provenance"]["sourceOrdinal"] = 3
        third["provenance"]["sourceRef"].update(recordId="native.jsonl:3", ordinal=3)
        third["attributes"]["coderails.usage.identity_sha256"] = "c" * 64
        self.write_inputs([first, second, third])
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["cohorts"]["baseline"]["usage_records"], 2)

    def test_malformed_usage_identity_refuses(self) -> None:
        """The metadata identity must be a digest, not retained native text."""
        self.event["attributes"]["coderails.usage.identity_sha256"] = "PRIVATE_NATIVE_ID"
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)

    def test_foreign_provider_source_reference_refuses(self) -> None:
        """A Claude event cannot claim a Codex native record reference."""
        self.event["provenance"]["sourceRef"]["kind"] = "codex_parent_record"
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign source reference", result.stderr)

    def test_named_worker_metadata_keeps_public_report_counts(self) -> None:
        """Safe display metadata cannot make a source-bound worker report unreadable."""
        plain = self.run_report()
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.event["attributes"].update(
            {
                "coderails.actor.kind": "worker",
                "coderails.actor.id": "child-one",
                "coderails.actor.name": "Builder",
            }
        )
        self.write_inputs()
        named = self.run_report()
        self.assertEqual(named.returncode, 0, named.stderr)
        named_counts = json.loads(named.stdout)["cohorts"]["baseline"]
        plain_counts = json.loads(plain.stdout)["cohorts"]["baseline"]
        for field in ("eligible_sessions", "observations", "coverage", "usage_records"):
            self.assertEqual(named_counts[field], plain_counts[field], field)
        self.assertEqual(named_counts["usage_records"], 1)
        self.assertEqual(named_counts["observations"]["read"], 1)
        self.assertNotIn("Builder", named.stdout)
        self.assertNotIn("SECRET BODY", named.stdout)

    def test_worker_display_metadata_requires_safe_name_kind_and_identity(self) -> None:
        """Hostile names and missing worker bindings cannot enter report metadata."""
        attrs = dict(self.event["attributes"])
        for change in (
            {"coderails.actor.name": "<img src=x>"},
            {"coderails.actor.name": "Builder\n"},
            {"coderails.actor.name": "A" * 41},
            {"coderails.actor.name": None},
            {"coderails.actor.kind": "orchestrator"},
            {"coderails.actor.id": ""},
            {"coderails.actor.id": " "},
            {"coderails.actor.id": None},
        ):
            with self.subTest(change=change):
                self.event["attributes"] = {
                    **attrs,
                    "coderails.actor.kind": "worker",
                    "coderails.actor.id": "child-one",
                    "coderails.actor.name": "Builder",
                    **change,
                }
                self.write_inputs()
                result = self.run_report()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("worker display", result.stderr)

    def test_changed_source_and_foreign_identity_refuse(self) -> None:
        """A changed source or foreign session cannot join a cohort."""
        self.source.write_bytes(b'{"message":"CHANGED"}\n')
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source hash", result.stderr)
        self.source.write_bytes(b'{"message":"SECRET BODY"}\n')
        self.event["provenance"]["nativeSessionId"] = "foreign"
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign event", result.stderr)

    def test_duplicate_event_and_raw_field_refuse(self) -> None:
        """Extra event fields and duplicate IDs cannot enter a report."""
        self.event["prompt"] = "SECRET BODY"
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("event fields", result.stderr)
        self.event.pop("prompt")
        self.write_inputs([self.event, self.event])
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate event ID", result.stderr)

    def test_exclusion_and_retry_change_denominator_not_raw_counts(self) -> None:
        """An excluded retry has no observation denominator."""
        self.session["eligible"] = False
        self.session["excluded_reason"] = "pilot session"
        self.session["retry_of"] = None
        self.config_path.write_text(json.dumps(self.config))
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        cohort = json.loads(result.stdout)["cohorts"]["baseline"]
        self.assertEqual(cohort["eligible_sessions"], 0)
        self.assertEqual(cohort["excluded_sessions"], 1)
        self.assertEqual(cohort["retry_sessions"], 0)
        self.assertEqual(cohort["observations"]["read"], 0)

    def test_foreign_retry_and_nonfinite_json_refuse(self) -> None:
        """A retry must name an enrolled session and NaN cannot be metadata."""
        self.session["retry_of"] = "other-provider-session"
        self.config_path.write_text(json.dumps(self.config))
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign retry join", result.stderr)
        self.session["retry_of"] = None
        self.config_path.write_text(json.dumps(self.config))
        self.event["attributes"]["gen_ai.usage.input_tokens"] = float("nan")
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nonfinite JSON value", result.stderr)

    def test_foreign_parent_and_changed_event_generation_refuse(self) -> None:
        """Parent and event-file identities must match the same source set."""
        self.event["parentSpanId"] = "foreign-span"
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign parent span", result.stderr)
        self.event["parentSpanId"] = None
        self.write_inputs()
        self.events_path.write_bytes(self.events_path.read_bytes() + b" ")
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("events hash mismatch", result.stderr)

    def test_duplicate_span_and_foreign_source_reference_refuse(self) -> None:
        """A joined span and native record must identify one local source row."""
        other = {**self.event, "eventId": "event-2"}
        self.write_inputs([self.event, other])
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate span ID", result.stderr)
        self.event["provenance"]["sourceRef"]["recordId"] = "foreign.jsonl:1"
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign source reference", result.stderr)

    def test_malformed_status_refuses(self) -> None:
        """A source hash does not make malformed trace metadata valid."""
        self.event["status"] = {"value": "ok", "basis": "unknown"}
        self.write_inputs()
        result = self.run_report()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid event status", result.stderr)


if __name__ == "__main__":
    unittest.main()
