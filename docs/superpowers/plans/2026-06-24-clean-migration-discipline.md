# Clean-Migration Discipline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clean-migration discipline to the agentic-loop skill so migrations land clean the first time instead of silently accreting compat shims.

**Architecture:** Five prose edits to a single markdown file (`skills/agentic-loop/SKILL.md`) plus three documented `progress.json` schema fields. A new disposition fork (Phase 2.6) is *decided* up front, *propagated* into worker prompts (Phase 3/3a), *enforced* by an independent reviewer made load-bearing (Phase 4b) with the worker assertion demoted to a smell test (Phase 3a), and *measured* by a Phase 13 counter. No code, no new hook, no new agent.

**Tech Stack:** Markdown (the skill is prose). Verification is `grep`-based content assertion against `skills/agentic-loop/SKILL.md`. There is no build step — edits take effect after `/reload-plugins`.

## Global Constraints

- **Single file modified:** `skills/agentic-loop/SKILL.md`. No other source file changes in Spec A. (The `progress.json` schema is *documented inside* that skill's "Context-window-persistence" section — there is no separate schema file.)
- **No hook scripts are touched**, so the project test gate (`bash -n hooks/scripts/*.sh`) is not exercised by these edits. Do not add hook changes here — that is Spec C.
- **Match the skill's existing voice:** dense, phase-structured, each rule carries a short "The why:" and, where real, a "Past failure:" grounding. Do not invent past failures — the only real one to cite is the migration-shim rework that motivated this spec.
- **Vocabulary is fixed and must be used verbatim across all tasks:** `clean-break`, `preserve-compat`, `disposition`, `named_blocker`, `removal_ticket`, `retires an existing code path`. A synonym in one task and the canonical term in another is a consistency bug.
- **Branch hygiene (battle-tested in this session):** an auto-commit-on-Write/Edit hook commits to the *current branch* the instant a file is edited. Before any edit, confirm the current branch is the implementation branch cut from `origin/main` — NOT `main`. If `main` ever ends up ahead of `origin/main` because the hook committed there, reset it: `git branch -f main origin/main` (only when not checked out on main). This is the Phase 2 clean-base discipline the skill itself encodes.
- **Commits:** because the auto-commit hook fires on edit, an explicit `git commit` step may report "nothing to commit." That is expected — verify the content landed with `git log --oneline -1` and `git show --stat HEAD` rather than assuming the explicit commit created it. Amend the auto-commit's generic message to the task's message with `git commit --amend -m "..."` when it has fired.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `skills/agentic-loop/SKILL.md` | The orchestration skill | Modify: add Phase 2.6; extend Phase 3, Phase 3a, Phase 4b, Phase 13, and the Context-window-persistence schema list |

All five tasks edit different, non-overlapping regions of the same file. Task 1 establishes the data contract (the schema fields) that Tasks 2, 3, and 5 reference, so it goes first.

---

### Task 1: Document the `progress.json` disposition schema fields

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` — the "Context-window-persistence" section, the sentence beginning "It is overwritten (not appended) on every phase boundary and holds:"

**Interfaces:**
- Produces: the three field names later tasks rely on — `disposition` (values `clean-break` | `preserve-compat`), `named_blocker` (string), `removal_ticket` (string). Tasks 2, 3, and 5 reference these exact names.

- [ ] **Step 1: Write the failing assertion**

Run: `grep -n "disposition" skills/agentic-loop/SKILL.md`
Expected now: no match in the Context-window-persistence section (the field is undocumented).

- [ ] **Step 2: Confirm it fails**

Run: `grep -c "disposition" skills/agentic-loop/SKILL.md`
Expected: `0`.

- [ ] **Step 3: Make the edit**

Find the sentence in the "Context-window-persistence" section that currently reads:

> ...and holds: the authorisation envelope verbatim, the current phase, each work-unit's status (`pending`/`in-progress`/`done`/`blocked` with `blockedBy`), verified state carried between units (deployed version, test counts), and the human-turn counters for Phase 13.

Replace it with:

> ...and holds: the authorisation envelope verbatim, the current phase, each work-unit's status (`pending`/`in-progress`/`done`/`blocked` with `blockedBy`), verified state carried between units (deployed version, test counts), the human-turn counters for Phase 13, and — for any work-unit that retires an existing code path — its `disposition` (`clean-break` | `preserve-compat`), plus, when `preserve-compat`, the `named_blocker` (the specific consumer still on the old path that justifies keeping it) and the `removal_ticket` tracking the deferred removal.

- [ ] **Step 4: Confirm it passes**

Run: `grep -n "disposition.*clean-break.*preserve-compat\|named_blocker\|removal_ticket" skills/agentic-loop/SKILL.md`
Expected: matches showing all three field names present in the persistence section.

- [ ] **Step 5: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): document disposition/named_blocker/removal_ticket in progress.json schema" || git commit --amend -m "feat(agentic-loop): document disposition/named_blocker/removal_ticket in progress.json schema"
git log --oneline -1
```

---

### Task 2: Add Phase 2.6 — resolve disposition before replacement work

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` — insert a new `### Phase 2.6` block immediately after the end of the Phase 2.5 block (after the paragraph ending "...keep it literally so.") and before `### Phase 3`.

**Interfaces:**
- Consumes: the `disposition` / `named_blocker` / `removal_ticket` fields from Task 1.
- Produces: the disposition decision and the "named blocker" rule that Task 3 propagates and Tasks 4–5 enforce/measure.

- [ ] **Step 1: Write the failing assertion**

Run: `grep -n "Phase 2.6" skills/agentic-loop/SKILL.md`
Expected now: no match.

- [ ] **Step 2: Confirm it fails**

Run: `grep -c "Phase 2.6" skills/agentic-loop/SKILL.md`
Expected: `0`.

- [ ] **Step 3: Make the edit**

Insert this block after the Phase 2.5 block and before `### Phase 3`:

```markdown
### Phase 2.6 — Resolve disposition before replacement work (clean-break vs preserve-compat)

When the Phase 1 plan contains a work-unit that **retires an existing code path** — there is a *named thing being replaced* (a function, module, endpoint, schema, or flag the change removes from use) — resolve its **disposition** once, up front, before the first spawn. This is the migration analogue of Phase 2.5's design fork: asked once, not re-litigated.

**Trigger precisely.** The fork fires only when an existing path is being *retired*, not merely when new code calls or wraps old code. If nothing is being removed from use, there is no disposition question. A concrete "what named thing does this remove?" test is deliberately harder to self-exempt from than a vague "is this a migration?".

**The fork, asked once:**
- **clean-break** — the old path is removed in the same unit. No shims, bridges, adapters, or compatibility flags remain.
- **preserve-compat** — the old path is kept behind a shim, justified by a **specific named blocker**: a named consumer still on the old path that cannot migrate in this unit. A generic justification ("safer", "less risky", "to avoid breakage") is NOT sufficient and must be rejected — name the consumer or choose clean-break.

**clean-break is the default recommendation for a retirement.** Recommend clean-break unless a specific named blocker exists. This is deliberate: the model's untold prior leans toward preserving the old path because removal feels destructive, and that prior is exactly what silently doubles migration work. Requiring a named blocker stops the prior being laundered into the human's explicit approval — where it would become invisible to the Phase 13 counter.

**What happens with the answer depends on the envelope class (Phase 0)** — this resolves the fork, it does NOT add a human gate:
- **Full-autonomous:** adopt clean-break by default, record it, proceed. Surface a preserve-compat choice (with its named blocker) at the next approval-gate; do not stall.
- **Narrow-fix / diagnostic / ambiguous:** surface the disposition as one decision — "clean-break recommended, here's why" — bounded like Phase 1 (ask once, don't loop).

**Record** per work-unit in `progress.json`: `disposition`, and when `preserve-compat`, the `named_blocker` and a mandatory `removal_ticket`.

The why: a retirement with an unresolved disposition is filled silently with the cautious answer, and the cautious answer on a migration is usually wrong — it keeps a path the change was meant to remove, and the work has to be redone clean. Closing the fork once, up front, with clean-break as the default, is the cheapest point to prevent the doubled work. Past failure: a migration defaulted to keeping legacy shims and bridges because the model reasoned the human wanted existing functionality preserved; the loop had to be re-invoked with an explicit "remove the shims" instruction — double the work instead of one clean migration.
```

- [ ] **Step 4: Confirm it passes**

Run: `grep -n "Phase 2.6 — Resolve disposition\|named blocker\|clean-break is the default" skills/agentic-loop/SKILL.md`
Expected: matches for the heading, the named-blocker rule, and the default recommendation.

- [ ] **Step 5: Verify placement**

Run: `grep -n "^### Phase 2.5\|^### Phase 2.6\|^### Phase 3 " skills/agentic-loop/SKILL.md`
Expected: line numbers in ascending order 2.5 < 2.6 < 3 (the new phase sits between them).

- [ ] **Step 6: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): add Phase 2.6 disposition fork (clean-break default + named-blocker rule)" || git commit --amend -m "feat(agentic-loop): add Phase 2.6 disposition fork (clean-break default + named-blocker rule)"
git log --oneline -1
```

---

### Task 3: Propagate the disposition into worker prompts (Phase 3 + Phase 3a)

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` — the Phase 3 bulleted list of what each task description must include ("Each task description must be **self-contained**..."), and the Phase 3a bulleted list of what the single-agent prompt must include.

