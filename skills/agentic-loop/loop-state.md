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
(`hooks/scripts/lib/agentic_loop_path.sh`) — outside the code repo, keyed to the repo (or cwd
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
| `schema_version` | Currently 1 for `progress.json`. |
| `session_id` | This session's id; the guard's ownership check compares it against the file's own path. |
| `status` | `initialising` → `in-progress` → `complete` (see Lifecycle). |
| `authorising_prompt_raw` | The authorisation envelope, verbatim. |
| `work_units` | JSON object keyed by unit id; each entry carries at least a `status`. In-flight values are `pending`/`in-progress`/`blocked` (with `blockedBy`); only `done` and `dropped` (with a mandatory sibling `dropped_reason`) are terminal — see below. `merged`/`complete`/other synonyms are retired: do not mint new status values. |
| `loop_stop_counts` | **HOOK-OWNED.** Per-category counts `{hard-stop, approval-gate, awaiting-input, complete}`, for Phase 13. |
| `disposition` | Per work-unit that retires an existing code path: `clean-break` \| `preserve-compat`. |
| `named_blocker` | When `preserve-compat`: the specific consumer still on the old path that justifies keeping it. |
| `removal_ticket` | When `preserve-compat`: tracks the deferred removal. |
| `decisions_absorbed` | Chronological (oldest-first) array of `{phase, decision}` appended at each phase boundary that absorbs an in-scope decision (Phases 2.5, 2.6, 2.8, 5, 6). |
| `completed_marker` | Count of agentic-loop loops completed in this session; bumped at teardown, carried forward by the Phase -2 stub. |
| `last_updated` | Refreshed at each phase boundary. |

**`work_units` feeds the loop-scope eval gate.** `loop_state_guard` reads `.work_units | length`
to decide whether the ≥3-work-unit eval threshold applies, and fails open (no block) when the
field is absent — so keep it populated whenever the loop tracks ≥1 work-unit.

**`work_units` also feeds the `loop_stall_guard` deferral gate.** A `LOOP-STOP: complete`
declaration is blocked while any unit's `status` is not terminal (`pending`, `in-progress`, or
`blocked` all block; so does any other value). `done` is terminal outright; `dropped` is terminal
only with a non-empty **string** `dropped_reason` — an absent, empty, whitespace-only, or
non-string (number, boolean, array, object) reason all still block. A unit whose value is not an
object blocks too: a unit that cannot be proven terminal is not terminal. The block message names
the offending unit id(s).

Fails open (allows) only at the FILE level: jq absent, the field absent/null, an empty
object, or an unparseable file. Note this is **not** the retro-presence gate's posture — that gate
*blocks* on an absent/malformed retro.json, because a retro is mandatory at Phase 13 whereas
`work_units` is optional and a trivial loop may never populate it. Absence of the field fails open;
an individual unit that cannot be proven terminal fails closed, so one malformed entry can never
launder an unfinished unit into a completion. This is structural enforcement of "nothing is
deferred": prose alone (a standing order) was observed to fail, so the gate makes deferral
impossible rather than merely discouraged.

**`loop_stop_counts` is written solely by the `loop_stall_guard` hook** on each valid `LOOP-STOP`
declaration. The orchestrator never writes or increments it. On any wholesale rewrite of the file
you must re-read the existing `progress.json` first and carry `loop_stop_counts` forward by the
same conditional as the Phase -2 stub rule: verbatim on a mid-loop rewrite, reset to `{}` when the
prior file's `status` was `"complete"`.

## Lifecycle

Enforced by the `loop_state_guard` Stop hook (presence + ownership) — it blocks any stop where an
active loop has no session-owned file.

- **Stub-first (Phase -2):** `status: "initialising"`, stamped with this `session_id`.
- **Enrich at Phase 0:** record the envelope verbatim in `authorising_prompt_raw`; `status: "in-progress"`.
- **Update at each phase boundary:** current phase, work-unit states, disposition fields, `last_updated` — carry `loop_stop_counts` forward per the rule above.
- **Teardown at Phase 13:** `status: "complete"`, and set `completed_marker` to the number of agentic-loop loops run in this session so far — the prior `completed_marker` (default 0) **plus 1**. Because this skill is invoked once per loop, that ordinal matches the guard's count of agentic-loop invocations, which is how the guard distinguishes a finished loop from a new one.

## Recency

A prior loop's `status: "complete"` must not silence the guard for a later loop in the same long
session. Phase -2's stub-first overwrite (`status` back to `initialising`) is the primary re-arm
signal. `completed_marker` is the backstop: if a new loop skips its stub, the guard still sees the
current invocation count exceed the recorded `completed_marker` and blocks, forcing
re-initialisation. This is why teardown must bump `completed_marker` and stub-first must carry it
forward.

## Concurrent loops in one directory

Keyed by repo (or cwd outside a repo) *and* session_id, so two concurrent `agentic-loop` sessions
against the same repo each get their own file — no race, no last-writer-wins — regardless of which
worktree each session's cwd is in: worktrees of the same repo resolve to the SAME directory by
design, and `session_id` is the sole isolating key within it. This relies on `session_id` staying
stable across one conversation's own compaction/restart while differing between separate
conversations. `loop_state_guard.sh`'s session-mismatch check fails closed if a file's path
disagrees with the session_id recorded inside it (a copied or hand-edited file). A loop that must
not let another session see its working-tree changes still wants a separate git worktree — that
isolation is about the working tree, not `progress.json`, which is shared on purpose across a
repo's worktrees.

## Honest boundary

The guard guarantees the file *exists* and is *this session's* — not that its content is
faithfully maintained (the same limit `check_verify_loop.sh` documents). Keeping the file current
is still your job; the guard only catches its absence.

## Siblings in the same directory

- **`sdd-ledger.md`** — when a work-unit delegates to `subagent-driven-development`, that skill's ledger lives beside `progress.json`, written by its own workspace helper rather than by this skill.
- **`retro.json`** — session-keyed, beside `progress.json`, written once by the Phase 13 teardown contract.
- **`standing-orders.md` / `standing-orders-decayed.md`** — repo-keyed, one dir up (the grandparent of the `progress.json` path), shared across every session and loop against that repo.

The asymmetry is deliberate: a retro belongs to the loop that produced it, but a lesson is meant
to outlive any single loop. Two concurrent loops updating `standing-orders.md` at once is
last-writer-wins, and self-correcting rather than a data-loss risk — a lesson lost to the race
re-adds itself the next time its failure mode recurs.
