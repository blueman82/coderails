# Retry-until-green

Not a stop condition — applies BEFORE hard-stop #1 in the main skill's stop-conditions section.

A single failing test, lint error, or verification check is not, by itself, a reason to stop and
ask. Diagnose the failure, fix it, re-verify — in a tight cycle — the same way a human engineer
would iterate on their own failing test, up to a bounded number of attempts (default: 5 distinct
fix attempts per failure; re-trying the identical fix without a new diagnosis does not count as a
new attempt). Only escalate to hard-stop #1 once that bound is exhausted and the failure still
reproduces — at that point it has stopped being "a bug to fix" and become "a wall to report." The
bound exists so retry-until-green cannot become an infinite loop against a fundamentally broken or
mis-specified test; hitting it is itself useful information for the human, not a failure of the
loop. Log each attempt's diagnosis in `progress.json` so the eventual hard-stop report (if reached)
shows the exhausted attempts, not just the final failure.

**Multiple independent failures — use `coderails:dispatching-parallel-agents`.** When a
verification failure turns out to be multiple independent broken things, don't fix them one at a
time. A single test run failing across 2+ unrelated files/subsystems with different root causes
(not "fixing one might fix the others") is exactly that skill's trigger condition. Dispatch one
focused agent per independent failure domain, in parallel, each scoped to its own file/subsystem
with an explicit "don't touch other code" constraint; integrate and re-run the full suite once
they all report back. This is a parallelisation tactic inside one retry-until-green cycle, not a
substitute for it — the bound is per failure (as stated above), so each independent failure domain
gets its own 5-attempt budget, not a pool shared or split across the dispatched agents. A
genuinely single, related failure (fixing one thing likely fixes the rest) should NOT be split
into parallel agents — that's this skill's own explicit "don't use when" case.

**Cause not obvious — use `coderails:systematic-debugging`.** "Diagnose" above is not "try
something plausible." If the first fix attempt doesn't make the cause clear, the second attempt
should be preceded by an actual `coderails:systematic-debugging` invocation rather than another ad
hoc guess. This is distinct from Phase 5's premise-disproven check: Phase 5 asks "does this bug
exist at all, verified against source-of-truth" *before* any fix work starts;
`systematic-debugging` is *how* to investigate a confirmed, reproducing failure once inside the
retry cycle. A guessed fix that happens to pass does not excuse skipping this — it just means the
next unrelated failure gets the same undisciplined treatment. Each `systematic-debugging`
invocation still counts toward the 5-attempt bound; it makes the attempts count for more, not more
of them.
