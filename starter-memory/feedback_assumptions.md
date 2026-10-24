---
name: Surface assumptions before acting
description: Forces silent inference to be labeled rather than hidden inside confident prose
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
Before non-trivial actions or claims, list assumptions. Mark each `verified`
when a tool result, file read, or user statement confirms it in this session.
Mark each `inferred` when it comes from training, recall, or context.

**Why:** Silent inference is the main failure mode. Confident prose can make a guess look verified. The user identified this in the recursive critique on 2026-05-01. They asked for explicit inference labels.

**How to apply:** Use this for any multi-step task. Use it for claims about paths, functions, behavior, or external state that this session did not observe. List assumptions before acting. Do not hide them in narrative.
