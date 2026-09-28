# Loop state — `progress.json` reference

Detail-carrier for the loop's durable state artifact, referenced from the main skill's
"Context-window persistence" section. The imperatives stay in SKILL.md (stub it at Phase -2,
resolve the path via the helper, overwrite at every phase boundary, re-read it to re-orient);
this file is the field-by-field spec, the lifecycle, and the concurrency/ownership rules —
consult it when writing or repairing the file.

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

It is overwritten (not appended) on every phase boundary. A single overwritten JSON object — read
the whole file in one shot to know current state. Do not use an append-log (`.jsonl`) that has to
be replayed to derive position, and that can leave a torn tail line after a crash.

## Fields

| Field | Notes |
|---|---|
| `schema_version` | Exactly `3`. Legacy, missing and malformed graph schemas fail closed; no schema-2 reader or alternate writer exists. |
| `proof_disposition` | Required when no `proof.json` exists: `"none"` or `"none: <reason>"`. Other or absent values block completion. A present proof file must validate independently. |
| `session_id` | This session's id; the guard's ownership check compares it against the file's own path. |
| `loop_id` | Unique non-blank identity for this loop. Preserve it during mid-loop rewrites; create a new value when re-arming for a new loop. Dispatch evals bind `session_id` + `loop_id`. |
| `revision` | Positive integer starting at `1`. Graph operations advance it. Dispatch envelopes bind the active revision; frozen dispatch evals bind only session and loop; final neutral grading binds the completion revision. |
| `status` | `initialising` → `in-progress` → `complete` (see Lifecycle). |
| `authorising_prompt_raw` | The authorisation envelope, verbatim. |
| `work_units` | JSON object keyed by unit id; each entry carries at least a `status`. In-flight values are `pending`/`in-progress`/`blocked` (with `blockedBy`); only `done` and `dropped` (with a mandatory sibling `dropped_reason`) are terminal — see below. `merged`/`complete`/other synonyms are retired: do not mint new status values. |
| `graph` | `{nodes, edges, joins, active_wave, hard_stop}`. Nodes use stable IDs, registry labels, matching status/outcome, retry bounds, evidence arrays and `respawn: {generation, intent}`. Edges reference existing nodes; all-input joins carry `id`, `inputs`, and `released`. The native adapter owns transcript cursors and wave history. |
| `loop_stop_counts` | **HOOK-OWNED.** Per-category counts `{hard-stop, approval-gate, awaiting-input, complete}`, for Phase 13. |
| `disposition` | Per work-unit that retires an existing code path: `clean-break` \| `preserve-compat`. |
| `named_blocker` | When `preserve-compat`: the specific consumer still on the old path that justifies keeping it. |
| `removal_ticket` | When `preserve-compat`: tracks the deferred removal. |
| `decisions_absorbed` | Chronological (oldest-first) array of `{phase, decision}` appended at each phase boundary that absorbs an in-scope decision (Phases -1, 2.5, 2.6, 2.8, 5, 6). Phase -1 appends only in a full-autonomous envelope, where it auto-adopts the improve-prompt output instead of asking. In the Phase 2.5/2.6 graph wave, both worker results are collected and appended by the orchestrator in one read-modify-write; workers never write this field. |
| `completed_marker` | Count of agentic-loop loops completed in this session; bumped at teardown, carried forward by the Phase -2 stub. |
| `last_updated` | Refreshed at each phase boundary. |

**`work_units` feeds the loop-scope eval gate.** `loop_state_guard` reads `.work_units | length`
to decide whether the ≥1-work-unit eval threshold applies, and fails open (no block) when the
field is absent — so keep it populated whenever the loop tracks ≥1 work-unit.

**`work_units` also feeds the `loop_stall_guard` deferral gate.** A `LOOP-STOP: complete`
declaration is blocked while any unit's `status` is not terminal (`pending`, `in-progress`, or
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
returns the node to pending, or hard-stops at `retry.max` (1 through 5).
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

**`loop_stop_counts` is written solely by the `loop_stall_guard` hook** on each valid `LOOP-STOP`
declaration. The orchestrator never writes or increments it. On any wholesale rewrite of the file
you must re-read the existing `progress.json` first and carry `loop_stop_counts` forward by the
same conditional as the Phase -2 stub rule: verbatim on a mid-loop rewrite, reset to `{}` when the
prior file's `status` was `"complete"`.

## Lifecycle

Enforced by the `loop_state_guard` Stop hook (presence + ownership) — it blocks any stop where an
active loop has no session-owned file. When `progress.json` is absent, this is a nag-once grace, not
an unconditional block: the guard blocks once per session + invocation count, then stands down for
the rest of that count, so a skill loaded only to read this file isn't blocked forever — a new
invocation count re-arms the block. Session-mismatch and stale-complete-after-rearm carry no such
grace and block every time.

- **Stub-first (Phase -2):** `status: "initialising"`, stamped with this `session_id`, a new unique non-blank `loop_id`, and integer `revision: 1` — with an empty graph and no active wave. The stub is an orchestrator action, not synthetic worker evidence. See phases-setup.md's Phase -2 stub for the exact shape; it is validated, not decorative.
- **Enrich at Phase 0:** record the envelope verbatim in `authorising_prompt_raw`; `status: "in-progress"`.
- **Update at each phase boundary:** `graph` node states, work-unit states, disposition fields, `last_updated` — carry `loop_stop_counts` forward per the rule above.
- **Teardown at Phase 13:** first run `python3 "${PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" verify-completion <state> --session <session>` after final grading, proofs and retro exist. Then run `python3 "${PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete <cwd> <session>` to set status and the live invocation-count marker together under the state lock. Never hand-derive or increment `completed_marker`.

