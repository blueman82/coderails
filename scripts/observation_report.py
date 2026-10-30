#!/usr/bin/env python3
"""Count source-bound native trace observations without copying transcript text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib.observation_report_schema import (  # noqa: E402
    EVENT_FILE,
    FINGERPRINT,
    KINDS,
    ReportError,
    bound_file,
    check_event,
    mapping,
    named,
    object_keys,
    parse_json,
    require,
    sequence,
)


def check_manifest(
    manifest: object, session: dict[str, Any], sources: dict[str, str], events_path: Path, events_hash: str
) -> dict[str, Any]:
    """Bind the native sources and event generation to one parser/session."""
    keys = {
        "schemaVersion",
        "parserVersion",
        "provider",
        "nativeSessionId",
        "loopId",
        "sources",
        "generatedAt",
        "complete",
        "errors",
        "eventCount",
        "eventFile",
    }
    data = object_keys(manifest, keys, "manifest")
    require(
        data["schemaVersion"] == 1
        and type(data["parserVersion"]) is int
        and data["parserVersion"] == session["parser_version"],
        "parser version mismatch",
    )
    require(
        data["provider"] == session["provider"] and data["nativeSessionId"] == session["native_session_id"],
        "foreign manifest",
    )
    require(data["loopId"] is None or isinstance(data["loopId"], str), "invalid loop identity")
    require(
        type(data["complete"]) is bool
        and all(isinstance(item, str) for item in sequence(data["errors"], "manifest errors")),
        "invalid manifest coverage",
    )
    require(type(data["eventCount"]) is int and data["eventCount"] >= 0, "invalid event count")
    match = EVENT_FILE.fullmatch(str(data["eventFile"]))
    require(
        match is not None and match.group(1) == events_hash and events_path.name == data["eventFile"],
        "event generation mismatch",
    )
    found: dict[str, str] = {}
    for item in sequence(data["sources"], "sources"):
        source = object_keys(item, {"sourceId", "fingerprint", "cursor"}, "source")
        source_id = named(source["sourceId"], "source ID")
        match = FINGERPRINT.fullmatch(str(source["fingerprint"]))
        if match is None or source_id in found:
            raise ReportError("invalid source fingerprint")
        found[source_id] = match.group(1)
    require(found == sources, "source hash mismatch")
    return data


def session_result(session: object, base: Path) -> dict[str, Any]:
    """Validate one enrolled session and count eligible observations."""
    keys = {
        "provider",
        "native_session_id",
        "parser_version",
        "manifest_path",
        "manifest_sha256",
        "events_path",
        "events_sha256",
        "source_files",
        "eligible",
        "excluded_reason",
        "retry_of",
    }
    row = object_keys(session, keys, "session")
    require(
        row["provider"] in ("claude", "codex") and type(row["parser_version"]) is int and row["parser_version"] > 0,
        "invalid provider or parser",
    )
    named(row["native_session_id"], "session ID")
    require(
        type(row["eligible"]) is bool
        and (row["excluded_reason"] is None or isinstance(row["excluded_reason"], str))
        and (row["retry_of"] is None or isinstance(row["retry_of"], str)),
        "invalid eligibility",
    )
    require(row["eligible"] != bool(row["excluded_reason"]), "eligibility reason mismatch")
    sources: dict[str, str] = {}
    for entry in sequence(row["source_files"], "source files"):
        item = object_keys(entry, {"source_id", "path", "sha256"}, "source file")
        source_id = named(item["source_id"], "source ID")
        require(source_id not in sources, "duplicate source ID")
        bound_file(item["path"], item["sha256"], base, "source")
        sources[source_id] = item["sha256"]
    manifest_path, manifest_bytes = bound_file(row["manifest_path"], row["manifest_sha256"], base, "manifest")
    events_path, events_bytes = bound_file(row["events_path"], row["events_sha256"], base, "events")
    require(events_path.parent == manifest_path.parent, "foreign event generation")
    manifest = check_manifest(parse_json(manifest_bytes), row, sources, events_path, row["events_sha256"])
    lines = events_bytes.splitlines()
    require(all(line for line in lines) and len(lines) == manifest["eventCount"], "event count mismatch")
    counts: dict[str, int] = {kind: 0 for kind in KINDS}
    event_ids: set[str] = set()
    span_ids: set[str] = set()
    parent_ids: set[str] = set()
    usage_records: set[tuple[str, int | str]] = set()
    for line in lines:
        event = mapping(parse_json(line), "event")
        event_id, kind, usage, span_id, parent_id = check_event(event, row, set(sources))
        require(event_id not in event_ids, "duplicate event ID")
        event_ids.add(event_id)
        require(span_id not in span_ids, "duplicate span ID")
        span_ids.add(span_id)
        if parent_id is not None:
            parent_ids.add(parent_id)
        if kind is not None and row["eligible"]:
            counts[kind] += 1
        if usage and row["eligible"]:
            provenance = event["provenance"]
            identity = event["attributes"].get("coderails.usage.identity_sha256")
            usage_id = identity if row["provider"] == "claude" and identity else provenance["sourceOrdinal"]
            usage_records.add((provenance["sourceId"], usage_id))
    require(parent_ids <= span_ids, "foreign parent span")
    return {
        "provider": row["provider"],
        "native_session_id": row["native_session_id"],
        "parser_version": row["parser_version"],
        "eligible": row["eligible"],
        "retry": row["retry_of"] is not None,
        "retry_of": row["retry_of"],
        "complete": manifest["complete"],
        "manifest_sha256": row["manifest_sha256"],
        "events_sha256": row["events_sha256"],
        "sources": [{"source_id": key, "sha256": sources[key]} for key in sorted(sources)],
        "observations": counts,
        "usage_records": len(usage_records),
    }


def report(config: object, base: Path) -> dict[str, Any]:
    """Return deterministic baseline and comparison counts."""
    data = object_keys(config, {"schema_version", "cohorts"}, "cohort config")
    cohorts = mapping(data["cohorts"], "cohorts")
    require(data["schema_version"] == 1 and set(cohorts) == {"baseline", "comparison"}, "invalid cohort config")
    out: dict[str, Any] = {}
    identities: set[tuple[str, str]] = set()
    for label in ("baseline", "comparison"):
        rows = sequence(cohorts[label], "cohort sessions")
        results = [session_result(row, base) for row in rows]
        for item in results:
            identity = (item["provider"], item["native_session_id"])
            require(identity not in identities, "duplicate session identity")
            identities.add(identity)
        for item in results:
            if item["retry_of"] is not None:
                require(
                    (item["provider"], item["retry_of"]) in identities
                    and item["retry_of"] != item["native_session_id"],
                    "foreign retry join",
                )
        eligible = [item for item in results if item["eligible"]]
        counts = {kind: sum(item["observations"][kind] for item in eligible) for kind in KINDS}
        out[label] = {
            "registered_sessions": len(results),
            "eligible_sessions": len(eligible),
            "excluded_sessions": len(results) - len(eligible),
            "retry_sessions": sum(item["retry"] for item in results),
            "coverage": {"complete": sum(item["complete"] for item in eligible), "eligible": len(eligible)},
            "usage_records": sum(item["usage_records"] for item in eligible),
            "observations": counts,
            "sessions": sorted(results, key=lambda item: (item["provider"], item["native_session_id"])),
        }
    return {
        "schema_version": 1,
        "cohorts": out,
        "limits": [
            "Counts describe enrolled sessions only.",
            "Usage records can be cumulative; token totals are unavailable.",
            "No quality or causal result is inferred.",
        ],
    }


def main() -> int:
    """Read one cohort file and write a metadata-only report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path)
    args = parser.parse_args()
    try:
        result = report(parse_json(args.cohort.read_bytes()), args.cohort.resolve().parent)
    except OSError:
        print("cohort file unavailable", file=sys.stderr)
        return 2
    except ReportError as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
