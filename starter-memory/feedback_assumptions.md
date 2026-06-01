---
name: Surface assumptions before acting
description: Forces silent inference to be labeled rather than hidden inside confident prose
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
Before non-trivial actions or claims, list assumptions explicitly and mark each as `verified` (directly observed this session via tool result, file read, or user statement) or `inferred` (pattern-matched from training, recall, or context).

**Why:** Silent inference is the dominant failure mode. Wrapping a guess in confident prose makes it indistinguishable from a verified fact. The user identified this in the recursive critique on 2026-05-01 and explicitly requested mechanical surfacing of inference.

**How to apply:** Any multi-step task. Any claim about file paths, function names, behavior, or external state that isn't directly observed in this session. Output the assumption list before acting; do not bury it in narrative.
