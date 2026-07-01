# Design: Harden `skills/agentic-loop/SKILL.md` — 7 resolved review findings

**Date:** 2026-07-01
**Status:** Approved (design) — pending implementation plan
**Topic:** Resolve seven design issues surfaced by review of `skills/agentic-loop/SKILL.md`
(the coderails multi-agent orchestration skill): a cold-read scale problem, a phase-numbering
duplication, a self-attestation loophole in the clean-break gate, a gameable terminal KPI, an
unenforced model rule, a concurrency invariant that isn't written down, and three stale memory
citations.

---

## 1. Problem / motivation

`skills/agentic-loop/SKILL.md` is coderails' orchestration discipline for autonomous multi-PR
sessions. It has grown to 19+ numbered phases (-2 through 13, with lettered sub-phases) as new
failure modes were folded in one at a time. A review pass surfaced seven distinct issues, spanning
readability, structural duplication, a security-relevant self-grading loophole, a gameable
self-audit metric, an unenforced convention, an undocumented concurrency hazard, and dead
citations to memory files that no longer exist. Each was investigated and resolved independently;
this spec records the seven decisions in one place before implementation touches the file.

## 2. Goal

Harden `SKILL.md` (and two small satellite touchpoints — `AGENTS.md` and
`hooks/scripts/lib/agentic_loop_path.sh`) against the seven findings below, each already resolved
to a single decision. No new findings are introduced by this spec; it is a record of decisions, not
a fresh brainstorm.

## 3. Decisions

### 3.1 Cold-read problem — phase count exceeds working memory

**Problem.** `SKILL.md`'s `## The phases` section runs from Phase -2 through Phase 13 (19+ items
counting lettered sub-phases: -2, -1, 0, 0.5, 1, 2, 2.5, 2.6, 2.7, 2.8, 3, 3a, 4, 4b, 5, 6, 7&8, 9,
10, 11, 12, 13). A reader opening the file cold has no way to hold the shape of the whole method in
mind before diving into phase-by-phase detail.

**Options considered:**
- **Full renumbering** (collapse to a shorter sequential list). Rejected: a check of the numbering
  found 9 inbound cross-references into specific phase numbers (not the 3 originally estimated),
  plus `docs/coderails-review.md` cites exact `SKILL.md` line numbers (see §3.2) that would go
  stale. The churn is disproportionate to the benefit — the phases are already independently
  addressable by number, and renumbering does not by itself make the *count* easier to hold in
  mind.
- **Convert phases to H2 headings.** Technically low-risk — a repo-wide check found no anchor
  links anywhere pointing at `SKILL.md` headings — but a heading-level change is a bigger diff for
  no more benefit than a short prose summary placed once at the top.
- **Add a short stage-map paragraph grouping the existing phases (chosen).**

**Decision.** Add a short overview paragraph immediately under the `## The phases` heading (before
the existing "The phases below are sequential…" line), grouping the current phases into 5
plain-language stages, with no renumbering and no heading-level changes:

| Stage | Phases |
|---|---|
| Setup | -2, -1, 0, 0.5 |
| Pre-flight | 1, 2, 2.5, 2.6, 2.7, 2.8 |
| Build | 3, 3a, 4 |
| Review & Ship | 4b, 5, 6, 7&8 |
| Wrap-up | 9, 10, 11, 12, 13 |

**Reasoning.** The stage-map gives a cold reader a five-item shape to hold in mind before descending
into the nineteen-phase detail, at the cost of one paragraph — no cross-reference, anchor, or line
number changes. Full renumbering was rejected once its true blast radius (9 refs + two stale
doc-citation lines) was measured against an equivalent-benefit, near-zero-cost alternative.

### 3.2 Phase 2.7 / Phase 2.8 numbering duplication

**Problem.** Phase 2.7 (`SKILL.md:195-197`) and Phase 2.8 (`SKILL.md:208-210`) each independently
state the identical complexity guard — "fires ONLY when the loop has ≥3 work-units or a cross-unit
dependency" — as their opening sentence. Verified duplication, not a stylistic echo: the same
condition, restated twice, gating two adjacent phases that are otherwise a single logical step
(commit the resolved design to durable state, in two files).

