---
name: premortem
description: 'Use this skill for premortem analysis: assume a plan, decision, or approach has already failed, then reason backwards to identify the failure modes and causes. Trigger on explicit premortem requests ("premortem this/X"), "steelman the failure", "what could go wrong with this plan", or requests to adversarially stress-test a specific commitment. The distinguishing signal is backwards reasoning from an assumed bad outcome — not forward-looking checklists ("what should I check before X"), code review, general architecture critique, or fact verification.'
---

# Premortem

For a premortem, assume the plan failed. Work backward to find why. Use
the findings before commitment, while you can still change the plan.

This skill works on plans, decisions, arguments, features, architectures, or your own previous response. The user may explicitly invoke it (`premortem this`, `premortem <X>`) or it may be appropriate to trigger it proactively before a high-stakes commitment.

---

## The process

### Step 1: Establish what's being premortemed

If the subject is clear from context, identify it directly. For example,
the user might ask you to assess a plan or your previous answer. If the
subject is unclear, ask: "What specifically should I premortem?"

### Step 2: Reason adversarially

Use a `<thinking>` block to reason before writing output. The goal is genuine adversarial thinking, not a checklist. Work through:

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

<thinking>
[adversarial reasoning — assumption failures, execution gaps, optimism bias, unknowns]
</thinking>

**Failure modes**

1. **[Name]** — [what goes wrong and why it's credible]
   - Likelihood: low/medium/high
   - Impact: [one line]
   - Mitigation: [concrete action or hedge]

2. **[Name]** — ...

[2–5 failure modes. More is usually noise.]

**Verdict**
[One short paragraph: is the plan sound? what's the most important thing to fix or watch?]
```

---

## What good looks like

- Failure modes are *specific to this plan*, not generic project risks copy-pasted from a template.
- Mitigations are *actionable*, not reassurances.
- The verdict is *direct* — it doesn't hedge by listing everything as "worth considering".
- If the plan is mostly fine, say so. A premortem that finds catastrophe in everything is as useless as one that finds nothing.

## What to avoid

- Generic risk lists ("team alignment", "scope creep", "technical debt") without grounding them in *this specific plan*.
- Softening a serious finding. State when an idea has a serious flaw.
- Exhaustive lists. Give a few specific failure modes.
