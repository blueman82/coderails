# Coderails run observability design

## Status and intent

The design has approval. The implementation plan awaits inspection.
This design covers post-cutover observability and measurement. The dashboard gives diagnostic records for one native Coderails session and its parallel workers.
The baseline uses verification records from after migration.

Each provider keeps its dispatch, transcript parsing, graph data, record validation, and authority for loop end.
The design does not edit the LLM Wiki, combine `work_units` with graph nodes, or add a shared runtime to the graph-semantics package.

## User outcome

For a selected native session, the user can follow orchestrator and worker operations, their graph nodes, waves, and tries.
The view gives results, errors, recovery, reported file changes and external operations, and records for the loop-end checks.
It marks facts that are unavailable or derived. Native records remain authoritative.

The measurements compare divergence between loop records, duplicate mutations, repair incidents, incorrect blocks and passes at loop end, adapter and test duplication, and maintenance cost.
Each measurement gives its observation method and denominator.
The `work_units` and `graph.nodes` values are different inventories. A difference does not show a defect on its own.

## Current source evidence

- Each provider has a native session ID and session-scoped graph data.
  A graph snapshot cannot show all changes from before the snapshot.

- Claude records connect each worker try to the parent Agent tool call and record UUID. They also identify the subagent type, child agent ID, and wave.
  Loop-end checks validate those links again. Native transcript records have timestamps, tool calls and results, model, and token use.
  The cost miner skips token use from headless child sessions without a parent link.

- Codex transcripts have timestamped turn and model metadata, token use, and tool calls and results. They also have command times and statuses, file changes, MCP call statuses and times, and child records.
  The graph verification records connect parent call, child thread, try, and wave.
  The dashboard reads the previous `~/.codex/projects` tree for broad project work and token use. The graph verification uses `~/.codex/sessions`.

- Codex hook audit defaults to `~/.coderails/codex/discipline.log`. The dashboard health collector defaults to `~/.codex/discipline.log`.
  If `CODERAILS_DISCIPLINE_LOG` does not align them, the hook-count tile can miss the plugin's hook log.

- Dashboard button runs have their own random `runId`. The system has no durable link to a native session.
  Use a `runId` as a native session ID only if a record proves the relationship.

- The dashboard summarizes project work, run totals, and frozen loop cost in different views. It has no session timeline.

- Tool calls and results cannot show all external effects. Timestamps can give an estimate of wait time.
  Native records do not give the cause of a wait directly.

Source paths: `hooks/scripts/lib/graph_evidence.py`, `hooks/scripts/lib/graph_evidence_bind.py`, `hooks/scripts/lib/graph_evidence_revalidate.py`, and `hooks/scripts/lib/loop_cost.py`.
Codex uses `packages/codex/skills/agentic-loop/scripts/graph_transcript.py`, `graph_evidence.py`, `graph_artifacts.py`, and `packages/codex/hooks/scripts/hook_common.py`.
Dashboard sources are `app/src/lib/collect/{sessions,usage,cost,contextTrend,health}.ts` and `app/src/app/api/{events,run}/route.ts` in each provider bundle.

## Proposed architecture

### OpenTelemetry choice

Use the OpenTelemetry model for IDs, parent and child relationships, span entries, status, and applicable GenAI and tool attributes.
Keep Coderails provenance, source sequence, nullable timestamps, and derived or unavailable markers as explicit Coderails attributes.
Historical provider records can fall short of live-span timing conditions.

Serialize the provider's local index as JSONL. The provider can build it again.
It follows the OTel model and does not export OTLP.
Do not add an OTel SDK, collector, LangSmith integration, remote exporter, or network transmission in this phase.
Build diagnostic records from native data. Do not add instrumentation to the model runtime.

### 1. Provider-owned read adapters

Each provider bundle finds and parses its native sessions and transcripts, connects workers to parents, reads graph and artifacts, and checks provenance.
The adapter maps recognized source records into a small versioned structure.
Source refs keep provider-only IDs and fields. Normalization keeps differences that change meaning.

The dashboard can run the adapters and display normalized entries.
The graph-semantic kernel and installed graph runtime do not import the dashboard or a telemetry service.
Adapters read only. They do not repair graph data, create loop-end records, or rewrite sources.

### 2. On-demand trace assembly and local cache

On user input, build the session timeline from native and linked worker transcripts, current graph data, hook audit, and eval, proof, and retro artifacts.
Use the provider's local index, which the dashboard can build again:

```text
~/.coderails/telemetry/<provider>/<safe-session-id>/manifest.json
~/.coderails/telemetry/<provider>/<safe-session-id>/events.jsonl
```

