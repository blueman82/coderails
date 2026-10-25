# Model routing — stamp reference

This file gives the model and effort rules for Phase 2.8. Before workers
start, assign a role to each Phase 3 or 3a build task. Record the roles once
and use the role table. Consult this file when you write a `Model:` stamp or
decide if a task needs a higher verification_level. The last section explains
the orchestrator's model (Phase 0.4).

## Contents

- [`frontier` resolves to opus, never automatically to fable](#frontier-resolves-to-opus)
- [Effort is part of the stamp](#effort-is-part-of-the-stamp)
- [Investigations get frontier FIRST](#investigations-get-frontier-first)
- [Fallback valves live in the stamp](#fallback-valves-live-in-the-stamp)
- [Escalation is safe by construction](#escalation-is-safe-by-construction)
- [Inline sites elsewhere](#inline-sites-elsewhere)
- [The orchestrator's own model (Phase 0.4)](#the-orchestrators-own-model-phase-04)

## frontier resolves to opus

**Never select fable automatically.** Anthropic's model guidance assigns
complex agentic coding to Opus at `xhigh` effort. Fable targets
next-generation intelligence and costs about twice as much. The loop has no
authority to select the more costly model without notice.

Escalating a task to fable requires BOTH:

1. Record in the task's `Model:` stamp the capability that Opus at `xhigh`
   lacks for this task. The phrase "it is important" is not a reason.
2. The same fallback-valve discipline as every other stamp.

Tune effort first; escalate model second.

## Effort is part of the stamp

Tuning effort is often a better lever than switching models. Every `Model:` stamp names role AND
effort:

| Role | Effort | Rules |
|---|---|---|
| `frontier` | opus at `xhigh` | The documented best setting for coding and agentic work. `max` is a per-task escalation needing a named reason in the stamp, same discipline as a fable escalation. |
| `default` | sonnet at its default (`high`) | A stamp MAY lower a bounded, exact-recipe task to `medium` when the verify-criteria are mechanical (the gates catch a wrong answer cheaply). Never lower investigation or review tasks. |
| `fast-mechanical` | haiku | No effort parameter applies. |

The valve discipline is unchanged: an effort change mid-task that isn't named in the stamp does
not exist for the worker.

## Investigations get frontier FIRST

For an ambiguous investigation, start with `frontier`. A weaker investigator
can use time before it finds that it cannot complete the task. Then a second
agent must repeat the work. For other tasks, start with at least `default`.
Give a reason if you select `frontier`.

## Fallback valves live in the stamp

Set fallback conditions before a worker starts. For example, a task can use
`fast-mechanical` and switch to `default` after two failed gate attempts.
Write the exact condition in the plan's `Model:` stamp
(`superpowers:writing-plans`). For a loop that needs no plan.md, put it in the
task's `Model:` bullet (Phase 3/3a). The worker can use only a fallback named
in its prompt.

## Escalation is safe by construction

Routing controls cost and time. Every PR must clear the same review, eval, and
hook gates, regardless of the worker's model. A role mismatch alone does not
show a quality defect.

## Inline sites elsewhere

Phase 2.8 routes only Phase 3 and 3a build tasks. Assign roles for agents in
other phases when you spawn them. This includes the Phase 2 pre-flight agent,
the Phase 2.5 design agent, the Phase 2.6 disposition agent, and the Phase 9
wiki and docs agents. Use the Phase 2.8 role table and terms.

## The orchestrator's own model (Phase 0.4)

This section concerns the orchestrator's model. The sections above concern
worker models. On each turn, the orchestrator reads its growing context again.
Its cache-read costs add up through the session. Rates differ by model; see
`hooks/scripts/lib/model_prices.json` for current rates. The loop's
verification_level can change how much work the session does. In Phase 0.4,
the orchestrator tells the user about token use. Only
the user can type `/model` to change the orchestrator's model.
