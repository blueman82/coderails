# Coderails Run Observability Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for the tasks in this plan. The first skill is preferred. The steps use checkbox syntax (`- [ ]`).

**Goal:** Add a local, read-only session diagnostic log and a measured post-cutover baseline for native Claude and Codex runs.

**Architecture:** Each provider dashboard has its own installation. It finds and parses its own native session, worker, graph, hook, and loop-end records.
It builds an OpenTelemetry-aligned record in a local JSONL cache that it can build again. It gives a paginated session timeline without changes to authoritative files.
The baseline reports the cohort, denominators, exclusions, and verification records.

**Tech Stack:** Use the TypeScript and Next.js dashboards, Node filesystem APIs, and Vitest.
Do not add a runtime dependency, OTel SDK or collector, LangSmith integration, or remote exporter.

**Spec:** `docs/superpowers/specs/2026-09-28-coderails-run-observability-design.md`

## Global Constraints

- Keep the provider adapters, transcript parsing, record validation, and caches in each provider's installation.
- The graph-semantics kernel and graph runtime do not import dashboard or telemetry code.
- Native records are authoritative. The dashboard can discard and regenerate the cache. It does not write to source files.
- The cache, session-list API, and summary API use normalized metadata and source refs only.
  They do not copy prompts, tool arguments, command output, or transcript text.
  Read full records only if the user explicitly asks through the local-origin and dashboard-token checks.
- Keep missing time, token use, cost, elapsed time, identity, or status unavailable. Do not use zero or file mtime for the occurrence time.
- A dashboard `runId` identifies a native session only if a tested mapping links them.
- Use OTel identifiers `traceId` and `spanId`. Use its hierarchy, log entries, status, and applicable GenAI and tool attributes. The local JSONL does not use OTLP.
- Do not add a daemon, network transmission, remote backend, or bulk raw transcript access. Do not edit the wiki or combine the graph and data models.
- Keep the graph fixes and tests in the active worktree. Do not change those files for observability work.

## Review Focus

- Show missing, incorrect, or truncated records as unfinished with source refs. Test malformed records and truncated JSONL.
- Do not merge workers if child IDs recur or are ambiguous. Test duplicate IDs and parent-child identities from a different session.
- A rewrite of the same length or a truncation must invalidate stale cache entries. Test fingerprints and cursors.
- Keep source ordinals for missing or tied timestamps. Show ambiguity between sources. Test Claude and Codex.
- Keep large or sensitive content out of the cache, summaries, and list and summary APIs.
  Test metadata-only payloads, pagination, and authorization and local source checks for full record reads.

---

### Task 1: Freeze the provider-neutral trace contract

**Files:**

- Make `skills/dashboard/app/src/lib/collect/sessionTrace.ts`.
- Make `packages/codex/skills/dashboard/app/src/lib/collect/sessionTrace.ts`.
- Test `skills/dashboard/app/test/sessionTrace.schema.test.ts`.
- Test `packages/codex/skills/dashboard/app/test/sessionTrace.schema.test.ts`.

**Interfaces:**

- Each module exports `TraceEvent`, `TraceManifest`, `TracePage`, `NativeSessionSummary`, `TraceCollectionDeps`, `SourceRef`, and `TraceDetail`.
  Each defines `TRACE_SCHEMA_VERSION = 1`.

- `TraceEvent` has `traceId`, `spanId`, nullable `parentSpanId`, `name`, and `kind`.
  The `kind` values are `internal`, `client`, `server`, `producer`, and `consumer`.
  The `status` values are `unset`, `ok`, `error`, and `unavailable`, with a basis.
  Time fields `startTimeUnixNano` and `endTimeUnixNano` are nullable.
  The record keeps `events` in sequence and primitive-valued attributes.
  Provenance includes provider, native session or thread ID, source identity and ordinal, basis, and source ref.

- `TraceManifest` has schema and parser versions, provider and session IDs, and source fingerprints and cursors. It also has generation time, completeness, errors, and entry count.
  `TracePage` has entries, input and next cursors, and completeness.

