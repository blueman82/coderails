# Coderails Run Observability Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Prefer the first skill. Implement one task at a time. Checkboxes (`- [ ]`) track the steps.

**Goal:** Add a local, read-only session trace and a measured post-cutover baseline for native Claude and Codex runs.

**Architecture:** Each provider dashboard finds and parses its own native
session, worker, graph, hook, and completion evidence. It builds an
OpenTelemetry-aligned trace in a rebuildable local JSONL cache. It then serves
a paginated session timeline without changing authoritative files. Baseline
metrics name the cohort, denominators, exclusions, and evidence.

**Tech Stack:** Existing TypeScript/Next.js dashboards, Node filesystem APIs, Vitest; no new runtime dependency, OTel SDK/collector, LangSmith integration, or remote exporter.

**Spec:** `docs/superpowers/specs/2026-09-28-coderails-run-observability-design.md`

## Global Constraints

- Provider adapters, transcript parsing, evidence validation, and caches remain independent in the Claude and Codex installs.
- The graph-semantics kernel and graph runtime do not import dashboard or telemetry code.
- Native evidence remains authoritative; the local cache is disposable, derived, and read-only with respect to sources.
- The cache, session-list API, and trace-summary API store only normalized metadata and source references. They do not copy prompts, tool arguments, command output, or transcripts. Read full details only after an explicit user request. Apply the existing local-origin and dashboard-token checks first.
- Missing timestamp, usage, cost, duration, identity, or status remains explicitly unavailable; never substitute zero or file mtime for event time.
- A dashboard `runId` is not a native session ID without an explicit tested link.
- OTel alignment means trace/span identity, hierarchy, events, status, and applicable GenAI/tool attributes; the local JSONL is not OTLP export.
- No daemon, network transmission, remote backend, bulk raw-transcript exposure, wiki edits, or graph/state-model unification.
- Preserve the current active worktree’s graph fixes and tests; do not modify those files as part of observability work.

## Review Focus

- Missing/invalid/partial source records must remain visible as incomplete with source references; test truncated JSONL and malformed records.
- Reused or ambiguous child IDs must not merge workers; test duplicate and foreign parent-child identities.
- Same-size rewrites and truncation must invalidate stale cache entries; test fingerprint and cursor invalidation.
- Missing timestamps and tied timestamps must preserve source ordinal and show ambiguous cross-source order; test both providers.
- Large or sensitive details must not leak from summary/cache/API; test metadata-only payloads, pagination, and detail authorization/origin checks.

---

### Task 1: Freeze the provider-neutral trace contract

**Files:**
- Create: `skills/dashboard/app/src/lib/collect/sessionTrace.ts`
- Create: `packages/codex/skills/dashboard/app/src/lib/collect/sessionTrace.ts`
- Test: `skills/dashboard/app/test/sessionTrace.schema.test.ts`
- Test: `packages/codex/skills/dashboard/app/test/sessionTrace.schema.test.ts`

**Interfaces:**
- Both modules independently export `TraceEvent`, `TraceManifest`, `TracePage`, `NativeSessionSummary`, `TraceCollectionDeps`, `SourceRef`, and `TraceDetail` plus `TRACE_SCHEMA_VERSION = 1`.
- `TraceEvent` records `traceId`, `spanId`, nullable `parentSpanId`, and `name`.
  Its `kind` is `internal`, `client`, `server`, `producer`, or `consumer`.
  Its `status` is `unset`, `ok`, `error`, or `unavailable`, with a basis.
  It also records nullable `startTimeUnixNano` and `endTimeUnixNano`, ordered events, and primitive-valued attributes.
  Provenance records provider, native session or thread ID, source identity and order, basis, and source reference.
- `TraceManifest` records schema and parser versions, provider and session IDs, source fingerprints and cursors, creation time, completeness, errors, and event count.
- `TracePage` records events, input and next cursors, and completeness.
- `NativeSessionSummary` records native ID, provider, safe project or display label, and last activity with its basis.
- `TraceCollectionDeps` supplies source and cache roots, clock, and filesystem operations.
- `SourceRef` combines a provider-defined source kind with a validated record ID and order.
- `TraceDetail` holds one requested record's content and provenance. Never cache it.
- Unknown time/status/usage is `null` or explicit `unavailable`; derived fields carry method and source IDs.

