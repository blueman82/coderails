# Standalone Factory Design

## Boundary

`factory/` is a local Factory application. It is separate from both existing
dashboard trees. It must not import, modify, launch, or share runtime state
with `skills/dashboard/app` or its Codex package mirror.

## Shape

The supplied Factory mockup is the visual contract:

- a Factory header with project, provider, connection, and Light/Dark/System;
- a launch bar for one selected local project, one provider, and one prompt;
- a left run queue;
- a central, readable workflow map with live activity below it; and
- a persistent right inspector with the exact prompt, activity, evidence,
  graph state, checks, outputs, and attempt history.

On a narrow screen, the queue stacks above the workflow map and the inspector
opens as a full-height sheet. Activity and inspector content scroll separately.

## Local runtime

Use a small Node local server and browser assets in `factory/`; add no runtime
dependency. The server owns an allowlisted project registry, run records, a
single provider per run, process spawning, durable event files, and SSE.
Codex runs through `codex exec --json --skip-git-repo-check`; Claude runs
through `claude -p --output-format stream-json`. A Factory run records only the
provider process it starts. Provider-internal children are not separate runs.

Provider records are normalised before persistence or SSE. Event type, source,
order, timestamp, run, node, provider, and redaction marker remain visible;
provider payload values are redacted by default. The exact user prompt is a
separate retained run field and is visible in the inspector.

## Evidence

The Factory reads its own run files and, when configured for a Coderails
project, parses the selected project's `progress.json` into named nodes,
dependencies, joins, readiness, outcomes, retries, and evidence references.
Malformed or unavailable state is a visible record, never a raw JSON dump or
silent omission. Duplicate `(runId, order)` events are rejected and an event
gap is displayed.

## Acceptance

1. Existing dashboard files are unchanged by Factory work.
2. A browser opening Factory sees the mockup's header, launch bar, queue,
   workflow map, live stream, and inspector layout.
3. A selected node exposes the exact retained prompt and all available,
   labelled evidence; unknown, malformed, and unavailable records stay visible.
4. Factory-owned Codex and Claude processes stream safe, ordered evidence over
   SSE, with one provider per run and no browser-supplied command or path.
5. Light, Dark, and System modes work; keyboard controls and phone layout work.
