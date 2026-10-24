---
name: Auto mode escalates to user after 3 retries
description: In auto mode, after 3 failed attempts at the same action or goal, stop retrying and escalate to the user via AskUserQuestion
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---
In auto mode, count failed attempts at each action, command, or goal. After
three failures at the same target, stop retrying and ask the user how to
proceed via AskUserQuestion.

**Why:** Repeated failures can make auto mode waste tokens and hide the cause. A permission, missing configuration, or wrong assumption may block the action. The user set this rule on 2026-05-01 after repeated retries in the self-checking-loop build.

**How to apply:** Count retries for each action or goal in auto mode. After the third failure, report each attempt and its cause. Ask the user how to proceed. Reset the count for a different action or after user input.