**Interfaces:**
- Consumes: the `disposition` decision and `named_blocker` from Phase 2.6 (Task 2).
- Produces: the guarantee that the decision reaches the worker prompt, which Task 4's assertions depend on.

- [ ] **Step 1: Write the failing assertion**

Run: `grep -n "copied **verbatim**\|disposition.*verbatim" skills/agentic-loop/SKILL.md`
Expected now: no match.

- [ ] **Step 2: Confirm it fails**

Run: `grep -c "verbatim into the" skills/agentic-loop/SKILL.md`
Expected: `0`.

- [ ] **Step 3: Edit Phase 3's task-description list**

In the Phase 3 list that includes "Worktree path", "Branch name", "Model: sonnet", etc., add this bullet (place it after the "Manifest" bullet and before "Terminal state"):

```markdown
- Disposition — for a retirement unit, the `clean-break`/`preserve-compat` decision from Phase 2.6 copied **verbatim** into the task description, plus (if preserve-compat) the `named_blocker`. The worker acts only on its own prompt; a disposition recorded in `progress.json` but absent from the prompt silently reverts the unit to the model's preserve-default — the exact failure this discipline exists to stop.
```

- [ ] **Step 4: Edit Phase 3a's single-agent prompt list**

In the Phase 3a list of what the self-contained prompt must include (the list with "`model: sonnet` — non-negotiable...", "A verify step...", "Report-back contract...", "A manifest..."), add this bullet after the manifest bullet:

