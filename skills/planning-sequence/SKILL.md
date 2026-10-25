---
name: planning-sequence
description: >-
  Run Pre-Parade, Premortem, and Red Team on a plan, idea, or decision.
  Trigger phrases include "run the planning sequence", "put this through
  the planning techniques", "stress-test my plan", and "Pre-Parade this".
  Use it for analysis before a major decision. Also use it before
  a high-stakes commitment without adversarial planning. Run the stages
  in order: success conditions, failure modes, and adversarial challenge.
effort: high
---

# Planning Sequence

Run three checks on the same plan, idea, or decision. First identify the
conditions for success. Then identify credible failures. Last, test the
plan against an opponent or constraint. Use facts about this plan.

## Identify the subject

Use the subject the user named. If none is named, identify it from the
conversation. Ask one short question only if the subject remains unclear.
State the subject in one sentence at the start of the report.

## Stage 1: Pre-Parade

Imagine that the plan succeeded one year from now.

1. State that success in one sentence.
2. List three to five conditions that made it possible.
3. Mark each condition `in place`, `missing`, or `uncertain` now.
4. Name the gaps that need work.

Use conditions that someone can check, such as an API contract with a named
owner. Do not use general claims such as "the team communicated well".

## Stage 2: Premortem

Assume that the plan failed. Find the most credible causes. Check its
assumptions, execution, people, dependencies, timing, and unknown factors.
Include behavior that could differ from the plan.

1. State the failure scenario in one sentence.
2. Give two to four failure modes. For each, state its cause, likelihood
   (`low`, `medium`, or `high`), impact, and a concrete mitigation.
3. Say whether the plan has risks to address or a structural problem.

Do not turn every possible failure into a catastrophe. Tie each one to
evidence or a clear assumption.

## Stage 3: Red Team

Select the strongest credible opponent or constraint. It can be a
competitor, an internal sceptic, a regulator, a technical limit, or a market
force. Give two or three specific attacks on the plan's weak points.

For each attack, state what the opponent does or says and what damage it
causes. Then state what the plan owner must change or prove. Use a different
angle from the Premortem: test an active challenge rather than an accidental
failure.

## Synthesis

Write three to five sentences. Name risks that appear in more than one
stage, what the Pre-Parade found on its own, and the first issue to address.
Choose one clear priority action.

## Output format

```markdown
## Stage 1: Pre-Parade
**Success scenario:** ...
**Conditions:**
1. ... — in place / missing / uncertain
**Gaps to address:** ...

## Stage 2: Premortem
**Failure scenario:** ...
**Failure modes:**
1. ... — Cause: ...; Likelihood: ...; Impact: ...; Mitigation: ...
**Verdict:** ...

## Stage 3: Red Team
**Adversary:** ...
**Attacks:**
1. ... — Damage: ...
**Challenge:** ...

## Synthesis
...
```
