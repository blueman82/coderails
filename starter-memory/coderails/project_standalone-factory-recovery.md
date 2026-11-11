---
name: standalone-factory-recovery
description: Standalone Factory app recovery after dashboard implementation was rejected
type: project
---

# Standalone Factory recovery

## Goal

Build a local Factory web app in `factory/`. It starts one selected provider headlessly, streams redacted records, and follows the accepted Factory mockup. Keep the existing dashboards unchanged.

## Decisions

- Factory and dashboard operate independently. Do not change, import, or launch `skills/dashboard/**` or `packages/codex/skills/dashboard/**`. Do not share runtime data with them.
- The earlier dashboard implementation was rejected and reverted. The file `progress.dashboard-rejected.json` holds a copy of that graph in the active graph's directory.
- Use a dependency-free local Node app in `factory/`: Node built-ins plus
  browser HTML/CSS/ES modules. No remote service, telemetry, or dependency.
  No free-form shell API, second store for run records, or provider-child tracking.
- The visual contract is `/private/tmp/factory-mockup.html`: header, launch
  bar, queue, workflow map, scrollable run history, and a permanent inspector.
- Factory launches only configured project IDs and runs one provider at a time. Codex argv is `codex exec --json --skip-git-repo-check`. Claude argv is `claude -p --output-format stream-json`. Use no shell.
- Provider payload leaves are redacted by default. Keep the verbatim user prompt on its own and let the user examine it.

## Key files

- `docs/superpowers/specs/2026-08-27-standalone-factory-design.md`
- `docs/superpowers/plans/2026-08-27-standalone-factory.md`
- `factory/server.mjs`: localhost static server, snapshot, SSE, Factory API.
- `factory/lib/{runs,graph,evidence,config,launch}.mjs`: Factory-owned model,
  safe handling for graph data and run records, allowlist, and launch.
- `factory/public/{index.html,app.js,ui.js,styles.css}`: standalone page.
- `factory/test/*.test.mjs`: Node tests.
- Active graph record: `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a03d46-3a67-7b82-98d2-6e25e9ed3a77/progress.json`.
- Frozen evals: sibling `evals.json`.

## Done so far

- Dashboard Factory changes were reverted and their untracked files removed.
- The worktree uses the two previous dashboard lockfiles from `origin/main`. Commit these reversions to remove dashboard paths from the branch diff.
- `factory/` is untracked and currently has a local server, mockup-shaped
  layout, allowlisted launch, safe run records, SSE, and 21 Node tests that passed.
- The evaluator worked independently. E1/E2/E3 succeeded. E4/E5/E6 did not succeed.

## Required repair

1. In Factory only, add a safe server-owned demo graph fixture or input. Do not accept a browser path or command. The app must be able to make graph nodes from this input.
2. Show named dependencies, joins, readiness, outcomes, retries, and the verbatim prompt in the inspector. Show the run log in sequence, checks, outputs, and each try. Mark malformed or unavailable records explicitly. Do not dump raw graph JSON.
3. Test keyboard node selection and focus restoration when the inspector closes. Test that the log scrolls on its own at 390px. Use that non-empty fixture.
4. Add tracked Factory documentation. Give its own local entry point, one-provider boundary, and limits on redaction and run records. Factory does not own dashboards, host remotely, run free shell commands, or track provider children.
5. Rerun `node --test factory/test/*.test.mjs` and direct browser checks for desktop and 390px. Have a new evaluator check E1-E6 independently.
6. Wait for an evaluator to report GO independently. Commit the dashboard lockfile reversions and Factory sources and docs. Also commit the graph dispatch-gate repair, which is its own change.

## Constraints and graph state

- This session reached the native agent-thread limit. Start a new Codex session before dispatching the repair worker.
- The active graph hard-stopped at node B because of that limit. E4-E6 did not succeed. Do not claim the graph is complete. Clear or rebuild its records deliberately in the new session before dispatching work.
- After the architecture correction, the graph started again with manual intervention. The records include administrative retries. Check the current graph data before relying on earlier node labels.

## Open questions

- None. The user approved the standalone Factory design and asked to continue.