**Options considered:**
- **Leave as two separate phases, guard stated twice.** Rejected — the guard is one fact; stating
  it twice invites the two copies to drift out of sync on a future edit.
- **Merge 2.7 and 2.8 into one guard-gated phase with lettered sub-steps (chosen).**
- **Also merge Phase 2.5 and Phase 2.6 into the same consolidation.** Rejected — 2.5 and 2.6 fire
  unconditionally (no guard), and each has 6 inbound cross-references elsewhere in the file (Phase
  2.5: the design-fork recommendation is referenced by Phase 3's task manifest and Phase 13's audit;
  Phase 2.6: the disposition decision is referenced by Phase 3, Phase 3a, Phase 4b, and Phase 13).
  Merging them risks breaking those references for no corresponding duplication to remove.

**Decision.** Merge Phase 2.7 and Phase 2.8 into a single phase, keeping the "Phase 2.7" number
(so only one downstream reference — Phase 2.8's own — needs updating, not two), retitled to cover
both artifacts:

> **Phase 2.7 — Commit the resolved design to durable `spec.md` and `plan.md`**

State the `≥3 work-units or cross-unit dependency` guard once, at the top of the merged phase, then
two lettered sub-steps:
- **2.7a** — write `spec.md` (envelope, design-fork decision, disposition decision(s), success
  criteria, high-level work-unit boundaries) — the content currently under Phase 2.7.
- **2.7b** — write `plan.md` via `/coderails:writing-plans` (the static SSOT for the decomposition,
  consumed by Phase 3's task list and re-read after compaction) — the content currently under
  Phase 2.8.

Phase 2.5 and Phase 2.6 are left as standalone phases, unmerged.

**Reasoning.** The two phases already describe one action — commit the resolved design to durable
state — split across two files only because they touch two different artifacts. Merging removes
the duplicated guard sentence at its single source of truth without touching 2.5/2.6, which carry
too many inbound references to safely fold and don't share this phase's actual defect (they were
never duplicated in the first place).

**Follow-up (not fixed in this spec).** `docs/coderails-review.md` lines 160 cite `SKILL.md:209`,
`SKILL.md:239,260`, and `SKILL.md:207-260` as evidence for a prior correction. Once this file's
line count shifts (from the stage-map addition in §3.1 and the phase merge in this section), those
line-number citations go stale. Flag as a follow-up task in the implementation plan — do not fix
`coderails-review.md` as part of this spec.

### 3.3 Phase 4b self-attestation override loophole

**Problem.** `SKILL.md:311` lets the orchestrator demote a clean-break compat `MERGE-BLOCKER`
finding — raised by the independent `code-simplifier` reviewer — to a logged note, by writing
free-text "reviewed, not compat — `<reason>`". The party doing the demoting is the orchestrator:
the same party whose worker just shipped the compat path and who has the motive to keep the
shortcut. No counter-check exists on the override text.

**Options considered:**
- **Keep self-demotion, but require the override to cite a specific re-checkable fact (file:line),
  logged as structured data for a later independent auditor.** Rejected. A fabricated-but-plausible
  citation costs the same effort to write as a true one, and nothing re-runs the check at override
  time — this makes bad overrides *auditable after the fact*, not *prevented*. Prevention is
  achievable here at a small cost (an occasional hard-stop), so the cheaper "make it auditable"
  compromise isn't worth taking when outright prevention is on the table.
- **Remove the orchestrator's self-demote power entirely (chosen).**

**Decision.** Remove the orchestrator's ability to self-demote a clean-break compat finding. On a
clean-break unit, an independent reviewer's compat finding becomes a `MERGE-BLOCKER` that the
orchestrator **cannot** downgrade unilaterally. Its only two moves:
- (a) actually fix it — remove the compat path, or
- (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason.

If a fully-unattended envelope genuinely cannot tolerate ever hard-stopping at this gate, the human
must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never
something the orchestrator grants itself mid-run.

**Reasoning.** The loophole exists because the self-demoting party and the party with motive to
keep the shortcut are the same party. Removing the power outright closes that in every case except
one the human opted into up front, in the envelope, before any specific finding exists to be biased
about. The rejected alternative only made bad overrides visible in hindsight; this decision
prevents them.

### 3.4 Phase 13 KPI gaming (zero-stall metric)

**Problem.** `SKILL.md:410-417`'s terminal self-audit reports "human turns approaching zero" as a
target metric. That reading is identical whether the orchestrator was well-calibrated (correctly
absorbing every in-scope decision) or silently suppressed asks it should have made. The metric
can't distinguish a genuinely quiet loop from a loop that hid its stalls.

**Options considered:**
- **Have a freshly-spawned independent agent audit the same `progress.json` fields and issue a
  "calibrated zero" vs "suppressed zero" verdict.** Rejected. That auditor's only inputs are still
  orchestrator-authored records — it grades homework against homework. Worse, a clean automated
  verdict can look *more* trustworthy than an honest raw list while being equally gameable: the safe
  strategy under that scheme becomes padding the record with trivial non-decisions to look
  thorough (a Goodhart's-law failure mode).
- **Drop the scorecard; report raw, unscored facts and let the human judge (chosen).**

**Decision.** Remove the numeric pass/fail scorecard from Phase 13 entirely. Phase 13 instead
reports two raw, unscored facts:
- (a) the `LOOP-STOP` category counts broken down by type — already artifact-backed from the
  declared stops (`progress.json`'s `loop_stop_counts`), hard to fake.
- (b) a flat, unscored list of in-scope decisions the loop made autonomously without asking
  ("decisions absorbed") — no self-justification text attached, no automated "this looks
  calibrated" stamp.

The human is the only party positioned to judge "should I have been asked about that?" — hand them
the raw list rather than have the process pre-grade itself.

**Reasoning.** Any self-issued verdict is graded by the party being graded, or by an auditor reading
only that party's own records — both are gameable, and a clean-looking verdict is more dangerous
than an honest unscored list because it's more likely to be trusted uncritically. Raw counts and a
flat decision list can't be gamed by looking good; they can only be gamed by omission, and omission
from a flat list is easier for a human to spot than a fabricated pass on a scorecard.

### 3.5 `model: sonnet` rule is unenforced

**Problem.** `SKILL.md` asserts "model: sonnet" for spawned workers roughly 6 times (Phases 2, 2.5,
3, 3a, 10), but no hook mechanically enforces it — confirmed by grepping `hooks/hooks.json` and
`hooks/scripts/*.sh`, which only match `Bash` and `Write`/`Edit`/`MultiEdit` tool events, nothing
for `Agent`/`Task` spawns.

**Options considered:**
- **Build a hook that gates spawn calls on the requested model.** Rejected — see reasoning below;
  the rule's own text already carves out a legitimate escalation exception that a blunt gate can't
  distinguish from a disallowed spawn.
- **Leave it advisory (prose-only) and document that this is deliberate, not a gap (chosen).**

**Decision.** Leave the `model: sonnet` rule advisory. Do not build an enforcement hook. Add one
documentation bullet to `AGENTS.md`'s "Enforcement ceilings" list (after the existing bullet ending
`...never before, or a window opens where neither gate is active.`, i.e. appended as the next
ceiling bullet, before the "Hook script conventions" subsection) stating this is a deliberate
choice:

> - **`model: sonnet` for spawned workers is advisory, not hook-enforced.** `agentic-loop`
>   SKILL.md asserts it ~6 times (Phases 2, 2.5, 3, 3a, 10) but no hook gates `Agent`/`Task` spawn
>   calls on the requested model — `hooks/hooks.json` and `hooks/scripts/*.sh` only match `Bash`
>   and `Write`/`Edit`/`MultiEdit` events. This is deliberate: the rule's purpose is cost control,
>   not correctness — an opus worker still produces a valid, fully-gated PR; nothing load-bearing
>   breaks if it fires. Phase 2.5 also sanctions a legitimate opus-escalation exception ("escalate
>   the synthesis to opus only if the tradeoff is genuinely close") that a blunt model-gate hook
>   cannot distinguish from a disallowed worker spawn without a self-reported carve-out flag —
>   which reintroduces the same trust-the-agent problem one level down.

**Reasoning.** Building a hook trades an advisory cost-control convention for a mechanical gate
that either blocks a legitimate, already-sanctioned exception (Phase 2.5's opus escalation) or has
to trust a self-reported flag to distinguish the two cases — the exact trust-the-agent problem
the hook was meant to remove, just moved one level down. Since nothing correctness-relevant breaks
when the rule is skipped, the cost of the false-positive-prone hook outweighs the benefit.

### 3.6 Concurrent-loop race on `progress.json`

**Problem.** The loop-state file is keyed only by project working directory, not by session. Two
`agentic-loop` sessions in the same directory — or a new session that skips the Phase -2 stub and
inherits a stale prior session's completed `progress.json` — collide. Verified live during the
design session that produced this spec: a leftover `completed` `progress.json` from an earlier
finished loop blocked the new session's Stop hook until it was manually re-stubbed. The existing
`loop_state_guard.sh` correctly detects and blocks on session mismatch (fail-closed, visible, not
silent), but it does not prevent genuine concurrent last-writer-wins overwrites between Stop
events.

**Options considered:**
- **Build file-locking machinery** (staleness detection, PID-liveness checks, cross-platform lock
  files). Rejected — this is a rare, unsupported-configuration failure mode (two loops in the same
  checkout), and the cross-platform complexity of a correct lock implementation is not worth it for
  that likelihood.
- **Document the single-loop-per-project-working-directory invariant explicitly, pointing at
  existing worktree tooling as the resolution (chosen).**

**Decision.** Do not build locking. Add one sentence each to:
- `SKILL.md`'s `## Context-window persistence` section, stating that concurrent loops in the same
  checkout will race for ownership of `progress.json` and must be isolated via separate git
  worktrees.
- The header comment of `hooks/scripts/lib/agentic_loop_path.sh`, stating the same invariant at the
  source of the path-keying logic.

Both sentences point at the existing `coderails:using-git-worktrees` skill as the resolution
mechanism.

**Reasoning.** `loop_state_guard.sh` already fails closed and visibly on session mismatch — the
dangerous case (silent data loss) is already handled. What's missing is that the single-loop
invariant was never written down, so a user hits the guard's block without knowing *why* or what
to do about it structurally. A one-sentence invariant plus a pointer to the existing worktree skill
closes that gap without adding any new machinery.

### 3.7 Stale memory citations

**Problem.** `SKILL.md` cites three feedback-memory files by name as load-bearing justification:
`feedback_wiki_ingest_and_lint_post_merge` (Phase 9, `SKILL.md:342`), `feedback_parallel_wiki_agents`
(Phase 9, `SKILL.md:344`), and `feedback_three_parallel_adversarial_agents` (Phase 4b, `SKILL.md:313`,
cited via `CLAUDE.md`). Verified by listing the actual memory directory
(`/Users/harrison/.claude/projects/-Users-harrison-Github-coderails/memory/`, 14 files) and grepping
`~/.claude/CLAUDE.md`: none of the three exist under those names or any plausible variant, right
now — not a future-rot risk, a present-tense broken citation.

**Options considered:**
- **Leave the citations as-is on the theory they document historical intent.** Rejected — a
  citation to a nonexistent file is worse than no citation; a reader who checks it finds nothing,
  which undermines trust in every other citation in the file.
- **Delete the citations and restate the underlying principle inline, so the sentence no longer
  depends on an external file (chosen).**

**Decision.** Remove the three named-memory citations and replace each with the principle restated
as inline prose:

1. **Phase 9, `SKILL.md:342`** — current text: *"Per memory `feedback_wiki_ingest_and_lint_post_merge`, lint must always pair with ingest; running one without the other is incomplete."*
   Replacement: *"Lint must always pair with ingest — running one without the other leaves the wiki either unverified (ingest with no lint) or unrefreshed (lint with no ingest); treat the two as one step, not two optional ones."*

2. **Phase 9, `SKILL.md:344`** — current text: *"This matches memory `feedback_parallel_wiki_agents` (cluster together, don't fragment)."*
   Replacement: *"Clustering related updates into one pass keeps the wiki's per-topic pages coherent; running one wiki agent per PR instead fragments a single theme across many small, redundant edits."*

3. **Phase 4b, `SKILL.md:313`** — current text: *"That three-agent set is a separate general-purpose adversarial pattern (CLAUDE.md `feedback_three_parallel_adversarial_agents`) for design/architecture stress-tests — it is NOT the PR-review step."*
   Replacement: *"That three-agent set (`architect-review` + `debugger` + `ai-engineer`) is a separate general-purpose adversarial pattern for design/architecture stress-tests, used elsewhere for pressure-testing a proposed design before it's built — it is NOT the PR-review step."*

**Reasoning.** Where the principle is still true (all three are), restating it inline makes the
sentence self-contained and correct regardless of what exists in any particular memory store —
memory is per-user, per-machine state, and a skill file shipped to other users/machines should
never depend on it being present. This also removes the present-tense defect (citing something
that doesn't exist) without waiting for a future rot event.

## 4. File-by-file change list

- `skills/agentic-loop/SKILL.md`:
  - Add stage-map paragraph under `## The phases` (§3.1).
  - Merge Phase 2.7 + Phase 2.8 into one guard-gated phase with sub-steps 2.7a/2.7b (§3.2).
  - Rewrite the Phase 4b override paragraph to remove self-demote language, add the two-move
    contract and the envelope-time auto-demote-authority carve-out (§3.3).
  - Rewrite Phase 13 to drop the scorecard/target-shape language; report raw `LOOP-STOP` counts and
    an unscored "decisions absorbed" list (§3.4).
  - Add one sentence to `## Context-window persistence` about the single-loop-per-directory
    invariant, pointing at `coderails:using-git-worktrees` (§3.6).
  - Replace the three named-memory citations in Phase 9 (×2) and Phase 4b (×1) with inline prose
    (§3.7).
- `AGENTS.md`: append one new "Enforcement ceilings" bullet documenting the unenforced
  `model: sonnet` rule as deliberate (§3.5).
- `hooks/scripts/lib/agentic_loop_path.sh`: add one sentence to the header comment about the
  single-loop-per-directory invariant (§3.6).

**Out of scope for this spec (flagged, not fixed):** `docs/coderails-review.md`'s stale
`SKILL.md:209` / `SKILL.md:239,260` / `SKILL.md:207-260` line-number citations, which will drift
once the phase merge (§3.2) and stage-map addition (§3.1) change the file's line count. Carry this
as a follow-up task in the implementation plan.

## 5. Verification plan

- `SKILL.md` still parses as valid frontmatter + markdown (no broken structure from the merge).
- Grep confirms zero remaining references to `feedback_wiki_ingest_and_lint_post_merge`,
  `feedback_parallel_wiki_agents`, or `feedback_three_parallel_adversarial_agents` in `SKILL.md` or
  `CLAUDE.md`.
- Grep confirms the Phase 2.7/2.8 guard sentence now appears exactly once in the merged phase.
- Manual read-through: the merged Phase 2.7 preserves both the `spec.md` and `plan.md` content
  verbatim (modulo the sub-step split), with no dropped detail.
- Manual read-through: Phase 4b no longer contains any language permitting orchestrator
  self-demotion of a clean-break compat finding.
- Manual read-through: Phase 13 contains no numeric scorecard or "target: approaching zero"
  language; it reports the two raw facts only.
- `AGENTS.md`'s new ceiling bullet renders correctly in the existing list (no markdown break).
- `hooks/scripts/lib/agentic_loop_path.sh`'s header comment reads correctly (comment syntax valid
  for the script's language).

## 6. Sequencing

This is implementation-plan territory (the next step after this spec), not decided here. All seven
decisions above are independent edits to the same file (plus two satellite files) and can be
sequenced as a single pass over `SKILL.md` followed by the two satellite edits.
