---
name: Auto mode escalates to user after 3 retries
description: In auto mode, after 3 failed attempts at the same action or goal, stop retrying and escalate to the user via AskUserQuestion
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
In auto mode, count failed attempts at each action, command, or goal. After
three failures at the same target, stop retrying and ask the user how to
proceed via AskUserQuestion.

**Why:** Auto mode's bias toward action becomes harmful when an action keeps failing — repeated retries waste tokens, hide root cause, and may mask a structural blocker (permission, missing config, broken assumption). The user established this rule on 2026-05-01 after observing retry-heavy behavior during the self-checking-loop build.

**How to apply:** Track retry count per discrete action/goal in auto mode. After the 3rd failure, surface what was tried, why each attempt failed, and ask the user how to proceed. Counter resets on a different action or user input.
