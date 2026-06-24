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