- `NativeSessionSummary` gives the native ID, provider, safe project or display label, and last-activity value and basis.
  `TraceCollectionDeps` supplies source and cache roots, clock, and filesystem operations.
  `SourceRef` uses the provider's source type and a checked record ID or ordinal.
  `TraceDetail` has content and provenance for one record that the user asks for. Do not cache it.

- Use `null` or explicit `unavailable` for unknown time, status, or token use.
  Derived fields have method and source IDs.

- [ ] **Step 1:** Write contract tests in the two test files. Check version, all fields above, and nullable timing.
  Check that serialized entries have no prompt, raw arguments, or result body.

- [ ] **Step 2:** Run `npm test -- test/sessionTrace.schema.test.ts` in each package. Result: FAIL because there is no module.

- [ ] **Step 3:** Use the same local types and a small runtime validator in each `sessionTrace.ts`.
  Use OTel concepts and `gen_ai.*` and tool attributes where the source facts allow them.

- [ ] **Step 4:** Run the two tests again. Result: PASS with the same contract structure and no shared import.

### Task 2: Build the Claude native trace adapter and cache

**Files:**

- Change `skills/dashboard/app/src/lib/collect/sessionTrace.ts`.
- Make `skills/dashboard/app/test/sessionTrace.claude.test.ts`.
- Make a sanitized fixture in `skills/dashboard/app/test/fixtures/session-trace/claude/`.
- Read `hooks/scripts/lib/graph_evidence.py`, `graph_evidence_bind.py`, `graph_evidence_revalidate.py`, and `loop_cost.py` without changes.

**Interfaces:**

- Export `listClaudeSessions(deps: TraceCollectionDeps): Promise<NativeSessionSummary[]>`.
  Export `collectClaudeSessionTrace(sessionId: string, deps: TraceCollectionDeps): Promise<TraceManifest>`.
  Export `readClaudeTracePage(sessionId: string, cursor: string | null, limit: number, deps: TraceCollectionDeps): Promise<TracePage>`.
  Export `readClaudeTraceDetail(sessionId: string, sourceRef: SourceRef, deps: TraceCollectionDeps): Promise<TraceDetail>`.

- Find parent JSONL in `~/.claude/projects`.
  Connect child `subagents/agent-<agentId>.jsonl` to the parent only through native Agent tool-use and result IDs and checked graph dispatch envelopes.

- Use `~/.coderails/telemetry/claude/<safe-session-id>/manifest.json` and `events.jsonl`.
  Read full records from native sources only on demand. Do not cache them.

- [ ] **Step 1:** Add tests for parent and child joins, ordinals, and timestamps with and without values.
  Test retry, hard stop, record refs, ambiguous child links, malformed or truncated JSONL, and metadata-only serialization.

- [ ] **Step 2:** Run `npm test -- test/sessionTrace.claude.test.ts`. Result: FAIL because there is no collector or page reader.

- [ ] **Step 3:** Implement Claude parsing and joins with the native transcript and verification contracts.
  Use no terminal-looking text as proof of loop end. Check a child's parent before accepting it.

- [ ] **Step 4:** Invalidate the cache with schema and parser versions and file identity. Also use length, mtime, full content fingerprint, and record cursor.
  Calculate fingerprints while you read source bytes. This detects a rewrite with the same length and mtime.
  Replace manifest and entries atomically when a source changes or truncates.

- [ ] **Step 5:** Run the tests again. Result: PASS. Mark malformed or ambiguous records unfinished and do not write to sources.

### Task 3: Build the Codex native trace adapter and cache

**Files:**

- Change `packages/codex/skills/dashboard/app/src/lib/collect/sessionTrace.ts`.
- Make `packages/codex/skills/dashboard/app/test/sessionTrace.codex.test.ts`.
- Make a sanitized fixture in `packages/codex/skills/dashboard/app/test/fixtures/session-trace/codex/`.
- Read `packages/codex/skills/agentic-loop/scripts/graph_transcript.py`, `graph_evidence.py`, `graph_artifacts.py`, and `packages/tests/codex_fixture.py` without changes.

**Interfaces:**

