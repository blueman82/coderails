# Design — Universal progress record with independent-review truth seam

**Date:** 2026-06-30
**Status:** Approved (design), pre-implementation
**Files (planned):** `hooks/scripts/progress_record_guard.sh` (new — **DEFERRED, not in the first implementation slice; see the implementation plan's scope decision**),
`hooks/scripts/tests/progress_record_guard.test.sh` (new — **DEFERRED, see plan**),
`commands/post-review.md` (new — coderails-owned post-review step),
`hooks/scripts/lib/loop_state_common.sh` (reuse; possibly small additions),
`hooks/scripts/lib/agentic_loop_path.sh` (reuse, unchanged),
`scripts/lib/git-common.sh` (reuse `pr::*`; possibly add a comment-fetch helper),
`hooks/hooks.json` (register new Stop hook),
`commands/prep.md` (write the stub on the non-loop path),
`commands/workflow.md` (insert `/coderails:post-review` between review and merge),
`skills/agentic-loop/SKILL.md` (post-review step at Phase 4b),
`scripts/merge.sh` (gate `complete` on a GitHub-visible SHA-bound review artifact),
`AGENTS.md` + `docs/REFERENCE.md` (hook map + command entry).

**Note:** coderails does **not** own `/pr-review-toolkit:review-pr` (it is an
external plugin command — verified: no review command in `commands/`, and
`workflow.md` invokes `/pr-review-toolkit:review-pr`). The durable-artifact
behaviour therefore lives in a **new coderails-owned** `/coderails:post-review`
step that runs *after* `review-pr`, not in `review-pr` itself.

## Problem

`progress.json` — the loop's durable state file — is **loop-only**. In an
agentic loop, agents continuously write progress to it, leaving a durable trace
of what happened. On a **plain** (non-loop) workflow run (`/prep → /push →
review → /merge`), nothing writes a record anywhere. The work happens and
evaporates. Two consequences:

1. **No durable trace** of a plain run — what was built, what was verified, what
   was decided — survives the session.
2. **No durable record of the review.** `review-pr` (and its six agents) write
   their findings to the **chat window only**; nothing lands on the PR or in any
   file. `enforce_pr_workflow` gates merge on the *transcript event* that
   `review-pr` ran, not on any durable artifact.

The deeper question this surfaced: a Stop guard can only ever check that a
record **exists and is well-formed**, never that it is **true** — the agent
writes the record and is judged on it, with no privilege boundary between
writer and judge (the same enforcement ceiling `AGENTS.md` documents for every
other gate). So "always write a record" does not, by itself, get us a
*trustworthy* record.

## Decision

Adopt **independent authorship as the truth mechanism**, realised by *extending
existing components* (not building a parallel subsystem):

- **The record is always written** — loop and non-loop alike — but everything
  the **doer** writes is treated as a *claim*, not truth.
- **Truth enters as a durable GitHub artifact, not a local boolean.** After the
  independent reviewer (`review-pr` / Phase 4b) runs, a coderails-owned
  `/coderails:post-review` step posts a **machine-marked, SHA-bound review
  comment to the PR**. That comment — on the current PR, tagged with the current
  head SHA, fetchable from GitHub — is the authority. The local
  `progress.json.review` block is a **cache/index** of it, never the proof.
- **`/merge` gates on GitHub reality, not the local record.** Before merge,
  `/merge` fetches PR comments (`gh pr view --json headRefOid,comments`) and
  requires a coderails review marker whose `head_sha` equals the **current** PR
  head. A review posted against an earlier push no longer satisfies the gate.
- **The Stop guard is a ledger-completion guard, not a truth gate.** It blocks
  (not nudges) on the record's *presence + ownership + terminal status* —
  forcing a run to close its ledger. It explicitly does **not** enforce review
  truth; that lives entirely in the durable PR artifact.

The honest core: **a self-authored local record cannot be review-truth.** Truth
is moved out of the doer's writable file and onto a SHA-bound, human-auditable
GitHub artifact that `/merge` verifies against live PR state (see "The truth
seam" below).

## Approach: extend, don't invent (chosen over two alternatives)

- **Chosen — extend.** Reuse the cwd-keyed `agentic_loop_path.sh` (already
  loop-agnostic) and the loop-agnostic helpers in `loop_state_common.sh`
  (`als_resolve_path`, `als_read_file_state`, `als_log`). Add: stub-creation on
  the non-loop path (`/prep`), one small sibling Stop guard, and the
  `/coderails:post-review` step (post-to-PR + cache write).
- **Rejected — new subsystem.** A dedicated `progress_common.sh` lib + schema
  migration + rename of the `agentic-loop/` dir. Violates YAGNI; reintroduces
  the "system that maintains itself" weight this work is meant to reduce. Only
  justified if the loop / non-loop codepaths must genuinely diverge — they do
  not (same file, same fields).
- **Rejected — review-record only.** Post the review to the PR but drop the
  universal-trace goal. Smallest, but does not deliver the stated intent
  (a record on *every* run).

## Architecture — three parts

### A. Universal trace (the file)

`progress.json` becomes the record for **every tracked run**. Path is the
existing cwd-derived one from `agentic_loop_path.sh`
(`<base>/<cwd-slug>/progress.json`) — already loop-agnostic and a sole path
authority. `/prep` writes the stub on the non-loop path (it already opens every
workflow); the loop keeps writing it at Phase -2. **Same path, same file, same
schema for a given cwd** — loop and non-loop unified, not duplicated.

### B. Durable, SHA-bound review artifact (the truth seam)

`review-pr` is external and writes only to chat. coderails adds a **new owned
command `/coderails:post-review <PR>`** that runs *after* `review-pr` and:

1. Reads/summarises the just-completed review output (the agent passes or
   summarises the in-session findings — the one agent-hand-off seam, same class
   as the loop's existing hand-offs).
2. **Posts a machine-marked, SHA-bound comment to the PR**, e.g.:

   ```
   <!-- coderails-review-summary v1 pr=123 head_sha=abc123 -->
   ## Coderails review summary
   PR: #123 · Head SHA: abc123
   <Critical / Important / Suggestion findings>
   ```

3. Writes `progress.json.review` as a **cache** of the posted artifact (URL, id,
   head_sha) — not as authority.

**Anti-hollow requirement (the weakest seam).** Because `review-pr` writes to
chat, the findings reach `/post-review` via an **agent-mediated hand-off** — the
single hollowable point in the design. `/post-review` MUST reject a placeholder
summary: it requires a **structured body** with explicit Critical / Important /
Suggestion sections, **or** an explicit `No findings` declaration. A one-line
"review done" does not satisfy the step. This cannot prove the review was
*substantive* (the ceiling), but it stops a trivially-empty artifact from
becoming the durable record. Resolving the exact structural minimum is the first
plan task (see Open Items).

**Marker parse — narrowly anchored, not loose grep.** The marker is
`<!-- coderails-review-summary v1 pr=<n> head_sha=<sha> -->`. `/merge` parses it
exactly: prefix literal `<!-- coderails-review-summary `, version exactly `v1`,
`pr` exactly the current PR number, `head_sha` exactly the current `headRefOid`,
trailing ` -->`. An unrecognised version → no-match → fail-closed (block). This
keeps the gate from matching a stray or hand-typed lookalike.

`/workflow` order becomes: `… → /pr-review-toolkit:review-pr → /coderails:post-review → (ship-it pause) → /coderails:merge`.
post-review runs **before** the ship-it pause so the durable artifact is present
*during* the pause (a reason it is not folded into `/merge`).

### C. The non-loop guard (enforcement)

A new ~30-line Stop hook, `progress_record_guard.sh`, that **sources
`loop_state_common.sh`** and reuses its loop-agnostic helpers.

- **Activation:** an explicit workflow-command marker in the transcript —
  `<command-name>/coderails:(prep|push|workflow)</command-name>` — mirroring how
  the loop guard keys on an explicit mode-entry action rather than ambient state
  (config presence, branch name, or file existence — all rejected as
  over/under-firing). If no such marker is present (plain Q&A, manual git work),
  the guard stands aside (exit 0).
- **Check:** record exists + session-owned + reached terminal `status`. **No**
  `LOOP-STOP` per-turn declaration (that stays `loop_stall_guard`'s loop-only
  job); **no** re-arm math (meaningless off-loop, where invocation count is 0).
- **Stop-loop safety:** inherits `als_gate_stop_loop` (block at most once per
  turn) by reusing the shared lib.

### Deliberately NOT built (YAGNI guardrails)

No new lib; no schema migration; no rename of the `agentic-loop/` dir; no scribe
agent; no widening of the existing loop guards (their re-arm logic is
loop-specific and bailing-at-zero-invocations is their entire purpose — gutting
that to force non-loop enforcement would destroy it).

## Data flow

### Schema (additive — extends the existing stub, no migration)

```json
{
  "schema_version": 1,
  "session_id": "<this session>",
  "status": "initialising | in-progress | complete",
  "created": "<ISO8601>",
  "authorising_prompt_raw": "<verbatim first instruction>",
  "completed_marker": 0,
  "work": [
    { "what": "<built>", "verified": "<doer's claim, e.g. 'tests pass'>", "pr": null }
  ],
  "review": {
    "ran": false,
    "pr": null,
    "head_sha": null,
    "summary_posted": false,
    "summary_url": null,
    "summary_author": null,
    "posted_at": null
  }
}
```

The `review` block is a **cache/index** of the durable GitHub artifact, never
the authority. `/merge` treats it as a hint and verifies against live PR state.

The six existing fields are untouched. `work[]` and `review` are **new and
ignored by the loop guards**, which read only `status` / `session_id` /
`completed_marker` (verified: `als_read_file_state`). Adding fields therefore
cannot break the loop path; a loop-guard regression test makes this non-theoretical.

`work[]` granularity: **per-task** (multiple entries per PR), aligning with the
loop's existing per-work-unit recording. On the non-loop path the single agent
appends one cheap line per logical task; designed as a one-line append, not a
ceremony. (Per-PR is the fallback if per-task ever feels heavy on the plain path.)

### Non-loop flow

| Step | Who writes/reads | Effect on the record |
|---|---|---|
| `/prep` | doer | Creates stub: `status: initialising`, `session_id`, `created`, `authorising_prompt_raw`. Path from `agentic_loop_path.sh`. |
| code/iterate | doer | Appends `work[]` entries (what built + claimed verified). `status: in-progress`. **Self-authored = claims.** |
| `/push` | doer | Records PR number into the relevant `work[]` entry. |
| `review-pr` (external) | reviewer (independent) | Runs the specialist agents; writes findings to chat. coderails cannot change this step. |
| `/coderails:post-review` | post-review step | Posts the SHA-marked review comment to the PR (**the durable artifact**); writes `progress.json.review` as a cache (url, head_sha, …). **Truth seam.** |
| `/merge` | doer | Fetches `gh pr view --json headRefOid,comments`; requires a `coderails-review-summary` marker whose `head_sha` == current head. Only then sets `status: complete`. Guard sees terminal status → allows stop. |

### Loop flow (differs in one way only)

Doer and reviewer are **already separate agents** (worker vs. Phase 4b
reviewer), so independence is structural there already. Same file, same fields,
same post-review artifact step — `work[]` entries come from worker agents, the
orchestrator owns `status`. No second data codepath.

## The truth seam (corrected from an earlier "two gates" framing)

An earlier draft argued `/merge` gating on a local `review.ran` boolean formed a
second independent gate alongside `enforce_pr_workflow`. **That was wrong, and a
code-review pass caught it:** `review.ran` lives in a doer-writable file with no
writer-authentication, so `/merge` checking it proves only "the file says so,"
not "the reviewer wrote a verdict." It is a hollowable local proxy, not a gate.

The corrected model moves the authority **out of the local file and onto a
GitHub-visible artifact**:

- **Authority:** a `coderails-review-summary` comment on the PR, tagged with the
  **current head SHA**, posted by `/coderails:post-review`, fetchable via
  `gh pr view --json headRefOid,comments`.
- **`/merge` gate:** fetch the comments, require a marker whose `head_sha`
  equals the current PR head. A review posted against an earlier push fails the
  gate — forcing re-review after the code changes (the stale-review hole that
  "existence-only" would leave open).
- **`progress.json.review`:** a cache/index of that artifact, never the proof.
- **`enforce_pr_workflow`** still independently requires `review-pr` was
  *invoked* in the transcript (unfakeable by file edit) — a check on the
  invocation axis. **But see the obsolescence note below: this transcript arm is
  expected to become redundant once the artifact gate ships.**

### Obsolescence of the `review-pr` transcript arm (consequence to evaluate)

Once `/post-review` and the SHA-bound `/merge` gate exist, `review-pr`'s
occurrence is enforced **transitively** (in practice, for a cooperating agent),
with no transcript scan:

> no `review-pr` → no legitimate findings source → any summary is visibly
> unsupported → `/post-review` must reject it or the posted artifact is an
> auditable lie on the PR → no valid artifact → `/merge` blocks.

**Precision (consistent with the ceiling):** `/post-review` validates the
summary's *structure*, not its *provenance* — it cannot prove the findings came
from `review-pr`. A hollow agent could fabricate a structurally-valid summary
without running `review-pr`; that summary clears `/post-review` but lands as a
visible, attributable, SHA-bound artifact a human can audit. So the chain above
enforces review *in practice for a cooperating agent* and makes non-cooperation
*auditable*, not cryptographically impossible. This is the same ceiling as
§"Honest ceiling": the gate guarantees an auditable artifact exists, never that
its content is genuine.

At that point the `review-pr` arm of `enforce_pr_workflow` is no longer
load-bearing — it retains the transcript-schema coupling (`.message.content[]?`,
the flush-race retries) for a guarantee the artifact gate now provides more
robustly and without that coupling. This is the same "weak transcript-grep
spine" critiqued at the project's outset; the artifact gate is its stronger
replacement. **Recommendation: after this design ships, re-evaluate the
`review-pr` arm and likely demote it from block to nudge** (the `gh pr
create`/push arms are separate and unaffected). **Ordering constraint (must
not regress):** the transcript arm may only be demoted *after* `/post-review` +
the artifact gate are live and verified — demoting it earlier would leave a
window with **no** review enforcement on either axis. This is a follow-up, not
part of this design's implementation, and is recorded so the old proxy is not
silently enshrined alongside its replacement.

### Honest ceiling of this seam (do not re-open as a finding)

The GitHub-artifact gate proves that a **durable, SHA-bound, human-auditable
review artifact exists for the code being merged**. It does **not** prove the
review was *substantive or correct* — a hollow or low-quality comment with the
right marker and SHA still clears the gate. The improvement over the rejected
local boolean is real but bounded: hollowness becomes **visible, attributable,
and tied to the merged SHA** instead of hidden in a doer-flipped boolean.
No local mechanism can verify review *quality*; that is the ceiling, stated here
with the same candour as the original (and itself a correction of an oversold
earlier claim).

## Error handling (fail-closed)

| Failure | Behaviour | Notes |
|---|---|---|
| Trace missing at Stop (guard armed) | **block** (exit 2), message names path + stub | mirrors `loop_state_guard`'s `block_state_failure`; models don't follow nudges |
| Malformed JSON trace | **block** (empty status → not terminal) | `als_read_file_state` already degrades via `// ""` / `// 0` — no new code |
| post-review fails to post the artifact | no SHA-matching marker on PR → `/merge` blocks | the durable artifact, not a local boolean, is the gate |
| Review posted, then more code pushed | old marker's `head_sha` ≠ current head → `/merge` blocks → re-review required | the SHA-match property; stale reviews don't pass |
| Guard armed in non-workflow session | **stands aside** (exit 0) | activation predicate requires a `/coderails:*` command marker |
| Stop-loop (two guards ping-pong) | **stands aside** after first block this turn | inherits `als_gate_stop_loop` |

**Acknowledged soft spot:** a marker comment can be posted by the doer too (no
auth boundary on *who* posts a PR comment). But unlike the rejected local
boolean, a hollow marker is **visible, attributable, and SHA-bound** — a durable
lie on the PR, not an invisible flag. Review *quality* remains unverifiable
locally (the ceiling in "The truth seam"). Documented so it is not re-opened.

## Testing

Follows the existing `hooks/scripts/tests/*.test.sh` + `run_all.sh` convention
with env-override seams (`CLAUDE_AGENTIC_LOOP_DIR`, `CLAUDE_DISCIPLINE_LOG`).
The guard is bash → TDD per `test-driven-development` (failing test first).

New `progress_record_guard.test.sh` — one test per failure mode:

| # | Scenario | Assert |
|---|---|---|
| 1 | Workflow command in transcript, no progress.json | blocks (exit 2), path in message |
| 2 | Workflow command, valid in-progress, session-owned | allows (exit 0) |
| 3 | Workflow command, `status: complete`, session-owned | allows |
| 4 | Workflow command, trace owned by different session | blocks (ownership) |
| 5 | Malformed JSON trace | blocks (empty status) |
| 6 | No workflow command (plain Q&A) | stands aside (anti-false-fire) |
| 7 | `stop_hook_active=true` | stands aside (stop-loop) |
| 8 | Activation matcher present (`/coderails:prep`) | arms (pairs with #6) |

**Loop-regression proof:** re-run existing `loop_state_guard.test.sh` and
`loop_stall_guard.test.sh` unchanged, require green — proves the additive
`work[]` / `review` fields don't disturb the loop guards.

**Merge change:** extend the merge/`git-common` test surface — assert `/merge`
refuses to merge when no PR comment carries a `coderails-review-summary` marker
matching the current head SHA, and allows when one does. Mock the
`gh pr view --json headRefOid,comments` output (the script already shells to
`gh`; tests stub it the way the existing `gh`-dependent paths are tested).

**Not unit-tested (by nature):** the *truthfulness* of the reviewer's verdict
(unverifiable — the ceiling); the `review-pr` agents' internals (third-party
plugin); the post-review summarise-and-post behaviour, which is a **prompt
instruction**, verified by inspection/inclusion like the loop skill's phases,
not a `.test.sh` (the `gh`-fetch/marker-parse in `/merge` *is* unit-tested).

## Open items for the implementation plan

- Exact stub-write mechanism in `prep.md` (Bash step vs. Write tool) and how it
  reuses `agentic_loop_path.sh` without the model computing the path.
- **[Highest-priority — the weakest seam] The chat → `/post-review` hand-off.**
  `review-pr` writes to chat, so the findings reach post-review agent-mediated.
  Resolve: (a) the exact hand-off (argument vs. agent re-summarise); (b) the
  **structured-summary minimum** that rejects a placeholder — the concrete shape
  required (Critical / Important / Suggestion sections, or an explicit
  `No findings` declaration), and how `/post-review` validates it before posting.
  This is the one point a hollow artifact can still enter; the merge gate is
  solid, so this is where plan effort concentrates.
- Exact `gh`-fetch and marker-parse: prefer **helpers in `git-common.sh`** over
  inline `merge.sh` parsing, so tests target the helper — e.g.
  `pr::head_sha "$num"` (→ `gh pr view --json headRefOid`) and
  `pr::has_coderails_review_for_head "$num" "$sha"` (fetch `--json comments`,
  match the narrowly-anchored marker). `merge.sh` calls the predicate; the parse
  logic is unit-tested in isolation.
- **Loop-path symmetry — SETTLED: the SHA-match gate applies on BOTH paths.**
  `/merge`'s GitHub-artifact check is path-agnostic — the loop also runs
  `/post-review` and posts the same SHA-marked artifact, and the loop's `/merge`
  runs the same fetch+SHA-match. Rationale (raised in review): a per-path gate
  would create *two review-truth models* (non-loop: durable artifact; loop:
  Phase-4b event), which is exactly the inconsistency this design removes. No
  special-case unless a concrete double-block surfaces in the plan; if one does,
  the fix is to make Phase 4b's gate and the merge gate read the *same* artifact,
  not to exempt the loop. The plan must confirm Phase 4b posts a `/post-review`
  artifact so the loop's `/merge` has something to match.
- Marker format versioning: `v1` is specified; define what `/merge` does on an
  unrecognised future version (default: treat as no-match → block, fail-closed).
- **Concrete summary grammar (testable by inspection).** The anti-placeholder
  rule needs an exact shape, e.g. required headings `## Critical` / `## Important`
  / `## Suggestions` (or `## No findings`), each populated section carrying ≥1
  bullet or the literal `None`. Without a grammar the "reject placeholder" rule
  is prose only. Define it so `/post-review` validation is checkable.
- **No local fallback in `/merge`.** There must be NO path like "if `gh` fetch
  fails but `progress.json.review.summary_posted == true`, allow." A `gh` failure
  or a no-match is fail-closed (block). The plan asserts this explicitly with a
  test.
- **`/post-review` shape: script-backed vs. prompt-driven.** Marker construction,
  SHA stamping, the cache write, and summary-grammar validation are safer in a
  small backing script (deterministic) than prose. The plan decides; bias toward
  a script for the validate/post/cache mechanics, with the command prose handling
  only the agent-mediated summary hand-off. Allowed-tools will need `gh pr view`,
  `gh pr comment`, and the progress.json read/write path.
