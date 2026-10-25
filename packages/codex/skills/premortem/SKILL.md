---
name: premortem
description: >-
  Assume a plan, decision, or approach has failed. Work backward to find
  the causes. Use this skill for "premortem this/X",
  "steelman the failure", "what could go wrong with this plan", or a
  request to stress-test a commitment.
  Do not use it for a forward-looking checklist, code review, architecture
  critique, or fact check.
---

# Premortem

For a premortem, assume the plan failed. Work backward to find why. Use
the findings before commitment, while you can still change the plan.

Apply this skill to a plan, decision, argument, feature, architecture, or
your previous response. Use it when the user asks for a premortem or
before a high-stakes commitment.

---

## The process

### Step 1: Establish what's being premortemed

If the subject is clear from context, identify it directly. For example,
the user might ask you to assess a plan or your previous answer. If the
subject is unclear, ask: "What specifically should I premortem?"

### Step 2: Reason adversarially

Examine the plan from an adversarial position. Consider these sources of
failure. Show the user the selected failure modes and supporting facts,
not a private reasoning block:

- **Assumptions:** Which assumption might be false?
- **Execution:** Where could execution fail, even with a sound plan?
- **People:** Who might resist, disengage, or act differently?
- **Dependencies:** Which external condition might change or fail?
- **Optimism:** Where does the plan assume too much success?
- **Unknown factors:** What has the plan not considered?
- **Timing:** Which sequence or deadline could slip?

Select the most plausible and consequential failures. Keep the list short
and specific.

### Step 3: Assess each failure

For each significant failure mode, give a brief verdict:
- **Likelihood**: low / medium / high (use judgment)
- **Impact**: if it happens, how bad?
- **Mitigation**: what would actually reduce this risk?

Give an action that reduces the risk. "Monitor closely" does not do this.
"Add a circuit breaker" and "validate assumption X before commitment"
are concrete actions.

### Step 4: Verdict

End with one direct verdict:
- Is this plan basically sound with specific risks to address?
- Are there structural problems that should reshape the plan?
- Is there a fatal flaw that makes the plan unlikely to succeed as stated?

If you assess your own answer, say so. Update your recommendation if needed.

---

## Output format

```
**Premortem: [what's being assessed]**

**Failure modes**

1. **[Name]** — [what goes wrong and why it's credible]
   - Likelihood: low/medium/high
   - Impact: [one line]
   - Mitigation: [concrete action or hedge]

2. **[Name]** — ...

[2–5 failure modes. More is usually noise.]

**Verdict**
[One short paragraph. Is the plan sound? Name the first issue to fix or watch.]
```

---

## What good looks like

- Failure modes refer to this plan and its evidence.
- Mitigations are *actionable*, not reassurances.
- The verdict states the main risk directly.
- If the plan is mostly sound, say so. Do not invent a severe failure.

## What to avoid

- Generic risk lists ("team alignment", "scope creep", "technical debt") without grounding them in *this specific plan*.
- Softening a serious finding. State when an idea has a serious flaw.
- Exhaustive lists. Give a few specific failure modes.
