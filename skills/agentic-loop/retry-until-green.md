# Retry-until-green

Use this procedure for the `U5 -> U5-repair -> U4` edge in the execution graph.
It applies before hard-stop #1 in the skill's stop-conditions section.

Continue this procedure if the only problem is a test, lint, or verification check that fails.
Find the cause, correct the problem, and run the check again.
The default limit is five different corrections for each problem.
If you try the same correction without new information about the cause, it does not count as a new try.
It does not move the graph to the next node.

If you use all the tries and can reproduce the problem again, use hard-stop #1.
The limit prevents an endless loop if a test is broken or its specification is incorrect.
Report that you used all the tries.

In `progress.json`, record the cause you checked on each try.
In the hard-stop report, include the full record of tries and the last result.

**If problems have different causes, use `superpowers:dispatching-parallel-agents`.**
For example, one test run can report problems in two or more unrelated files or subsystems.
If "fixing one might fix the others", correct the shared cause as one task.
This is the skill's "don't use when" condition.

For problems with different causes, start one agent for each group that can be corrected independently.
Start them in parallel as `subagent_type: general-purpose`.
Include the instructions from `agents/loop-worker.md` and the scope for that file or subsystem.
Specify "don't touch other code".
After all agents report, integrate the corrections and run the full suite again.

Use this parallel work as part of one retry-until-green cycle.
Each problem has its own limit of five tries.
Do not share that limit across agents.

Do not use generic agents without the loop-worker instructions.
Each agent must write the test first and check its result before it reports.

**If the cause is unclear, use `superpowers:systematic-debugging`.**
"Diagnose" does not mean "try something plausible."
If the first correction does not show the cause, invoke `superpowers:systematic-debugging` before you try the second correction.
Do not make an ad hoc guess.

In Phase 5, check "does this bug exist at all, verified against source-of-truth" before you start work on a correction.
Use `superpowers:systematic-debugging` during the retry cycle to find the cause of a problem you checked and can reproduce.
A guess can make a check succeed when you do not know the cause.
It does not remove the need to use the skill.
Count each `superpowers:systematic-debugging` invocation as one of the five tries.
