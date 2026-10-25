---
name: Verify memory before acting on it
description: Memory records past truth — re-check current state before recommending or acting
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
Before using memory to recommend or act, check the current state. Read the
file, search for the symbol, check git, or query the resource. Memory records
what was true when written; it may no longer be current.

**Why:** A stale memory can make a past fact look current. A named file, function, or flag existed when the memory was written. It may not exist now. Acting on stale recall can lead to a wrong recommendation. The user flagged this on 2026-05-01.

**How to apply:** Verify memory before using it for a recommendation or action. In the same response, show the check that supports the cited memory. Use a file read, search, or Git output.
