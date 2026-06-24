# Spec D — Construction-discipline seam (vendored TDD): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agentic-loop a construction discipline by vendoring a coderails-owned `test-driven-development` skill (zero cross-plugin dependency) and wiring a code-guarded reference to it into the worker contract at Phase 3/3a.

**Architecture:** Two tasks. Task 1 creates a new, focused coderails skill (`skills/test-driven-development/SKILL.md` + a `testing-anti-patterns.md` companion), adapted from superpowers' red-green-refactor discipline, via skill-creator. Task 2 adds two code-guarded one-line references to that skill in `agentic-loop` Phase 3 and Phase 3a, the Phase 3a one placed high in the prompt contract. No code, no test framework — verification is markdown/grep/diff plus the existing hook suites.

**Tech Stack:** Markdown skills; bash (`grep`, `diff`, `wc`) for verification; the three hook test suites under `hooks/scripts/tests/`.

## Global Constraints

- **Self-contained, no cross-plugin dependency.** The vendored skill is coderails-owned; the agentic-loop reference uses the `coderails:` namespace. No `superpowers:` reference may appear in shipped skill text.
- **Code-guarded, concrete test.** The seam fires when "the change adds or alters a function, method, or branch that *can* carry a test" — even if the PR also touches non-code files. Pure docs/config/prose (no testable code) keep the verify-by-inspection contract. No unconditional "always TDD" phrasing.
- **Sonnet-only untouched.** TDD is *how* to build, not *which model*. The Phase 3/3a `model: sonnet` rules stay verbatim. The new skill must contain NO model-selection guidance (no `opus`, no `model:` escalation, no "most capable").
- **Six C1/C2 no-touch regions in `agentic-loop/SKILL.md` stay byte-identical to `origin/main`:** frontmatter `description:` line; the `### Phase -2` block; the Phase 0.5 LOOP-STOP bullet (`- End any stopping turn inside an active loop…`); the Phase 13 KPI bullet (`- **LOOP-STOP declarations by category** —`); the Stop-conditions `**Declaring the stop (the LOOP-STOP contract).**` block; the entire `## Context-window persistence` section. Task 2 edits only Phase 3 and Phase 3a, none of which is a no-touch region — but verify with the region diff.
- **Vendored skill is FOCUSED, not a 371-line copy.** Target ~120 lines for SKILL.md.
- **Frontmatter `description:` of the new skill is single-quoted** (strict-YAML safe, per commit `e6e39dd`).
- **Auto-commit hook** fires on every Write/Edit (generic messages). `git commit` saying "nothing to commit" is fine. Do NOT run `git reset --hard` (destructive-bash gate blocks it); the controller squashes at the end.

### Base
Branch `spec/d-construction-seam` off `origin/main` = `bcf9305` (Spec B merge). The design + plan doc commits sit on top.

---

### Task 1: Create the `coderails:test-driven-development` skill (+ companion)

**Files:**
- Create: `skills/test-driven-development/SKILL.md`
- Create: `skills/test-driven-development/testing-anti-patterns.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a skill invocable as `coderails:test-driven-development`, with a code-guarded triggering `description`. Task 2 references this exact name.

- [ ] **Step 1: Use skill-creator to scaffold the skill, then write the exact content below.**

Invoke the `skill-creator` skill to create a new skill named `test-driven-development`. Use it to scaffold the directory and validate the frontmatter/description. The CONTENT is fixed by this plan — seed skill-creator with it; do not let an eval rewrite the code-guard out of the description. Write `skills/test-driven-development/SKILL.md` with EXACTLY this content:

```markdown
---
name: test-driven-development
description: 'Use when about to implement or fix CODE that can carry a test — a feature, bugfix, or refactor that adds or alters a function, method, or branch. Build test-first: write the failing test, watch it fail for the right reason, then the minimal code to pass, then refactor (red-green-refactor). Does NOT apply to docs, config, or prose edits with no testable code — those verify by inspection, not a failing test.'
---

# Test-Driven Development

Write the test first. Watch it fail. Write the minimal code to pass. If you didn't watch the test fail, you don't know it tests the right thing.

## When this applies — and when it doesn't

**Applies** when the change adds or alters a function, method, or branch that *can* carry a test — a feature, a bugfix, a refactor. This holds even if the same PR also touches non-code files.

**Does not apply** to pure docs, config, or prose edits with no testable code, or to throwaway exploratory spikes. There is no failing test to write first — verify those by inspection instead. Tempted to call a code change "mostly config" to skip the test? That is the rationalization this guard exists to stop.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Wrote the code before the test? Delete it and start over from the test. Don't keep it "as reference" — you'll adapt it, and that is testing after. Delete means delete.

