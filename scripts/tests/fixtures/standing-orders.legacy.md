# Standing Orders (repo-key: -Users-garyharr-Github-coderails-.git)

These entries record problems from earlier agentic loops. Add entries or update their counters when a problem occurs again. A match resets `loops_since_recurrence` to 0. If there is no match, increase the counter. At K=5, move the entry to `standing-orders-decayed.md` and keep its tombstone.

## Entry: subagent-final-report-truncated-to-dnv-correction
- **loops_since_recurrence:** 0
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** The subagent's own verify-loop Stop hook runs during its report. The orchestrator gets only the correction that the hook caused.
- **Mitigation that worked:** Tell each agent "send your COMPLETE report in ONE message". If it occurs again, use `SendMessage` to tell the agent to send the complete report.
- **Detection:** A task notification with only a DNV correction is an unfinished report. Do not record it as "no findings."

## Entry: verification-ceiling-counter-shared-across-context-not-reset-by-delegation
- **loops_since_recurrence:** 2
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** The volume ceiling blocks the third run of the same command on a branch. It uses a counter file. A new subagent uses the same counter.
- **Mitigation that worked:** If a validation command passed, use its result and report which run it came from. Do not run it again.

## Entry: standing-crack-on-envelope-does-not-pre-authorize-individual-merges
- **loops_since_recurrence:** 0
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** The auto-mode classifier denies a merge without a new instruction for that PR. An autonomous envelope does not remove this requirement.
- **Mitigation that worked:** Get explicit approval for each PR's merge in its own turn.

## Entry: dispatch-prompt-must-explicitly-instruct-worktree-isolation-even-for-audit-tasks
- **loops_since_recurrence:** 4
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** An audit agent edited a file in the shared `main` checkout. The dispatch prompt did not tell it to use its own worktree.
- **Mitigation that worked:** If a dispatched agent can write to a checkout, tell it to use its own worktree.

## Entry: hardcoded-default-literal-can-have-more-than-one-stale-copy
- **loops_since_recurrence:** 1
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** A stub template used a different default from the documentation. A reviewer found the same outdated value in a different file.
- **Mitigation that worked:** Use `grep` on the full repository for the same literal before you report the repair as complete.
