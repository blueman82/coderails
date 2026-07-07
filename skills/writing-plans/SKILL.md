---
name: writing-plans
description: 'Use when you have a spec or resolved design for a multi-step task and need a durable, task-by-task implementation plan before any code is written — each task with exact files, interfaces, bite-sized steps, and verify-criteria. Not for single trivial edits, which need no separate plan.'
---

# Writing Plans

Turn a spec into an ordered set of self-contained tasks, each dispatchable to a worker without re-reading the conversation. A worker reads only their task; it must contain everything they need.

## When this applies — and when it doesn't

**Applies** when the work spans multiple tasks, files, or reviewable units — a feature, a refactor, a new subsystem.

**Does not apply** to a single trivial edit. If the change fits in one task description, write the task description. A separate plan adds ceremony without value. This is the guard this skill exists to enforce.

## What each task carries

Every task in the plan must include:

- **Files**: exact paths to create or modify (e.g. `src/auth/validator.py:42-89`). No "somewhere in the auth module."
- **Interfaces**: what this task consumes from earlier tasks (exact signatures) and what it produces for later ones (exact function names, parameter and return types). A worker sees only their task — interfaces are how they learn the names and types neighboring tasks use.
- **Steps**: one action each, 2–5 minutes. "Write the failing test" is a step. "Implement auth" is not.
- **Verify-criteria**: something runnable or inspectable that proves the task is done — a test command with expected output, a grep, a visible UI state.

## Per-task construction method

When a task's deliverable is code — adds or alters a function, method, or branch that can carry a test — the plan instructs test-first construction using `coderails:test-driven-development`. The step sequence is: write the failing test → watch it fail for the right reason → write minimal code to pass → watch it pass → commit. For pure docs, config, or prose tasks with no testable code, verify by inspection instead.

## DRY / YAGNI / no placeholders

Each task says exactly what to build. Code steps show the code. Command steps show the command and expected output. These are plan failures — never write them:

- "TBD", "TODO", "implement later"
- "Add appropriate error handling" or "handle edge cases" without showing how
- "Similar to Task N" — repeat the content; a worker may read tasks out of order
- References to types or functions not defined in any task

See [plan-anti-patterns.md](plan-anti-patterns.md) for the full failure-mode catalogue.

## File structure first

Before writing tasks, map every file the plan will create or modify and what each is responsible for. This locks in decomposition. Each file: one clear responsibility. Files that change together live together.

## Task right-sizing

A task is the smallest unit that carries its own test cycle and is worth a reviewer's gate. Fold setup, config, and docs into the task whose deliverable needs them. Split only where a reviewer could reject one task while approving its neighbor.

## Self-review gate

After the plan is written, re-read it against the spec:

1. **Spec coverage**: every spec requirement maps to a task. List gaps.
2. **Placeholder scan**: check for the anti-patterns above. Fix them.
3. **Type consistency**: a function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug. Reconcile.
4. **Engineering principles**: each task's design honours YAGNI/KISS/DRY/Fail-Fast/SSOT/Law of Demeter — no speculative abstraction, no duplicated logic, fail-fast validation. See `/engineering-principles` for the rubric; bake the constraints into tasks now rather than refactoring after review.

Fix issues inline. If a spec requirement has no task, add the task.

## Stress-test before implementation (required)

After the plan passes the self-review gate, put it through `/coderails:planning-sequence` before any implementation begins. The sequence runs three stages against the plan — Pre-Parade (success conditions), Premortem (failure modes), Red Team (adversarial challenge) — surfacing weaknesses while they are still cheap to fix on paper rather than after code is written.

Feed it the written plan and the spec it derives from. Fold the findings back into the plan inline: add tasks for gaps it exposes, tighten verify-criteria it shows to be weak, and record any failure mode you consciously accept rather than fix. Only once the plan reflects the sequence's output do you freeze evals (next section) and hand off to implementation (`coderails:subagent-driven-development` or `coderails:executing-plans`).

In an agentic multi-agent loop, run the sequence in a delegated agent, not main context (per the agentic-loop skill) — the gate is unchanged, only the venue differs.

## Freeze evals after stress-test, before implementation

Once the plan has passed both the self-review gate above and the stress-test pass above (so the task list is stable and will not change shape again), invoke `/coderails:task-evals` (scope: `pr`) to generate and freeze the plan's end-state success evals, tiered per that skill's predicates. This must happen BEFORE Task 1 is ever dispatched to an implementer — freezing after implementation has started defeats the purpose of a frozen, game-resistant gate. Per-task verify-criteria (already required above) remain as cheap inner-loop checks during implementation; they are NOT a substitute for this frozen eval gate.

## Final task: grade and post only

Every plan produced by this skill ends with one final task invoking `/coderails:post-evals` to grade the already-frozen evals.json (frozen in the step above, before any implementation) against the finished implementation, and post the result. This final task never generates or freezes evals itself — by the time it runs, evals.json already exists and is frozen; this task's only job is grading + posting the artifact that gates `/merge`.

This is the one deliberate exception to the "Task right-sizing" section's rule to fold setup, config, and docs into the task whose deliverable needs them: the grade-and-post task is always its own final task, never folded into the last implementation task, because it must run AFTER all other tasks' code exists.

`scripts/merge.sh` hard-blocks every merge without a SHA-bound eval artifact for the current head — no config opt-out. A docs-only or single-unit PR isn't exempt from this step; it takes the lightweight tier-0 path through `/coderails:task-evals`, not a skip.

## Plan header

Every plan begins with this header verbatim, before the title:

```markdown
**For agentic workers:** REQUIRED SUB-SKILL: Use `coderails:subagent-driven-development` (recommended) or `coderails:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
```

Then continue with:

```markdown
# [Feature Name] Implementation Plan

**Goal:** [one sentence]
**Architecture:** [2–3 sentences]

## Global Constraints
[spec-wide requirements — version floors, naming rules, platform requirements — one line each, verbatim from the spec]

---
```