## Red → Green → Refactor

**RED — write one failing test.** One behaviour, a clear name, real code (no mocks unless unavoidable). It states what *should* happen, not what the code currently does.

**Verify RED — watch it fail. MANDATORY, never skip.** Run the focused test. Confirm it FAILS (not errors), and fails for the right reason — the feature is missing, not a typo. A test that passes immediately tests existing behaviour; fix the test. A test that errors needs the error fixed until it fails cleanly.

**GREEN — minimal code to pass.** The simplest thing that makes the test pass. No extra options, no speculative flags, no refactoring other code (YAGNI).

**Verify GREEN — watch it pass. MANDATORY.** Run the test: it passes, other tests still pass, output is pristine (no stray warnings). Test still fails? Fix the code, not the test.

**REFACTOR — clean up, stay green.** Remove duplication, improve names, extract helpers. Add no behaviour. Re-run; stay green. Then the next failing test.

## What a good test looks like

- **One thing.** An "and" in the test name means split it.
- **Clear name** describing the behaviour, not `test1`.
- **Real code, real assertions** — a test that asserts a mock was called tests the mock, not your code (see [testing-anti-patterns.md](testing-anti-patterns.md)).

## Why order matters

Tests written after the code pass immediately — and passing immediately proves nothing: the test may check the wrong thing, test the implementation instead of the behaviour, or miss the edge case you forgot. You never saw it catch anything. Test-first forces the test to fail once, proving it can.

## Rationalizations — each means STOP and start over

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. The test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Already manually tested it" | Ad-hoc, no record, can't re-run. |
| "Deleting my work is wasteful" | Sunk cost. Unverified code IS the waste. |
| "Keep it as reference" | You'll adapt it — that's testing after. Delete. |
| "TDD is dogmatic, I'm pragmatic" | TDD is pragmatic: bugs caught now beat debugging later. |
| "Hard to test" | Hard to test = hard to use. Listen to the test; simplify the design. |

## When stuck

| Problem | Fix |
|---------|-----|
| Don't know how to test it | Write the wished-for API call and assert on it first. |
| Test is too complicated | The design is too complicated. Simplify the interface. |
| Must mock everything | Too coupled. Use dependency injection. |

## Bug fixes

Found a bug? Write a failing test that reproduces it, then fix via the cycle. The test proves the fix and prevents the regression. Never fix a bug without a test.

## Done check

- Every new function/method has a test you watched fail first, for the right reason.
- Minimal code to pass; all tests green; output pristine.
- Tests use real code (mocks only if unavoidable); edge cases and errors covered.

Can't check all of these? You skipped TDD. Start over.
```

- [ ] **Step 2: Write the companion `skills/test-driven-development/testing-anti-patterns.md` with EXACTLY this content.**

```markdown
# Testing Anti-Patterns

Read this when adding mocks or test utilities. These are the ways a test can look green while proving nothing.

## Testing the mock instead of the code

A test that configures a mock to return X, runs the code, and asserts the mock returned X tests the mock framework, not your code. Assert on the *real behaviour or output* the code produces, not on "the mock was called". If the only thing you can assert is a mock interaction, the test is a tautology.

**Bad:** mock the dependency to resolve `'success'`, then assert the result is `'success'` — you asserted your own mock setup.
**Good:** drive real inputs through the code and assert the real result (e.g. "retries 3 times then returns success" with a counter, not a pre-scripted mock).

## Test-only methods on production classes

Adding a `reset()`, `_setState()`, or `getInternalsForTest()` to production code so a test can reach inside means the test is coupled to internals, and production now carries surface area that only tests use. Test through the public interface. If you can't, the design is too coupled — fix the design, not the test.

## Mocking without understanding the dependency

