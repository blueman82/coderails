---
name: Cite or label every non-trivial claim
description: Source-cited claims are verifiable; bare assertions are not — force one or the other
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
For every non-trivial claim, cite a source or label the claim `(inferred)`.
Sources include `file:line`, tool output, an exact quote, or a git reference.
Apply this to claims about code, files, behavior, and external state.

**Why:** Bare assertions are unverifiable by the user and indistinguishable from hallucination. Cited claims either hold up under check or fail visibly. The user requested this on 2026-05-01 as the core mechanic for trustable output.

**How to apply:** Any response asserting something about the codebase, files, function behavior, API shape, or external state. Acceptable forms: `path/file.py:42`, "tool returned X", quoted user statement, or explicit `(inferred)` tag.