- [ ] **Step 1: Write failing contract tests** in both test files. Assert the schema version and all interface fields above, nullable timing, and that serialized events contain no prompt, raw arguments, or result body fields.
- [ ] **Step 2: Run each focused test** with `npm test -- test/sessionTrace.schema.test.ts` from each dashboard package. Expected: FAIL because the contract module does not exist.
- [ ] **Step 3: Define matching provider-local types and a minimal runtime validator** in each `sessionTrace.ts`; use OTel trace concepts and `gen_ai.*`/tool attributes only where source facts support them.
- [ ] **Step 4: Re-run both focused tests**; expected: PASS with structurally matching contracts and no shared import between providers.

### Task 2: Build the Claude native trace adapter and cache

**Files:**
- Modify: `skills/dashboard/app/src/lib/collect/sessionTrace.ts`
- Create: `skills/dashboard/app/test/sessionTrace.claude.test.ts`
- Create: sanitized shape fixture under `skills/dashboard/app/test/fixtures/session-trace/claude/`
- Read-only sources: `hooks/scripts/lib/graph_evidence.py`, `graph_evidence_bind.py`, `graph_evidence_revalidate.py`, `loop_cost.py`

**Interfaces:**
- Export `listClaudeSessions(deps: TraceCollectionDeps): Promise<NativeSessionSummary[]>`.
- Export `collectClaudeSessionTrace(sessionId: string, deps: TraceCollectionDeps): Promise<TraceManifest>`.
- Export `readClaudeTracePage(sessionId: string, cursor: string | null, limit: number, deps: TraceCollectionDeps): Promise<TracePage>`.
- Export `readClaudeTraceDetail(sessionId: string, sourceRef: SourceRef, deps: TraceCollectionDeps): Promise<TraceDetail>`.
- Resolve parent JSONL under `~/.claude/projects`; join child `subagents/agent-<agentId>.jsonl` only through native Agent tool-use/result IDs and validated graph dispatch envelopes.
- Cache root: `~/.coderails/telemetry/claude/<safe-session-id>/manifest.json` and `events.jsonl`; raw details are read from native sources only on demand and never cached.

- [ ] **Step 1: Add failing tests** for parent-child links and native source order. Cover known and missing timestamps. Cover retry, hard stop, evidence references, and ambiguous child links. Cover malformed or truncated JSONL and metadata-only output.
- [ ] **Step 2: Run the focused Claude tests** with `npm test -- test/sessionTrace.claude.test.ts`; expected: FAIL for missing collector and page reader.
- [ ] **Step 3: Implement provider-local parsing and correlation** using the native transcript/evidence contracts; never infer completion from a terminal-looking message or accept a child without validated parent linkage.
- [ ] **Step 4: Add cache rebuild and invalidation** using schema and parser version, file identity, size, mtime, content fingerprint, and record cursor. Compute fingerprints while reading source bytes. Detect rewrites even when size and mtime match. Replace the manifest and events atomically when a source changes or is truncated.
- [ ] **Step 5: Re-run focused tests**; expected: PASS, with malformed/ambiguous records surfaced as incomplete and no writes to source artifacts.

### Task 3: Build the Codex native trace adapter and cache

**Files:**
- Modify: `packages/codex/skills/dashboard/app/src/lib/collect/sessionTrace.ts`
- Create: `packages/codex/skills/dashboard/app/test/sessionTrace.codex.test.ts`
- Create: sanitized shape fixture under `packages/codex/skills/dashboard/app/test/fixtures/session-trace/codex/`
- Read-only sources: `packages/codex/skills/agentic-loop/scripts/graph_transcript.py`, `graph_evidence.py`, `graph_artifacts.py`; `packages/tests/codex_fixture.py`

