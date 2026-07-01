**For agentic workers:** REQUIRED SUB-SKILL: Use `coderails:subagent-driven-development` (recommended) or `coderails:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

# Agentic-Loop Hardening (7 Resolved Design Decisions) — Implementation Plan

**Goal:** Apply the seven resolved decisions from `docs/coderails/specs/2026-07-01-agentic-loop-hardening-design.md` to `skills/agentic-loop/SKILL.md`, `AGENTS.md`, and `hooks/scripts/lib/agentic_loop_path.sh` — pure markdown/prose/comment edits, no code, no tests.

**Architecture:** All seven changes are independent edits to the same file (`SKILL.md`, six of seven) plus two one-sentence satellite edits (`AGENTS.md`, `agentic_loop_path.sh`). No shared interfaces, no build step. Each task verifies by inspection (grep + manual read-through) per this spec's own "pure docs/config/prose" carve-out from TDD — there is no testable code here.

## Global Constraints

- Source spec: `docs/coderails/specs/2026-07-01-agentic-loop-hardening-design.md`. Every requirement traces there (§3.1–§3.7).
- All target files are prose/markdown/bash-comment. Verify by inspection (grep for exact added/removed text, confirm markdown structure/headers unbroken), not by running tests — per `coderails:writing-plans`'s own rule for pure docs/config/prose tasks.
- Do not renumber any phase. Every decision below is additive or in-place rewrite; phase numbers 2.5, 2.6, 3, 3a, 4, 4b, 5, 6, 9, 10, 11, 12, 13 stay exactly as they are today except the explicit 2.7/2.8 merge in Task 2.
- Line numbers below are as of `SKILL.md`/`AGENTS.md`/`agentic_loop_path.sh` at the start of this plan (commit `e72e578` era). If a prior task in this same execution has already shifted line numbers, use the grep pattern given (not the raw number) to relocate the target — every task includes both.
- `docs/coderails-review.md:160` cites `SKILL.md:209`, `SKILL.md:239,260`, `SKILL.md:207-260` — these WILL go stale once Tasks 1 and 2 land (stage-map addition + phase merge shift line counts). Task 7 below tracks this as a flagged follow-up, per the spec's explicit "out of scope for this spec" instruction — do NOT fix `coderails-review.md` in this plan; only confirm the drift and leave a note.

---

## Task 1 — Add stage-map overview paragraph to `## The phases` (§3.1)

**Files:** `skills/agentic-loop/SKILL.md:21-23` (insert after).

**Why:** A cold reader hits 19+ numbered phases with no shape to hold in mind first. A five-row stage-map table closes that without renumbering or heading changes (spec §3.1 decision).

**Current text at the insertion point (`SKILL.md:21-23`):**
```
## The phases

The phases below are sequential. Run them in order. Inside an authorised loop, phases 4-6 repeat per PR / per work-unit.
```