- Export `listCodexSessions(deps: TraceCollectionDeps): Promise<NativeSessionSummary[]>`.
  Export `collectCodexSessionTrace(sessionId: string, deps: TraceCollectionDeps): Promise<TraceManifest>`.
  Export `readCodexTracePage(sessionId: string, cursor: string | null, limit: number, deps: TraceCollectionDeps): Promise<TracePage>`.
  Export `readCodexTraceDetail(sessionId: string, sourceRef: SourceRef, deps: TraceCollectionDeps): Promise<TraceDetail>`.

- Find native transcripts in `~/.codex/sessions` and check `session_meta.payload.id`.
  Connect `spawn_agent` call IDs with `SubAgentActivity` and child thread metadata.
  Keep legacy `CollabAgentToolCall` only if the current graph verification contract accepts it.

- Use cache files `~/.coderails/telemetry/codex/<safe-session-id>/manifest.json` and `events.jsonl`.

- [ ] **Step 1:** Add tests for current and legacy dispatch structure, native parent and child joins, and task lifecycle.
  Test tool, command, MCP, and file changes. Test source sequence without timestamps, missing token use, duplicate calls, and child metadata from a different session.
  Check metadata-only serialization.

- [ ] **Step 2:** Run `npm test -- test/sessionTrace.codex.test.ts`. Result: FAIL because there is no collector or page reader.

- [ ] **Step 3:** Implement native Codex parsing and checked joins. Use the graph verification contracts.
  Do not import graph write code or change verification rules.

- [ ] **Step 4:** Use the cache invalidation and atomic replacement rules from Task 2 in the Codex namespace.

- [ ] **Step 5:** Run the tests again. Result: PASS. Keep parent ordinals without timestamps. Keep ambiguous joins unresolved.

### Task 4: Add authenticated, paginated session and trace routes

**Files:**

- Change `skills/dashboard/app/src/lib/collect/index.ts`.
- Change `packages/codex/skills/dashboard/app/src/lib/collect/index.ts`.
- Make `skills/dashboard/app/src/app/api/sessions/route.ts`.
- Make `packages/codex/skills/dashboard/app/src/app/api/sessions/route.ts`.
- Make `skills/dashboard/app/src/app/api/sessions/[sessionId]/trace/route.ts`.
- Make `packages/codex/skills/dashboard/app/src/app/api/sessions/[sessionId]/trace/route.ts`.
- Add each provider's endpoint to read a full source record on demand.
- Test `skills/dashboard/app/test/sessionTrace.route.test.ts`.
- Test `packages/codex/skills/dashboard/app/test/sessionTrace.route.test.ts`.

**Interfaces:**

- `GET /api/sessions` gives small native session summaries. It does not use project directory mtime for a native timestamp.

- `GET /api/sessions/<id>/trace` accepts a cursor that clients do not interpret and a bounded limit.
  It gives only page metadata and provenance.
  `GET /api/sessions/<id>/trace/detail` finds one checked source ref and gives the record only on explicit user input.

- Each endpoint checks `isLocalOrigin`, the dashboard token through `tokensEqual`, and a UUID-shaped native ID.
  An endpoint for a full record checks the source ref structure, session ownership, indexed ref, and source fingerprint before it reads one record.

- Full transcript records come only from the provider transcript root. Full hook records come only from the configured audit path.
  Full records for a graph come only from allowlisted artifacts in the one session-owned graph root that discovery finds in the configured loops root.
  The dashboard assembles the log on demand apart from the fast frame for project work and KPIs.

- [ ] **Step 1:** Add endpoint tests for refused `Origin` values, tokens, session IDs, and source refs. Test stable pagination.
  Check that list and summary endpoints have no full records. A call for a full record gives only the selected record.

- [ ] **Step 2:** Run `npm test -- test/sessionTrace.route.test.ts` in the two packages. Result: FAIL before you add the endpoints.

- [ ] **Step 3:** Implement the three endpoints in each provider. Limit pagination and use the dashboard local-origin and token checks.
  Keep transcript reads out of the SSE collector for project work.

- [ ] **Step 4:** Run the tests again. Result: PASS. Dashboard `runId` has no automatic link to native session IDs.