The manifest has schema and parser version, provider, session and loop IDs, source identities and fingerprints, scan cursors, generation time, completeness, and errors.
The `events.jsonl` file has normalized metadata, correlation IDs, provenance, and source refs only.
It does not copy prompts, tool arguments, command output, or transcript text.

Provider adapters own path resolution, parsing, locking, atomic replacement, and index regeneration.
If sources change or truncate, build the index again.
The index cannot authorize a graph update. The user can remove it and regenerate it from native artifacts.

Keep source paths, record IDs, and line or item refs so the user can check each entry.
Read large inputs and results from the native source only when the user opens the full record.
Keep source content unchanged and show unavailable or truncated content explicitly.

Measure cache length and retrieval behavior before adding a time limit for expiry.
The user can clear the derived index. Source removal makes the corresponding timeline unavailable without leaving copied source text.

The first view is a session timeline in the local dashboard. The native session row opens it.
A button run `runId` can point to a native session only when output or explicit metadata establishes the relationship.
If there is no relation, show it as its own run.

### 3. Event shape and provenance

Each normalized entry has schema version, deterministic ID, provider, native session or thread ID, type, actor or worker identity when available, and a source ref.
Time is nullable because snapshots and some artifacts have no timestamp. Each entry keeps the source sequence or ordinal.

Optional correlation fields are loop ID, graph revision, wave ID, node ID, and try. They also include native tool or call ID, child thread or agent ID, and parent entry ID.
Other fields are measured time, status or error, command or tool name, file-change summary, token use, and artifact refs.

Proposed JSONL record:

```json
{
  "schema_version": 1,
  "event_id": "sha256(provider, session_id, source_id, source_record_id, event_kind)",
  "provider": "codex",
  "session_id": "native-session-id",
  "loop_id": "loop-id",
  "event_kind": "tool_result",
  "timestamp": {"value": "2026-09-28T12:34:56Z", "basis": "source"},
  "source_order": {"source_id": "parent-transcript", "ordinal": 82},
  "actor": {"kind": "worker", "native_id": "child-thread-id"},
  "correlation": {
    "parent_event_id": "...",
    "wave_id": "wave-2",
    "node_id": "U3[2]",
    "attempt": 1,
    "native_call_id": "call-id"
  },
  "status": {"value": "failed", "basis": "source"},
  "duration_ms": {"value": 1200, "basis": "source"},
  "source_ref": {"kind": "codex_transcript_record", "record_id": "item-id"},
  "details_ref": {"kind": "transcript_content", "record_id": "item-id"}
}
```

The `timestamp.value` and `duration_ms` fields are nullable. The `basis` is `source`, `derived`, or `unavailable`.
Keep the source sequence when available. For snapshots or artifacts without time, keep their sequence and show unknown time.
Merge the source sequences by timestamp only if the timestamps are correct.

If times tie or are unavailable across sources, mark the sequence as ambiguous.
For display only, use a stable sort by source and source sequence.
Do not use file mtime as the time of an occurrence.

Facts use `observed`, `derived`, or `unavailable`. Time-gap estimates and joins across sources are derived. Record their method and source IDs.
Do not encode missing model, token use, cost, or time as zero.
Keep observed token use and estimated USD cost as different measures. Mark the frozen retro cost as an estimate and do not calculate a new price.

### 4. Trace sections

- Orchestrator and worker lifecycle: dispatch, start, loop end, abort, stale recovery, retry, and hard stop.
- Tool calls and available results in source time sequence and connected by provider-native IDs.
- Times from source results and estimated intervals from timestamps. The estimated intervals have unknown cause.
- Reported file changes and Git boundary snapshots when available. A tool call cannot prove that files changed.
- External command and service effects only if the native result or an artifact that someone checks independently records them.
  A command try cannot count as a checked external effect.
- Source links for graph data, evals, proofs, retro, and verification records for loop end through source links. Provider checks remain authoritative.
- Token use and cost from measurements or explicit estimates, with coverage and exclusions.

### 5. Baseline measurement and counting rules

Use a census of sessions for a declared date window and provider set. List exclusions.
Each metric has name and version, numerator, denominator, nullable rate, cohort and window, source refs, observation method, exclusions, and basis.
The basis is `observed`, `derived`, or `manual`. Publish counts with rates. A small cohort cannot show a stable rate.

Counting rules:

- **Divergence between loop records:** Count mismatches only for explicit work-unit and node relationships.
  Divide by the number of those relationships that someone inspects independently. Current `eval_refs` do not map them.
  Without a mapping, report divergence as `not measurable`. Report the two inventories on their own. A difference in counts is not a defect by itself.

