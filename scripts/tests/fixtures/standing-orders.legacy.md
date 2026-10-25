# Standing Orders (repo-key: -Users-garyharr-Github-coderails-.git)

Failure modes observed in past agentic loops for this repo. Additive-or-recurrence-only: a match resets `loops_since_recurrence` to 0; a non-matched entry increments; an entry moves to `standing-orders-decayed.md` at K=5 (tombstone, never deleted).

## Entry: subagent-final-report-truncated-to-dnv-correction
- **loops_since_recurrence:** 0
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** A dispatched subagent's OWN verify-loop Stop hook fires mid-report, and the final message to the orchestrator ends up being only the hook-triggered correction.
- **Mitigation that worked:** Instruct every dispatched agent: "send your COMPLETE report in ONE message". When it recurs, SendMessage the agent to resend the complete report.
- **Detection:** A task-notification result that reads like a standalone DNV-fix is truncated, not "no findings."

## Entry: verification-ceiling-counter-shared-across-context-not-reset-by-delegation
- **loops_since_recurrence:** 2
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** The volume ceiling hard-blocks the 3rd same-command invocation per branch, keyed by a counter file, not by agent; a fresh subagent shares the counter.
- **Mitigation that worked:** Stop re-running a validation command that already passed; proceed on the genuine prior evidence and disclose it.

## Entry: standing-crack-on-envelope-does-not-pre-authorize-individual-merges
- **loops_since_recurrence:** 0
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** The auto-mode classifier denies merges lacking a fresh PR-specific instruction, even inside a granted autonomous envelope.
- **Mitigation that worked:** Treat each PR's merge as needing its own explicit sign-off turn.

## Entry: dispatch-prompt-must-explicitly-instruct-worktree-isolation-even-for-audit-tasks
- **loops_since_recurrence:** 4
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** An audit agent edited a file directly on the shared main checkout because the dispatch prompt never told it to isolate.
- **Mitigation that worked:** Any dispatch that may write to a checkout must instruct worktree isolation in the prompt.

## Entry: hardcoded-default-literal-can-have-more-than-one-stale-copy
- **loops_since_recurrence:** 1
- **First observed:** session 51f0b168-4b09-471a-96c0-2b5e9d7add89
- **Pattern:** A stub template drifted from the doc default; a reviewer found a second stale copy of the same literal in another file.
- **Mitigation that worked:** Repo-wide grep for the same literal before calling a drift fix complete.
