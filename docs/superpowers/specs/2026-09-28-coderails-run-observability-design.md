# Coderails run observability design

## Status and intent

Design approved; implementation plan review pending. This covers the accepted post-cutover observability and measurement phase. The target is an inspectable trace of one native Coderails session, including parallel workers, alongside an evidence-based post-migration baseline.

The design preserves provider-local dispatch, transcript parsing, graph state, evidence validation, and completion authority. It does not update the LLM Wiki, unify `work_units` with graph nodes, or introduce a shared runtime in the graph-semantics package.

## User outcome

For a selected native session, the user can follow what the orchestrator and workers attempted, how work relates to graph nodes/waves/attempts, what returned or failed, what recovery occurred, what files or external actions were reported, what evidence supports completion, and which facts are unavailable or inferred. The trace is a diagnostic view, not a second source of truth.

The measurement output must support comparisons of state divergence, duplicate mutations, repair incidents, false completion blocks/passes, adapter/test duplication, and maintenance cost. Each measurement names its observation method and denominator. Separate `work_units` and `graph.nodes` remain separate; a difference between them is not itself a defect.

## Current source evidence

- Both providers have a native session identifier and session-scoped graph state. Graph state is a snapshot and does not by itself preserve every transition.
- Claude graph evidence binds worker attempts to the parent transcript's Agent tool call, parent record UUID, subagent type, child agent ID, wave, and attempt. Completion revalidates those links. Native transcript records include timestamps, tool requests/results, model, and usage. Usage from headless child sessions without parent linkage is excluded by the current cost miner.
- Codex native session transcripts contain timestamped turn/model metadata, token-usage records, tool calls/results, command durations/status, file-change records, MCP call status/duration, and subagent activity. Existing graph evidence joins the parent call, child thread, attempt, and wave. The dashboard currently reads the older `~/.codex/projects` tree for broad activity/usage, while native graph verification uses `~/.codex/sessions`.
- Codex hook audit defaults to `~/.coderails/codex/discipline.log`, while the dashboard health collector defaults to `~/.codex/discipline.log`; unless `CODERAILS_DISCIPLINE_LOG` aligns them, its hook-count tile may not observe the Codex plugin's hook log.
- Dashboard button runs have a separate random `runId`; no durable native session link is present. A `runId` must not be treated as a native session ID without explicit evidence.
- Dashboard views currently summarize project activity, run totals, and frozen loop cost separately. They do not assemble a session-level timeline.
- Tool invocation and recorded result do not prove every external side effect. Wait duration may be estimated from timestamps; the reason for a wait is not directly emitted.

Source anchors: `hooks/scripts/lib/graph_evidence.py`, `hooks/scripts/lib/graph_evidence_bind.py`, `hooks/scripts/lib/graph_evidence_revalidate.py`, `hooks/scripts/lib/loop_cost.py`; `packages/codex/skills/agentic-loop/scripts/graph_transcript.py`, `graph_evidence.py`, `graph_artifacts.py`; Codex `packages/codex/hooks/scripts/hook_common.py` and dashboard `app/src/lib/collect/{sessions,usage,cost,contextTrend,health}.ts`; dashboard `app/src/app/api/{events,run}/route.ts` in each provider bundle.

## Proposed architecture

### OpenTelemetry choice

Use the OpenTelemetry trace model for trace/span identity, parent-child work relationships, span events, status, and standard GenAI/tool attributes where they fit. Keep Coderails provenance, source ordering, nullable timestamps, and derived/unavailable markers as explicit Coderails attributes because historical provider records do not always satisfy live-span timing requirements. Serialize the rebuildable local index in the provider-owned JSONL format below; it is OTel-aligned, not an OTLP export. Do not add an OTel SDK, collector, LangSmith integration, remote exporter, or network transmission in this phase. This reconstructs traces from existing native evidence rather than instrumenting the model runtime.

### 1. Provider-owned read adapters

