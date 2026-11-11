---
name: planning-sequence
description: 'Run the full three-stage planning sequence — Pre-Parade, Premortem, and Red Team — on a plan, idea, or decision. Use this skill whenever someone wants to stress-test a plan before committing, says "run the planning sequence", "put this through the planning techniques", "stress-test my plan", "Pre-Parade this", or wants anticipatory analysis before a major decision. Also trigger proactively when a user is about to commit to something high-stakes and hasn''t done any adversarial planning yet. The three stages run in order: Pre-Parade (success conditions), Premortem (failure modes), Red Team (adversarial challenge).'
---

# Planning Sequence

Run three planning checks on the same plan, idea, or decision.
Before commitment, find missing conditions for success, likely problems, and weak points.

Use these three methods:

1. **Pre-Parade** — what conditions are necessary for success?
2. **Premortem** — what is most likely to prevent the plan from working?
3. **Red Team** — can the plan succeed against an active opponent?

Run them in this sequence on the same subject.

---

## Step 0: Extract the subject

If the user gave a subject, use it directly. For example:
`/planning-sequence "migrate to Kubernetes"`.

If the user gave no subject, read the conversation. Identify the plan, idea, or decision.
If the subject is unclear, ask one question:
"What should I run the planning sequence on?"

Name the subject at the top in one sentence.

---

## Stage 1: Pre-Parade

Imagine that the plan succeeded one year after this point. Identify the conditions necessary for that result.

List the conditions, assumptions, and decisions that made success possible.

**Use these steps:**

1. Give the success scenario in one sentence: "It's [timeframe] from now. This worked."
2. List 3–5 concrete conditions that made it work. For example, "the API contract was locked before frontend work started".
   Do not use general claims such as "the team executed well".
3. Check if each condition currently holds. Identify missing or uncertain conditions.

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

Use the premortem procedure here. Do not invoke its skill independently.

Imagine that the plan did not succeed. Start from that result and identify the most credible causes.

**Use these steps:**

1. Give the scenario in one sentence: "It's [timeframe] from now. This failed."
2. Check assumptions, implementation, participants, dependencies, timing, optimism bias, and unknowns.
   For participants, consider resistance, disengagement, and behavior that does not follow the plan.
3. Give 2–4 problems that could stop the plan from working. For each, say what can occur and why it is credible.
   Include likelihood (`low`, `medium`, or `high`), effect, and a concrete mitigation.
4. Give a verdict. Say if the plan is sound after the owner addresses the named risks, or if structural problems exist.

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

For Red Team, argue against the plan from the strongest opposing position.
Attack its weakest points directly. Make the challenge one-sided.

Premortem considers problems that can occur without a deliberate opponent.
Red Team considers deliberate opposition. The opponent can be a competitor, skeptic, regulator, or hostile stakeholder.

**Use these steps:**

1. Identify the most credible opponent or constraint for this plan.
   Possible examples are a competitor, internal skeptic, technical constraint, or pressure from the market.
2. From that position, find 2–3 concrete attacks. Use weak assumptions, exposed weak points, and points where the plan can break.
3. For each attack, say what the opponent does or says. Identify the damage.
4. Tell the plan owner what to change or prove so the plan can resist the attack.

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

After all three steps, write a short synthesis (3–5 sentences):

- What risks or weak points appear in all three steps? You can report these with the most confidence.
- What did Pre-Parade surface that the other two missed?
- What is the single most important thing to address before committing?

```
## Synthesis

[3–5 sentences. Highest-confidence findings. One clear priority action.]
```

---

## What good looks like

- All three steps use facts from this plan.
- Pre-Parade conditions are concrete and checkable. For example: "Alice
  owns the API contract, confirmed."
- The premortem gives credible problems that can stop the plan from working.
- Red Team gives a credible attack that can be uncomfortable.
- The synthesis names one most important step.

## What to avoid

- Giving the same critique in all three steps. Identify different problems in each step.
- Making the Red Team challenge weaker to prevent discomfort. Its value comes from the discomfort.
- Giving the same results again in the synthesis. Use the results together to give a new verdict.