**Interfaces:**
- Export `listCodexSessions(deps: TraceCollectionDeps): Promise<NativeSessionSummary[]>`.
- Export `collectCodexSessionTrace(sessionId: string, deps: TraceCollectionDeps): Promise<TraceManifest>`.
- Export `readCodexTracePage(sessionId: string, cursor: string | null, limit: number, deps: TraceCollectionDeps): Promise<TracePage>`.
- Export `readCodexTraceDetail(sessionId: string, sourceRef: SourceRef, deps: TraceCollectionDeps): Promise<TraceDetail>`.
- Resolve native transcripts under `~/.codex/sessions`; validate `session_meta.payload.id`, join `spawn_agent` call IDs to `SubAgentActivity` and child thread metadata, and preserve legacy `CollabAgentToolCall` only when the current graph evidence contract accepts it.
- Cache root: `~/.coderails/telemetry/codex/<safe-session-id>/manifest.json` and `events.jsonl`.

- [ ] **Step 1: Add failing tests** for current and legacy dispatch shapes, parent-child joins, and task life cycle. Cover tool, command, MCP, and file-change records. Cover missing time or usage, duplicate calls, foreign child data, and metadata-only output.
- [ ] **Step 2: Run the focused Codex tests** with `npm test -- test/sessionTrace.codex.test.ts`; expected: FAIL for missing collector and page reader.
- [ ] **Step 3: Implement Codex-native parsing and validated joins**; use the graph evidence helpers’ contracts without importing graph state mutation or changing evidence validation.
- [ ] **Step 4: Add the same cache invalidation and atomic rebuild rules** as Task 2, under the Codex provider namespace.
- [ ] **Step 5: Re-run focused tests**; expected: PASS, with untimed parent events retaining ordinals and ambiguous joins remaining unresolved.

### Task 4: Add authenticated, paginated session and trace routes

**Files:**
- Modify: `skills/dashboard/app/src/lib/collect/index.ts`
- Modify: `packages/codex/skills/dashboard/app/src/lib/collect/index.ts`
- Create: `skills/dashboard/app/src/app/api/sessions/route.ts`
- Create: `packages/codex/skills/dashboard/app/src/app/api/sessions/route.ts`
- Create: `skills/dashboard/app/src/app/api/sessions/[sessionId]/trace/route.ts`
- Create: `packages/codex/skills/dashboard/app/src/app/api/sessions/[sessionId]/trace/route.ts`
- Create: each provider’s on-demand source-detail route
- Test: `skills/dashboard/app/test/sessionTrace.route.test.ts`
- Test: `packages/codex/skills/dashboard/app/test/sessionTrace.route.test.ts`

**Interfaces:**
- `GET /api/sessions` returns lightweight native session summaries; it never uses project-directory mtime as native event time.
- `GET /api/sessions/<id>/trace` accepts an opaque cursor and bounded limit and returns page metadata/provenance only. `GET /api/sessions/<id>/trace/detail` resolves one validated source reference and returns that detail only after explicit request.
- Every route checks `isLocalOrigin`, the dashboard token with `tokensEqual`, and a UUID-shaped native ID. A detail route checks reference shape, session ownership, indexed reference, and source fingerprint before it reads one record. Native transcript details stay under the provider's transcript root. Hook details come from the configured audit path. Graph details come from allowed artifacts in the unique, session-owned graph root under the configured loops root. Build the trace on request, outside the fast activity and KPI frame.

- [ ] **Step 1: Add failing route tests** proving bad origin/token/session/source refs are rejected, pagination is stable, no detail is returned by list/trace routes, and explicit detail requests return only the referenced record.
- [ ] **Step 2: Run `npm test -- test/sessionTrace.route.test.ts`** in both packages; expected: FAIL until the routes exist.
- [ ] **Step 3: Implement the three provider-local routes** with bounded pagination and existing dashboard origin/token guards; keep transcript reads out of the SSE/activity collector.
- [ ] **Step 4: Re-run focused tests**; expected: PASS without coupling dashboard `runId` to native session IDs.

