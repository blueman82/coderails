---
name: planning-sequence
description: 'Run the full three-stage planning sequence — Pre-Parade, Premortem, and Red Team — on a plan, idea, or decision. Use this skill whenever someone wants to stress-test a plan before committing, says "run the planning sequence", "put this through the planning techniques", "stress-test my plan", "Pre-Parade this", or wants anticipatory analysis before a major decision. Also trigger proactively when a user is about to commit to something high-stakes and hasn''t done any adversarial planning yet. The three stages run in order: Pre-Parade (success conditions), Premortem (failure modes), Red Team (adversarial challenge).'
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

1. State the success scenario in one sentence: "It's [timeframe] from now. This worked."
2. List 3–5 conditions that made it work. Be specific — not "the team executed well" but "the API contract was locked before frontend work started".
3. For each condition, ask: is this condition currently in place? Flag any that are missing or uncertain.

**Output format:**

```
## Stage 1: Pre-Parade

<thinking>
What success actually required — focus on the least obvious conditions, what the team will assume is fine without checking, and the single missing condition that would make all others irrelevant.
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
3. Give 2–4 failure modes. For each, state what goes wrong, why it is credible,
   likelihood (low/medium/high), impact, and a concrete mitigation.
4. Give a verdict. State whether the plan is sound with specific risks to
   address, or has structural problems.

**Output format:**

```
## Stage 2: Premortem

<thinking>
What does this plan assume that's almost certainly wrong? Where is the optimism? What's the failure mode everyone will recognise in hindsight but nobody said out loud? What's the dependency nobody owns? Who will resist or disengage?
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

For Red Team, take the strongest position against the plan. Attack its
weakest points directly. Make the challenge one-sided.

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
Who specifically would want this to fail, and why? What do they know that the plan owner is hoping they don't notice? What's the single attack vector that, if it landed, would be hardest to recover from?
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

- What risks or gaps appear in all three stages? These are the highest-confidence risks or gaps.
- What did Pre-Parade surface that the other two missed?
- What is the single most important thing to address before committing?

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
