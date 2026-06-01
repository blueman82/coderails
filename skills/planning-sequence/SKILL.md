---
name: planning-sequence
description: Run the full three-stage planning sequence — Pre-Parade, Premortem, and Red Team — on a plan, idea, or decision. Use this skill whenever someone wants to stress-test a plan before committing, says "run the planning sequence", "put this through the planning techniques", "stress-test my plan", "Pre-Parade this", or wants anticipatory analysis before a major decision. Also trigger proactively when a user is about to commit to something high-stakes and hasn't done any adversarial planning yet. The three stages run in order: Pre-Parade (success conditions), Premortem (failure modes), Red Team (adversarial challenge).
---

# Planning Sequence

This skill runs three anticipatory planning techniques in sequence on a plan, idea, or decision. The goal is to surface structural gaps, execution failures, and adversarial weaknesses *before* commitment, while there's still time to act.

The three techniques are:
1. **Pre-Parade** — what does success actually require?
2. **Premortem** — what's the most credible story of failure?
3. **Red Team** — does this survive a genuine adversary?

They are always run in this order, on the same subject.

---

## Step 0: Extract the subject

If the user passed an explicit subject (e.g., `/planning-sequence "migrate to Kubernetes"`), use it directly.

If not, read the current conversation and extract the plan, idea, or decision being discussed. If genuinely ambiguous, ask one question: "What should I run the planning sequence on?"

State clearly at the top what you're analysing. One sentence.

---

## Stage 1: Pre-Parade

Pre-Parade is the success-first pass. You imagine it's a year from now and this worked brilliantly. Then you ask: what had to be true for that to happen?

This surfaces the *conditions for success* — the things that must be in place, the assumptions that must hold, the decisions that must go right. It's not optimism; it's forensic reverse-engineering of a good outcome.

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

Run the premortem skill logic here. Do not call the skill separately — execute its process inline.

You assume the plan has already failed. You work backwards to find out why. The goal is the most *credible* failure story, not a comprehensive list of everything that could go wrong.

**Run this stage as follows:**

1. State the failure scenario in one sentence: "It's [timeframe] from now. This failed."
2. Reason adversarially through: assumption failures, execution failures, people failures (who resists, disengages, or behaves differently than expected), dependency failures, optimism bias, unknown unknowns, timing failures.
3. Surface 2–4 failure modes. Each needs: what goes wrong, why it's credible, likelihood (low/medium/high), impact, and a concrete mitigation.
4. Give a verdict: is the plan sound with specific risks to address, or does it have structural problems?

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

Red Team is the adversarial challenge. You take the strongest possible position *against* the plan and attack it directly. This is not a balanced critique — it's an intentional one-sided assault on the weakest points.

The difference from premortem: premortem imagines accidental failure. Red Team imagines a motivated opponent — a competitor, a sceptic, a regulator, a hostile stakeholder — who wants this to fail and is actively working against it.

**Run this stage as follows:**

1. Identify the most credible adversary for this specific plan (competitor, internal sceptic, technical constraint, market force — whatever is most realistic).
2. Attack the plan from that adversary's position. Find 2–3 specific vectors of attack — the weakest assumptions, the most exploitable gaps, the points where the plan is most exposed.
3. For each attack: what is the adversary doing or saying, and what damage does it cause?
4. End with a challenge to the plan owner: what would you need to change or prove to survive this attack?

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

- What do all three stages agree on? (These are your highest-confidence risks or gaps)
- What did Pre-Parade surface that the other two missed?
- What is the single most important thing to address before committing?

```
## Synthesis

[3–5 sentences. Highest-confidence findings. One clear priority action.]
```

---

## What good looks like

- All three stages are specific to *this plan*, not generic.
- Pre-Parade conditions are concrete and checkable, not vague ("clear ownership" → "Alice owns the API contract, confirmed").
- Premortem failure modes are credible, not catastrophist.
- Red Team is genuinely adversarial — it should sting a little.
- Synthesis converges on one clear priority, not a hedged list.

## What to avoid

- Running all three stages as variations of the same critique. They should surface *different* things.
- Softening the Red Team to avoid discomfort. Its value is exactly the discomfort.
- Synthesis that just restates the three stages. It should add something by combining them.
