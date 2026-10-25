---
name: standalone-factory-recovery
description: Historical recovery plan for the standalone Factory app after a dashboard implementation was rejected.
type: project
---

# Standalone Factory recovery

## Goal

Build a local Factory web app in `factory/`. It must launch one selected
provider without a UI. It must stream safe evidence and follow the accepted
Factory mockup.

The existing dashboards must remain untouched.

## Decisions

- Factory and dashboard are separate products. Do not modify, import,
  launch, or share runtime state with `skills/dashboard/**` or
  `packages/codex/skills/dashboard/**`.
- The earlier dashboard implementation was rejected and reverted. Its
  graph-state backup is `progress.dashboard-rejected.json` beside the
  active state.
- Use Node built-ins and browser HTML, CSS, and ES modules. Add no remote
  service, telemetry, dependency, free-form shell API, second event store,
  or provider-child tracking.
- The visual contract is `/private/tmp/factory-mockup.html`. It has a header,
  launch bar, queue, workflow map, scrollable activity, and persistent inspector.
- Factory launches only configured project IDs. It uses one provider per
  run. Codex argv is `codex exec --json --skip-git-repo-check`. Claude argv
  is `claude -p --output-format stream-json`. It does not use a shell.
- Provider payload leaves are redacted by default. The exact user prompt
  is stored separately and remains inspectable.

## Key files

- `docs/superpowers/specs/2026-08-27-standalone-factory-design.md`
- `docs/superpowers/plans/2026-08-27-standalone-factory.md`
- `factory/server.mjs`: Localhost static server, snapshot, SSE, and Factory API.
- `factory/lib/{runs,graph,evidence,config,launch}.mjs`: Factory model,
  graph and evidence handling, allowlist, and launch.
- `factory/public/{index.html,app.js,ui.js,styles.css}`: standalone page.
- `factory/test/*.test.mjs`: Node tests.
- Active state: `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a03d46-3a67-7b82-98d2-6e25e9ed3a77/progress.json`.
- Frozen evals: sibling `evals.json`.

## Done so far

- Dashboard Factory changes were reverted and their untracked files removed.
- Two old dashboard lockfiles were restored from `origin/main` in the
  working tree. The former next step was to commit these reversions so the
  branch diff had no dashboard paths.
- At this checkpoint, `factory/` was untracked. It had a local server,
  mockup-shaped layout, allowlisted launch, safe evidence, SSE, and 21
  passing Node tests.
- Independent evaluation: E1/E2/E3 pass. E4/E5/E6 fail.

## Required repair

1. In Factory only, add a server-owned demo graph fixture. Do not accept a
   browser path or command for it. The app must create graph nodes from it.
2. Show dependencies, joins, readiness, outcomes, retries, exact prompt,
   ordered activity, checks, outputs, and attempts in the inspector. Show
   malformed or unavailable records clearly. Do not dump raw graph JSON.
3. Test keyboard node selection at 390px with the non-empty fixture. Test
   close and focus return. Test activity scrolling independently.
4. Add tracked Factory docs. State the local entry point, one-provider
   boundary, and evidence limits. State that Factory has no dashboard
   ownership, remote hosting, free shell dispatch, or child tracking.
5. Rerun `node --test factory/test/*.test.mjs`. Check desktop and 390px
   browser views. Then run a fresh independent E1-E6 evaluation.
6. Commit the dashboard lockfile reversions, Factory source and docs, and
   the separate graph dispatch-gate repair only after independent eval is GO.

## Constraints and graph state

- This session exhausted the native agent-thread limit. The former next
  step was a fresh Codex session before the repair worker.
- The active graph was hard-stopped at node B for that limit and failed
  E4-E6. It was not complete. The planned new session needed to clear or
  rebuild its state before dispatch.
- The graph was restarted after the architecture correction. It has
  administrative retry history. The former next step was to verify state
  rather than trust old node labels.

## Open questions

- None. The user approved the standalone Factory design and asked to continue.
