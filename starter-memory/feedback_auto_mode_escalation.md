---
name: Auto mode escalates to user after 3 retries
description: In auto mode, after 3 failed attempts at the same action or goal, stop retrying and escalate to the user via AskUserQuestion
type: feedback
originSessionId: 445479ca-d469-4749-b261-83394794c9a4
---

In auto mode, stop retrying if the same step, command, or goal does not succeed after three runs. Use `AskUserQuestion` to get the user's next instruction.

**Why**. To retry many times uses tokens and can hide the cause. The cause can be a permission problem, missing config, or an incorrect assumption. The user set this rule on 2026-05-01 after they saw many retries during the self-checking-loop build.

**When to apply**. Count retries for each step or goal in auto mode. After the third unsuccessful run, say what you tried and why each run did not succeed. Use `AskUserQuestion` to get the user's next instruction. Set the count to 0 for a different step or after user input.
