# Coderails run observability design

## Status and intent

Design approved; implementation plan review pending. This design covers the
accepted post-cutover observability and measurement phase. It calls for a trace
of one native Coderails session, including parallel workers, and an
evidence-based post-migration baseline.

Each provider keeps its own dispatch and transcript parser. Graph state, evidence checks, and completion authority stay with the provider. This design does not update the LLM Wiki. It does not combine `work_units` with graph nodes. It does not add a shared runtime to the graph-semantics package.

## User outcome

For a selected native session, the user can see the actions that the orchestrator and workers attempted. The view links work to graph nodes, waves, and attempts. It shows results, failures, and recovery. It shows reported file changes and external actions. It links completion to its evidence. It marks facts that are unavailable or inferred. The trace is a diagnostic view. It is not a second source of truth.

The measurement output compares state divergence, duplicate mutations, and repair incidents. It also compares false completion blocks and passes, duplicated adapter or test work, and maintenance cost. Each measurement names its method and denominator. `work_units` and `graph.nodes` remain separate. A difference between their counts is not itself a defect.

## Current source evidence

- Both providers have a native session identifier and session-scoped graph state. Graph state is a snapshot and does not by itself preserve every transition.
- Claude graph evidence binds each worker attempt to its parent Agent call and record UUID. It also records the subagent type, child agent ID, wave, and attempt. Completion checks those links again. Native transcripts record time, tool calls and results, model, and usage. The current cost miner excludes headless child usage when no parent link exists.
- Codex native transcripts record turn and model time, token usage, and tool calls and results. They also record command status and duration, file changes, MCP call status and duration, and subagent activity. Graph evidence joins the parent call to the child thread, attempt, and wave. The dashboard reads the older `~/.codex/projects` tree for broad activity and usage. Native graph verification reads `~/.codex/sessions`.
- Codex hook audit defaults to `~/.coderails/codex/discipline.log`, while the dashboard health collector defaults to `~/.codex/discipline.log`; unless `CODERAILS_DISCIPLINE_LOG` aligns them, its hook-count tile may not observe the Codex plugin's hook log.
- Dashboard button runs have a separate random `runId`; no durable native session link is present. A `runId` must not be treated as a native session ID without explicit evidence.
- Dashboard views currently summarize project activity, run totals, and frozen loop cost separately. They do not assemble a session-level timeline.
- Tool invocation and recorded result do not prove every external side effect. Wait duration may be estimated from timestamps; the reason for a wait is not directly emitted.

Source anchors:

- Claude: `hooks/scripts/lib/graph_evidence.py`, `graph_evidence_bind.py`, `graph_evidence_revalidate.py`, and `loop_cost.py`.
- Codex: `packages/codex/skills/agentic-loop/scripts/graph_transcript.py`, `graph_evidence.py`, and `graph_artifacts.py`; also `packages/codex/hooks/scripts/hook_common.py`.
- Dashboards: `app/src/lib/collect/{sessions,usage,cost,contextTrend,health}.ts` and `app/src/app/api/{events,run}/route.ts` in each provider bundle.

## Proposed architecture

### OpenTelemetry choice

Use the OpenTelemetry trace model for trace and span IDs. Use it for parent-child work, span events, status, and suitable GenAI or tool attributes. Keep Coderails provenance and source order as explicit attributes. Keep nullable times and derived or unavailable markers explicit. Historical records do not always meet live-span timing requirements. Store the rebuildable local index as provider-owned JSONL, as shown below. Its format follows OTel, but it is not an OTLP export. This phase adds no OTel SDK, collector, LangSmith integration, remote exporter, or network transfer. It reconstructs traces from native evidence. It does not instrument the model runtime.

### 1. Provider-owned read adapters

Each provider bundle finds its own sessions and parses its own transcripts. It links workers, loads graph records and artifacts, and checks provenance. Each adapter maps supported records to a small, versioned trace-event shape. Provider-specific IDs and fields remain available as source references. Normalization must retain differences that affect meaning.

The dashboard may orchestrate these adapters and render the normalized events. The graph-semantic kernel and installed graph runtime do not import the dashboard or a telemetry service. Adapters are read-only and never repair graph state, synthesize completion, or rewrite source evidence.

