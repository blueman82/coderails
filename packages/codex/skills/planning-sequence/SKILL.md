---
name: planning-sequence
description: >-
  Run Pre-Parade, Premortem, and Red Team on a plan, idea, or decision.
  Trigger phrases include "run the planning sequence", "put this through
  the planning techniques", "stress-test my plan", and "Pre-Parade this".
  Use it for analysis before a major decision. Also use it before
  a high-stakes commitment without adversarial planning. Run the stages
  in order: success conditions, failure modes, and adversarial challenge.
---

# Planning Sequence

Run three planning checks on the same plan, idea, or decision. Find missing
success conditions, likely failures, and weaknesses before commitment.

The three techniques are:
1. **Pre-Parade** — what does success actually require?
2. **Premortem** — what's the most credible story of failure?
3. **Red Team** — does this survive a genuine adversary?

Run them in this order on the same subject.

---

## Step 0: Extract the subject

If the user gave a subject, use it directly. For example:
`/planning-sequence "migrate to Kubernetes"`.

Otherwise, read the conversation. Identify the plan, idea, or decision.
If the subject is unclear, ask one question:
"What should I run the planning sequence on?"

State the subject at the top in one sentence.

---

## Stage 1: Pre-Parade

Imagine that the plan succeeded one year from now. Ask what had to be
true for that result.

List the conditions, assumptions, and decisions that made success possible.

**Run this stage as follows:**

1. State the success scenario in one sentence: "It's [timeframe] from now.
   This worked."
2. List 3–5 conditions that made it work. Use specific conditions. For
   example: "The API contract was locked before frontend work started."
3. Check each condition now. Mark it as in place, missing, or uncertain.

**Output format:**

```
## Stage 1: Pre-Parade

<thinking>
Identify the conditions for success. Find conditions the team has not
checked. Find one missing condition that could defeat all others.
</thinking>

**Success scenario**: [one sentence]

**What made it work:**
1. [Condition] — [currently in place / missing / uncertain]
2. ...

**Gaps to address**: [bullet list of conditions that are missing or uncertain]
```

---

## Stage 2: Premortem

Run the premortem process here. Do not call its skill separately.

Assume the plan failed. Work backward to find the most credible causes.

**Run this stage as follows:**

1. State the failure scenario in one sentence: "It's [timeframe] from now. This failed."
2. Check assumptions, execution, people, dependencies, timing, optimism
   bias, and unknown factors. For people, consider resistance, disengagement,
   and behavior that differs from the plan.
3. Give 2–4 failure modes. For each, state the failure, its cause,
   likelihood (low/medium/high), impact, and a concrete mitigation.
4. Give a verdict. State whether specific risks need work or the plan has
   a structural problem.

**Output format:**

```
## Stage 2: Premortem

<thinking>
Find assumptions that are likely to be wrong. Find optimism and unowned
dependencies. Identify likely resistance or disengagement. Name the
failure that others have not yet raised.
</thinking>

**Failure scenario**: [one sentence]

**Failure modes:**
1. **[Name]** — [what goes wrong and why credible]
   - Likelihood: low/medium/high
   - Impact: [one line]
   - Mitigation: [concrete action]

**Verdict**: [one paragraph — sound plan with risks, or structural problem?]
```

---

## Stage 3: Red Team

For Red Team, take the strongest position against the plan. Test its
weakest points directly.

Premortem considers accidental failure. Red Team considers an opponent
who acts against the plan. The opponent can be a competitor, sceptic,
regulator, or hostile stakeholder.

**Run this stage as follows:**

1. Identify the most credible opponent or constraint for this plan.
   Consider a competitor, internal sceptic, technical constraint, or
   market force.
2. From that position, find 2–3 specific attacks. Use weak assumptions,
   exposed gaps, and points where the plan can fail.
3. For each attack, state what the opponent does or says. State the damage.
4. Tell the plan owner what to change or prove to withstand the attack.

**Output format:**

```
## Stage 3: Red Team

<thinking>
Identify the opponent and its motive. Find facts the plan owner has
missed. Name the attack that would be hardest to recover from.
</thinking>

**Adversary**: [who is attacking and why they're motivated]

**Attack vectors:**
1. **[Vector name]** — [what the adversary does and what damage it causes]
2. ...

**Challenge**: [what the plan owner must change or prove to survive this]
```

---

## Closing synthesis

After all three stages, write a short synthesis (3–5 sentences):

- What risks or gaps appear in all three stages?
- What did Pre-Parade surface that the other two missed?
- What is the first issue to address before commitment?

```
## Synthesis

[3–5 sentences. Highest-confidence findings. One clear priority action.]
```

---

## What good looks like

- All three stages are specific to *this plan*, not generic.
- Pre-Parade conditions are concrete and checkable. For example: "Alice
  owns the API contract, confirmed."
- Premortem failure modes are credible, not catastrophist.
- Red Team presents a credible attack, even if it is uncomfortable.
- Synthesis converges on one clear priority, not a hedged list.

## What to avoid

- Running all three stages as variations of the same critique. They should surface *different* things.
- Softening the Red Team to avoid discomfort. Its value is exactly the discomfort.
- Synthesis that just restates the three stages. It should add something by combining them.
