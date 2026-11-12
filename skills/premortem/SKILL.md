---
name: premortem
description: 'Use this skill for premortem analysis: assume a plan, decision, or approach has already failed, then reason backwards to identify the failure modes and causes. Trigger on explicit premortem requests ("premortem this/X"), "steelman the failure", "what could go wrong with this plan", or requests to adversarially stress-test a specific commitment. The distinguishing signal is backwards reasoning from an assumed bad outcome — not forward-looking checklists ("what should I check before X"), code review, general architecture critique, or fact verification.'
effort: high
---

# Premortem

For a premortem, start with the assumption that the plan did not succeed. Find the causes of that outcome. Use the results to change the plan before you commit to it.

This skill works on plans, decisions, arguments, features, architectures, or your own previous response. The user can invoke it directly (`premortem this`, `premortem <X>`). You can also use it before a high-stakes commitment.

---

## The process

### Step 1: Establish what's being premortemed

If the subject is clear from context, identify it directly. For example,
the user might want you to check a plan or your previous answer. If the
subject is unclear, ask: "What specifically should I premortem?"

### Step 2: Reason adversarially

Use a `<thinking>` block before you write the output. Use these questions to find where the plan could break.

- **Assumptions:** Which assumption might be incorrect?
- **Execution:** Where could a sound plan break during execution?
- **Participants:** Who might resist, disengage, or act differently?
- **Dependencies:** Which external condition might change or fail?
- **Optimism:** Where does the plan assume too much success?
- **Unknowns:** What does the plan omit?
- **Timing:** Which sequence or deadline could slip?

Select the problems that are most likely and would cause the most damage. Keep the list short and connect each item to the plan.

### Step 3: Assess each failure

Give a brief verdict for each important problem.
- **Likelihood**: use judgment to select `low`, `medium`, or `high`.
- **`Impact`**: how much damage could it cause?
- **Mitigation**: what would actually reduce this risk?

Give a step that reduces the risk. "Monitor closely" does not do this.
"Add a circuit breaker" and "validate assumption X before commitment"
are concrete steps.

### Step 4: Verdict

End with one clear verdict.
- Can the plan succeed if you correct the listed risks?
- Are there structural problems that should reshape the plan?
- Does a defect make the plan unlikely to succeed as specified?

If you check your own answer, say so. Update your recommendation if needed.

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

- Connect each problem to this plan.
- Mitigations are *actionable*, not reassurances.
- Give a clear verdict. Do not list all problems as "worth considering".
- If the plan is sound overall, say so. A premortem that finds catastrophe in everything is as useless as one that finds nothing.

## What to avoid

- Generic risk lists ("team alignment", "scope creep", "technical debt") without grounding them in *this plan*.
- Downplaying an important defect. Say if the idea has an important defect.
- Long lists. Give a short list of problems that can stop the plan.