- **Duplicate mutation:** Count retries that repeat an accepted change. An audit must show independently that the retry used the same operation and target.
  Divide by all mutation sequences someone audited independently. Skip rejected calls and retries necessary to finish a change.
  Use a manual incident record until a source can prove the mutation mechanically.

- **Repair incidents:** Count repair episodes that someone groups independently. Divide by the number of sessions inspected.
  Record the session, affected data, cause, repair step, and verification records.
  Count multiple commands from one episode as one incident.

- **Incorrect block at loop end:** Count blocks that someone independently shows violated their documented condition.
  Divide by blocks someone replays independently against the same source artifacts.

- **Incorrect pass at loop end:** Count results that someone shows independently permitted loop end despite an unmet condition.
  Divide by results that permitted loop end and that someone audited independently. A provider's own success claim cannot count as the audit.

- **Adapter and test duplication:** For each shared semantic change, list the implementation and test files for each provider. Give the lines added or edited.
  Count tests that exercise duplicate behavior. Report each change and the total. Do not count mandatory provider-native behavior as duplication.

- **Updates across loop views:** Count audited items with repeat manual updates in `work_units` and graph nodes.
  Divide by items where the owner explicitly intended the two views to show the same decision.
  Do not infer a one-to-one relationship.

- **Maintenance cost:** Use a small manual task record of active engineering minutes for graph changes.
  Count shared-kernel, Claude-adapter, Codex-adapter, test, and repair work.
  Report minutes for each change and their sum for each category. Token use does not give minutes.

For release, each entry must have a source ref that resolves or an explicit unavailable marker.
Each correlation field must come from a source or carry a derived label.
100% of published metric values must have a denominator, source, and method.
The number of missing values shown silently as zero must be 0.
The fixtures must give no incorrect external-effect or loop-end claims.

The live baseline is a census of the declared cohort. Report cohort count and all exclusions.
Set no numeric target for operation before the first baseline.
The report compares the current graph data model and adapters as used. The decision to unify the inventories is out of scope.
Use an RFC only if measurements justify it.

## Safety and retention

- Read only from the local dashboard and provider artifact roots. Do not upload or publish telemetry.

- Do not copy full transcripts into a new durable store. Native files stay authoritative.
  Give source refs. Read a full source record only when the user opens it.

- Tool inputs and results can be sensitive. Do not put full records in the cache, list responses, or summary pages.
  Give only the selected record after the user expands it and the local-origin and token checks succeed.
  Display escaped plain text without HTML. Do not log the content.

  These checks control access and display. They cannot promise secret redaction.
  Show missing content as unavailable. Do not report the timeline as complete if the source has no content for it.

- Follow each provider's transcript permissions and uniqueness checks. Mark ambiguous session or worker links unresolved.

- Limit scans with measured source behavior. Paginate large timelines.
  Give the scan and output counts and report truncation explicitly. Do not infer a safe fixed excerpt length.

## Acceptance criteria

1. Use a fixture from a live session for each provider. One timeline shows the orchestrator and parallel workers with correct native correlation IDs.
2. Test retry, stale recovery, hard stop, errors and abort, and unfinished or ambiguous joins. Also test missing token use, inferred timing, and loop-end records.
   Check links for eval, proof, and retro records.
3. A tool call cannot count as a checked external effect. A provider status cannot count as a result someone verified independently.
   Missing values cannot count as zero.
4. Dashboard `runId` identifies a native session only if a test checks an explicit mapping.
5. The view is read-only. It shows corrupt, truncated, or unreadable data with provenance and writes no graph or source files.
6. The view reads large source records on demand, gives measured retrieval and truncation, and keeps the source readable.
7. Metrics give cohort, denominator, observation method, exclusions, and a basis of observed, derived, or manual for each value.
8. Each provider installs its own adapters. The shared semantic kernel does not parse provider transcripts or apply their verification policies.

## Resolved implementation decisions

- Use OpenTelemetry-aligned local JSONL. This phase adds no OTel SDK or collector or remote exporter.
- Use provider-local dashboard modules for assembly and cache. The provider CLIs do not own that logic.
- Use only native transcript and entry structures from sanitized fixtures from live sessions and current verification readers.
  Mark unknown or malformed structures unfinished or unresolved.
  Do not infer version or launch-mode behavior from undocumented fields.

- Session summaries and pages contain metadata only. Read one full record on explicit user input after local-origin and token checks.
  Display it as escaped plain text. Do not cache or log it. This does not redact secrets.
- The baseline cohort starts at the Python cutover merge (`e1090098`, 2026-09-28 11:32:24 UTC). It ends at the UTC census time in the report.
  The report holds metrics and incident and task records. Mark historical maintenance minutes unavailable when there is no record. Do not estimate them.

These decisions add no daemon, remote backend, new graph authority, or work to unify loop inventories.
