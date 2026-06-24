# Spec E — Spec→Plan Artifact Discipline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agentic-loop the two durable build artifacts it lacks — a `spec.md` and a `plan.md` — by vendoring a `coderails:writing-plans` skill and adding two additive, complexity-guarded phases (2.7/2.8) to `agentic-loop/SKILL.md`.

**Architecture:** Two independent deliverables. (1) A new focused coderails skill `skills/writing-plans/SKILL.md` (+ companion), adapted from superpowers' writing-plans, built with skill-creator and its genuine description-optimization loop, referencing `coderails:test-driven-development` in its per-task construction step (E→D tie). (2) Two new markdown phases inserted between Phase 2.6 and Phase 3 of `agentic-loop/SKILL.md`: Phase 2.7 writes a durable `spec.md`, Phase 2.8 writes a durable `plan.md` via `coderails:writing-plans`. Both phases fire only on ≥3 work-units or a cross-unit dependency. The artifacts live in the loop-state dir (`~/.claude/agentic-loop/<slug>/`, resolved by `agentic_loop_path.sh`), outside the repo, uncommitted.

**Tech Stack:** Markdown (skills + SKILL.md phases). Python only insofar as skill-creator's `run_loop.py` (model `claude-sonnet-4-6`) runs the description optimization. No code shipped; no hooks/`hooks.json`/`install.sh`/`lib/` changes.

## Global Constraints

- **The six C1/C2 no-touch regions in `skills/agentic-loop/SKILL.md` stay BYTE-IDENTICAL to `origin/main`.** They are: (1) the frontmatter `description:` line (single-quoted); (2) the `### Phase -2` stub-first block; (3) the Phase 0.5 LOOP-STOP bullet (`- End any stopping turn inside an active loop…`); (4) the Phase 13 KPI bullet (`- **LOOP-STOP declarations by category** —`); (5) the Stop-conditions `**Declaring the stop (the LOOP-STOP contract).**` block; (6) the **entire** `## Context-window persistence` section. The byte-diff gate (`git diff origin/main -- skills/agentic-loop/SKILL.md`) is the PRIMARY verification — a token grep is necessary-not-sufficient.
- **Additive phases only, NO renumber.** New phases are `2.7` and `2.8`, between `2.6` and `3`. No existing phase heading changes.
- **Complexity guard = ≥3 work-units OR a cross-unit dependency** — exactly Phase 3's `TeamCreate` line. Never "≥2".
- **No cross-plugin dependency.** The vendored skill is coderails-owned; phase references use the `coderails:` namespace. No `superpowers:` string ships in skill text or new phases.
- **Sonnet-only untouched.** No model-selection guidance in the new skill or new phases that could escalate a worker off sonnet.
- **Single-quoted `description:`** in the new skill's frontmatter (strict-YAML safe, per commit `e6e39dd`).
- **Markdown-only delivery.** The three hook suites (path 3/3, state-guard 8/8, stall-guard 8/8) must stay green (unaffected).

---

### Task 1: Vendor the `coderails:writing-plans` skill

**Files:**
- Create: `skills/writing-plans/SKILL.md`
- Create: `skills/writing-plans/plan-anti-patterns.md` (companion — the plan-quality failure modes)

**Interfaces:**
- Produces: a skill invocable as `coderails:writing-plans`. Phase 2.8 (Task 2) references it by that exact name.
- Consumes: nothing from Task 2 (Task 1 is independent and can ship first).