### Task 5: Render a session timeline and source-backed detail view

**Files:**

- Change `skills/dashboard/app/src/components/DashboardApp.tsx`.
- Change `packages/codex/skills/dashboard/app/src/components/DashboardApp.tsx`.
- Make `skills/dashboard/app/src/components/SessionTracePanel.tsx` and `SessionTracePanel.test.tsx`.
- Make `packages/codex/skills/dashboard/app/src/components/SessionTracePanel.tsx` and `SessionTracePanel.test.tsx`.

**Interfaces:**

- Add a native session picker. Current dashboards show project work and loop entries without native session-ID entries.
  The picker uses only checked native IDs.
  The view shows orchestrator and worker spans, source entries, links to the graph, eval, proof, and retro, token use and cost, status, and provenance.

- Read a source record only after the user expands an entry and supplies the dashboard token.
  Summaries and pages do not have transcript content. Give the selected record as escaped plain text without HTML. Do not cache or log it.
  Show the basis for each derived or unavailable value.

- [ ] **Step 1:** Add component tests for native session selection, parallel workers, dispatch, retry, and hard stop.
  Test errors, abort, unresolved joins, null time, tied source sequence, and unavailable token use and cost.
  Test explicit full record reads, plain-text escaping, and the difference between dashboard run ID and native session ID.

- [ ] **Step 2:** Run the component tests in each package. Result: FAIL before the full record view and data hook are available.

- [ ] **Step 3:** Implement a timeline for each provider. Use OTel parent and child grouping and labels for observed, derived, and unavailable values.
  Read large source records only on explicit user input.

- [ ] **Step 4:** Run the component tests again. Result: PASS. Use no unverified wording about external effects or loop end.

### Task 6: Produce the measured post-cutover baseline report

**Files:**

- Make `docs/superpowers/reports/2026-09-28-coderails-run-observability-baseline.md`.
- Read native session artifacts and documented cutover and repair records. Do not edit the wiki.

**Interfaces:**

- Set the closed UTC cohort window and providers before the count.
  Report the cohort count, exclusions, numerator, denominator, rate, source refs, method, and observed, derived, or manual basis for each metric.

- Mark divergence between loop records unavailable until there is an explicit work-unit and node mapping.
  Keep frozen loop cost and transcript token use as different measurements.

- [ ] **Step 1:** Add a checklist for each spec metric and counting rule.
  Check that each metric gives denominator, method, cohort, and exclusions.

- [ ] **Step 2:** List available artifacts and freeze the cohort window.
  Record missing, deleted, and unreadable sessions as exclusions. Do not count them as zero.

- [ ] **Step 3:** Calculate divergence, duplicate mutations, repair incidents, and incorrect loop-end blocks and passes. Count adapter and test duplication, repeat updates to views, and maintenance time.
  Mark the measurements that are unavailable.

- [ ] **Step 4:** Check each claim against the named records. Each rate must have an auditable numerator and denominator.
  Set no target for operation before the first baseline.

### Task 7: End-to-end safety and parity verification

**Files:**

- Change or add focused fixtures and tests in the two dashboards.
- Keep graph semantics, provider verification policy, and wiki unchanged.

- [ ] **Step 1:** Add integration fixtures for stale cache and changed, truncated, or unreadable source. Test a duplicate child identity or an identity from a different session.
  Test large source records, ambiguous sequence, and the difference between a call and its observed external effect.

- [ ] **Step 2:** In `skills/dashboard/app`, run `npm test -- test/sessionTrace.schema.test.ts test/sessionTrace.claude.test.ts`.
  In `packages/codex/skills/dashboard/app`, run `npm test -- test/sessionTrace.schema.test.ts test/sessionTrace.codex.test.ts`.

- [ ] **Step 3:** In each dashboard package, run `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build`.
  All checks must succeed. If dependencies are unavailable, report the limit without a success claim.

- [ ] **Step 4:** Examine cache and source diffs and API payload fixtures.
  Check for no native source edits and metadata and refs only in the cache. The contract results must agree across providers.
