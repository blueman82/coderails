# Loop state — `progress.json` reference

Detail-carrier for the loop's durable state artifact, referenced from the main skill's
"Context-window persistence" section. The imperatives stay in SKILL.md (start it with `graph.py start` at Phase -2,
resolve the path via the helper, update it through graph commands at each phase boundary, re-read it to re-orient);
this file is the field-by-field spec, the lifecycle, and the concurrency/ownership rules —
consult it when recording or repairing state through the supported commands.

## Contents

- [Path and keying](#path-and-keying)
- [Fields](#fields)
- [Lifecycle](#lifecycle)
- [Recency — a second loop is not masked by a stale `complete`](#recency)
- [Concurrent loops in one directory](#concurrent-loops-in-one-directory)
- [Honest boundary](#honest-boundary)
- [Siblings in the same directory](#siblings-in-the-same-directory)

## Path and keying

One `progress.json` at the path printed by the loop-state path helper
(`python3 hooks/scripts/lib/agentic_loop_path.py`) — outside the code repo, keyed to the repo (or cwd
outside a repo) **and this session's id**. That keying is what makes it survive the session's own
restart/compaction, never pollute the base every worker branches from, and never collide with
another session's file in the same directory. Resolve the path by running the helper (Phase -2);
never compute it yourself. The helper reads `$CLAUDE_CODE_SESSION_ID` (set in every Bash tool
call) when no session_id argument is given, so you normally don't need to pass one explicitly.

The graph commands replace it (not append) at each phase boundary. A single JSON object — read
the whole file in one shot to know current state. Do not use an append-log (`.jsonl`) that has to
be replayed to derive position, and that can leave a torn tail line after a crash.

## Fields

| Field | Notes |
|---|---|
| `schema_version` | Exactly `3`. Legacy, missing and malformed graph schemas fail closed; no schema-2 reader or alternate writer exists. |
| `proof_disposition` | Required when no `proof.json` exists. Use `graph.py record-proof-disposition` to save `"none: <nonblank reason>"` for an owned loop with no executable surface. Other or absent values block completion. A present proof file must validate independently. |
| `session_id` | This session's id; the guard's ownership check compares it against the file's own path. |
| `loop_id` | Unique non-blank identity for this loop. Preserve it during mid-loop rewrites; create a new value when re-arming for a new loop. Dispatch evals bind `session_id` + `loop_id`. |
| `revision` | Positive integer starting at `1`. Graph operations advance it. Dispatch envelopes bind the active revision; frozen dispatch evals bind only session and loop; final neutral grading binds the completion revision. |
| `status` | `in-progress` → `complete` (see Lifecycle); `graph.py start` writes `in-progress`. |
| `authorising_prompt_raw` | The authorisation envelope, verbatim. |
| `work_units` | JSON object keyed by unit id; each entry carries at least a `status`. In-flight values are `pending`/`in-progress`/`blocked` (with `blockedBy`); only `done` and `dropped` (with a mandatory sibling `dropped_reason`) are terminal — see below. `merged`/`complete`/other synonyms are retired: do not mint new status values. |
| `graph` | `{nodes, edges, joins, active_wave, hard_stop}`. Nodes use stable IDs, registry labels, matching status/outcome, retry bounds, evidence arrays and `respawn: {generation, intent}`. Edges reference existing nodes; all-input joins carry `id`, `inputs`, and `released`. The native adapter owns transcript cursors and wave history. |
| `loop_stop_counts` | **HOOK-OWNED.** Per-category counts `{hard-stop, approval-gate, awaiting-input, complete}`, for Phase 13. |
| `disposition` | Per work-unit that retires an existing code path: `clean-break` \| `preserve-compat`. |
| `named_blocker` | When `preserve-compat`: the specific consumer still on the old path that justifies keeping it. |
| `removal_ticket` | When `preserve-compat`: tracks the deferred removal. |
| `decisions_absorbed` | Chronological (oldest-first) array of typed, hash-chained rows `{seq, phase, decision, flip_condition, unit, revision, ts, prev_sha256, row_sha256, muninn: {state: syncing\|written\|degraded\|unknown\|disabled, id, reason_code}}`, appended ONLY by `graph.py record-decision` through `scripts/lib/decision_record.py` at each phase boundary that absorbs an in-scope decision (Phases -1, 2.5, 2.6, 2.8, 5, 6); never hand-appended. `{phase, decision}` stay exactly as the dashboard reads them. The local row is claimed before Muninn (`kind=decision`, cite quoted from `authorising_prompt_raw`); a safely degraded sync is retried by `graph.py flush-decisions` at teardown. `syncing` or `unknown` requires store reconciliation before retry. Phase -1 records only in a full-autonomous envelope, where it auto-adopts the improve-prompt output instead of asking. In the Phase 2.5/2.6 graph wave the orchestrator records each worker result; workers never write this field (Muninn writers cannot run in subagents). |
| `completed_marker` | Count of agentic-loop loops completed in this session; bumped at teardown, carried forward by `graph.py start` when it re-arms a completed loop. |
| `last_updated` | Refreshed at each phase boundary. |
| `state_minor` | Integer (absent = 0) naming the `progress.json` layout minor within schema 3; current is 1 (v1 adds `graph.wave_history {}`, `stops []`, `updated_at`). `graph.py start` writes it; `graph.py convert <state> --session <id> [--check]` upgrades an older file in place on either provider, refusing with `convert_refused_<code>` when it would have to guess (unknown `schema_version`, `state_minor` from a newer tool, an in-flight wave with no `wave_history` entry, malformed `stops`/`work_units`, non-object `graph`, a foreign session, an existing `progress.json.pre-convert`). It writes `progress.json.pre-convert` once (never overwritten or deleted) before replacing the file, and a second run is a no-op. |

**`work_units` feeds the loop-scope eval gate.** `loop_state_guard` reads `.work_units | length`
to decide whether the ≥1-work-unit eval threshold applies, and fails open (no block) when the
field is absent — so keep it populated whenever the loop tracks ≥1 work-unit.

**`work_units` also feeds the `loop_stall_guard` deferral gate.** A recorded `complete`
stop (`graph.py stop --category complete`) is blocked while any unit's `status` is not terminal (`pending`, `in-progress`, or
`blocked` all block; so does any other value). `done` is terminal outright; `dropped` is terminal
only with a non-empty **string** `dropped_reason` — an absent, empty, whitespace-only, or
non-string (number, boolean, array, object) reason all still block. A unit whose value is not an
object blocks too: a unit that cannot be proven terminal is not terminal. The block message names
the offending unit id(s).

An absent or null `work_units` field, or an empty object, represents no registered
units. A non-object roster or malformed individual unit blocks completion. A
missing or corrupt graph state cannot complete. Retrospective presence is a
separate mandatory gate.

**Graph coordination and evidence.** Every loop carries non-blank `session_id`
and `loop_id`, schema 3, and a positive revision. Graph waves are manually
operated by the orchestrator. Use the native Python CLI from
`execution-graph.md`; all transition validation, retry reads, transcript binding
and the single atomic write occur under the same provider-owned lock.

A pending node becomes ready only after every incoming dependency is
`done` or `skipped`. An open wave or hard stop prevents another wave.
`blocked` and `stale` are not successful prerequisites. `failed` is a wave
outcome, never a persisted status: recording it increments `retry.attempts` and
returns ordinary nodes to pending. FULL-profile `U4`, `U4b-review`, and
`U4b-merge-gate` become blocked until a distinct diagnosed `record-repair`
transition requeues verification. Every node hard-stops at `retry.max` (1 through 5).
A stale result requires an artifact check in that same result:
`{"checked":true,"method":"<check>","result":"<observation>"}`.
A bare idle event is insufficient. `respawn-stale` records the reason and a new
generation; a fresh native dispatch must follow, with prior attempt evidence
preserved. Only the adapter releases joins after every input succeeds.

Frozen dispatch evals bind `session_id` + `loop_id`, **not revision**. Native
Agent prompts bind the exact current session, loop, revision, wave and node.
Completion re-derives original parent and child records, requested native role,
child attribution, successful terminal output and genuine harness notification.
No caller-supplied identity, echoed notification or worker claim can replace
these records. All children of a fan-out must qualify, and identities cannot be
reused across nodes or attempts.

**`work_units` and `graph.nodes` remain separate views.** A unit need not mirror
a graph node. Graph completion does not make an unfinished unit terminal, and a
done unit does not supply missing native graph evidence. Both gates must pass;
there is no reconciliation or automatic status copying between them.

**`loop_stop_counts` is written solely by the `loop_stall_guard` hook** on each consumed stop
(a `stops[]` row written by `graph.py stop`, marked `consumed` in the same atomic write that counts it;
final text is only a rendering and is never read, so a missing row blocks with `stop_row_missing`; `stops[]` is intent, `loop_stop_counts` the count). The orchestrator never writes or increments it. `graph.py start` never writes
it and drops it when re-arming a completed loop (the finished loop's counts live in its `retro.json`);
never rewrite the file wholesale.

## Lifecycle

Enforced by the `loop_state_guard` Stop hook (presence + ownership) — it blocks any stop where an
active loop has no session-owned file. When `progress.json` is absent, this is a nag-once grace, not
an unconditional block: the guard blocks once per session + invocation count, then stands down for
the rest of that count, so a skill loaded only to read this file isn't blocked forever — a new
invocation count re-arms the block. Session-mismatch and stale-complete-after-rearm carry no such
grace and block every time.

- **Start (Phase -2):** run `graph.py start` (see phases-setup.md). It stamps this `session_id`, your unique non-blank `loop_id`, `revision: 1` and `status: "in-progress"` with an empty graph and no active wave, then `graph.py add-unit` registers each work unit. Never hand-write these; the initial state is validated, not decorative. A different `loop_id` over an unfinished loop is refused: resume it.
- **Phase 0:** the envelope is already in `authorising_prompt_raw`; update it only when an improved envelope is adopted.
- **Update at each phase boundary:** `graph` node states, work-unit states, disposition fields, `last_updated` — these fields are written through the graph commands (`add-unit`, `begin-wave`, `record-wave`, `record-unit`, `hard-stop`) and read back with `inspect` or `summarize`; never hand-edit `progress.json` and never touch `loop_stop_counts`.
- **Teardown at Phase 13:** record any standing-order candidates with
  `orders.py record` before completion. After final grading, proofs, and
  retro, run `python3 "${PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" verify-completion <state> --session <session>`.
  Then run `python3 "${PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete <cwd> <session>`.
  The helper prepares orders, saves native completion with the live
  invocation marker, then ticks and renders orders. It also handles a loop
  with no recorded candidates. A pending apply or render needs an idempotent
  `mark-complete` retry. Do not call `prepare`, `tick`, or `render` separately,
  and never hand-derive or increment `completed_marker`.

## Recency

A prior loop's `status: "complete"` must not silence the guard for a later loop in the same long
session. `graph.py start` re-arming a completed loop (new `loop_id`, `status` back to `in-progress`) is the primary re-arm
signal. `completed_marker` is the backstop: if a new loop skips `graph.py start`, the guard still sees the
current invocation count exceed the recorded `completed_marker` and blocks, forcing
a fresh `start`. This is why teardown must run the native `mark-complete` helper (never a bare write of
`status: "complete"`) and `start` carries `completed_marker` forward.

## Concurrent loops in one directory

Keyed by repo (or cwd outside a repo) *and* session_id, so two concurrent `agentic-loop` sessions
against the same repo each get their own file — no race, no last-writer-wins — regardless of which
worktree each session's cwd is in: worktrees of the same repo resolve to the SAME directory by
design, and `session_id` is the sole isolating key within it. This relies on `session_id` staying
stable across one conversation's own compaction/restart while differing between separate
conversations. `loop_state_guard.py`'s session-mismatch check fails closed if a file's path
disagrees with the session_id recorded inside it (a copied or hand-edited file). A loop that must
not let another session see its working-tree changes still wants a separate git worktree — that
isolation is about the working tree, not `progress.json`, which is shared on purpose across a
repo's worktrees.

## Honest boundary

The guard guarantees the file *exists* and is *this session's* — not that its content is
faithfully maintained (the same limit `check_verify_loop.py` documents). Keeping the file current
is still your job; the guard only catches its absence.

## Siblings in the same directory

- **`sdd-ledger.md`** — when a work-unit delegates to `superpowers:subagent-driven-development`, that skill's ledger lives beside `progress.json`, written by its own workspace helper rather than by this skill.
- **`retro.json`** — session-keyed, beside `progress.json`, written once by the Phase 13 teardown contract.
- **`orders-prepared-<logical-loop sha256>.json`** and **`teardown.jsonl`** — session-keyed preparations and honest lifecycle observations. Preparations bind the repo directory, state directory, session, separate logical loop, revision and progress hash. They stage claims without recurrence/aging effects; a receipt alone cannot authorize apply.
- **`evals.json`** — loop-scope and pr-scope, frozen at Phase 2.7c/2.7d via `/coderails:task-evals`; see `skills/agentic-loop/SKILL.md` for the field contract.
- **`proof.json`** — loop-scope, frozen at Phase 2.7e beside `evals.json`.
  A separate agent writes it from only `authorising_prompt_raw`, `session_id`,
  and `loop_id`. Do not give that agent the plan, spec, design conversation,
  or `progress.json`. Schema:
  `{"schema_version":1,"session_id","loop_id","frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`.
  A loop with no executable surface writes no proof file. It records that
  choice in `decisions_absorbed`. Use the supported
  `graph.py record-proof-disposition` command to save the no-proof reason in
  state. The proof gate reads that disposition.

  **The proof gate reads the orchestrator's transcript.** On a recorded
  `complete` stop, `loop_stall_guard` looks for a Bash `tool_use` and
  `tool_result` pair for each proof command. The match uses trimmed exact
  command text, never a substring. Run each command in the foreground;
  `run_in_background` does not supply a final outcome. The gate blocks
  when a proof is not satisfied. It reports:

  - `unexecuted`: no matching call or no returned result;
  - `failed`: the last matching result has `is_error: true`;
  - `badcmd`: the command is absent, non-string, or blank;
  - `unverifiable`: the proof entry is not a JSON object.

  The gate does not read a proof's `status` field. Writing `"pass"` there
  cannot replace an observed command run.

  **A failed proof can be withdrawn.** Add it to `withdrawn_proofs` in the
  same file: `[{"id","cmd","withdrawn_reason"}]`. The gate requires a
  matching command run in this session whose last result has
  `is_error: true`. It also requires a non-empty `withdrawn_reason` and an
  ID absent from `.proofs`. A withdrawal cannot use the proof rule that
  tolerates a run with no clear result. The two arrays have a combined
  100-entry cap, checked before transcript mining. A valid withdrawal is
  reported in the `complete` system message and does not block.

  **Absence requires a disposition.** Missing `proof.json` requires `proof_disposition` to equal `"none"` or start with `"none:"`. No legacy schema exemption exists. A present proof file must carry this session and loop identity and a numeric schema version >= 1. A malformed file, non-array proof collection or unprovable entry blocks. Empty/absent proof arrays are allowed only after the file-level checks; populated withdrawals are always checked. The combined cap is 100 entries. Proofs execute in the orchestrator's own foreground Bash transcript; a worker's execution cannot satisfy them.

  **Declaration boundary:** the gate checks that the no-proof disposition exists, not whether its reason is true. It also checks execution, not whether the frozen command is a good proof. These remain auditable declarations, not an external trust boundary.

  **Honest boundary:** the gate verifies a command RAN in this session's transcript and did not error — it cannot verify it was the RIGHT command. A weak, poorly-chosen proof set still passes trivially. What it buys is that the proof CHOICE is auditable and time-stamped (frozen before implementation, authored blind to the plan), and that EXECUTION can no longer be self-reported. **Trust boundary:** the gate treats the transcript as harness-written — a session that deliberately appends forged tool_use/tool_result records to its own (ordinary, writable) transcript file can defeat it; no transcript-reading hook can stop that. The gate's actual target is honest self-deception and lazy self-reporting, not adversarial transcript forgery.
- **`orders.json`** (the typed ledger, written only by `scripts/lib/orders.py`) and its generated views **`standing-orders.md` / `standing-orders-decayed.md`** — repo-keyed, one dir up (the grandparent of the `progress.json` path), shared across every session and loop against that repo. The views are read-only (mode 0444, marker-stamped); read current cited lessons with `scripts/lib/lessons.py --dir <repo-key dir> --session <known native caller id> query --format contract`. Refused or degraded reads remain unknown; a view cannot replace the query.

The asymmetry is deliberate: a retro belongs to the loop that produced it, but a lesson is meant
to outlive any single loop. `orders.py` holds one `dir_lock` through currentness lookup, tagged-claim reconciliation,
bounded sync and direct atomic ledger save. A failed read retains a prior K-id and degrades explicitly. External
Muninn sync stays outside the progress lock. The same-user orders lock supplies no exactly-once network guarantee.
