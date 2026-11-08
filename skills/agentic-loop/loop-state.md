# Loop state — `progress.json` reference

Detail-carrier for the loop's durable state artifact, referenced from the main skill's
"Context-window persistence" section. The imperatives stay in SKILL.md (start it with `graph.py start` at Phase -2,
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
| `proof_disposition` | Required when no `proof.json` exists. Use `graph.py record-proof-disposition` to save `"none: <nonblank reason>"` for an owned loop with no executable surface. Other or absent values block completion. A present proof file must validate independently. |
| `session_id` | This session's id; the guard's ownership check compares it against the file's own path. |
| `loop_id` | Unique non-blank identity for this loop. Preserve it during mid-loop rewrites; create a new value when re-arming for a new loop. Dispatch evals bind `session_id` + `loop_id`. |
| `revision` | Positive integer starting at `1`. Graph operations advance it. Dispatch envelopes bind the active revision; frozen dispatch evals bind only session and loop; final neutral grading binds the completion revision. |
| `status` | `in-progress` → `complete` (see Lifecycle); `graph.py start` writes `in-progress`. |
| `authorising_prompt_raw` | The authorisation envelope, verbatim. |
| `work_units` | JSON object keyed by unit id; each entry carries at least a `status`. In-flight values are `pending`/`in-progress`/`blocked` (with `blockedBy`); only `done` and `dropped` (with a mandatory sibling `dropped_reason`) are terminal — see below. `merged`/`complete`/other synonyms are retired: do not mint new status values. |
| `graph` | `{nodes, edges, joins, active_wave, hard_stop}`. Nodes use stable IDs, registry labels, matching status/outcome, retry bounds, evidence arrays and `respawn: {generation, intent}`. Edges reference existing nodes; all-input joins carry `id`, `inputs`, and `released`. The native adapter owns transcript cursors and wave history. |
| `loop_stop_counts` | **HOOK-OWNED.** Per-category counts `{hard-stop, approval-gate, awaiting-input, complete}`, for Phase 13. |
| `disposition` | Per work-unit, stored as `work_units[u].disposition = {kind, named_blocker?, removal_ticket?}` by `graph.py add-unit --disposition clean-break\|preserve-compat [--named-blocker X --removal-ticket Y]` and carried into the dispatch contract. `kind` is `clean-break` or `preserve-compat`; refusal code `add_unit_refused_disposition`. |
| `named_blocker` | `disposition.named_blocker`: required and non-blank when `preserve-compat` (the specific consumer still on the old path that justifies keeping it); forbidden on `clean-break`. |
| `removal_ticket` | `disposition.removal_ticket`: required and non-blank when `preserve-compat` (tracks the deferred removal); forbidden on `clean-break`. `graph.py disposition-audit <state>` exits 1 on a hand-edited unit that lost half the pair, and completion refuses it. |
| `decisions_absorbed` | Chronological typed, hash-chained rows `{seq, phase, decision, flip_condition, unit, chosen?, worker_status_seq?, revision, ts, prev_sha256, row_sha256, muninn}`. Only `graph.py record-decision` through `scripts/lib/decision_record.py` appends them. A worker-status answer resolves the named status in the same locked save as one hashed row; Muninn sync follows outside the lock. A pending or unknown sync blocks that node's next wave until safely reconciled. `{phase, decision}` remain the dashboard keys. Phase -1 records only in a full-autonomous envelope. Workers never write this field. |
| `worker_statuses` | **RECORD-WAVE-OWNED.** Array of `{seq, node, wave_id, status, payload, decision_pending, revision}`, one per typed worker status (`NEEDS_DECISION`/`OUTSIDE_SCOPE`/`IRREVERSIBLE_ACTION`) that `graph.py record-wave` validated; `decision_pending` is true until `graph.py record-decision --worker-status-seq <seq>` marks it resolved. Written in the same locked save as its one typed stop row. |
| `final_reports` | **RECORD-WAVE-OWNED.** Object keyed by node id holding the validated `final_report {claims, did_not_verify}` a worker returned with a `done` result (required when the node's dispatch record has `final_report_required`). |
| `completed_marker` | Count of agentic-loop loops completed in this session; bumped at teardown, carried forward by `graph.py start` when it re-arms a completed loop. |
| `last_updated` | Refreshed at each phase boundary. |
| `state_minor` | Integer (absent = 0) naming the `progress.json` layout minor within schema 3; current is 3 (v1 adds `graph.wave_history {}`, `stops []`, `updated_at`; v2 adds `graph.dispatches {}` - one single-use record per dispatched node written by `begin-wave` - and `graph.contract_from_revision`, the first revision whose waves must carry a begin-wave envelope; v3 adds `graph.context_from_revision`, the first revision whose records must carry typed required skills and checks; `begin-wave` and `authorize-dispatch` refuse a state below 3, and both v1->v2 and v2->v3 refuse while a wave is open: `convert_refused_active_wave_in_flight`). `graph.py start` writes it; `graph.py convert <state> --session <id> [--check]` upgrades an older file in place on either provider, refusing with `convert_refused_<code>` when it would have to guess (unknown `schema_version`, `state_minor` from a newer tool, an in-flight wave with no `wave_history` entry, malformed `stops`/`work_units`, non-object `graph`, a foreign session, torn version-2 dispatch data, an existing `progress.json.pre-convert`). It writes `progress.json.pre-convert` once (never overwritten or deleted) before replacing the file, and a second run is a no-op. |

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
- **Teardown at Phase 13:** after final progress updates, stage any orders with `orders.py record` and run `orders.py --dir <repo-key dir> --session <session> prepare --loop <logical loop>` even when none were recorded. Preparation binds the eligible owned source and emits `orders_prepared`; it changes no lifecycle counters. Run `python3 "${PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" verify-completion <state> --session <session>` after final grading, proofs and retro exist. Then run `python3 "${PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete <cwd> <session>` to set status and the live invocation-count marker together under the state lock. Only after a successful durable completion save, run the bound `orders.py tick --loop <logical loop>` and `render`. `orders_ticked` follows the ledger save; a failed postcompletion apply or observation is pending teardown, recoverable by idempotent retry. Automatic provider wiring remains pending in this checkpoint. Never hand-derive or increment `completed_marker`.

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
- **`proof.json`** — loop-scope, frozen at Phase 2.7e beside `evals.json`, by a SEPARATE agent given only `authorising_prompt_raw`, `session_id`, and `loop_id` as explicit dispatch inputs (never the plan/spec/conversation, never a `progress.json` read) — generalising `task-evals`' grader-independence to the author. Schema: `{"schema_version":2,"session_id","loop_id","frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`. A loop with no executable surface writes none and records that choice in `decisions_absorbed` and `progress.json`'s `proof_disposition` field (see the Fields table above).

  **`proof.json` feeds the `loop_stall_guard` proof gate** (`loop_proofs.validate_proofs`; Codex: `graph_artifacts.validate_completion_evidence`). The CONTROLLER runs the proofs: `scripts/lib/proof.py freeze <state-dir>` validates the file (schema_version 2: unique ids, nonblank `cmd`, structured `expect` `{exit_code, stdout_contains, stdout_not_contains}`, optional `timeout_s`; at least one non-withdrawn proof; schema 1 is refused because it ignores structured `expect`) and appends a freeze row holding the sha256 of the canonical document. `proof.py run <state-dir> [--id X|--all]` runs each frozen `cmd` unchanged inside pinned sandbox-runtime 0.0.65 with a timeout (default 600 s). The command can read host files, write only below its fresh `TMPDIR`, and use no network. The controller refuses a command that the destructive classifier matches (`proof_cmd_destructive`) and refuses a run when the sandbox does not start (`proof_sandbox_unavailable`). It appends the result row outside the sandbox. `proof.py status` prints each proof's latest verdict.

  Rows live in `proof_results.jsonl` beside `proof.json`: `{seq, kind: freeze|run|disposition|supersede, proof_id, cmd_sha256 (= sha256 of cmd.strip()), proof_json_sha256, session_id, loop_id, head_sha, source_tree_sha, cwd, exit_code, stdout_sha256, stderr_sha256, excerpt (capped 2000), started, ended, expect_matched, verdict: satisfied|failed|expect_mismatch|timeout|refused|sandbox_unavailable|output_limit, prev_sha256, row_sha256}`. The hash chain detects edits to retained rows and removal of a nonfinal row. It cannot detect removal of final rows that leaves a valid prefix. On `LOOP-STOP: complete` the gate stops reading the transcript and the `status` field; each proof needs a LATEST run row whose `cmd_sha256` equals its current cmd, whose `proof_json_sha256` equals the latest freeze row (same session and loop), whose repository checkout and HEAD match the current controller checkout, and whose verdict is `satisfied`, on a valid chain. Block reason codes (also trace rows `proof.freeze|run|gate`): `proof_unexecuted`, `proof_failed` (failed/timeout), `proof_expect_mismatch`, `proof_stale_cmd` (proof.json edited after the freeze, or a different cmd hash), `proof_stale_head` (checkout or HEAD changed), `proof_chain_broken`, `proof_cmd_destructive`, `proof_sandbox_unavailable`, `proof_output_limit`, `proof_disposition_no_reason`; the message names each offending proof id.

  **One replacement in the same graph:** An isolated proof author writes a pending schema-2 candidate and a separate author report outside the active graph. After review, run `proof.py supersede <state-dir> --candidate <path> --reason <text> --original-sha256 <raw-sha> --author-evidence <path>`. The command leaves `proof.json` unchanged, stores the candidate under its raw SHA, and appends one chained `supersede` row. The row binds both documents' raw and canonical hashes, their loop identity, the report's byte hash and path, the reason, and issuance HEAD. The reader checks those bindings before selecting the candidate. Then run `proof.py freeze`, `run --all`, and `status`; old rows cannot satisfy the selected proofs. The current HEAD must still match each new run row. A second replacement, changed input, missing report, or broken chain blocks. A file left after an interrupted append stays inactive. This checks report bytes; it does not prove who wrote the report or that the author stayed independent.

  **A proof can be withdrawn instead of fixed via a sibling `withdrawn_proofs` array** (same file): `[{"id","cmd","withdrawn_reason"}]`. It is frozen and run like any proof, but STRICTER: it passes only when its latest run row is an observed `failed` or `timeout` and `withdrawn_reason` is nonblank (`proof_withdrawn_unobserved` otherwise); its `id` must not also appear in `.proofs`. `.proofs` and `withdrawn_proofs` share a cap of 100 entries. Cleared withdrawals are disclosed, never blocking, in the `complete` systemMessage.

  **Absence requires a disposition.** With no `proof.json`, completion needs a valid no-proof disposition on BOTH providers: `proof_disposition` `"none: <nonblank reason>"` (traced `proof_disposition_legacy`), the typed `{"kind":"none","reason_code","reason"}`, or a disposition row from `proof.py disposition <state-dir> --none --reason-code <code> --reason <text>`, where code is one of `docs_only|no_executable_surface|research_only|superseded|other`; the accepted disposition is echoed in the completion message. A proof.json with no non-withdrawn proof blocks as `proof_no_proofs` unless such a disposition exists. A bare `"none"` is rejected. A present proof file must carry this session and loop identity and a numeric schema version >= 1; a malformed file or non-array collection blocks.

  **Declaration boundary:** the gate checks that the no-proof disposition exists, not whether its reason is true. It also checks that the frozen command ran and matched its `expect`, not whether it is a good proof.

  **Honest limit (cooperating-agent safeguard):** the results file is written by the same user as the agent. An agent can forge rows and recompute the chain, remove a valid-prefix tail, or re-freeze a weaker proof set. The command sandbox limits host writes and network access, but does not make the proof selection or result ledger independent of the agent. A weak proof can still pass. The gate is non-disableable (no config key or env var).

  **Retained schema 1 proofs:** Preserve the old files. Start a new session and loop with a schema 2 proof for new work. The current gate cannot recheck completion or retry teardown for an old schema 1 loop. Use the prior plugin version in an isolated checkout for that historical recovery operation.

  **Committed source:** The proof command starts in a private copy of `HEAD`. Use relative paths for repository files. The original checkout is not readable. Each run row includes `source_tree_sha`. The gate checks that hash, the repository, and `HEAD` before it accepts a pass.

  **Platform limit:** This proof runner uses `/tmp` for private scratch on macOS and Linux. It refuses proof runs on Windows until a Windows policy is implemented and checked.
- **`orders.json`** (the typed ledger, written only by `scripts/lib/orders.py`) and its generated views **`standing-orders.md` / `standing-orders-decayed.md`** — repo-keyed, one dir up (the grandparent of the `progress.json` path), shared across every session and loop against that repo. The views are read-only (mode 0444, marker-stamped); read current cited lessons with `scripts/lib/lessons.py --dir <repo-key dir> --session <known native caller id> query --format contract`. Refused or degraded reads remain unknown; a view cannot replace the query.

The asymmetry is deliberate: a retro belongs to the loop that produced it, but a lesson is meant
to outlive any single loop. `orders.py` holds one `dir_lock` through currentness lookup, tagged-claim reconciliation,
bounded sync and direct atomic ledger save. A failed read retains a prior K-id and degrades explicitly. External
Muninn sync stays outside the progress lock. The same-user orders lock supplies no exactly-once network guarantee.