```markdown
- **The disposition, verbatim** — for a retirement unit, the `clean-break`/`preserve-compat` decision from Phase 2.6 and (if preserve-compat) the `named_blocker`. The single agent cannot re-read the conversation; the decision must travel in its prompt or it does not exist for the worker.
```

- [ ] **Step 5: Confirm it passes**

Run: `grep -n "copied \*\*verbatim\*\*\|The disposition, verbatim" skills/agentic-loop/SKILL.md`
Expected: two matches — one in Phase 3, one in Phase 3a.

- [ ] **Step 6: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): propagate disposition verbatim into worker prompts (Phase 3 + 3a)" || git commit --amend -m "feat(agentic-loop): propagate disposition verbatim into worker prompts (Phase 3 + 3a)"
git log --oneline -1
```

---

### Task 4: Enforce clean-break — reviewer load-bearing, worker assertion secondary (Phase 3a + Phase 4b)

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` — the Phase 3a manifest/scope-assertion bullet (the one requiring `git diff origin/main --name-only` equals the manifest), and the Phase 4b section (after the six-reviewer table and the `/security-review` paragraph).

**Interfaces:**
- Consumes: the `disposition` carried into the worker prompt (Task 3); the existing `code-simplifier` reviewer (Phase 4b row 6).
- Produces: the MERGE-BLOCKER semantics and the override path that Task 5's counter audits against.

- [ ] **Step 1: Write the failing assertions**

Run: `grep -n "relabelled compatibility\|first-pass smell test\|Clean-break gate" skills/agentic-loop/SKILL.md`
Expected now: no match. (NB: the bare word "relabelled" already occurs once at ~line 367 in the Phase 13 approval-gate text — do NOT assert on the bare word; use the specific phrase "relabelled compatibility".)

- [ ] **Step 2: Confirm it fails**

Run: `grep -c "MERGE-BLOCKER" skills/agentic-loop/SKILL.md`
Note the current count (the term may already appear in Phase 4b). Record it; Step 5 expects it to increase.

- [ ] **Step 3: Edit the Phase 3a manifest assertion bullet**

At the end of the Phase 3a bullet that requires the pre-push scope assertion ("before you push, run `git diff origin/main --name-only`..."), append:

```markdown
  When the unit's disposition is `clean-break`, the assertion also covers compat: before push, confirm no compatibility shim, bridge, adapter, or legacy code path for the replaced functionality remains. If one does, clean-break is not finished — remove it or STOP and report. This worker assertion is a **first-pass smell test, not the gate** — the independent reviewer (Phase 4b) is the gate, because the worker that wrote a shim is the party least able to see it as one.
```

