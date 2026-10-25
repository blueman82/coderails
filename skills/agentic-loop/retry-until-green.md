# Retry-until-green

This rule applies to the `U5 -> U5-repair -> U4` graph edge. Use it before
hard-stop #1 in the main skill.

A failed test, lint check, or verification check alone is not a reason to stop.
Find the cause, fix it, and check again. Make at most five distinct fix attempts
per failure by default. A repeat of the same fix without a new diagnosis does
not count as a new attempt or advance the edge.

Use hard-stop #1 only if the failure remains after the attempt limit. The
limit prevents an endless cycle on a broken or incorrect test. Record each
attempt's diagnosis through the supported graph command so the hard-stop
report shows all attempts. Do not edit `progress.json` by hand.

**For independent failures, use `superpowers:dispatching-parallel-agents`.**
If one test run finds unrelated failures in two or more files or subsystems,
give each failure to one focused `general-purpose` agent. Give each agent the
instructions in `agents/loop-worker.md`. Assign separate files and tell each
agent not to change other code. Each agent must write the failing test first
and verify its fix. Integrate the fixes and run the full suite again.

Each independent failure has its own five-attempt limit. Keep related
failures together when one fix could resolve the others.

**If the cause is unclear, use `superpowers:systematic-debugging`.** If the
first attempt does not identify the cause, invoke this skill before the second
attempt. Phase 5 first checks that the bug exists. Systematic debugging then
investigates the confirmed failure. Count each debugging invocation toward
the five-attempt limit.