Mocking a collaborator whose real contract you haven't read produces a mock that behaves differently from the real thing — the test passes against a fiction. Before mocking, read the real dependency's contract (raise vs return, sync vs async, error shape). Prefer the real object or a thin fake that honours the contract over a mock that guesses it.
```

- [ ] **Step 3: Verify the skill is well-formed.**

```bash
cd /Users/harrison/Github/coderails
ls skills/test-driven-development/
echo "--- frontmatter (must be single-quoted description with the code-guard) ---"
sed -n '1,4p' skills/test-driven-development/SKILL.md
echo "--- code-guard present in description? (expect >=1) ---"
grep -c "Does NOT apply to docs, config, or prose" skills/test-driven-development/SKILL.md
echo "--- NO model-selection guidance (expect 0) ---"
grep -ciE "\bopus\b|most capable|model: (sonnet|opus|haiku)|model selection" skills/test-driven-development/SKILL.md
echo "--- NO superpowers reference (expect 0) ---"
grep -c "superpowers:" skills/test-driven-development/SKILL.md skills/test-driven-development/testing-anti-patterns.md
echo "--- focused length (expect <= ~140) ---"
wc -l skills/test-driven-development/SKILL.md
echo "--- companion linked + exists ---"
grep -c "testing-anti-patterns.md" skills/test-driven-development/SKILL.md
```
Expected: both files listed; line 2 is `name: test-driven-development`; line 3 is a single-quoted `description:` containing the code-guard (`Does NOT apply…` count ≥1); model-selection count = 0; superpowers count = 0; SKILL.md ≤ ~140 lines; companion link count ≥1.

- [ ] **Step 4: Confirm it loads as a plugin skill.**

```bash
cd /Users/harrison/Github/coderails
# frontmatter parses (name + single-quoted description, closed by ---):
awk 'NR==1&&$0=="---"{ok=1} /^name: test-driven-development$/{n=1} /^description: '"'"'/{d=1} NR>1&&$0=="---"{print (ok&&n&&d)?"FRONTMATTER OK":"FRONTMATTER BAD"; exit}' skills/test-driven-development/SKILL.md
```
Expected: `FRONTMATTER OK`. (No build step exists; `/reload-plugins` at runtime is how a live session would pick it up — note that, don't block on it.)

- [ ] **Step 5: Commit.**

```bash
cd /Users/harrison/Github/coderails
git add skills/test-driven-development/
git commit -m "feat(skills): vendor coderails:test-driven-development (+ testing-anti-patterns)"
```
(Auto-commit may have already captured it — "nothing to commit" is fine.)

---

### Task 2: Wire the code-guarded seam into agentic-loop Phase 3 and Phase 3a

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` (one bullet into the Phase 3 task-description list; one bullet placed high in the Phase 3a prompt-contract list)

**Interfaces:**
- Consumes: the skill name `coderails:test-driven-development` from Task 1.
- Produces: the construction seam. No downstream task.

- [ ] **Step 1: Add the construction-method bullet to the Phase 3 task-description checklist.**

In `skills/agentic-loop/SKILL.md`, the Phase 3 list begins `Each task description must be **self-contained**… Include:`. Insert a new bullet immediately AFTER the line `- Exact step-by-step sub-steps` and BEFORE `- Verify criteria`:

```
- Construction method — when the deliverable is code (the change adds or alters a function, method, or branch that *can* carry a test), instruct the worker to build it test-first via `coderails:test-driven-development` (failing test → minimal code → refactor). This holds even if the unit also touches non-code files. For pure docs/config/prose with no testable code, there is no test to write first — keep the verify-your-artifact contract.
```

- [ ] **Step 2: Add the construction-method bullet HIGH in the Phase 3a prompt-contract list.**

In Phase 3a, the prompt-contract list begins `The agent's prompt must be self-contained… and include:`. Insert a new bullet immediately AFTER the line `- The exact change to make, with file paths and the success criteria stated as something testable.` and BEFORE `- **A verify step the agent runs itself before reporting**…` (this places it near the top of the contract, per the Phase 9 placement lesson — construction method must register before the worker starts):

```
- **Construction method (when the deliverable is code).** If the change adds or alters a function, method, or branch that *can* carry a test, the worker builds it test-first via `coderails:test-driven-development`: write the failing test, watch it fail for the right reason, then the minimal code to pass, then refactor green — even if the PR also touches non-code files. For pure docs/config/prose with no testable code, there is no failing test to write first; the verify step below is by inspection instead.
```

- [ ] **Step 3: PRIMARY GATE — confirm no no-touch region was touched.**

