---
name: Cite or label every non-trivial claim
description: Source-cited claims are verifiable; bare assertions are not — force one or the other
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
For every non-trivial claim, cite a source or label the claim `(inferred)`.
Sources include `file:line`, tool output, an exact quote, or a git reference.
Apply this to claims about code, files, behavior, and external state.

**Why:** The user cannot check a bare assertion. A cited claim can pass or fail a source check. The user requested this rule on 2026-05-01 to make output trustworthy.

**How to apply:** Use this for claims about code, files, functions, APIs, or external state. Cite `path/file.py:42`, a tool result, or a user statement. Otherwise add `(inferred)`.