Each provider bundle owns its native session discovery, transcript parsing, worker correlation, graph/artifact loading, and provenance checks. Each adapter maps supported source records into a small versioned normalized trace-event shape. Provider-only source IDs and fields remain available as source references; normalization must not erase differences that affect meaning.

The dashboard may orchestrate these adapters and render the normalized events. The graph-semantic kernel and installed graph runtime do not import the dashboard or a telemetry service. Adapters are read-only and never repair graph state, synthesize completion, or rewrite source evidence.

### 2. On-demand trace assembly and local cache

Assemble a session trace on request from native transcripts, current graph state, linked worker transcripts, hook audit records, and eval/proof/retro artifacts. Use a rebuildable, provider-owned local index rather than a second raw-evidence store:

```text
~/.coderails/telemetry/<provider>/<safe-session-id>/manifest.json
~/.coderails/telemetry/<provider>/<safe-session-id>/events.jsonl
```

The manifest records schema/parser version, provider/session/loop IDs, source file identities and fingerprints, scan cursors, generated time, and completeness/errors. `events.jsonl` stores only normalized event metadata, correlation IDs, provenance, and source references; it does not copy prompts, tool arguments, command output, or transcript contents. Provider adapters own path resolution, parsing, locking, atomic replacement, and rebuild behavior. On changed or truncated sources, rebuild the derived index. The index is disposable and never authorizes a graph transition. It can be deleted and regenerated from native artifacts.

Keep source paths/record IDs/line or item references so each event can be checked against its origin. Load large tool inputs/results from the native source only when the detail view requests them; preserve source content and make any unavailable/truncated content explicit. Do not add an independent time-based expiry before real cache size and retrieval behavior are measured. The user can clear derived indexes; source deletion makes the corresponding trace unavailable rather than leaving copied content behind.

The first surface is a session detail/timeline view in the existing local dashboard, linked from a native session row. A dashboard button `runId` can link to a native session only when the run output or explicit metadata establishes that relation; otherwise show it as a separate run.

### 3. Event shape and provenance

Every normalized event carries: schema version, deterministic event ID, provider, native session/thread ID, event kind, actor/worker identity when available, and a source reference. A timestamp is nullable because graph snapshots and some artifacts are untimed. Each event also carries source-local sequence/ordinal data. Optional correlation fields include loop ID, graph revision, wave ID, node ID, attempt, native tool/call ID, child thread/agent ID, and parent-event ID. Event-specific fields include duration, status/error, command/tool name, file-change summary, usage, and evidence-artifact references.

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

`timestamp.value` and `duration_ms` are nullable. `basis` is `source`, `derived`, or `unavailable`; source sequence is retained when available. For untimed snapshots/artifacts, preserve their source order and show time as unknown. Merge sources by timestamp only where timestamps are valid; ties or untimed cross-source ordering are marked ambiguous and use a stable source/order tie-break solely for display. Never synthesize a timestamp from file mtime and present it as event time.

Facts are marked `observed`, `derived`, or `unavailable`. Derived values include timestamp-gap durations and cross-source joins; record the calculation/source IDs. Do not encode missing model/usage/cost/timing as numeric zero. Observed token usage remains separate from estimated USD cost. Existing frozen retro cost is labeled as an estimate and is not repriced by the viewer.

### 4. Trace sections

- Orchestrator and worker lifecycle, including dispatch, start, completion, abort, stale recovery, retry, and hard-stop events.
- Tool requests and available results, ordered by source timestamps and linked by provider-native IDs.
- Timings and gaps, clearly distinguishing emitted durations from inferred elapsed gaps with unknown cause.
- Reported file changes and Git boundary snapshots when available; tool requests alone are not proof that files changed.
- External command/service effects only to the extent recorded by the native result or independent artifact. Never promote an attempted command to a verified external effect.
- Graph state, evaluations, proofs, retro, and completion gate evidence by source link, without replacing provider validation.
- Usage and cost only where observed or explicitly estimated, with coverage and exclusions shown.