- [ ] **Step 4: Add the clean-break gate to Phase 4b**

After the `/security-review` paragraph in Phase 4b (the paragraph beginning "**Plus the native `/security-review` pass.**"), insert:

```markdown
**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not the report-only suggestions row 6 produces by default. **Override path:** the orchestrator may record "reviewed, not compat — `<reason>`" against a finding to demote a false-positive to a logged note, so a reviewer misfire degrades to a note, never a wall. The why: clean-break enforced by worker self-assertion alone is self-attestation by the party with motive to keep the path; the independent reviewer carries the gate. Past failure: the original shim rework happened precisely because no independent check hunted for the compat the author had rationalised as necessary.
```

- [ ] **Step 5: Confirm it passes**

Run: `grep -n "first-pass smell test\|relabelled compatibility\|Clean-break gate\|Override path:" skills/agentic-loop/SKILL.md`
Expected: matches for the Phase 3a smell-test clause and all three Phase 4b elements.

Run: `grep -c "MERGE-BLOCKER" skills/agentic-loop/SKILL.md`
Expected: count increased by 1 versus Step 2.

- [ ] **Step 6: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): clean-break gate — independent reviewer load-bearing, worker assertion demoted (Phase 3a + 4b)" || git commit --amend -m "feat(agentic-loop): clean-break gate — independent reviewer load-bearing, worker assertion demoted (Phase 3a + 4b)"
git log --oneline -1
```

---

### Task 5: Measure — Phase 13 disposition-violations counter

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` — the Phase 13 ("Confirm the factory actually ran") bulleted list of what the orchestrator audits.

**Interfaces:**
- Consumes: the `disposition` and `removal_ticket` records (Task 1), the merged-artifact state, and the clean-break gate (Task 4).
- Produces: nothing downstream within Spec A — this is the terminal measurement.

- [ ] **Step 1: Write the failing assertion**

Run: `grep -n "Disposition violations\|audit failure" skills/agentic-loop/SKILL.md`
Expected now: no match.

- [ ] **Step 2: Confirm it fails**

Run: `grep -c "Disposition violations" skills/agentic-loop/SKILL.md`
Expected: `0`.

- [ ] **Step 3: Make the edit**

In the Phase 13 bulleted list (currently "Human turns inside the envelope", "Genuine gates vs avoidable stalls", "Artifacts produced"), add this bullet after "Artifacts produced":

```markdown
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the metric reads "factory clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.
```

- [ ] **Step 4: Confirm it passes**

Run: `grep -n "Disposition violations\|no disposition record found\|compat-debt drift" skills/agentic-loop/SKILL.md`
Expected: matches for the counter, the audit-failure distinction, and the removal-ticket drift signal.

- [ ] **Step 5: Final cross-task consistency check**

Run: `grep -no "clean-break\|preserve-compat\|named_blocker\|removal_ticket\|disposition" skills/agentic-loop/SKILL.md | sort | uniq -c`
Expected: every canonical term appears (no stray synonyms like "clean break" with a space, "preserve compat", or "blocker_name"). Eyeball the list; fix any variant spelling inline.

- [ ] **Step 6: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): Phase 13 disposition-violations counter (record-absent = audit failure)" || git commit --amend -m "feat(agentic-loop): Phase 13 disposition-violations counter (record-absent = audit failure)"
git log --oneline -1
```

---

## Self-Review (completed against the spec)

**1. Spec coverage** — every spec section maps to a task:
- DECIDE (disposition fork, tighter trigger, anti-laundering, recording) → Task 2 (+ schema in Task 1)
- PROPAGATE (verbatim into worker prompt) → Task 3
- ENFORCE (reviewer load-bearing, worker assertion secondary, relabelling hunt, override path) → Task 4
- MEASURE (counter, 0-vs-no-record, removal-ticket drift) → Task 5
- Supporting progress.json fields → Task 1
- All four planning-sequence hardenings (self-attestation → Task 4; relabelling → Task 4; laundering → Task 2 named-blocker; ghost counter → Task 5 audit-failure) are covered.

**2. Placeholder scan** — no TBD/TODO; every edit step contains the exact prose to insert and the exact grep to verify.

**3. Type/term consistency** — canonical vocabulary (`clean-break`, `preserve-compat`, `disposition`, `named_blocker`, `removal_ticket`, "retires an existing code path") is used identically in every task; Task 5 Step 5 adds an explicit consistency sweep.

**Out of scope (correctly):** mechanical enforcement of `progress.json` presence and the anti-stall hook are Spec C; slimming is Spec B. This plan does not touch them.
