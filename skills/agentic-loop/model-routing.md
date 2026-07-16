# Model routing — stamp reference

Detail-carrier for Phase 2.8. The main skill keeps the imperative (assign a role to every Phase
3/3a build task before any worker spawns, record the set once, use the role table); this file is
the escalation and effort rules you consult **when writing a `Model:` stamp** or deciding whether
a task justifies a stronger tier.

## Contents

- [`frontier` resolves to opus, never automatically to fable](#frontier-resolves-to-opus)
- [Effort is part of the stamp](#effort-is-part-of-the-stamp)
- [Investigations get frontier FIRST](#investigations-get-frontier-first)
- [Fallback valves live in the stamp](#fallback-valves-live-in-the-stamp)
- [Escalation is safe by construction](#escalation-is-safe-by-construction)
- [Inline sites elsewhere](#inline-sites-elsewhere)

## frontier resolves to opus

**Never automatically to fable.** Anthropic's model-selection guidance places complex agentic
coding on Opus at `xhigh` effort; Fable targets next-generation-intelligence needs at roughly
twice the price. Auto-picking the most expensive model is a cost decision the loop has no
authority to make silently.

Escalating a task to fable requires BOTH:

1. A named reason why opus-at-`xhigh` is insufficient for that specific task — not "it's
   important", but *what capability is missing* — recorded in the task's `Model:` stamp.
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

Not escalated-to. For a genuinely ambiguous investigation, spawn `frontier` from the start — a
weak investigator burns wall-clock discovering it's out of its depth, then a second run re-does
the work anyway. This is the one place `default`-first cost control does not apply; everywhere
else `default` is the floor and `frontier` needs a reason.

## Fallback valves live in the stamp

Never improvised by a worker. If a task needs an escape hatch (e.g. "fast-mechanical; default
fallback after two failed gate attempts"), write the exact valve condition into the plan's
`Model:` stamp (`coderails:writing-plans`) or, for a loop below the plan.md threshold, into the
task description's `Model:` bullet (Phase 3/3a). The valve must already be named in the prompt, or
it does not exist for the worker.

## Escalation is safe by construction

Not a correctness control. PR gates (review, evals, hook-seam) are model-independent — a
`frontier` worker's PR clears the same gates a `default` worker's PR does. Routing exists for cost
and latency, never for correctness; do not read a role mismatch as a quality risk in itself.

## Inline sites elsewhere

Phase 2.8 routes Phase 3/3a *build* tasks only. Agents spawned at other phases — the Phase 2
pre-flight agent, the Phase 2.5 design-fork agent, and Phase 9's wiki and sync-docs delegates —
are each assigned their role inline at their own spawn point, using Phase 2.8's vocabulary and
table.
