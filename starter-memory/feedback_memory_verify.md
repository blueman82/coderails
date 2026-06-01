---
name: Verify memory before acting on it
description: Memory records past truth — re-check current state before recommending or acting
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
Before recommending or acting on anything cited from memory, verify against current state — read the file, grep for the symbol, check git, query the resource. Memory records what was true at write-time, not necessarily now.

**Why:** Stale memory presented as current is a top failure mode. A memory naming a file, function, or flag is a claim that it existed when written, not that it exists now. Acting on stale recall produces confidently-wrong recommendations. The user flagged this on 2026-05-01 as a structural gap.

**How to apply:** Every time memory content is used as the basis for a recommendation or an action. Single-turn verification: the same response that cites the memory must also show the verification step (Read, Grep, or git output).