```bash
cd /Users/harrison/Github/coderails
git --no-pager diff origin/main -- skills/agentic-loop/SKILL.md | grep -nE '^@@'
```
Expected: exactly two hunks, both inside Phase 3 (around the task-description list) and Phase 3a (around the prompt-contract list). Inspect each `@@` range and confirm neither overlaps any of the six no-touch regions. Then prove the most-adjacent ones unchanged:
```bash
O(){ git show origin/main:skills/agentic-loop/SKILL.md; }; C(){ cat skills/agentic-loop/SKILL.md; }
echo "frontmatter:"; diff <(O|sed -n '3p') <(C|sed -n '3p') && echo IDENTICAL
echo "Phase -2 block:"; diff <(O|sed -n '/^### Phase -2 /,/see the teardown rule below)\./p') <(C|sed -n '/^### Phase -2 /,/see the teardown rule below)\./p') && echo IDENTICAL
echo "persistence section:"; diff <(O|sed -n '/^## Context-window persistence/,/^## Stop conditions for the loop/p') <(C|sed -n '/^## Context-window persistence/,/^## Stop conditions for the loop/p') && echo IDENTICAL
echo "Declaring the stop block:"; diff <(O|sed -n '/Declaring the stop (the LOOP-STOP contract)/,/audit on that\./p') <(C|sed -n '/Declaring the stop (the LOOP-STOP contract)/,/audit on that\./p') && echo IDENTICAL
```
Expected: every `diff` prints `IDENTICAL`.

- [ ] **Step 4: Verify the seam — present, code-guarded, placed high, no dependency leak.**

```bash
cd /Users/harrison/Github/coderails
echo "--- references to the coderails skill (expect 2) ---"
grep -c "coderails:test-driven-development" skills/agentic-loop/SKILL.md
echo "--- each is code-guarded (expect 2 lines mentioning a testable function/method/branch) ---"
grep -c "can.* carry a test\|that \*can\* carry a test" skills/agentic-loop/SKILL.md
echo "--- no superpowers leak in the shipped seam (expect 0 new; pre-existing superpowers mentions elsewhere are fine) ---"
git --no-pager diff origin/main -- skills/agentic-loop/SKILL.md | grep -E '^\+' | grep -c "superpowers:"
echo "--- Phase 3a placement: TDD bullet appears BEFORE the 'verify step' bullet ---"
awk '/Construction method \(when the deliverable is code\)/{c=NR} /A verify step the agent runs itself/{v=NR} END{print (c>0 && c<v)?"PLACED HIGH (ok)":"NOT HIGH (fix)"}' skills/agentic-loop/SKILL.md
echo "--- sonnet-only rule still intact (expect the two model: sonnet contract lines) ---"
grep -c "model: sonnet" skills/agentic-loop/SKILL.md
```
Expected: 2 references; both code-guarded; 0 new `superpowers:` additions; `PLACED HIGH (ok)`; `model: sonnet` count unchanged from origin/main (re-run the same grep on `git show origin/main:…` to compare — must be equal).

- [ ] **Step 5: Hook suites still green (D is markdown-only).**

```bash
cd /Users/harrison/Github/coderails
for t in agentic_loop_path loop_state_guard loop_stall_guard; do printf '%-20s ' "$t:"; bash "hooks/scripts/tests/$t.test.sh" 2>&1 | grep -c '^ok'; done
```
Expected: `3`, `8`, `8`.

- [ ] **Step 6: Commit.**

```bash
cd /Users/harrison/Github/coderails
git add skills/agentic-loop/SKILL.md
git commit -m "feat(agentic-loop): wire code-guarded coderails:test-driven-development seam into Phase 3/3a"
```

---

## Self-Review

**Spec coverage:**
- Deliverable 1 (vendored skill + companion, focused, code-guarded description, no model guidance, no superpowers ref) → Task 1 (content + Step 3/4 checks). ✓
- Deliverable 2 (two code-guarded references, Phase 3a placed high) → Task 2 Steps 1–2, verified Step 4. ✓
- Constraint: sonnet-only untouched → Task 2 Step 4 (model: sonnet count compared to origin). ✓
- Constraint: six no-touch regions byte-identical → Task 2 Step 3 PRIMARY GATE. ✓
- Constraint: no cross-plugin dependency → Task 1 Step 3 (superpowers count 0) + Task 2 Step 4 (no new superpowers line). ✓
- Constraint: focused, single-quoted frontmatter → Task 1 Step 3/4. ✓
- Reachability (verified in spec) needs no task — it's an existing property of the skill. ✓
- Registration: none required (skills auto-discovered) — no task, correct. ✓

**Placeholder scan:** No TBD/TODO. Both new files have full content. Both seam bullets are given verbatim. All verification steps show exact commands + expected output. ✓

**Type consistency:** The skill name `test-driven-development` (invoked `coderails:test-driven-development`) is identical across Task 1 frontmatter, Task 2 bullets, and all greps. The code-guard phrase ("a function, method, or branch that can carry a test") is identical in the skill body, both seam bullets, and the Step-4 grep. ✓