### 2. On-demand trace assembly and local cache

Build a session trace when requested. Read native and linked worker transcripts, current graph state, hook audit records, and eval, proof, and retro artifacts. Use a rebuildable local index owned by the provider:

```text
~/.coderails/telemetry/<provider>/<safe-session-id>/manifest.json
~/.coderails/telemetry/<provider>/<safe-session-id>/events.jsonl
```

The manifest records schema and parser versions. It records provider, session, and loop IDs; source identities and fingerprints; scan cursors; creation time; and any errors or gaps. `events.jsonl` stores event metadata, correlation IDs, provenance, and source references. It does not copy prompts, tool arguments, command output, or transcript content. Provider adapters resolve paths, parse records, lock files, and replace or rebuild the index. Rebuild the index when a source changes or is truncated. The index is disposable. It never authorizes a graph transition. Native artifacts can regenerate it.

Keep source paths, record IDs, and line or item references. A reader must be able to check each event against its source. Load large tool input or output only when the detail view requests it. Preserve source content and mark missing or truncated content. Do not add a time-based expiry until cache size and retrieval behavior are measured. The user can clear derived indexes. If a source is deleted, its trace becomes unavailable because the index holds no copy of its content.

The first surface is a session detail/timeline view in the existing local dashboard, linked from a native session row. A dashboard button `runId` can link to a native session only when the run output or explicit metadata establishes that relation; otherwise show it as a separate run.

### 3. Event shape and provenance

Every event records its schema version, deterministic ID, provider, native session or thread ID, event kind, and source reference. It records the actor or worker when known. Time is nullable because some graph snapshots and artifacts have no time. Each event keeps its source-local order. Optional links identify the loop, graph revision, wave, node, attempt, native call, child thread or agent, and parent event. Event fields can record duration, status or error, command or tool name, file changes, usage, and evidence references.

Proposed JSONL event record:

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

`timestamp.value` and `duration_ms` can be null. `basis` is `source`, `derived`, or `unavailable`. Keep source order when known. For an untimed snapshot or artifact, show time as unknown. Merge sources by time only when their times are valid. Mark ties and untimed cross-source order as ambiguous. Use a stable source and order tie-break only for display. Never present a file modification time as event time.

Mark each fact `observed`, `derived`, or `unavailable`. Derived values include durations between timestamps and joins across sources. Record the calculation and source IDs. Do not record missing model, usage, cost, or time as zero. Keep observed token usage separate from estimated USD cost. Label frozen retro cost as an estimate. The viewer must not reprice it.

### 4. Trace sections

- Orchestrator and worker lifecycle, including dispatch, start, completion, abort, stale recovery, retry, and hard-stop events.
- Tool requests and available results, ordered by source timestamps and linked by provider-native IDs.
- Timings and gaps, clearly distinguishing emitted durations from inferred elapsed gaps with unknown cause.
- Reported file changes and Git boundary snapshots when available; tool requests alone are not proof that files changed.
- External command/service effects only to the extent recorded by the native result or independent artifact. Never promote an attempted command to a verified external effect.
- Graph state, evaluations, proofs, retro, and completion gate evidence by source link, without replacing provider validation.
- Usage and cost only where observed or explicitly estimated, with coverage and exclusions shown.

### 5. Baseline measurement and counting rules

Count sessions in a declared date window and provider set. List exclusions. Each metric records its name and version, numerator, denominator, and nullable rate. It also records the cohort and window, source references, method, exclusions, and `observed`, `derived`, or `manual` basis. Publish counts with rates. Do not claim a stable rate from a small cohort.

Counting rules:

