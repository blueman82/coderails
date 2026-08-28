# Standalone Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Build a local standalone Factory app without altering either dashboard.

**Architecture:** `factory/server.mjs` is a dependency-free Node server that
serves `factory/public/`, owns allowlisted launch/run files, and streams safe
Factory events through one SSE endpoint. Browser code renders the approved
Factory layout and reads only Factory snapshot/event endpoints.

**Tech Stack:** Node built-ins, browser HTML/CSS/ES modules, `node --test`.

**Spec:** `docs/superpowers/specs/2026-08-27-standalone-factory-design.md`

## Global constraints

- Do not modify `skills/dashboard/**` or `packages/codex/skills/dashboard/**`.
- Add no runtime dependency, remote service, telemetry, free-form shell API,
  second event store, or provider-internal child registration.
- Keep one provider per run and accept only configured project identifiers.
- Make the supplied mockup's page structure the visual contract.

### Task 1: Factory server and static page shell

**Files:** Create `factory/server.mjs`, `factory/public/index.html`,
`factory/public/app.js`, `factory/public/styles.css`, `factory/test/server.test.mjs`.

- [ ] Write a failing `node:test` request test for `/`, `/api/snapshot`, and
  `/api/events`; prove no dashboard path is imported.
- [ ] Implement the smallest localhost-only Node server with static assets,
  JSON snapshot, and SSE keepalive.
- [ ] Render the mockup structure: header, launch bar, queue, workflow map,
  live activity, and persistent inspector.
- [ ] Run `node --test factory/test/server.test.mjs` and a browser smoke check.

### Task 2: Factory records, parsed graph, and evidence inspector

**Files:** Create `factory/lib/{runs,graph,evidence}.mjs`,
`factory/test/{runs,graph,evidence}.test.mjs`; modify `factory/server.mjs` and
`factory/public/app.js`.

- [ ] Write failing tests for a named parsed graph, malformed graph record,
  duplicate `(runId, order)` rejection, and redacted provider values.
- [ ] Implement Factory-owned JSON records and safe normalisation. Retain exact
  user prompt separately; provider payload leaves are redacted by default.
- [ ] Render named graph fields and all inspector sections; never raw-dump JSON.
- [ ] Run focused tests and an SSE/selection browser check.

### Task 3: Allowlisted headless provider launch

**Files:** Create `factory/lib/{config,launch}.mjs`,
`factory/test/launch.test.mjs`; modify `factory/server.mjs`.

- [ ] Write failing tests for unknown project/provider rejection, argv-safe
  provider commands, pre-spawn run binding, and safe streamed events.
- [ ] Implement configured local project IDs only; spawn one Codex or Claude
  process per run and persist only safe normalised records.
- [ ] Verify with a controlled child-process fixture, then safe empty-directory
  provider probes when authentication permits.

### Task 4: Responsive theme and release checks

**Files:** Modify `factory/public/{app.js,styles.css,index.html}`; create
`factory/test/ui-contract.test.mjs`; modify `README.md` only to document the
separate local Factory entry point.

- [ ] Write checks for Light/Dark/System persistence, keyboard node selection,
  390px sheet layout markers, and no dashboard-file changes.
- [ ] Implement semantic theme variables, reduced motion, independent scroll
  regions, and mobile inspector sheet.
- [ ] Run all Factory tests, `node --check`, `git diff --check`, and browser
  desktop/390px screenshots before review.