**Steps:**
- [ ] Insert a new paragraph immediately under the `## The phases` heading (line 21), BEFORE the existing "The phases below are sequential…" line (line 23). Do not alter the existing sequential-order line itself.
- [ ] The inserted text (verbatim, matches spec §3.1's decision table):

```markdown
Nineteen-plus numbered phases (−2 through 13, with lettered sub-phases) is too many to hold in mind cold. Group them into five stages before descending into per-phase detail:

| Stage | Phases |
|---|---|
| Setup | -2, -1, 0, 0.5 |
| Pre-flight | 1, 2, 2.5, 2.6, 2.7 |
| Build | 3, 3a, 4 |
| Review & Ship | 4b, 5, 6, 7&8 |
| Wrap-up | 9, 10, 11, 12, 13 |

```
- [ ] Note the Pre-flight row reads `2.7` not `2.7, 2.8` — Task 2 merges 2.8 into 2.7, so the stage-map must reflect the post-merge phase set, not the pre-merge one. Write the table with `2.7` only (do not write `2.7, 2.8` and then edit it again in Task 2).
- [ ] Commit.

**Verify-criteria:**
- `grep -n "Group them into five stages" skills/agentic-loop/SKILL.md` returns exactly one line, positioned between the `## The phases` heading and the "sequential. Run them in order" line (confirm via `grep -n -A2 "## The phases" skills/agentic-loop/SKILL.md`).
- The table has exactly 5 data rows (`grep -c '^| ' skills/agentic-loop/SKILL.md` includes the 2 header rows of this new table plus the pre-existing Phase 4b review-dimension table — spot check by reading the inserted block back, not by a blind count).
- The existing "The phases below are sequential. Run them in order..." line is unchanged and still immediately precedes `### Phase -2`.
- No other phase content in the file was touched by this task.

---

## Task 2 — Merge Phase 2.7 + Phase 2.8 into one guard-gated phase with 2.7a/2.7b (§3.2)

**Files:** `skills/agentic-loop/SKILL.md:195-216` (replace); `skills/agentic-loop/SKILL.md:163` (fix cross-reference); `skills/agentic-loop/SKILL.md` Task 1's stage-map (already written as `2.7` only, per Task 1 — no further edit needed there).

**Why:** Phase 2.7 (`SKILL.md:195-197`) and Phase 2.8 (`SKILL.md:208-210`) restate the identical `≥3 work-units or cross-unit dependency` guard as their opening sentence — one fact stated twice, at risk of drifting apart. Merge into a single Phase 2.7 with sub-steps 2.7a (the old 2.7 content, `spec.md`) and 2.7b (the old 2.8 content, `plan.md`), guard stated once. Phase 2.5 and Phase 2.6 are explicitly NOT touched (spec §3.2 — 6 inbound cross-references each, no duplication defect to fix).

**Reference audit (must account for all 9, not the 3 originally estimated) — confirmed by grep before editing:**

| # | Location | Text | Disposition |
|---|---|---|---|
| 1 | `SKILL.md:163` (end of Phase 2.5) | "...the loop can't run brainstorming itself (its steps block on a human — see Phase 2.7)..." | Update: still points at Phase 2.7 (number unchanged), no edit needed to the number itself — confirm it still resolves post-merge. |
| 2 | `SKILL.md:201` (inside old Phase 2.7 body) | "the design-fork decision and its flip-condition (Phase 2.5)" | Carries into new 2.7a verbatim — internal to the block being rewritten, not a separate fix. |
| 3 | `SKILL.md:202` (inside old Phase 2.7 body) | "the disposition decision(s) and any named blocker (Phase 2.6)" | Carries into new 2.7a verbatim. |
| 4 | `SKILL.md:204` (inside old Phase 2.7 body) | "the detailed decomposition is Phase 2.8's plan" | Becomes "Phase 2.7b's plan" in the merged text (2.8 no longer exists as a standalone number). |
| 5 | `SKILL.md:243` (Phase 3 task list, disposition bullet) | "the `clean-break`/`preserve-compat` decision from Phase 2.6" | Unaffected — Phase 2.6 untouched, no edit. |
| 6 | `SKILL.md:268` (Phase 3a, disposition bullet) | "the `clean-break`/`preserve-compat` decision from Phase 2.6" | Unaffected — Phase 2.6 untouched, no edit. |
| 7 | `SKILL.md:428` (`## Context-window persistence`, lifecycle bullet) | "Spec A's disposition fields" | Unaffected — refers to Phase 2.6's disposition fields via the informal name "Spec A"; not a phase-number reference, no edit. |
| 8 | `SKILL.md:195` (Phase 2.7 heading itself) | Self-reference (the phase being renamed) | Rewritten as part of this task (not an inbound reference to preserve). |
| 9 | `SKILL.md:208` (Phase 2.8 heading itself) | Self-reference (the phase being removed) | Removed as part of this task (not an inbound reference to preserve — its number ceases to exist, folded into 2.7b). |

Net: of the 9 occurrences, only #1 and #4 are true *inbound* references from elsewhere in the file that need a text check/edit; #2, #3 travel with the block being rewritten; #5, #6, #7 are references to Phase 2.6 (untouched) and require no change; #8, #9 are the phase's own headings being merged, not inbound references. This matches the spec's "9 inbound cross-references, not 3" finding while confirming only one (#4) needs an actual number/word change beyond the merge itself.

**Current text to replace (`SKILL.md:195-216`, verify with `grep -n "### Phase 2.7" skills/agentic-loop/SKILL.md` to confirm the start line before editing):**
```
### Phase 2.7 — Commit the resolved design to a durable `spec.md`

This phase fires ONLY when the loop has **≥3 work-units or a cross-unit dependency** — the same line Phase 3 draws to choose `TeamCreate` over a single agent. A 1–2-unit fix that Phase 3 routes to a single agent needs no separate design docs: the envelope (Phase 0) + `progress.json` + the one self-contained task description already carry everything. If the loop is below that threshold, skip 2.7 and 2.8 entirely.

When it fires, write a durable `spec.md` to the loop-state dir — the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`, run at Phase -2), next to `progress.json`, outside the code repo, **not committed** (loop state, not a PR deliverable). This is a **commit of design the loop has already resolved**, not interactive brainstorming — a loop cannot brainstorm with itself; the forks were closed at 2.5 and 2.6. Record:
- the authorisation envelope verbatim (Phase 0);
- the design-fork decision and its flip-condition (Phase 2.5);
- the disposition decision(s) and any named blocker (Phase 2.6);
- the success criteria — what "done" means for the whole loop;
- the high-level work-unit boundaries (the detailed decomposition is Phase 2.8's plan).

The `spec.md` is loop state, keyed to this orchestrator's run, exactly like `progress.json` — not a shareable design record. When ad-hoc loop work genuinely needs handing to a human, that is what `/coderails:handoff` is for.

### Phase 2.8 — Write the durable `plan.md` via `/coderails:writing-plans`

This phase fires under the same complexity guard as 2.7 (**≥3 work-units or a cross-unit dependency**). When it fires, produce a durable `plan.md` in the loop-state dir (next to `spec.md` and `progress.json`, outside the repo, not committed) by invoking **`/coderails:writing-plans`** — the same one-line skill-reference idiom Phase 3/3a use for `/coderails:test-driven-development`.

`plan.md` is the **static SSOT** for the decomposition; `progress.json` is the **dynamic position** against it. The plan is **consumed, not write-only**, in both directions:
- **Phase 3 builds its task list directly from `plan.md`** — the TeamCreate task list and the Phase 3/3a worker descriptions derive from the plan's tasks, so the two are consistent by construction rather than re-derived from conversation.
- **After any compaction the orchestrator re-reads `plan.md` to recover *scope* (what to build)** the same way it re-reads `progress.json` to recover *position* (where we are).

(This is the one place the `plan.md`↔`progress.json` relationship is named. It is stated here, standalone, on purpose — the `## Context-window persistence` section, which describes `progress.json`, is not edited.)
```

**Replacement text:**
```
### Phase 2.7 — Commit the resolved design to durable `spec.md` and `plan.md`

This phase fires ONLY when the loop has **≥3 work-units or a cross-unit dependency** — the same line Phase 3 draws to choose `TeamCreate` over a single agent. A 1–2-unit fix that Phase 3 routes to a single agent needs no separate design docs: the envelope (Phase 0) + `progress.json` + the one self-contained task description already carry everything. If the loop is below that threshold, skip 2.7 (both sub-steps) entirely.

When it fires, run both sub-steps in order:

**2.7a — write `spec.md`.** Write a durable `spec.md` to the loop-state dir — the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`, run at Phase -2), next to `progress.json`, outside the code repo, **not committed** (loop state, not a PR deliverable). This is a **commit of design the loop has already resolved**, not interactive brainstorming — a loop cannot brainstorm with itself; the forks were closed at 2.5 and 2.6. Record:
- the authorisation envelope verbatim (Phase 0);
- the design-fork decision and its flip-condition (Phase 2.5);
- the disposition decision(s) and any named blocker (Phase 2.6);
- the success criteria — what "done" means for the whole loop;
- the high-level work-unit boundaries (the detailed decomposition is Phase 2.7b's plan).

The `spec.md` is loop state, keyed to this orchestrator's run, exactly like `progress.json` — not a shareable design record. When ad-hoc loop work genuinely needs handing to a human, that is what `/coderails:handoff` is for.

**2.7b — write `plan.md` via `/coderails:writing-plans`.** Produce a durable `plan.md` in the loop-state dir (next to `spec.md` and `progress.json`, outside the repo, not committed) by invoking **`/coderails:writing-plans`** — the same one-line skill-reference idiom Phase 3/3a use for `/coderails:test-driven-development`.

`plan.md` is the **static SSOT** for the decomposition; `progress.json` is the **dynamic position** against it. The plan is **consumed, not write-only**, in both directions:
- **Phase 3 builds its task list directly from `plan.md`** — the TeamCreate task list and the Phase 3/3a worker descriptions derive from the plan's tasks, so the two are consistent by construction rather than re-derived from conversation.
- **After any compaction the orchestrator re-reads `plan.md` to recover *scope* (what to build)** the same way it re-reads `progress.json` to recover *position* (where we are).

(This is the one place the `plan.md`↔`progress.json` relationship is named. It is stated here, standalone, on purpose — the `## Context-window persistence` section, which describes `progress.json`, is not edited.)
```

**Steps:**
- [ ] Confirm the exact current line range with `grep -n "### Phase 2.7\|### Phase 2.8\|### Phase 3 —" skills/agentic-loop/SKILL.md` (three matches; the block to replace runs from the `### Phase 2.7` line up to but not including the `### Phase 3 —` line).
- [ ] Replace the block (old Phase 2.7 + old Phase 2.8, in full) with the merged replacement text above.
- [ ] Confirm `SKILL.md:163` ("...see Phase 2.7...") still reads correctly post-merge — no edit needed since the number `2.7` still exists and still refers to "committing the resolved design," but re-read the sentence in context to confirm it doesn't implicitly assume the old single-artifact (`spec.md`-only) framing. If it does, adjust only that one clause, not the whole sentence.
- [ ] Commit.

**Verify-criteria:**
- `grep -c "≥3 work-units or a cross-unit dependency" skills/agentic-loop/SKILL.md` — this exact guard phrase must appear exactly once inside the new Phase 2.7 (it appeared twice before the merge; confirm the total count across the merged block dropped from 2 to 1). Note: Phase 3 (`SKILL.md` current line 218) also uses a similar phrase ("3+ PRs or any cross-step dependency") — grep the guard's EXACT wording `≥3 work-units or a cross-unit dependency` (with the `≥` and "work-units", not Phase 3's paraphrase) to avoid a false match.
- `grep -n "### Phase 2.8"` returns zero matches — the heading no longer exists.
- `grep -n "### Phase 2.7"` returns exactly one match.
- `grep -n "2.7a\|2.7b"` each return at least one match, inside the merged phase.
- Manual read-through: the merged Phase 2.7 preserves both the original `spec.md` content (2.7a) and `plan.md` content (2.7b) verbatim, modulo the sub-step split and the one "Phase 2.8's plan" → "Phase 2.7b's plan" wording fix.
- `grep -n "Phase 2.8" skills/agentic-loop/SKILL.md` returns zero matches anywhere in the file (confirms no dangling reference to the removed number survives).
- The file still parses as valid markdown: every `###` heading has non-empty body text before the next heading (spot-check by reading `SKILL.md` from the new Phase 2.7 through Phase 3's opening line).

---

## Task 3 — Rewrite Phase 4b's "Override path" to remove self-demote power (§3.3)

**Files:** `skills/agentic-loop/SKILL.md` — the sentence starting "**Override path:**" inside the "Clean-break gate" paragraph (currently `SKILL.md:311`; relocate via `grep -n "Override path:"` since Task 1/2 shift line numbers above this point).

**Why:** The orchestrator can currently self-demote a clean-break `MERGE-BLOCKER` finding to a logged note by writing free-text "reviewed, not compat — `<reason>`" — the same party whose worker shipped the shortcut grading its own override. Spec §3.3 removes this power entirely; the two remaining moves are fix-it or hard-stop-to-human.

**Current text (locate via `grep -n "Override path:" skills/agentic-loop/SKILL.md`, full paragraph is the "Clean-break gate" paragraph beginning "**Clean-break gate (when the unit's disposition is `clean-break`).**"):**
```
**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not the report-only suggestions row 6 produces by default. **Override path:** the orchestrator may record "reviewed, not compat — `<reason>`" against a finding to demote a false-positive to a logged note, so a reviewer misfire degrades to a note, never a wall. The why: clean-break enforced by worker self-assertion alone is self-attestation by the party with motive to keep the path; the independent reviewer carries the gate. Past failure: the original shim rework happened because no independent check hunted the compat the author had rationalised as necessary.
```

**Replacement text:**
```
**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not the report-only suggestions row 6 produces by default. **The orchestrator cannot downgrade this finding unilaterally.** Its only two moves: (a) actually fix it — remove the compat path, or (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason. If a fully-unattended envelope genuinely cannot tolerate ever hard-stopping at this gate, the human must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never something the orchestrator grants itself mid-run. The why: clean-break enforced by worker self-assertion alone is self-attestation by the party with motive to keep the path — and letting that SAME party (the orchestrator) also grade the independent reviewer's finding reintroduces the identical loophole one level up. Past failure: the original shim rework happened because no independent check hunted the compat the author had rationalised as necessary.
```

**Steps:**
- [ ] Locate the exact paragraph via `grep -n "Override path:" skills/agentic-loop/SKILL.md`.
- [ ] Replace the full paragraph (verbatim match above) with the replacement text.
- [ ] Commit.

**Verify-criteria:**
- `grep -n "Override path:" skills/agentic-loop/SKILL.md` returns zero matches.
- `grep -n "reviewed, not compat" skills/agentic-loop/SKILL.md` returns zero matches.
- `grep -n "cannot downgrade this finding unilaterally" skills/agentic-loop/SKILL.md` returns exactly one match.
- `grep -n "at envelope-authorisation time" skills/agentic-loop/SKILL.md` returns exactly one match, confirming the Phase-0-only carve-out is present.
- Manual read-through: no sentence anywhere in the Phase 4b section permits the orchestrator to unilaterally demote a clean-break compat finding mid-run.

---

## Task 4 — Rewrite Phase 13 to drop the scorecard; add raw LOOP-STOP counts + decisions-absorbed list (§3.4)

**Files:** `skills/agentic-loop/SKILL.md` — the `### Phase 13` section (currently `SKILL.md:408-417`; relocate via `grep -n "### Phase 13"`).

**Why:** "Human turns approaching zero" reads identically whether the orchestrator was well-calibrated or silently suppressed asks it should have made — the metric can't distinguish a genuinely quiet loop from one that hid its stalls. Spec §3.4 drops the numeric scorecard and reports two raw, unscored facts instead: LOOP-STOP category counts, and a flat "decisions absorbed" list.

**Current text (locate via `grep -n "### Phase 13" skills/agentic-loop/SKILL.md`, runs to the `## Context-window persistence` heading):**
```
### Phase 13 — Confirm the factory actually ran (terminal self-audit)

At the end of the loop, before declaring done, the orchestrator audits its own autonomy from the `progress.json` counters and reports:
- **Human turns inside the envelope** — how many times the human had to intervene on work that was already authorised. Target: approaching zero. These are stalls the factory should have absorbed.
- **Genuine gates vs avoidable stalls** — split those human turns into (a) legitimate approval-gates and hard-stops (the factory working as designed) and (b) avoidable stalls: re-asks inside scope, orchestrator hook-blocks, design forks litigated live, re-orientation prompts. Only (b) counts against the factory.
- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the metric reads "factory clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.
- **LOOP-STOP declarations by category** — the per-category counts of this loop's `LOOP-STOP` declarations (`progress.json` `loop_stop_counts`). Report the breakdown; a high `awaiting-input` count is a primary avoidable-stall signal — each one is a yield the factory should ideally have absorbed. This is the audit that keeps the anti-stall guard's honest boundary (a model can rubber-stamp `awaiting-input`) from hiding stalls behind a valid-looking tag.

This is the factory's own KPI — "are we a factory yet?" measured per run, not asserted. Target shape: zero avoidable stalls and one approval-gate; anything else names exactly what to fix. The avoidable-stall list is the input to the next iteration of this skill.
```

**Replacement text:**
```
### Phase 13 — Confirm the factory actually ran (terminal self-audit)

At the end of the loop, before declaring done, the orchestrator audits its own autonomy from the `progress.json` counters and reports two raw, unscored facts — no numeric pass/fail scorecard, no "target: approaching zero" framing. The human is the only party positioned to judge "should I have been asked about that?"; hand them the raw list rather than have the process pre-grade itself:

- **`LOOP-STOP` category counts, broken down by type** — the per-category counts of this loop's `LOOP-STOP` declarations (`progress.json` `loop_stop_counts`: `hard-stop`, `approval-gate`, `awaiting-input`, `complete`). Report the raw breakdown with no verdict attached — already artifact-backed from the declared stops, hard to fake. A high `awaiting-input` count is worth the human's attention, but this section states the count, not a judgement on it.
- **Decisions absorbed** — a flat, unscored list of in-scope decisions the loop made autonomously without asking (e.g. a Phase 2.5 design-fork auto-adopted, a Phase 2.6 disposition defaulted to clean-break, a Phase 6 in-scope action taken without a check-in). No self-justification text attached to each entry, no automated "this looks calibrated" stamp — just what was decided and where (phase/work-unit).

Also report, unscored, alongside the two facts above:
- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the report reads "clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.

This is the factory's own audit — raw facts for the human to judge, not a self-issued verdict. A clean-looking scorecard is more dangerous than an honest unscored list because it is more likely to be trusted uncritically; the two facts above can only be gamed by omission, and omission from a flat list is easier for a human to spot than a fabricated pass on a scorecard.
```

**Steps:**
- [ ] Locate the exact section via `grep -n "### Phase 13" skills/agentic-loop/SKILL.md` and confirm the end boundary via `grep -n "## Context-window persistence" skills/agentic-loop/SKILL.md`.
- [ ] Replace the full section (verbatim match above, from `### Phase 13` heading through the final "input to the next iteration" sentence) with the replacement text.
- [ ] Commit.

**Verify-criteria:**
- `grep -n "Target: approaching zero" skills/agentic-loop/SKILL.md` returns zero matches.
- `grep -n "Target shape: zero avoidable stalls" skills/agentic-loop/SKILL.md` returns zero matches.
- `grep -n "Human turns inside the envelope" skills/agentic-loop/SKILL.md` returns zero matches (the standalone human-turns-as-KPI bullet is gone; human turns are no longer the top-line metric).
- `grep -n "Decisions absorbed" skills/agentic-loop/SKILL.md` returns exactly one match.
- `grep -n "LOOP-STOP.*category counts, broken down by type\|category counts, broken down by type" skills/agentic-loop/SKILL.md` returns at least one match.
- Manual read-through: Phase 13 contains no numeric scorecard, no "target: approaching zero" or "target shape" language anywhere; it reports the `LOOP-STOP` counts and the decisions-absorbed list as the two headline unscored facts, with artifacts-produced and disposition-violations retained as supporting facts (per spec §3.4, which does not ask for these two to be removed — only the human-turns scorecard and target-shape framing).
- Confirm the section still ends cleanly before `## Context-window persistence` (no orphaned heading or dangling paragraph).

---

## Task 5 — Add `AGENTS.md` "Enforcement ceilings" bullet documenting `model: sonnet` as deliberately advisory (§3.5)

**Files:** `AGENTS.md:105-143` (insert new bullet inside the "Enforcement ceilings" list, currently ending at line 142 before the "Hook script conventions" subsection at line 144).

**Why:** `SKILL.md` asserts `model: sonnet` for spawned workers ~6 times but no hook enforces it (`hooks/hooks.json` and `hooks/scripts/*.sh` only match `Bash`/`Write`/`Edit`/`MultiEdit` events, nothing for `Agent`/`Task` spawns). Spec §3.5 keeps this advisory-only and documents the decision as deliberate so it isn't re-opened as a gap.

**Current text at the insertion point (`AGENTS.md:133-143`, the last existing bullet in the "Enforcement ceilings" list, immediately before the "Hook script conventions" subsection heading):**
```
- **`/coderails:post-review` validates summary structure, not provenance.** The
  review artifact gate proves an auditable, SHA-bound artifact exists on the PR;
  it does not prove the review was substantive. `/post-review` validates that the
  summary body satisfies the grammar (headings + bullets or `## No findings`) —
  it cannot verify that the underlying review effort matched the grammar's weight.
  The gate is auditable (the artifact is a public GitHub comment), not
  cryptographic. Follow-up note: the `review-pr` arm of `enforce_pr_workflow` is
  expected to demote from a block to a nudge once the artifact gate is live and
  verified in practice — ordering constraint: never before, or a window opens
  where neither gate is active.

**Hook script conventions** (follow these when editing or adding a script):
```

**Steps:**
- [ ] Locate the insertion point via `grep -n "where neither gate is active." AGENTS.md` (the last line of the last existing "Enforcement ceilings" bullet) and confirm the next non-blank line is `**Hook script conventions**` via `grep -n "Hook script conventions" AGENTS.md`.
- [ ] Insert a new bullet immediately after "...where neither gate is active." and before the blank line that precedes "**Hook script conventions**". Verbatim text (matches spec §3.5's decision):

```markdown
- **`model: sonnet` for spawned workers is advisory, not hook-enforced.** `agentic-loop`
  SKILL.md asserts it ~6 times (Phases 2, 2.5, 3, 3a, 10) but no hook gates `Agent`/`Task` spawn
  calls on the requested model — `hooks/hooks.json` and `hooks/scripts/*.sh` only match `Bash`
  and `Write`/`Edit`/`MultiEdit` events. This is deliberate: the rule's purpose is cost control,
  not correctness — an opus worker still produces a valid, fully-gated PR; nothing load-bearing
  breaks if it fires. Phase 2.5 also sanctions a legitimate opus-escalation exception ("escalate
  the synthesis to opus only if the tradeoff is genuinely close") that a blunt model-gate hook
  cannot distinguish from a disallowed worker spawn without a self-reported carve-out flag —
  which reintroduces the same trust-the-agent problem one level down.
```
- [ ] Commit.

**Verify-criteria:**
- `grep -n "model: sonnet.*for spawned workers is advisory" AGENTS.md` returns exactly one match.
- `grep -n "^\*\*Hook script conventions\*\*" AGENTS.md` still returns exactly one match, and the new bullet sits between the last pre-existing "Enforcement ceilings" bullet and this heading (confirm via `grep -n -B2 "Hook script conventions" AGENTS.md`).
- The bullet renders as valid markdown: starts with `- **`, no broken list continuation (each wrapped line indented consistently with the sibling bullets above it, matching the existing list's 2-space continuation indent).
- No other content in `AGENTS.md` is touched by this task.

---

## Task 6 — Add single-loop-per-directory invariant to `SKILL.md`'s "Context-window persistence" section AND `agentic_loop_path.sh`'s header comment (§3.6)

**Files:** `skills/agentic-loop/SKILL.md` — end of `## Context-window persistence` section (currently ends `SKILL.md:435`, immediately before the blank line preceding `Never artificially truncate...` at line 437 — relocate via `grep -n "## Context-window persistence"` and read to the next `##` heading to confirm exact end); `hooks/scripts/lib/agentic_loop_path.sh:1-16` (header comment block).

**Why:** `progress.json` is keyed only by project working directory, not by session. Two `agentic-loop` sessions in the same directory collide — verified live during the design session (a leftover `completed` `progress.json` blocked a new session's Stop hook until manually re-stubbed). `loop_state_guard.sh` already fails closed on session mismatch (the dangerous silent-data-loss case is handled); what's missing is that the single-loop invariant itself was never written down. Spec §3.6 adds one sentence in each of the two files, pointing at `coderails:using-git-worktrees` as the resolution — no new locking machinery.

**Current text in `SKILL.md` (locate via `grep -n "Honest boundary" skills/agentic-loop/SKILL.md`, this is the paragraph immediately before the one ending in "...the artifact wasn't being maintained..."):**
```
**Honest boundary.** The guard guarantees the file *exists* and is *this session's* — not that its content is faithfully maintained (the same limit `check_verify_loop.sh` documents). Keeping the file current is still your job; the guard only catches its absence.

After any compaction, drift, or "wait, where are we" moment, the orchestrator RE-READS `progress.json` — never the conversation — to re-orient. If the user ever has to remind the loop that it's mid-loop, the artifact wasn't being maintained. Git remains the authoritative checkpoint for code (commit all in-progress work before compaction); `progress.json` is the authoritative checkpoint for loop position.
```

**Steps:**
- [ ] In `SKILL.md`, locate the `## Context-window persistence` section via `grep -n "## Context-window persistence"` and confirm its last paragraph via `grep -n "authoritative checkpoint for loop position"`.
- [ ] Insert one new sentence/paragraph immediately after the "...`progress.json` is the authoritative checkpoint for loop position." sentence (still inside the `## Context-window persistence` section, before the next `##` heading, `## Stop conditions for the loop`). Verbatim text:

```markdown

**Single loop per directory.** `progress.json` is keyed only by project working directory (Phase -2), not by session — two `agentic-loop` sessions running concurrently in the same checkout will race for ownership of the same file, last-writer-wins. `loop_state_guard.sh` fails closed on a session mismatch (the dangerous silent-data-loss case), but does not prevent this race. Isolate concurrent loops via separate git worktrees (`coderails:using-git-worktrees`) — one loop per working directory, not locking machinery.
```
- [ ] In `hooks/scripts/lib/agentic_loop_path.sh`, add one sentence to the header comment block (lines 1-16), after the existing "Usage" / "Path" documentation (i.e. append after line 16, the last comment line, before the blank line that precedes the executable code). Verbatim text:

```bash
#
# Single-loop-per-directory invariant: this path is keyed on cwd only, not session,
# so two concurrent agentic-loop sessions in the same directory will race for
# ownership of the same progress.json (last-writer-wins). Isolate concurrent loops
# via separate git worktrees (coderails:using-git-worktrees) — this script does not
# lock.
```
- [ ] Commit both files together (they document the same invariant from the two sides the spec names).

**Verify-criteria:**
- `grep -n "Single loop per directory" skills/agentic-loop/SKILL.md` returns exactly one match, located inside `## Context-window persistence` (confirm via `grep -n -B1 "## Stop conditions for the loop" skills/agentic-loop/SKILL.md` — the new paragraph's closing line should be the last content before that heading).
- `grep -n "coderails:using-git-worktrees" skills/agentic-loop/SKILL.md` returns at least one match (may already appear elsewhere in the file from prior content — confirm the NEW occurrence is in the inserted paragraph specifically).
- `grep -n "Single-loop-per-directory invariant" hooks/scripts/lib/agentic_loop_path.sh` returns exactly one match.
- `bash hooks/scripts/lib/agentic_loop_path.sh` still runs and prints a path (comment-only change must not break the script) — run it and confirm output matches the pre-existing `<base>/<slug>/progress.json` format.
- The added bash comment lines all start with `#` (valid comment syntax) and sit within the header block, before the first executable line (`cwd="${1:-$PWD}"`).

---

## Task 7 — Replace 3 stale memory-file citations in `SKILL.md` with inline prose (§3.7)

**Files:** `skills/agentic-loop/SKILL.md` — Phase 9 (two citations, locate via `grep -n "feedback_wiki_ingest_and_lint_post_merge\|feedback_parallel_wiki_agents"`), Phase 4b (one citation, locate via `grep -n "feedback_three_parallel_adversarial_agents"`).

**Why:** `SKILL.md` cites three feedback-memory files by name as load-bearing justification. None of the three exist under those names (or any plausible variant) in `/Users/harrison/.claude/projects/-Users-harrison-Github-coderails/memory/` right now (verified: 14 files in that directory, none matching) — a present-tense broken citation, not a future-rot risk. Memory is per-user, per-machine state; a skill file should never depend on it being present. Restate each principle inline instead.

**Verification of current staleness (run before editing, confirms the spec's claim still holds):**
```bash
ls /Users/harrison/.claude/projects/-Users-harrison-Github-coderails/memory/*.md | xargs -n1 basename
grep -rn "feedback_wiki_ingest_and_lint_post_merge\|feedback_parallel_wiki_agents\|feedback_three_parallel_adversarial_agents" /Users/harrison/.claude/CLAUDE.md /Users/harrison/.claude/projects/-Users-harrison-Github-coderails/memory/
```
Expect zero matches in both — confirming the three citations are dead before removing them.

**Replacement 1 — Phase 9, first citation (locate via `grep -n "feedback_wiki_ingest_and_lint_post_merge"`):**

Current: `Per memory \`feedback_wiki_ingest_and_lint_post_merge\`, lint must always pair with ingest; running one without the other is incomplete.`

Replacement: `Lint must always pair with ingest — running one without the other leaves the wiki either unverified (ingest with no lint) or unrefreshed (lint with no ingest); treat the two as one step, not two optional ones.`

**Replacement 2 — Phase 9, second citation (locate via `grep -n "feedback_parallel_wiki_agents"`):**

Current: `This matches memory \`feedback_parallel_wiki_agents\` (cluster together, don't fragment).`

Replacement: `Clustering related updates into one pass keeps the wiki's per-topic pages coherent; running one wiki agent per PR instead fragments a single theme across many small, redundant edits.`

**Replacement 3 — Phase 4b (locate via `grep -n "feedback_three_parallel_adversarial_agents"`):**

Current: `That three-agent set is a separate general-purpose adversarial pattern (CLAUDE.md \`feedback_three_parallel_adversarial_agents\`) for design/architecture stress-tests — it is NOT the PR-review step.`

Replacement: `That three-agent set (\`architect-review\` + \`debugger\` + \`ai-engineer\`) is a separate general-purpose adversarial pattern for design/architecture stress-tests, used elsewhere for pressure-testing a proposed design before it's built — it is NOT the PR-review step.`

**Steps:**
- [ ] Run the staleness-verification commands above; confirm zero matches in both the memory dir listing and the grep (if either citation IS found to exist by the time this task runs, STOP and report — do not blindly remove a citation that turned out to be live).
- [ ] Locate and replace Phase 9's first citation sentence (verbatim swap, no other change to the surrounding sentence).
- [ ] Locate and replace Phase 9's second citation sentence (verbatim swap).
- [ ] Locate and replace Phase 4b's citation sentence (verbatim swap).
- [ ] Commit all three replacements together (one logical change: de-citation).

**Verify-criteria:**
- `grep -n "feedback_wiki_ingest_and_lint_post_merge\|feedback_parallel_wiki_agents\|feedback_three_parallel_adversarial_agents" skills/agentic-loop/SKILL.md` returns zero matches.
- `grep -rn "feedback_wiki_ingest_and_lint_post_merge\|feedback_parallel_wiki_agents\|feedback_three_parallel_adversarial_agents" /Users/harrison/.claude/CLAUDE.md` returns zero matches (should already be zero — this task does not edit CLAUDE.md, only confirms no lingering citation there needs a companion fix).
- `grep -n "Lint must always pair with ingest — running one without the other leaves the wiki" skills/agentic-loop/SKILL.md` returns exactly one match.
- `grep -n "Clustering related updates into one pass keeps the wiki" skills/agentic-loop/SKILL.md` returns exactly one match.
- `grep -n "architect-review.*+.*debugger.*+.*ai-engineer.*is a separate general-purpose adversarial pattern" skills/agentic-loop/SKILL.md` returns exactly one match.
- Manual read-through: all three replacement sentences read as self-contained prose with no dangling reference to an external file.

---

## Task 8 — Flag `docs/coderails-review.md` line-citation drift as a follow-up note (out of scope for this plan, confirm only)

**Files:** none modified. Read-only confirmation task.

**Why:** The spec (§3.2 follow-up, §4 "out of scope") explicitly flags that `docs/coderails-review.md:160` cites `SKILL.md:209`, `SKILL.md:239,260`, and `SKILL.md:207-260` as evidence for a prior correction, and that Tasks 1–2 of this plan (stage-map insertion + phase merge) will shift `SKILL.md`'s line count, making those citations stale. The spec is explicit: do NOT fix `coderails-review.md` in this plan — only carry the flag forward.

**Steps:**
- [ ] After Tasks 1–7 are complete, run `grep -n "SKILL.md:209\|SKILL.md:239,260\|SKILL.md:207-260" docs/coderails-review.md` to reconfirm the citation still exists at line 160.
- [ ] Run `grep -n "coderails:writing-plans\|coderails:test-driven-development" skills/agentic-loop/SKILL.md` and manually compare the new line numbers against the old ones (`209`, `239`, `260`) to confirm they have in fact shifted (expected, given Task 1 inserted a table and Task 2 changed the 2.7/2.8 boundary).
- [ ] Do NOT edit `docs/coderails-review.md`. Report the new (now-correct) line numbers in the task's completion message as a note for a future, separate task — this plan's scope ends at confirming the drift exists, per the spec's explicit exclusion.

**Verify-criteria:**
- `docs/coderails-review.md` has zero diff (`git diff docs/coderails-review.md` empty) after this task — confirms nothing was edited.
- The completion report states the old cited line numbers (209, 239, 260, 207-260) and the new actual line numbers for the same content, demonstrating the drift is real and quantified, not just asserted.

---

## Self-review gate (per `coderails:writing-plans`)

**1. Spec coverage** — every spec requirement (§3.1–§3.7) maps to a task:
- §3.1 (stage-map) → Task 1
- §3.2 (2.7/2.8 merge + 9-reference audit) → Task 2
- §3.3 (remove self-demote) → Task 3
- §3.4 (drop scorecard, add raw facts) → Task 4
- §3.5 (`model: sonnet` advisory doc) → Task 5
- §3.6 (single-loop invariant, two files) → Task 6
- §3.7 (three stale citations) → Task 7
- §3.2's follow-up / §4's explicit out-of-scope flag (`coderails-review.md` drift) → Task 8
No gaps found.

**2. Placeholder scan** — no "TBD", "implement later", or "similar to Task N" phrasing anywhere above; every task shows the exact current text and the exact replacement text verbatim, not a description of the change.

**3. Type/reference consistency** — Task 1's stage-map deliberately writes `2.7` (not `2.7, 2.8`) in the Pre-flight row, anticipating Task 2's merge; Task 2's replacement text uses "Phase 2.7b's plan" (not the pre-merge "Phase 2.8's plan") consistently; Task 2's reference audit table cross-checks all 9 occurrences found by grep, reconciling the spec's "9, not 3" finding against what actually needs a text change (only #4) versus what merely travels with the rewritten block (#2, #3) or is unaffected (#5, #6, #7) or is the heading itself being merged (#8, #9). No naming drift between tasks.

**4. Engineering principles** — every task is a like-for-like prose/comment replacement with no speculative abstraction; Task 6 explicitly rejects building locking machinery (YAGNI, per the spec's own rejected-alternatives analysis) in favour of a one-sentence invariant + pointer to existing tooling; no task introduces a new file, script, or mechanism beyond what the spec names (SSOT — the spec is the sole source of the seven decisions, and no task adds an eighth).

---

## Planning-sequence stress-test (Pre-Parade / Premortem / Red Team)

Run per `coderails:writing-plans`'s required gate, against this plan and its source spec.

**Pre-Parade — success conditions.** This plan succeeds if: (a) all 7 spec decisions are reflected in `SKILL.md`/`AGENTS.md`/`agentic_loop_path.sh` with the exact text the spec specifies (not a paraphrase that drifts from the resolved decision); (b) every grep-based verify-criterion in Tasks 1–8 passes after execution; (c) no phase number other than the deliberate 2.7/2.8 merge changes, so no OTHER inbound reference (Phase 3, 3a, 4, 4b, 5, 6, 9, 10, 11, 12, 13, or the Context-window-persistence section) silently breaks; (d) `docs/coderails-review.md` is confirmed stale but left untouched, matching the spec's explicit scope boundary; (e) a fresh read-through of the merged `SKILL.md` reads as one coherent document, not a patchwork of seven independent edits with inconsistent voice.

**Premortem — assume this plan has already failed six months from now. Why?**
1. **Task 2's reference audit missed a real dangling reference.** The 9-occurrence table was built from a single grep pass at plan-writing time; if `SKILL.md` changed between spec-writing and plan-execution, a 10th reference could exist. *Mitigation already in the plan:* Task 2's first step re-runs the locating greps at execution time (not relying on the plan's cached line numbers), and the task's own verify-criteria include a blanket `grep -n "Phase 2.8"` returning zero — this would catch ANY leftover reference to the removed number, not just the ones enumerated in the table, closing the exact gap this premortem raises.
2. **Task 1's stage-map, written to already assume the Task 2 merge, gets executed out of order (Task 2 skipped or done later) leaving the stage-map's `2.7` row inconsistent with a still-separate 2.7/2.8 in the file.** *Mitigation:* the plan sequences Task 1 before Task 2 explicitly and both are in the same file; a worker executing tasks in written order never hits this. Flagged as a REQUIRED-ORDER dependency: Task 1 must not be verified as "fully correct" in isolation before Task 2 lands — added as an explicit note below rather than silently trusted.
3. **Task 4's Phase 13 rewrite drops "Human turns inside the envelope" as a standalone bullet per the spec, but the spec's own file-by-file change list (§4) doesn't explicitly say to remove "Genuine gates vs avoidable stalls" — a worker might over-delete and remove that supporting bullet too, or under-delete and leave the human-turns bullet in duplicate form.** *Mitigation:* Task 4 gives the full current text and full replacement text verbatim (not a diff description), so there is no ambiguity about what survives (artifacts-produced and disposition-violations bullets are explicitly kept) versus what's cut (human-turns-as-KPI and genuine-gates-split bullets, folded conceptually into the "decisions absorbed" list instead). This is a deliberate plan-level interpretation of spec §3.4, which names "drop the scorecard" and "report two raw facts" but doesn't itemize what happens to the genuine-gates-split bullet specifically — recorded here as an intentional plan refinement, not an oversight: the genuine-gates-split bullet was a subjective self-grading step (which turns were "genuine" vs "avoidable"), which is exactly the self-grading the spec's Goodhart's-law argument rejects, so it is folded into the "decisions absorbed" flat list rather than kept as a separate scored split.
4. **Task 6's two-file edit (SKILL.md + agentic_loop_path.sh) is committed as one task; if a worker splits it into two commits, the "confirm both files together" instruction is lost.** *Mitigation:* Task 6's steps explicitly say "Commit both files together" as the last step — a worker following the plan literally does not split it. Low residual risk, accepted.
5. **Task 8 is read-only but a worker unfamiliar with the spec's "out of scope" framing might "fix" `coderails-review.md` anyway, since fixing a stale citation feels like the obviously helpful move.** *Mitigation:* Task 8's verify-criteria explicitly checks `git diff docs/coderails-review.md` is empty — a worker who fixes it fails their own task's verify-criterion and must revert, self-correcting.

**Red Team — adversarial challenge.**
- *Challenge: "Why does this plan not just renumber the phases properly instead of this stage-map band-aid?"* — Rejected by the spec itself (§3.1), not re-litigated here: full renumbering was costed against the 9-reference audit (this plan's Task 2 confirms that count) plus the two now-stale `coderails-review.md` citations, and found disproportionate. This plan implements the spec's decision; re-opening the renumbering question is out of this plan's scope.
- *Challenge: "Task 4's Phase 13 rewrite still keeps artifacts-produced and disposition-violations as scored/structured facts — doesn't that reintroduce the same self-grading problem the spec objects to?"* — No: the spec's objection (§3.4) is specifically to a **pass/fail verdict** ("human turns approaching zero" as a target), not to reporting structured facts. Artifacts-produced and disposition-violations are already raw facts with an explicit audit-failure-vs-pass distinction (not a score) — they survive the spec's own test ("can only be gamed by omission, not by looking good"). No change needed to this plan's Task 4.
- *Challenge: "Task 3 removes the orchestrator's override power, but does any OTHER phase (Phase 5, Phase 6) grant a similar unilateral self-demote power that this plan misses, making the fix incomplete?"* — Checked: Phase 5 (disprove-the-premise) and Phase 6 (confirmation matching) don't grant demote power over an independent reviewer's finding — they're about the orchestrator's own confirmation cadence, not overriding another party's finding. Phase 4b is the only place a reviewer's finding can be self-demoted. No additional task needed.
- *Challenge: "Are Tasks 1–7 truly independent, or does execution order matter beyond the Task 1→2 ordering already flagged?"* — Tasks 3, 4, 5, 6, 7 touch disjoint regions of `SKILL.md` (Phase 4b, Phase 13, none, Context-window-persistence, Phase 9+4b citations respectively) and `AGENTS.md`/`agentic_loop_path.sh` — no other ordering constraint exists. Only Task 1 → Task 2 is a real sequencing dependency (flagged in Premortem #2 above); Task 7 touches Phase 4b's citation (a different sentence than Task 3's override-path paragraph) and Phase 9 (untouched by any other task) — confirmed disjoint from Task 3's edit region by line-range inspection during plan-writing.

**Findings folded back into the plan:** the Premortem's point 3 interpretation (fold "genuine gates vs avoidable stalls" into "decisions absorbed" rather than leaving a dangling scored bullet) is now recorded explicitly in Task 4's steps and this stress-test section, rather than left implicit. The Task 1→2 ordering dependency (Premortem #2) is recorded explicitly here as a REQUIRED-ORDER note for whoever executes this plan: **execute Task 1 before Task 2**, even though both are technically independent edits to the same file — because Task 1's table content assumes Task 2's merge has (or will imminently) happen. No new tasks were added by the stress-test; all three stages either confirmed an existing mitigation already present in the task steps/verify-criteria, or confirmed the finding was already resolved by the spec's own reasoning (Red Team point 1, 2) or out of scope (Red Team's renumbering challenge).
