---
name: premortem
description: 'Use this skill for premortem analysis: assume a plan, decision, or approach has already failed, then reason backwards to identify the failure modes and causes. Trigger on explicit premortem requests ("premortem this/X"), "steelman the failure", "what could go wrong with this plan", or requests to adversarially stress-test a specific commitment. The distinguishing signal is backwards reasoning from an assumed bad outcome — not forward-looking checklists ("what should I check before X"), code review, general architecture critique, or fact verification.'
---

# Premortem

For a premortem, imagine that the plan did not succeed. Start from that result and identify its causes.
Use the results before commitment, while you can change the plan.

Use this skill for plans, decisions, arguments, features, architectures, or your previous answer.
The user can invoke it explicitly (`premortem this`, `premortem <X>`). It also applies before a high-stakes commitment.

---

## The process

### Step 1: Establish what's being premortemed

If the context makes the subject clear, identify it directly.
The user can select a plan or your previous answer.
If the subject is unclear, ask: "What specifically should I premortem?"

### Step 2: Reason adversarially

Use a `<thinking>` block for analysis before you write the result.
Challenge the plan as you examine these topics:

- **Assumptions:** Which assumption could be incorrect?
- **Implementation:** If the plan is sound, what could prevent you from implementing it?
- **Participants:** Who could resist, disengage, or behave differently?
- **Dependencies:** Which external condition could change or stop work?
- **Optimism:** Where does the plan rely too much on success?
- **Unknowns:** What does the plan miss?
- **Timing:** Which sequence or deadline could slip?

Select the most plausible problems with important effects. Keep the list short and name each problem.

### Step 3: Assess each failure

For each important problem, give a brief verdict:

- **Likelihood**: `low`, `medium`, or `high` (use judgment)
- **`Impact`**: If the problem occurs, how bad is it?
- **Mitigation**: what change can decrease this risk?

Give a step that decreases the risk. "Monitor closely" does not do this.
"Add a circuit breaker" and "validate assumption X before commitment"
are concrete steps.

### Step 4: Verdict

End with one direct verdict:

- Is the plan sound if the owner addresses the risks you found?
- Do structural problems make changes necessary?
- Is there a problem that makes the current plan unlikely to succeed?

If you examine your own answer, say so. Update your recommendation if necessary.

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

- Name problems that can occur in this plan. Do not copy generic project risks from a template.
- Mitigations are *actionable*, not reassurances.
- Give an explicit verdict. Do not hedge by listing everything as "worth considering".
- If the plan is mostly sound, say so. Report the risks at their actual severity.

## What to avoid

- Generic risk lists ("team alignment", "scope creep", "technical debt") without facts from this plan.
- Language that makes an important problem sound less important. Say when an idea has an important problem.
- Long lists. Give a short list of problems in this plan.
