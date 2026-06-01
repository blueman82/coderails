---
name: premortem
description: Use this skill for premortem analysis: assume a plan, decision, or approach has already failed, then reason backwards to identify the failure modes and causes. Trigger on explicit premortem requests ("premortem this/X"), "steelman the failure", "what could go wrong with this plan", or requests to adversarially stress-test a specific commitment. The distinguishing signal is backwards reasoning from an assumed bad outcome — not forward-looking checklists ("what should I check before X"), code review, general architecture critique, or fact verification.
---

# Premortem

A premortem is a planning technique where you assume something has already failed — then work backwards to find out why. It's the opposite of a postmortem. The goal is to surface failure modes *before* you commit, while you can still act on them.

This skill works on plans, decisions, arguments, features, architectures, or your own previous response. The user may explicitly invoke it (`premortem this`, `premortem <X>`) or it may be appropriate to trigger it proactively before a high-stakes commitment.

---

## The process

### Step 1: Establish what's being premortemed

If it's clear from context (e.g., the user just made a plan, or said "premortem your answer"), extract it directly — don't ask. If genuinely ambiguous, ask one question: "What specifically should I premortem?"

### Step 2: Reason adversarially

Use a `<thinking>` block to reason before writing output. The goal is genuine adversarial thinking, not a checklist. Work through:

- **Assumption failures**: what does this plan assume that might not be true?
- **Execution failures**: even if the plan is sound, where could the execution break down?
- **People failures**: who might resist, disengage, or behave differently than expected?
- **Dependency failures**: what external things does this rely on that could change or fail?
- **Optimism bias**: where is the plan unduly optimistic? What's being glossed over?
- **Unknown unknowns**: what hasn't been considered at all?
- **Timing failures**: what's sensitive to sequencing or deadlines that could slip?

Don't be comprehensive for its own sake. Surface the *most credible* failure modes — the ones that are both plausible and consequential. A few sharp ones beat a long generic list.

### Step 3: Assess each failure

For each significant failure mode, give a brief verdict:
- **Likelihood**: low / medium / high (use judgment, not pseudoscience)
- **Impact**: if it happens, how bad?
- **Mitigation**: what would actually reduce this risk?

Keep mitigations honest. "Monitor closely" is not a mitigation. "Add a circuit breaker here" or "validate assumption X before committing" are.

### Step 4: Verdict

End with a crisp bottom line:
- Is this plan basically sound with specific risks to address?
- Are there structural problems that should reshape the plan?
- Is there a fatal flaw that makes the plan unlikely to succeed as stated?

If you're premortemed your own answer, say so explicitly and update your recommendation if warranted.

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
- Polite softening. The value of a premortem is honest adversarial thinking — if something is a bad idea, say so.
- Exhaustive lists. Five sharp failure modes are more useful than fifteen shallow ones.