- **State divergence:** Count mismatches only for declared relationships between work units and nodes. Divide by the number of those relationships independently inspected. Current `eval_refs` do not define that relationship. Until a mapping exists, report divergence as `not measurable`. Report structure counts separately; a count difference is not a defect by itself.
- **Duplicate mutation:** Count retries that repeat an accepted change to the same target and operation, when an independent audit confirms them. Divide by all audited mutation sequences. Exclude rejected calls and retries needed to finish a transition. Use a manual incident record until the source can prove repetition mechanically.
- **Repair incidents:** Count independently grouped repair episodes. Divide by sessions inspected. Record the session, affected state, trigger, repair action, and evidence. Count multiple commands in one episode once.
- **False completion block:** Count blocks independently shown to violate their documented gate condition. Divide by completion blocks independently replayed from exact source artifacts.
- **False completion pass:** Count completed runs independently shown to violate a required condition. Divide by successful completions independently audited. A provider's success claim is not an independent check.
- **Adapter/test duplication:** For each shared semantic change, record provider-specific implementation and test files or lines changed. Record duplicated semantic cases. Report counts per change and in total. Do not count required provider-native behavior as duplication.
- **Repeated updates across state views:** Count audited work items that needed manual status updates in both `work_units` and graph nodes. Divide by items for which an owner intended both views to show the same decision. Do not assume a one-to-one relation.
- **Maintenance cost:** Record active engineering minutes for graph changes in a small manual task log. Separate shared-kernel, Claude-adapter, Codex-adapter, test, and repair work. Report per change and sum by category. Do not infer minutes from token usage.

Acceptance requires a resolvable source reference for every event, or an explicit unavailable marker. Every correlation field has a source or a derived label. Every published metric has a denominator, source, and method. Missing values must never appear as zero. Adversarial fixtures must produce no false claim of an external effect or completion. The real-run baseline counts the declared cohort and reports its size and exclusions. Set no numeric operational target until that baseline exists.

The baseline report compares the current separated state model and adapters as operated. It does not decide whether state unification is desirable. A separate RFC is considered only if the measured evidence supports one.

## Safety and retention

- Keep reads local to the existing dashboard and provider artifact roots; do not upload telemetry or publish it.
- Do not duplicate full transcripts into a new durable store. Source files remain authoritative; expose source references and load details when requested.
- Treat tool inputs and results as potentially sensitive. Keep details out of cache, session lists, and trace summaries. Reveal one record only after the user expands it and the dashboard checks local origin and token. Render it as escaped plain text. Do not render it as HTML or log it. This boundary controls access and display. It does not promise secret redaction. Do not call a trace complete if content was omitted without notice.
- Respect each provider's transcript permissions and uniqueness checks. Ambiguous session or worker linkage is shown as unresolved, not guessed.
- Bound scans by measured source behavior and paginate large traces; report scanned/emitted counts and truncation explicitly instead of assuming a fixed safe excerpt size.

## Acceptance criteria

1. A real Claude session fixture and a real Codex session fixture each render the orchestrator plus parallel workers as one trace with correct native correlation IDs.
2. Tests cover retry/stale recovery, hard stop, failure/abort, incomplete or ambiguous joins, missing usage, inferred timing, and completion/eval/proof/retro links.
3. A trace never upgrades an attempted tool call into a verified external effect, a provider status into independent success, or a missing value into zero.
4. Dashboard `runId` remains distinct from native session ID unless a tested explicit link exists.
5. The view is read-only; corrupt, partial, or unreadable source data is surfaced with provenance and does not mutate graph or evidence files.
6. Large source records are retrieved on demand; measured retrieval/truncation behavior is visible, and the source remains recoverable.
7. Baseline metrics state cohort, denominator, observation method, exclusions, and whether each value is observed, derived, or manually recorded.
8. Provider adapters remain independent, installed independently, and keep transcript parsing/evidence policy out of the shared semantic kernel.

## Resolved implementation decisions

- The selected trace model is OpenTelemetry-aligned local JSONL, with no OTel SDK/collector or remote exporter in this phase.
- Trace assembly and cache logic live in provider-local dashboard modules, not provider CLIs; each install remains independent.
- Support native transcript and event shapes backed by sanitized real fixtures and current evidence readers. Show unknown or malformed shapes as incomplete or unresolved. Do not infer version or launch-mode behavior from undocumented fields.
- Session summaries and trace pages contain metadata only. Reveal one detail on request, behind the dashboard origin and token checks. Escape it as plain text. Do not cache or log it. This is not secret redaction.
- The baseline cohort begins at the Python cutover merge (`e1090098`, 2026-09-28 11:32:24 UTC). It ends at the UTC census time in the report. The report contains metric, incident, and task records. Mark unavailable historical maintenance minutes as unavailable; do not estimate them.

These decisions add no daemon, remote backend, new graph authority, or speculative state-unification work.