### 5. Baseline measurement and counting rules

Use a census of sessions in a declared date window and provider set, with exclusions listed. Every metric record contains metric name/version, numerator, denominator, rate (nullable), cohort/window, source references, observation method, exclusions, and `observed`/`derived`/`manual` basis. Publish counts alongside rates and do not claim a stable rate from a small cohort.

Counting rules:

- **State divergence:** count only mismatches for explicitly declared work-unit/node relationships, divided by the number of those relationships independently inspected. Current `eval_refs` are not such a mapping. Until a mapping exists, report divergence as `not measurable`; report the two structures' counts separately without calling count differences defects.
- **Duplicate mutation:** count same-target, same-operation retries that an independent audit confirms repeated an already accepted state change, divided by all independently audited mutation sequences. Exclude rejected calls and retries required to finish a transition. Use a manual incident record until a source can prove this mechanically.
- **Repair incidents:** count independently grouped repair episodes, divided by sessions inspected. Record session, affected state, trigger, repair action, and evidence. Multiple commands in one episode count once.
- **False completion block:** count blocks independently shown to violate their documented gate condition, divided by completion blocks independently replayed from their exact source artifacts.
- **False completion pass:** count successful completions independently shown to violate a required condition, divided by successful completions independently audited. A provider's own success claim is never the independent check.
- **Adapter/test duplication:** for each shared semantic change, record provider-specific implementation and test files/lines added or changed and the number of duplicated semantic cases. Report per change and in total; do not count required provider-native behavior as duplication.
- **Repeated updates across state views:** count audited work items that required manual repeated status updates in both `work_units` and graph nodes, divided by work items for which an owner explicitly intended both views to represent the same decision. Do not assume a one-to-one relation.
- **Maintenance cost:** use a small manual task record of active engineering minutes for graph changes, split into shared-kernel, Claude-adapter, Codex-adapter, test, and repair work. Report per change and summed by category; do not estimate minutes from token usage.

Acceptance thresholds for the observability release: every emitted event has a resolvable source reference or is explicitly marked unavailable; all correlation fields are source-backed or labeled derived; 100% of published metric values have a defined denominator and source/method; 0 missing values are silently represented as zero; adversarial fixtures produce zero false external-effect or completion claims. The real-run baseline is a census of the declared cohort, with the cohort size and all exclusions reported. No numeric operational target is set until that first baseline exists.

The baseline report compares the current separated state model and adapters as operated. It does not decide whether state unification is desirable. A separate RFC is considered only if the measured evidence supports one.

## Safety and retention

- Keep reads local to the existing dashboard and provider artifact roots; do not upload telemetry or publish it.
- Do not duplicate full transcripts into a new durable store. Source files remain authoritative; expose source references and load details when requested.
- Treat tool inputs/results as potentially sensitive. Keep details out of cache, session-list responses, and trace-summary pages. Reveal one requested record only after explicit expansion through the dashboard's local-origin and token checks; render it as escaped plain text, never HTML, and never log it. This boundary controls access and rendering; it does not promise secret redaction. Do not silently omit content while calling the trace complete.
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
- Support only native transcript/event shapes established by sanitized real fixtures and current evidence readers. Unknown or malformed shapes remain incomplete/unresolved; no version or launch-mode behavior is inferred from undocumented fields.
- Session summaries and trace pages contain metadata only. One detail is revealed on explicit request, behind the existing dashboard origin/token boundary, escaped as plain text, and never cached or logged; this is not secret redaction.
- Baseline cohort starts at the Python cutover merge (`e1090098`, 2026-09-28 11:32:24 UTC) and ends at the UTC census time recorded in the report. The report itself carries metric and incident/task records; unavailable historical maintenance minutes are reported unavailable, never estimated.

These decisions add no daemon, remote backend, new graph authority, or speculative state-unification work.
