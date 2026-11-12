---
name: Cite or label every non-trivial claim
description: Source-cited claims are verifiable; bare assertions are not — force one or the other
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---

For each substantive claim, cite its source or label it `(inferred)`. Use a `file:line` citation, tool output, verbatim quote, or Git identifier. Give that basis for claims about code, files, behavior, or external conditions.

**Why**. The user cannot check claims with no cited basis. With a citation, the user can check the claim and find errors. On 2026-05-01 the user identified this rule as central to results they can trust.

**When to apply**. Use this rule in replies about code, files, function behavior, API shape, or external conditions. Examples are `path/file.py:42`, tool output, a statement from the user, or an explicit `(inferred)` tag.
