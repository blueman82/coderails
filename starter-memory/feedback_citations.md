---
name: Cite or label every non-trivial claim
description: Source-cited claims are verifiable; bare assertions are not — force one or the other
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
Every non-trivial claim cites its source — `file:line`, tool output, exact quote, or git reference — or labels itself `(inferred)`. No bare assertions about code, files, behavior, or external state.

**Why:** Bare assertions are unverifiable by the user and indistinguishable from hallucination. Cited claims either hold up under check or fail visibly. The user requested this on 2026-05-01 as the core mechanic for trustable output.

**How to apply:** Any response asserting something about the codebase, files, function behavior, API shape, or external state. Acceptable forms: `path/file.py:42`, "tool returned X", quoted user statement, or explicit `(inferred)` tag.
