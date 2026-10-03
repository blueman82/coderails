# Agentic-loop delivery failures observed in provenance-context

Date: 2026-09-24
Session: `01a0c9bf-23e6-73d3-9c92-717a51cac912`
Status: investigation handoff; no Coderails fix is implemented here.

## Outcome

Coderails improved decomposition, durable state, evidence binding, and resistance
to false completion. (verified) It did not keep this run moving without repeated
human intervention. (verified) Several framework or runtime failures caused the
graph to stop making progress until the user explicitly challenged the state,
approved a recovery, or told the agent to continue. (verified)

The desired improvement is self-recovery without weakening terminal evidence.
(inferred) Pending nodes should not need completion evidence; completed or
skipped nodes must remain transcript-verified. (verified) An incomplete graph
should emit one useful diagnosis and either resume a safe ready node or record a
real human dependency. (inferred)

## Problems observed

### 1. Stop-hook repetition did not recover the graph

The same incomplete-graph message was injected over many turns. (verified) It
reported `running`, `ready`, or `hard_stop` state but did not itself reconcile a
missing worker, restart a ready node, or produce one durable recovery action.
(verified) The repeated message displaced useful conversation and required the
user to say `fix the blockage now`, `what do you need?`, `you are approved,
crack on`, and `continue`. (verified)

Expected improvement:

- Deduplicate identical stop output by `(session_id, loop_id, revision,
  active_wave, hard_stop)`. (inferred)
- Emit the diagnosis once, then back off until state changes. (inferred)
- If a node is `ready` and prior authority still covers it, begin and dispatch
  it automatically. (inferred)
- If a node is `running` but no matching live task or terminal transcript exists,
  reconcile or retry it after a bounded lease. (inferred)
- Ask the human only for a material decision, new authority, or external state
  change. (inferred)

### 2. Graph validation blocked non-terminal state

The run reached a state where a cache validator applied a universal completion
check to a pending node. (verified) The user had to approve changing the rule so
pending nodes require no transcript completion evidence while done/skipped nodes
remain verified. (verified) The user then had to challenge whether this weakened
Coderails. (verified)

Expected improvement:

- Encode evidence requirements by node state and test every state transition.
  (inferred)
- Preserve fail-closed verification for terminal outcomes. (inferred)
- Add regression fixtures for `pending`, `ready`, `running`, `done`, `skipped`,
  retry exhaustion, and stale transcript references. (inferred)
- Refuse a validator change that broadens the terminal evidence boundary.
  (inferred)

### 3. Resource failures affected hooks and Python

Codex repeatedly reported `Too many open files (os error 24)` while hooks were
running. (verified) macOS also reported repeated Python process crashes.
(verified) The provenance-context stability artifact later identified nine
historical MLX/Metal SIGABRT crash reports and verified that no new crash was
created during its controlled run. (verified) These failures reduced trust in
the framework's ability to observe or resume itself. (inferred)

Expected improvement:

- Record hook process count, open descriptors, runtime, timeout, and exit cause
  per invocation without retaining prompt content. (inferred)
- Enforce bounded concurrency and close every pipe/file/process handle.
  (inferred)
- Add a stress test that repeatedly fires SessionStart, UserPromptSubmit,
  PreToolUse, and Stop without descriptor growth. (inferred)
- Detect native Python/MLX termination separately from ordinary Python
  exceptions and show the crash-report path. (inferred)

### 4. Progress existed, but the user had to pull it out

`progress.json` retained graph position across interruptions. (verified) The
agent still needed repeated user prompts asking what was done, what remained,
what was being tracked, and what input was required. (verified) A durable graph
without an automatically useful progress summary did not remove supervisory
load. (inferred)

Expected improvement:

- Generate one compact status from `progress.json`: completed outcomes, active
  work, next ready work, hard stop, and exact human dependency. (inferred)
- Never answer a status request with only node names or generic intentions.
  (inferred)
- Distinguish `waiting for worker`, `waiting for evidence`, `ready to dispatch`,
  and `waiting for human`. (inferred)

### 5. Agent capacity prevented a required design review

During BENCH, a required read-only `design-scout` could not be spawned because
the session thread limit was reached. (verified) Reusing inherited scout names
also failed with `not_found` or `agent thread limit reached`. (verified) Only one
implementation worker was active at the time. (verified) The fallback was a
worker-authored read-only preflight, explicitly recorded as non-independent.
(verified)

Expected improvement:

- Release completed agent capacity or make lifecycle state inspectable.
  (inferred)
- Permit safe reuse of an idle named scout. (inferred)
- Explain which threads consume the limit and how to retire them. (inferred)
- Do not silently downgrade an independent-review requirement when capacity is
  unavailable. (inferred)

### 6. Framework friction obscured genuine product evidence

The framework correctly rejected invalid retrieval labels and prevented a
24-query release gate from becoming a superiority claim. (verified) It also
generated enough hook noise and repeated blocking that the user had to spend
time restoring the process rather than evaluating the second brain. (verified)
The system needs to keep strict evidence gates while reducing repeated ceremony
and self-inflicted operational failures. (inferred)

## Human interventions that changed progress

- The user repeatedly ordered the agent to continue after the graph stopped
  advancing. (verified)
