# Model routing — stamp reference

This file gives the model and `effort` rules for Phase 2.8. Before workers start, give each Phase 3 or 3a build task a role from the table. Record the roles one time.

Read this file before you write a `Model:` stamp or consider a higher verification_level. See the last section for the orchestrator’s model (Phase 0.4).

## Contents

- [`frontier` resolves to opus by default](#frontier-resolves-to-opus)
- [Include `effort` in the stamp](#effort-is-part-of-the-stamp)
- [Investigations get frontier FIRST](#investigations-get-frontier-first)
- [Fallback valves live in the stamp](#fallback-valves-live-in-the-stamp)
- [Escalation is safe by construction](#escalation-is-safe-by-construction)
- [Inline sites elsewhere](#inline-sites-elsewhere)
- [The orchestrator's own model (Phase 0.4)](#the-orchestrators-own-model-phase-04)

## frontier resolves to opus

**Do not select fable automatically.** Anthropic's model-selection guidance recommends Opus at `xhigh` for complex agentic coding. Fable targets next-generation intelligence and costs about two times as much. The loop has no authority to select the most expensive model silently.

To escalate a task to fable, meet the two conditions below.

1. In the task’s `Model:` stamp, identify the function that the task requires and Opus at `xhigh` cannot supply. A claim that "it is important" does not satisfy this condition.
2. The same fallback-valve discipline as each other stamp.

Adjust `effort` first. Then escalate the model if necessary.

## Effort is part of the stamp

Changing `effort` can give better results than changing models. Each `Model:` stamp gives the role and `effort`.

| Role | `effort` | Rules |
|---|---|---|
| `frontier` | opus at `xhigh` | The documented best setting for coding and agentic work. For a task to use `max`, give the justification in the stamp as for a fable escalation. |
| `default` | sonnet at its default (`high`) | Use `medium` only if the task has a fixed scope and procedure, and mechanical checks catch errors at low cost. Do not lower the setting for investigations or reviewer tasks. |
| `fast-mechanical` | haiku | No `effort` parameter applies. |

During a task, the worker can change `effort` only as specified in the stamp.

## Investigations get frontier FIRST

Start with `frontier` for a genuinely ambiguous investigation. A weaker model can spend more time before it finds it cannot solve the problem. A second run then does the work again. For other tasks, `default` is the minimum. Give a justification to use `frontier`.

## Fallback valves live in the stamp

Workers must use only the fallback in their prompt. For example, use "fast-mechanical; default fallback after two failed gate attempts".

Write the full fallback condition in the plan’s `Model:` stamp (`superpowers:writing-plans`). For a loop below the plan.md threshold, put it in the task description’s `Model:` bullet (Phase 3/3a).

## Escalation is safe by construction

Routing controls cost and latency. The PR gates for reviewer checks, evals, and hook checks apply to all models. A `frontier` worker’s PR and a `default` worker’s PR must clear the same gates. Do not infer a quality risk from a role mismatch alone.

## Inline sites elsewhere

Phase 2.8 sets roles only for Phase 3/3a *build* tasks. Give each other agent a role from the Phase 2.8 table when you start it. This applies to Phase 2 preflight, Phase 2.5 design decisions, Phase 2.6 retirement decisions, and Phase 9 wiki and sync-docs agents.

## The orchestrator's own model (Phase 0.4)

Phase 0.4 concerns the orchestrator’s model. The `Model:` stamp applies to workers. The orchestrator reads its full context again on each turn. As context grows, the model’s cache-read charges add up across the session.

The rates can be very different for each verification_level. See `hooks/scripts/lib/model_prices.json` for current rates by model. Only the user can type `/model`. This cost explains the notice to the user in Phase 0.4.
