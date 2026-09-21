---
name: standalone-factory-recovery
description: Standalone Factory app recovery after dashboard implementation was rejected
type: project
---

# Standalone Factory recovery

## Goal

Build a local Factory web app in `factory/` that launches one selected provider
headlessly, streams safe evidence, and follows the accepted Factory mockup.
The existing dashboards must remain untouched.

## Decisions

- Factory and dashboard are separate products. Never modify, import, launch,
  or share runtime state with `skills/dashboard/**` or
  `packages/codex/skills/dashboard/**`.
- The earlier dashboard implementation was rejected and reverted. A backup of
  that rejected graph state is beside the active state as
  `progress.dashboard-rejected.json`.
- Use a dependency-free local Node app in `factory/`: Node built-ins plus
  browser HTML/CSS/ES modules. No remote service, telemetry, dependency,
  free-form shell API, second event store, or provider-child tracking.
- The visual contract is `/private/tmp/factory-mockup.html`: header, launch
  bar, queue, workflow map, scrollable activity, and persistent inspector.
- Factory launches only configured project IDs; one provider per run. Codex
  argv is `codex exec --json --skip-git-repo-check`; Claude argv is
  `claude -p --output-format stream-json`; always shell-free.
- Provider payload leaves are redacted by default. Exact user prompt is stored
  separately and remains inspectable.

## Key files

- `docs/superpowers/specs/2026-08-27-standalone-factory-design.md`
- `docs/superpowers/plans/2026-08-27-standalone-factory.md`
- `factory/server.mjs`: localhost static server, snapshot, SSE, Factory API.
- `factory/lib/{runs,graph,evidence,config,launch}.mjs`: Factory-owned model,
  safe graph/evidence handling, allowlist, launch.
- `factory/public/{index.html,app.js,ui.js,styles.css}`: standalone page.
- `factory/test/*.test.mjs`: Node tests.
- Active state: `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a03d46-3a67-7b82-98d2-6e25e9ed3a77/progress.json`.
- Frozen evals: sibling `evals.json`.

## Done so far

- Dashboard Factory changes were reverted and their untracked files removed.
- Two old dashboard lockfiles were restored from `origin/main` in the working
  tree; commit these reversions so the branch diff has no dashboard paths.
- `factory/` is untracked and currently has a local server, mockup-shaped
  layout, allowlisted launch, safe evidence, SSE, and 21 passing Node tests.
- Independent evaluation: E1/E2/E3 pass. E4/E5/E6 fail.

## Required repair

1. In Factory only, add a safe server-owned demo graph fixture/input (never a
   browser path or command) so the served app can create graph nodes.
2. Expand the inspector to show named dependencies, joins, readiness, outcome,
   retries, exact prompt, ordered activity, checks, outputs, attempts, and
   explicit malformed/unavailable records. Never raw-dump graph JSON.
3. Directly test keyboard node selection, close/focus return, and independent
   activity scrolling at 390px against that non-empty fixture.
4. Add tracked Factory documentation: separate local entry point, one-provider
   boundary, redaction/evidence limits, no dashboard ownership, remote hosting,
   free shell dispatch, or provider-child tracking.
5. Rerun `node --test factory/test/*.test.mjs`, direct desktop/390px browser
   checks, then a fresh independent evaluator for E1-E6.
6. Commit dashboard lockfile reversions, Factory sources/docs, and the separate
   graph dispatch-gate repair only after independent eval is GO.

## Constraints and graph state

- This session exhausted the native agent-thread limit. Start a fresh Codex
  session before dispatching the repair worker.
- The active graph is hard-stopped at node B for that limit and failed E4-E6.
  Do not claim it complete; clear/rebuild its state deliberately in the new
  session before dispatching work.
- The graph was manually restarted after the architecture correction and has
  administrative retry history; verify state carefully rather than trusting
  old node labels.

## Open questions

- None. The user approved the standalone Factory design and asked to continue.