- The user explicitly approved recovery actions when the agent asked what it
  needed. (verified)
- The user directed the agent to fix the blocking condition instead of merely
  reporting it. (verified)
- The user challenged a validator change as possible weakening, forcing the
  evidence boundary to be stated. (verified)
- The user supplied Python crash evidence and demanded observability sufficient
  to diagnose it. (verified)
- The user required measured corpus scale and runner latency rather than design
  decisions based on guesses. (verified)

## Suggested acceptance tests

1. Start a graph with `pending`, `ready`, `running`, and terminal nodes; prove
   only terminal nodes require completion evidence. (inferred)
2. Kill a worker after `begin-wave`; prove the framework detects the lost task,
   records one diagnosis, and performs a bounded retry without a human `continue`.
   (inferred)
3. Leave a node ready after a successful prior wave; prove an authorised
   crack-on session dispatches it automatically. (inferred)
4. Trigger the same Stop condition 100 times; prove one user-facing message per
   unchanged graph revision and bounded descriptor/process growth. (inferred)
5. Exhaust agent capacity with completed and active tasks; prove completed tasks
   release slots and idle named agents can be reused. (inferred)
6. Simulate `EMFILE`, hook timeout, and native child crash; prove the status
   distinguishes them and links to content-free diagnostics. (inferred)
7. Request status at every graph state; prove the response states done, active,
   next, blocked, and exact human dependency in plain language. (inferred)

## Primary transcript source

Canonical session JSONL:

`/Users/garyharr/.codex/sessions/2026/09/22/rollout-2026-09-22T16-32-22-01a0c9bf-23e6-73d3-9c92-717a51cac912.jsonl`

The file is append-only and was still active when this handoff was written, so
its full-file SHA and final line count will change. (verified) Use the session ID
and source-line anchors below, then re-derive against the current file.
(verified)

Useful anchors:

- Line 7560: first observed `Too many open files` report. (verified)
- Lines 8203-8204 and many later lines: repeated incomplete-graph Stop output.
  (verified)
- Lines 10375-10376: user says `fix the blockage now.` (verified)
- Lines 10565-10566: user asks `what do you need?` (verified)
- Lines 10582-10583: user says `you are approved, crack on`. (verified)
- Lines 17972-17973: user reports Python quit again. (verified)
- Lines 20089-20090: user approves the state-specific cache-validator repair.
  (verified)
- Lines 20285-20286: user asks for the blocking reason to be fixed so the graph
  can be restored. (verified)
- Lines 20909-20910: user asks what is required and where the failing second
  brain, tracing, and observability stand. (verified)
- Lines 20982-20983: user asks for remaining work tracked in `progress.json`.
  (verified)
- Lines 23675-23676: user states delivery was not achieved without human
  intervention. (verified)
- Lines 23718-23719: user requests this improvement handoff. (verified)

Reproduction examples:

```bash
SESSION=/Users/garyharr/.codex/sessions/2026/09/22/rollout-2026-09-22T16-32-22-01a0c9bf-23e6-73d3-9c92-717a51cac912.jsonl
rg -n -o --fixed-strings 'The native Codex graph is not complete. Resume from:' "$SESSION"
rg -n -o --fixed-strings 'Too many open files' "$SESSION"
rg -n -o --fixed-strings 'fix the blockage now.' "$SESSION"
rg -n -o --fixed-strings 'what do you need?' "$SESSION"
rg -n -o --fixed-strings 'you are approved, crack on' "$SESSION"
rg -n -o --fixed-strings 'python quite again' "$SESSION"
rg -n -o --fixed-strings 'I approve replacing the cache validator' "$SESSION"
rg -n -o --fixed-strings 'but not without my human intervention though?' "$SESSION"
```

## Supporting durable artifacts

- Graph state:
  `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-.codex-sessions/01a0c9bf-23e6-73d3-9c92-717a51cac912/progress.json`
- Plan and frozen evals: sibling `plan.md`, `spec.md`, and `evals.json` beside
  that graph state. (verified)
- Stability evidence:
  `/Users/garyharr/Github/provenance-context-build/.agents/stability-v4/evidence.json`
  with SHA-256
  `32873691066325827ddaad71734ecd5549b9f8a8c077d6e5646c3f8509ffae7b`.
  (verified)
- Observability evidence:
  `/Users/garyharr/Github/provenance-context-build/.agents/observe-v4/evidence.json`
  with SHA-256
  `7a7b05bbcd2bc802e69d3d94e5f39a08cf52adc37b88aef3b61c00875ea94750`.
  (verified)
- BENCH primitive preflight:
  `/Users/garyharr/Github/provenance-context-build/.agents/bench-v4/design-preflight.md`.
  It records the unavailable independent scout and the measured design fallback.
  (verified)

## Scope for the next Coderails agent

Investigate and reproduce the six problems above in the Coderails repo. Do not
weaken terminal evidence, review, eval, or proof requirements. (verified)
Prioritise automatic stall recovery, stop-message deduplication, state-specific
validation, descriptor/process safety, and agent-slot lifecycle. (inferred)
Propose a graph and frozen evals before implementation, then prove the fixes
against the transcript-derived acceptance tests. (inferred)
