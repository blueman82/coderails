# Retry-until-green

This rule applies to the `U5 -> U5-repair -> U4` graph edge. Use it before
hard-stop #1 in the main skill.

A failed test, lint check, or verification check alone is not a reason to stop.
Find the cause, fix it, and check again. The graph allows at most five
distinct recorded repairs per work unit. A repeat with the same repair kind
and identity does not count or advance the edge.

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

The graph shares one five-repair limit across a work unit, even if that unit
has independent failures. Keep related failures together when one fix could
resolve the others.

**If the cause is unclear, use `superpowers:systematic-debugging`.** If the
first attempt does not identify the cause, invoke this skill before the next
repair. Phase 5 first checks that the bug exists. Systematic debugging then
investigates the confirmed failure. A diagnosis alone does not advance the
graph repair count. Record a distinct source, artifact, or check repair
through `graph.py record-repair` after the failed unit gate.
