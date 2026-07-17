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
| `schema_version` | 1 for `progress.json` written before `proof_disposition` existed; write `2` going forward so `als_gate_proofs_on_complete` enforces the disposition requirement below (schema_version < 2 is grandfathered to the old fail-open-on-absence behaviour — see that gate's own header for the removal condition). |
| `proof_disposition` | Required at `schema_version` 2 when no `proof.json` is frozen: the bare string `"none"` or a `"none: <reason>"`-prefixed value (e.g. `"none: no executable surface"`) records that skip visibly. Any other value — including one that merely starts with the letters "none" without the colon, e.g. `"nonexistent"` — or an absent/null field, blocks `complete` — see `als_gate_proofs_on_complete`. Never consulted once `proof.json` exists. |
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
- **`evals.json`** — loop-scope and pr-scope, frozen at Phase 2.7c/2.7d via `/coderails:task-evals`; see `skills/agentic-loop/SKILL.md` for the field contract.
- **`proof.json`** — loop-scope, frozen at Phase 2.7e beside `evals.json`, by a SEPARATE agent given only `authorising_prompt_raw` (never the plan/spec/conversation) — generalising `task-evals`' grader-independence to the author. Schema: `{"schema_version":1,"frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`. Voluntary adoption, same posture as `evals.json`: a loop with no executable surface writes none, and records that choice in `decisions_absorbed` **and** in `progress.json`'s own `proof_disposition` field (see the Fields table above) — the latter is what the gate actually reads.

  **`proof.json` feeds the `loop_stall_guard` proof gate** (`als_gate_proofs_on_complete`). On a `LOOP-STOP: complete` declaration, the gate mines THIS session's own transcript for a Bash `tool_use`/`tool_result` pair matching each proof's `cmd`, run in the FOREGROUND ONLY (never `run_in_background` — a backgrounded launch's immediate result is not an outcome) (trimmed, EXACT string equality — never substring), and blocks naming any proof whose verdict isn't `satisfied`. The offenders list a user will actually see: `unexecuted` (no matching call, or the matching call's result never returned), `failed` (the LAST matching call's result carried `is_error: true`), `badcmd` (the proof's own `cmd` is missing, non-string, or empty/whitespace-only — cannot even be searched for), or `unverifiable` (the proofs-array entry itself is not a JSON object, so no `id`/`cmd` can be read from it at all). The `status` field inside `proof.json` is present but never consulted — the gate's jq program never reads `.status`, so an orchestrator-written `"pass"` cannot rescue an unexecuted proof.

  **A proof can be withdrawn instead of fixed via a sibling `withdrawn_proofs` array** (same file, same schema_version): `[{"id","cmd","withdrawn_reason"}]`. The gate mines it in the same transcript pass as `.proofs`, but STRICTER — a withdrawal claims a failure was witnessed, so only a matching call whose LAST result was an observed `is_error: true` passes; `.proofs`' null-tolerance ("ran, no clear signal, let it through") does not apply here. An entry blocks `complete` unless its `cmd` executed in this session, its last result was a genuine failure, `withdrawn_reason` is non-empty, and its `id` does not also appear in `.proofs` (no double-dipping between pending and withdrawn). `.proofs` and `withdrawn_proofs` share a combined cap of 100 entries — checked before any transcript mining, to close a timeout-based bypass (an inflated proof.json making the gate's own scan time out, rather than satisfying it). A withdrawal that clears all its checks is reported, never blocking, in the `complete` systemMessage.

  **Absence is now disposition-gated, not unconditionally fail-open.** At `progress.json` `schema_version` >= 2, an absent `proof.json` requires `proof_disposition` to be the bare string `"none"` or a `"none: <reason>"`-prefixed value (e.g. `"none: no executable surface"`) or the gate BLOCKS — a value that merely starts with the letters "none" without the exact-match or colon (e.g. `"nonexistent"`) still blocks. This is the mechanical enforcement of the voluntary-adoption sentence above; a loop can no longer silently skip both the file and the recorded reason. `schema_version` < 2 (or absent/non-numeric) is grandfathered to the old unconditional fail-open-on-absence behaviour, so progress.json written before this field existed is unaffected — see the gate's own header comment in `hooks/scripts/lib/loop_state_common.sh` for the removal condition. Once `proof.json` IS present, `proof_disposition` is never consulted and the file-level rules are unchanged: jq absent, `.proofs` absent/null/empty fail open ONLY when `withdrawn_proofs` is also empty/absent (a populated `withdrawn_proofs` with empty `.proofs` still validates the withdrawn entries — see the paragraph above); a malformed file, a bad `schema_version` (must be a number ≥ 1), a non-array `.proofs`, or an individual proof that cannot be verified (missing/non-string/empty `cmd`, non-object entry) all BLOCK, mirroring `work_units`' "absence fails open, an unprovable entry fails closed" rule. Orchestrator-session scope is deliberate, not a limitation to route around: a proof run inside a dispatched worker's own transcript never reaches the orchestrator's transcript and can never satisfy this gate — proofs exist to be run by the orchestrator itself, in the open, where the gate can see them.

  **Honest boundary on `proof_disposition` itself:** the gate verifies the field is present and is `"none"` or `"none:"`-prefixed — it cannot verify the stated reason is true. A model can write `"none: no executable surface"` when a surface actually exists; no hook can detect that. This closes the SILENT-omission path (no file, no reason, no trace) for loops at `progress.json` `schema_version` >= 2 — it does not close it universally. Two boundary members remain uncaught: (a) a false `"none: <reason>"` when a surface actually exists, as above, and (b) a loop whose `progress.json` self-declares `schema_version` < 2 (or non-numeric, or omits the field), or whose `progress.json` is absent/unparseable — that loop is grandfathered and can still reach `complete` with no `proof.json` and no `proof_disposition`, logged as `proof_gate=allowed_no_proof_grandfathered` rather than blocked. Same posture as every other declaration this gate family checks (`work_units` status, `dropped_reason`, `retro.json` presence): checks the declaration is present, not that it's honest.

  **Honest boundary:** the gate verifies a command RAN in this session's transcript and did not error — it cannot verify it was the RIGHT command. A weak, poorly-chosen proof set still passes trivially. What it buys is that the proof CHOICE is auditable and time-stamped (frozen before implementation, authored blind to the plan), and that EXECUTION can no longer be self-reported. **Trust boundary:** the gate treats the transcript as harness-written — a session that deliberately appends forged tool_use/tool_result records to its own (ordinary, writable) transcript file can defeat it; no transcript-reading hook can stop that. The gate's actual target is honest self-deception and lazy self-reporting, not adversarial transcript forgery.
- **`standing-orders.md` / `standing-orders-decayed.md`** — repo-keyed, one dir up (the grandparent of the `progress.json` path), shared across every session and loop against that repo.

The asymmetry is deliberate: a retro belongs to the loop that produced it, but a lesson is meant
to outlive any single loop. Two concurrent loops updating `standing-orders.md` at once is
last-writer-wins, and self-correcting rather than a data-loss risk — a lesson lost to the race
re-adds itself the next time its failure mode recurs.