## Recency

A prior loop's `status: "complete"` must not silence the guard for a later loop in the same long
session. Phase -2's stub-first overwrite (`status` back to `initialising`) is the primary re-arm
signal. `completed_marker` is the backstop: if a new loop skips its stub, the guard still sees the
current invocation count exceed the recorded `completed_marker` and blocks, forcing
re-initialisation. This is why teardown must run the native `mark-complete` helper (never a bare write of
`status: "complete"`) and stub-first must carry `completed_marker` forward.

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
- **`evals.json`** — loop-scope and pr-scope, frozen at Phase 2.7c/2.7d via `/coderails:task-evals`; see `skills/agentic-loop/SKILL.md` for the field contract.
- **`proof.json`** — loop-scope, frozen at Phase 2.7e beside `evals.json`, by a SEPARATE agent given only `authorising_prompt_raw`, `session_id`, and `loop_id` as explicit dispatch inputs (never the plan/spec/conversation, never a `progress.json` read) — generalising `task-evals`' grader-independence to the author. Schema: `{"schema_version":1,"session_id","loop_id","frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`. Voluntary adoption, same posture as `evals.json`: a loop with no executable surface writes none, and records that choice in `decisions_absorbed` **and** in `progress.json`'s own `proof_disposition` field (see the Fields table above) — the latter is what the gate actually reads.

  **`proof.json` feeds the `loop_stall_guard` proof gate** (`loop_proofs.validate_proofs`). On a `LOOP-STOP: complete` declaration, the gate mines THIS session's own transcript for a Bash `tool_use`/`tool_result` pair matching each proof's `cmd`, run in the FOREGROUND ONLY (never `run_in_background` — a backgrounded launch's immediate result is not an outcome) (trimmed, EXACT string equality — never substring), and blocks naming any proof whose verdict isn't `satisfied`. The offenders list a user will actually see: `unexecuted` (no matching call, or the matching call's result never returned), `failed` (the LAST matching call's result carried `is_error: true`), `badcmd` (the proof's own `cmd` is missing, non-string, or empty/whitespace-only — cannot even be searched for), or `unverifiable` (the proofs-array entry itself is not a JSON object, so no `id`/`cmd` can be read from it at all). The `status` field inside `proof.json` is present but never consulted — the verifier never reads `.status`, so an orchestrator-written `"pass"` cannot rescue an unexecuted proof.

  **A proof can be withdrawn instead of fixed via a sibling `withdrawn_proofs` array** (same file, same schema_version): `[{"id","cmd","withdrawn_reason"}]`. The gate mines it in the same transcript pass as `.proofs`, but STRICTER — a withdrawal claims a failure was witnessed, so only a matching call whose LAST result was an observed `is_error: true` passes; `.proofs`' null-tolerance ("ran, no clear signal, let it through") does not apply here. An entry blocks `complete` unless its `cmd` executed in this session, its last result was a genuine failure, `withdrawn_reason` is non-empty, and its `id` does not also appear in `.proofs` (no double-dipping between pending and withdrawn). `.proofs` and `withdrawn_proofs` share a combined cap of 100 entries — checked before any transcript mining, to close a timeout-based bypass (an inflated proof.json making the gate's own scan time out, rather than satisfying it). A withdrawal that clears all its checks is reported, never blocking, in the `complete` systemMessage.

  **Absence requires a disposition.** Missing `proof.json` requires `proof_disposition` to equal `"none"` or start with `"none:"`. No legacy schema exemption exists. A present proof file must carry this session and loop identity and a numeric schema version >= 1. A malformed file, non-array proof collection or unprovable entry blocks. Empty/absent proof arrays are allowed only after the file-level checks; populated withdrawals are always checked. The combined cap is 100 entries. Proofs execute in the orchestrator's own foreground Bash transcript; a worker's execution cannot satisfy them.

  **Declaration boundary:** the gate checks that the no-proof disposition exists, not whether its reason is true. It also checks execution, not whether the frozen command is a good proof. These remain auditable declarations, not an external trust boundary.

  **Honest boundary:** the gate verifies a command RAN in this session's transcript and did not error — it cannot verify it was the RIGHT command. A weak, poorly-chosen proof set still passes trivially. What it buys is that the proof CHOICE is auditable and time-stamped (frozen before implementation, authored blind to the plan), and that EXECUTION can no longer be self-reported. **Trust boundary:** the gate treats the transcript as harness-written — a session that deliberately appends forged tool_use/tool_result records to its own (ordinary, writable) transcript file can defeat it; no transcript-reading hook can stop that. The gate's actual target is honest self-deception and lazy self-reporting, not adversarial transcript forgery.
- **`standing-orders.md` / `standing-orders-decayed.md`** — repo-keyed, one dir up (the grandparent of the `progress.json` path), shared across every session and loop against that repo.

The asymmetry is deliberate: a retro belongs to the loop that produced it, but a lesson is meant
to outlive any single loop. Two concurrent loops updating `standing-orders.md` at once is
last-writer-wins, and self-correcting rather than a data-loss risk — a lesson lost to the race
re-adds itself the next time its failure mode recurs.
