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
