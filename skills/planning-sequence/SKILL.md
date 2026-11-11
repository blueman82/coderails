---
name: planning-sequence
description: 'Run the full three-stage planning sequence — Pre-Parade, Premortem, and Red Team — on a plan, idea, or decision. Use this skill whenever someone wants to stress-test a plan before committing, says "run the planning sequence", "put this through the planning techniques", "stress-test my plan", "Pre-Parade this", or wants anticipatory analysis before a major decision. Also trigger proactively when a user is about to commit to something high-stakes and hasn''t done any adversarial planning yet. The three stages run in order: Pre-Parade (success conditions), Premortem (failure modes), Red Team (adversarial challenge).'
effort: high
---

# Planning Sequence

Run three checks on the same plan, idea, or decision. First identify the conditions for success. Then identify credible problems that could stop the plan. Last, test the plan against an opponent or constraint. Use facts about this plan.

The three methods are:
1. **Pre-Parade** — what does success actually require?
2. **Premortem** — what is the most credible explanation if the plan does not succeed?
3. **Red Team** — can this plan survive opposition?

Run them in this sequence on the same subject.

---

## Step 0: Extract the subject

If the user passed an explicit subject (e.g., `/planning-sequence "migrate to Kubernetes"`), use it directly.

If not, read the current conversation and extract the plan, idea, or decision being discussed. If genuinely ambiguous, ask one question: "What should I run the planning sequence on?"

Name the subject at the top in one sentence.

---

## Stage 1: Pre-Parade

For Pre-Parade, imagine the plan succeeded one year after it started. Identify the conditions that made it succeed.

Find the prerequisites, assumptions, and decisions that must be correct for that outcome. Use the assumed result to find its causes.

Use these steps.

1. Give the success scenario in one sentence: "It's [timeframe] from now. This worked."
2. List 3–5 conditions that made it work. Give concrete conditions such as "the API contract was locked before frontend work started". Do not use "the team executed well".
3. Check each condition against current facts. Flag each missing or uncertain condition.

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

Use the premortem procedure here. Do not invoke the skill on its own.

Start with the assumption that the plan did not succeed. Find the most credible causes of that result. Keep the list short.

Use these steps.

1. Give the unsuccessful scenario in one sentence: "It's [timeframe] from now. This failed."
2. Check assumptions, execution, dependencies, and timing for problems. Identify who might resist, disengage, or act in an unexpected manner. Check for too much optimism and things the plan does not include.
3. Identify 2–4 problems. For each, give what could go incorrectly and why it is credible. Give the likelihood (`low`, `medium`, or `high`), `Impact`, and a concrete mitigation.
4. Give a verdict. Can the plan succeed if you correct the listed risks, or does it have structural problems?

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

For Red Team, argue against the plan from the strongest opposing position. Challenge the weakest parts of the plan from that position alone.

A premortem imagines that the plan did not succeed by accident. Red Team imagines an opponent who wants to stop it. The opponent could be a competitor, skeptic, regulator, or hostile stakeholder.

Use these steps.

1. Identify the most credible adversary for the plan. Possible adversaries include a competitor, internal skeptic, technical constraint, or market force.
2. Attack the plan from that adversary's position. Find 2–3 attack vectors. Look at weak assumptions, omissions, and other weak points in the plan.
3. For each attack: what is the adversary doing or saying, and what damage does it cause?
4. Give the plan owner a challenge. What must they change or prove for the plan to survive the attack?

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

After the three steps, write a short synthesis (3–5 sentences).

- What do all three steps agree on? (These are your highest-confidence risks or missing parts)
- What did Pre-Parade surface that the other two missed?
- What is the single most important thing to address before committing?

```
## Synthesis

[3–5 sentences. Highest-confidence findings. One clear priority action.]
```

---

## What good looks like

- Apply all three steps to this plan.
- Pre-Parade conditions are concrete and checkable, not vague ("clear ownership" → "Alice owns the API contract, confirmed").
- The premortem names credible problems.
- Red Team challenges the plan strongly from the opponent’s position.
- The synthesis gives one clear first step.

## What to avoid

- Using the same critique for all three steps. Look for a different result in each.
- Making the Red Team less forceful to make the critique comfortable. It must challenge the plan.
- A synthesis that only lists the earlier results. Use results from all three checks to identify the first change to make.