### Task 5: Render a session timeline and source-backed detail view

**Files:**
- Modify: `skills/dashboard/app/src/components/DashboardApp.tsx`
- Modify: `packages/codex/skills/dashboard/app/src/components/DashboardApp.tsx`
- Create: `skills/dashboard/app/src/components/SessionTracePanel.tsx` and `SessionTracePanel.test.tsx`
- Create: `packages/codex/skills/dashboard/app/src/components/SessionTracePanel.tsx` and `SessionTracePanel.test.tsx`

**Interfaces:**
- Add a native-session list/picker because current dashboards expose project activity and loop rows, not native session-ID rows. It links only validated native IDs and renders orchestrator/worker spans, source events, graph/eval/proof/retro links, usage/cost, status, and provenance.
- Load details only after the user expands a source event and passes the dashboard token check. Summaries and trace pages never embed transcript content. Escape requested detail as plain text, not HTML. Do not cache or log it. Show the basis of each derived or unavailable value.

- [ ] **Step 1: Add failing render tests** for native session selection and parallel workers. Cover dispatch, retry, hard stop, failure, abort, and unresolved joins. Cover null time, source-order ties, missing usage or cost, explicit detail loading, plain-text escaping, and the difference between dashboard run ID and native session ID.
- [ ] **Step 2: Run focused component tests** in each package; expected: FAIL until the detail view and data hook are wired.
- [ ] **Step 3: Implement provider-local timeline UI** with OTel parent/child grouping and clear observed/derived/unavailable labels; load large details only after an explicit detail request.
- [ ] **Step 4: Re-run focused component tests**; expected: PASS and no unverified external-effect/completion wording.

### Task 6: Produce the measured post-cutover baseline report

**Files:**
- Create: `docs/superpowers/reports/2026-09-28-coderails-run-observability-baseline.md`
- Source inventory: native session artifacts and already documented cutover/repair records; no wiki edits

**Interfaces:**
- The report declares a closed UTC cohort window and provider set before counting; reports cohort size, exclusions, each numerator/denominator/rate, evidence references, method, and observed/derived/manual basis.
- It reports state divergence as not measurable until explicit work-unit/node mapping exists and keeps frozen loop cost separate from transcript token usage.

- [ ] **Step 1: Add a report validation checklist** with every metric/counting rule from the spec and an explicit check that no metric omits a denominator, method, cohort, or exclusions.
- [ ] **Step 2: Inventory available artifacts and freeze the cohort window**; record missing/deleted/unreadable session sources as exclusions rather than treating them as zero.
- [ ] **Step 3: Calculate the baseline** for divergence, duplicate mutations, repair incidents, false completion blocks/passes, adapter/test duplication, repeated state-view updates, and maintenance time; mark unmeasurable categories explicitly.
- [ ] **Step 4: Review every claim against referenced evidence**; expected: all reported rates have auditable numerator/denominator and no operational target is invented before the first baseline.

### Task 7: End-to-end safety and parity verification

**Files:**
- Modify/add focused fixtures and tests in both provider dashboards
- No changes to graph semantics, provider evidence policy, or wiki

- [ ] **Step 1: Add adversarial integration fixtures** for stale cache, changed/truncated source, foreign/duplicate child identity, unreadable source, large details, ambiguous ordering, and attempted-vs-observed external effect.
- [ ] **Step 2: Run focused suites** from `skills/dashboard/app` and `packages/codex/skills/dashboard/app`: `npm test -- test/sessionTrace.schema.test.ts test/sessionTrace.claude.test.ts` and `npm test -- test/sessionTrace.schema.test.ts test/sessionTrace.codex.test.ts`, respectively.
- [ ] **Step 3: Run both dashboard package gates**: `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build`; expected: all pass. If a package lacks installed dependencies, report that limitation and do not claim it passed.
- [ ] **Step 4: Inspect cache/source diffs and API payload fixtures**; expected: native source files are unchanged, caches contain metadata/refs only, and both independent providers satisfy the same contract tests.