**Model for structure:** `skills/test-driven-development/SKILL.md` (D's vendored skill — 76 lines, single-quoted guarded `description`, one companion doc). Match that shape and length budget. Do NOT copy superpowers' full writing-plans file verbatim (re-importing bulk re-introduces what Spec B cut and makes a worse trigger).

**Reference for content (adapt, do not copy wholesale):** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/writing-plans/SKILL.md`.

- [ ] **Step 1: Draft `skills/writing-plans/SKILL.md` (focused, coderails voice)**

Create the file with single-quoted frontmatter and a focused body. Target ~70–90 lines (D's skill is 76). Frontmatter:

```markdown
---
name: writing-plans
description: 'Use when you have a spec or resolved design for a multi-step task and need a durable, task-by-task implementation plan before any code is written — each task with exact files, interfaces, bite-sized steps, and verify-criteria. Not for single trivial edits, which need no separate plan.'
---
```

Body must include, in coderails voice (short, declarative):
- **What a plan is:** an ordered set of **self-contained tasks**, each dispatchable to a worker without re-reading the conversation (the same contract Phase 3 of agentic-loop states for task descriptions — they agree by construction).
- **Each task carries:** exact files to create/modify; the interfaces/signatures it consumes and produces; bite-sized ordered steps (one action each, 2–5 min); and **verify-criteria stated as something testable**.
- **Per-task construction method references `coderails:test-driven-development`** — when a task's deliverable is code (adds/alters a function, method, or branch that can carry a test), the plan instructs test-first construction. (This is the E→D tie. Use the literal string `coderails:test-driven-development`.)
- **DRY / YAGNI / no-placeholders:** a plan task says exactly what to build — no speculative flexibility, no `TODO`/stub left for "later".
- **Self-review gate:** before the plan is final, re-read it against the spec — every spec requirement maps to a task, every task traces to a requirement; check type/signature consistency across tasks.
- **When NOT to use** (the complexity guard, stated explicitly): a single trivial edit needs no separate plan — the task description itself suffices. This is the body-level echo of the `description`'s exclusion clause.
- A link to `plan-anti-patterns.md`.

Do NOT include any `model:`/`opus`/`most capable` guidance. Do NOT reference `superpowers:` anywhere.

- [ ] **Step 2: Draft `skills/writing-plans/plan-anti-patterns.md` (companion)**

Create the companion (model: `skills/test-driven-development/testing-anti-patterns.md`, ~1.5 KB). Cover the plan-quality failure modes adapted from superpowers' "No Placeholders" section:
- placeholder steps (`TBD`/`TODO`/"implement later"/"add appropriate error handling");
- "similar to Task N" instead of repeating the content (an implementer may read tasks out of order);
- steps that say *what* without showing *how* (code steps need code blocks);
- references to types/functions/methods not defined in any task;
- tasks too large to carry one test cycle / one reviewer gate.

- [ ] **Step 3: Verify the skill loads and is structurally valid**

Run:
```bash
test -f skills/writing-plans/SKILL.md && test -f skills/writing-plans/plan-anti-patterns.md && echo "FILES OK"
head -4 skills/writing-plans/SKILL.md
grep -c "coderails:test-driven-development" skills/writing-plans/SKILL.md
grep -ci "superpowers:" skills/writing-plans/SKILL.md
grep -ciE 'opus|model:|most capable' skills/writing-plans/SKILL.md
grep -c "plan-anti-patterns.md" skills/writing-plans/SKILL.md
```
Expected: `FILES OK`; frontmatter `description:` is single-quoted; the `coderails:test-driven-development` count ≥ 1; the `superpowers:` count = 0; the opus/model count = 0; the companion-link count ≥ 1.

- [ ] **Step 4: Genuinely run skill-creator's description-optimization loop**

This step is NON-NEGOTIABLE and the most-checked part of the task (a Spec D worker only `mkdir`'d and Gary caught it). Invoke skill-creator via the `Skill` tool and run its description-optimization loop on the new skill. The loop machinery is at:
`~/.claude/plugins/cache/claude-plugins-official/skill-creator/unknown/skills/skill-creator/scripts/run_loop.py` (model `claude-sonnet-4-6`).

Provide an eval set that includes **should-trigger** queries (e.g. "turn this spec into an implementation plan", "decompose this design into tasks before coding") AND **should-NOT-trigger** negatives that protect the complexity-guard clause (e.g. "fix this one-line typo", "rename a variable", "just make this small edit" — these must NOT trigger writing-plans). Run the loop, capture the score and the optimizer's recommended description.

- [ ] **Step 5: Adopt the optimizer's result, re-assert the guards**

If the optimizer improved the description, replace the frontmatter `description:` with its result. Then RE-ASSERT the two non-negotiable properties the optimizer might have stripped:
```bash
# description still single-quoted:
sed -n '3p' skills/writing-plans/SKILL.md | grep -q "^description: '" && echo "SINGLE-QUOTED OK"
# exclusion clause still present (some phrasing of 'not for trivial/single edits'):
grep -iE "not for (single )?trivial|single trivial edit|no separate plan" skills/writing-plans/SKILL.md && echo "GUARD CLAUSE OK"
```
Expected: both `OK`. If the optimizer dropped the single-quoting or the exclusion clause, restore them by hand — these win over the optimizer.

- [ ] **Step 6: Commit**

```bash
git add skills/writing-plans/SKILL.md skills/writing-plans/plan-anti-patterns.md
git commit -m "feat(agentic-loop): vendor coderails:writing-plans skill (Spec E, Task 1)"
```

---

### Task 2: Add additive Phase 2.7 + Phase 2.8 to `agentic-loop/SKILL.md`

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` — insert two new phase sections between the end of Phase 2.6 (ends ~line 192) and the `### Phase 3` heading (~line 194).

**Interfaces:**
- Consumes: the `coderails:writing-plans` skill name from Task 1 (referenced in Phase 2.8). Task 2 should run after Task 1 so the referenced skill exists.
- Produces: nothing downstream depends on (it's the last task).

**⚠️ NO-TOUCH WARNING (read before editing):** The new phases describe loop-state artifacts, which makes the `## Context-window persistence` section (also about loop-state artifacts) a tempting place to "helpfully" add a `plan.md` sentence. DO NOT. Describe the new artifacts ONLY inside Phase 2.7/2.8. The persistence section and the other five no-touch regions stay byte-identical. There is NO failing test for markdown prose — the verify step is the byte-diff gate in Step 3.

- [ ] **Step 1: Insert Phase 2.7 and Phase 2.8 between Phase 2.6 and Phase 3**

The insertion point is immediately before the line `### Phase 3 — Delegate all implementation to sonnet agents; TeamCreate when work has ≥3 sequential units or dependency chains`. Insert the following two sections (verbatim), leaving Phase 3 and everything after it untouched:

````markdown
### Phase 2.7 — Commit the resolved design to a durable `spec.md`

This phase fires ONLY when the loop has **≥3 work-units or a cross-unit dependency** — the same line Phase 3 draws to choose `TeamCreate` over a single agent. A 1–2-unit fix that Phase 3 routes to a single agent needs no separate design docs: the envelope (Phase 0) + `progress.json` + the one self-contained task description already carry everything. If the loop is below that threshold, skip 2.7 and 2.8 entirely.

When it fires, write a durable `spec.md` to the loop-state dir — the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`, run at Phase -2), next to `progress.json`, outside the code repo, **not committed** (loop state, not a PR deliverable). This is a **commit of design the loop has already resolved**, not interactive brainstorming — a loop cannot brainstorm with itself; the forks were closed at 2.5 and 2.6. Record:
- the authorisation envelope verbatim (Phase 0);
- the design-fork decision and its flip-condition (Phase 2.5);
- the disposition decision(s) and any named blocker (Phase 2.6);
- the success criteria — what "done" means for the whole loop;
- the high-level work-unit boundaries (the detailed decomposition is Phase 2.8's plan).

The `spec.md` is loop state, keyed to this orchestrator's run, exactly like `progress.json` — not a shareable design record. When ad-hoc loop work genuinely needs handing to a human, that is what `coderails:handoff` is for.

### Phase 2.8 — Write the durable `plan.md` via `coderails:writing-plans`

This phase fires under the same complexity guard as 2.7 (**≥3 work-units or a cross-unit dependency**). When it fires, produce a durable `plan.md` in the loop-state dir (next to `spec.md` and `progress.json`, outside the repo, not committed) by invoking **`coderails:writing-plans`** — the same one-line skill-reference idiom Phase 3/3a use for `coderails:test-driven-development`.

`plan.md` is the **static SSOT** for the decomposition; `progress.json` is the **dynamic position** against it. The plan is **consumed, not write-only**, in both directions:
- **Phase 3 builds its task list directly from `plan.md`** — the TeamCreate task list and the Phase 3/3a worker descriptions derive from the plan's tasks, so the two are consistent by construction rather than re-derived from conversation.
- **After any compaction the orchestrator re-reads `plan.md` to recover *scope* (what to build)** the same way it re-reads `progress.json` to recover *position* (where we are).

(This is the one place the `plan.md`↔`progress.json` relationship is named. It is stated here, standalone, on purpose — the `## Context-window persistence` section, which describes `progress.json`, is not edited.)

````

- [ ] **Step 2: Verify the phases are present, guarded, and correctly placed**

Run:
```bash
grep -n "^### Phase 2.7\|^### Phase 2.8" skills/agentic-loop/SKILL.md
# Heading order — 2.6, 2.7, 2.8, 3 must be consecutive:
grep -n "^### Phase" skills/agentic-loop/SKILL.md | grep -E "2\.6|2\.7|2\.8|^[0-9]*:### Phase 3 "
# Guard wording present in both new phases, never "≥2":
grep -c "≥3 work-units or a cross-unit dependency" skills/agentic-loop/SKILL.md   # expect ≥2
grep -c "≥2 work-units" skills/agentic-loop/SKILL.md                              # expect 0
# Skill reference + namespace hygiene:
grep -c "coderails:writing-plans" skills/agentic-loop/SKILL.md                    # expect ≥1
# Sonnet-only intact in new text (no new model guidance):
grep -niE "opus|most capable" skills/agentic-loop/SKILL.md | grep -iE "2\.7|2\.8" # expect none
```
Expected: 2.7 and 2.8 headings exist; heading order is …2.6, 2.7, 2.8, 3…; `≥3` count ≥ 2; `≥2 work-units` count = 0; `coderails:writing-plans` count ≥ 1; no opus/most-capable in the new phases.

- [ ] **Step 3: Verify the six no-touch regions are byte-identical (PRIMARY GATE)**

Run the byte-diff gate and confirm every hunk falls strictly between Phase 2.6 and Phase 3:
```bash
git diff origin/main -- skills/agentic-loop/SKILL.md
```
Expected: the ONLY changes are the two inserted sections (Phase 2.7 + Phase 2.8). Confirm specifically that:
- the frontmatter `description:` line is unchanged;
- the `### Phase -2` block is unchanged;
- the Phase 0.5 LOOP-STOP bullet is unchanged;
- the Phase 13 KPI bullet is unchanged;
- the Stop-conditions "Declaring the stop" block is unchanged;
- **the entire `## Context-window persistence` section shows ZERO diff lines.**

Targeted re-assert:
```bash
# Persistence section must be byte-identical — extract it from both and diff:
git show origin/main:skills/agentic-loop/SKILL.md | awk '/^## Context-window persistence/{f=1} f{print} /^## Stop conditions for the loop/{if(f)exit}' > /tmp/persist_base.txt
awk '/^## Context-window persistence/{f=1} f{print} /^## Stop conditions for the loop/{if(f)exit}' skills/agentic-loop/SKILL.md > /tmp/persist_head.txt
diff /tmp/persist_base.txt /tmp/persist_head.txt && echo "PERSISTENCE BYTE-IDENTICAL"
```
Expected: `PERSISTENCE BYTE-IDENTICAL` (no diff output). If ANY no-touch region changed, STOP and report — do not push.

- [ ] **Step 4: Confirm the hook suites still pass (markdown-only sanity)**

Run the three hook test suites (E is markdown-only; they must be unaffected):
```bash
bash hooks/scripts/tests/test_agentic_loop_path.sh 2>/dev/null || ls hooks/scripts/tests/
```
Find and run the path / state-guard / stall-guard suites (expected 3/3, 8/8, 8/8). If the test runner paths differ, locate them under `hooks/` and run each. Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): additive Phase 2.7/2.8 spec+plan artifacts (Spec E, Task 2)"
```

---

## Self-Review

**1. Spec coverage:**
- Deliverable 1 (vendor `coderails:writing-plans` + companion, skill-creator + genuine description-optimization loop, E→D tie, single-quoted guarded description) → **Task 1** (Steps 1–6, optimization loop is Step 4, guards re-asserted Step 5).
- Deliverable 2 (additive Phase 2.7 spec.md + Phase 2.8 plan.md via `coderails:writing-plans`, complexity guard, consumption explicit) → **Task 2** (Steps 1–5).
- Constraint: six no-touch regions byte-identical incl. persistence → **Task 2 Step 3** (primary gate) + Global Constraints.
- Constraint: additive, no renumber → **Task 2 Step 1** (insert before Phase 3) + Step 2 (heading-order check).
- Constraint: ≥3 threshold, never ≥2 → Global Constraints + **Task 2 Step 2** grep asserts `≥2 work-units` count = 0.
- Constraint: no `superpowers:` leak, sonnet-only → **Task 1 Step 3** + **Task 2 Step 2** greps.
- Doc location uncommitted, outside repo → phase text in **Task 2 Step 1**; not committed (no `git add` of loop-state docs anywhere).

**2. Placeholder scan:** No `TBD`/`TODO`/"implement later". Every code/markdown step shows the actual content (the verbatim phase text, the exact frontmatter, the exact verification commands). The one irreducibly judgement-based step (Step 4 of Task 1, running skill-creator's loop) names the exact script path, model, and the eval-set shape required.

**3. Type consistency:** The skill name is `coderails:writing-plans` consistently in Task 1 (produced) and Task 2 Step 1/2 (consumed). The E→D reference string `coderails:test-driven-development` matches the existing skill name verified in `skills/test-driven-development/SKILL.md`. The threshold phrase "≥3 work-units or a cross-unit dependency" is identical in the spec, the plan constraints, and the Phase 2.7/2.8 body text.

**Note on TDD shape:** This plan is markdown/skill authoring, not code-with-tests. Per `coderails:test-driven-development`'s own guard, prose/skill edits with no testable function/branch verify *by inspection*, not a failing test first — so each task's verify steps are grep/byte-diff assertions, which is the correct discipline for this deliverable.
