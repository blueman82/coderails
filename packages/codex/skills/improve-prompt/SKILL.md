---
name: improve-prompt
description: Improve a prompt before execution. Find gaps, state grounded assumptions, and rewrite for clarity. Use for /improve-prompt, "improve this prompt", "what's missing from this prompt", or a vague or underspecified task.
---

# Improve Prompt

Rewrite an unclear prompt so the task has a clear target. This helps the
first attempt meet the user's intent.

Use this skill for `/improve-prompt`, "improve this prompt", or "what's
missing". Also use it when a vague prompt is likely to cause a wrong result.
"Just do it" skips this skill and starts the task.

<context_first>
Gather context in this order. Use it to resolve gaps before you ask.

1. Check memory files for prior context on the prompt topic
2. `AGENTS.md` — read the stack, conventions, and preferences
3. Files and code — read the relevant paths
4. Current conversation — use answers already given

Do not ask about a gap that the context resolves.
</context_first>

<diagnosis>
Before you write the result, check all seven foundations. Record what
context resolved. Identify open gaps and the most blocking gap. Use N/A
only when the foundation does not apply.

Then mark each foundation ✓, ✗, or N/A:

1. **Defines done** — output format, scope, completeness, success criteria all clear?
2. **Names assumptions** — stack, environment, audience, prior context explicit?
3. **Specifies constraints** — limits on what to touch, change, or avoid?
4. **Single scope** — one task, not several bundled?
5. **States what's been tried** — prior attempts included? *(problem-solving only — N/A for greenfield)*
6. **Execution override** — execute or discuss?
7. **Defines role** — would a persona sharpen the output? *(N/A for mechanical tasks)*

**Final check:** Could a capable colleague use the prompt without prior
context and produce the intended result? Check after diagnosis and again
after rewriting.
</diagnosis>

<gaps>
Before you ask or rewrite, list the remaining gaps. For each gap, choose
a question or a grounded assumption.

**Ask when context does not resolve a gap.**

- Bounded answer space (format, audience, mode, genre, platform) → ask one
  short multiple-choice question. Use an available question tool when the
  active session exposes one. Otherwise, ask in a normal user-facing reply.
- Open-ended answer space (constraints, success criteria, personal taste) →
  ask one short freeform question
- Personal preference → memory cannot ground this; always ask
- One question at a time, most blocking gap first

**Assume when** context provides solid evidence and error risk is low.
State each assumption so the user can correct it.
</gaps>

<rewrite>
Construct the improved prompt with these in mind:

- **Role:** If foundation 7 failed, start with one role sentence.
- **Positive instructions:** State the action to take.
- **XML sections:** Separate instructions, context, examples, and inputs
  when they appear together.
- **Reason:** Explain a constraint when its purpose is unclear.
- **Examples:** For a specific or unusual output format, give three to five
  `<example>` tags. Include one edge case.
- **Length:** Add structure only where the original prompt needs it. Keep
  clear parts of the original.

Check all seven foundations again. Fix an open gap before you present the
rewrite.
</rewrite>

<output_format>
Present four parts:

1. **Diagnosis:** Give one line and a ✓, ✗, or N/A mark for each foundation.
2. **Context used:** Name the memory, `AGENTS.md`, or code that resolved gaps.
3. **Assumptions made:** State the gaps closed by grounded assumptions.
4. **Improved prompt:** Put the ready-to-use text in a code fence.

On a later iteration, update only the affected foundations. Preserve the
others. If the prompt names a tool target, tailor the rewrite to it.
Put the improved prompt in a triple-backtick code fence. Do not use a
block quote; it can lose structure in a terminal.
</output_format>

<examples>

These examples show the response format. Their project facts are illustrative.

<example type="technical — strong context">
**Input**: `automate what you can from the Theo v1 evaluation process`

**Diagnosis**
```
✗ Defines done — no output format, time window, or thresholds
✗ Names assumptions — data sources and metrics absent from prompt
✗ Specifies constraints — human gates not identified
✓ Single scope
N/A States what's been tried — greenfield
✓ Execution override — implicit
✗ Defines role — audience unstated
```

**Context used**: Theo memory — evaluation window, metrics, thresholds, data sources, human gates. AGENTS.md — Python/Airflow, SRE audience.
**Assumptions made**: Output is implementation (runnable jobs + reports), not a plan — autonomous operation mode, low risk.

**Improved prompt**:
```
You are a senior SRE automating an evaluation pipeline for an AI memory system.

<instructions>
Automate the Theo v1 clean-slate evaluation. Implement the automation scope below. Leave the human gates untouched.
</instructions>

<context>
Objective: determine whether to continue v1 iteration or execute v2, using empirical evidence.
Window: 2026-02-27 through 2026-03-06. Stack: Python, Airflow.

Data sources: transcript session history, memory store events, recall/injection logs, classification outcomes, confidence-change events.

Metrics (fixed for the window):
1. Memory store quality (useful vs junk)
2. Classification accuracy (with human-audited sample)
3. Injection relevance: used / wrong / stale
4. Recall hit rate on real tasks

Thresholds: used >= 70%, wrong <= 15%, stale <= 15%, classification accuracy >= 85%, recall hit rate >= 75%, junk rate <= 20%.
</context>

<automation_scope>
Daily metric jobs · daily scorecards and alerts · final summary with trend analysis and pass/fail
</automation_scope>

<human_gates>
Out of scope: auditing ambiguous labels · final go/no-go approval
</human_gates>

<done_when>
1. Daily report: metrics, threshold status, anomalies
2. Final report 2026-03-06 — "v1 iterate" if thresholds consistently met, "execute v2 now" if noise/error remains above threshold. Include evidence and confidence.
</done_when>
```
</example>

<example type="personal preference — clarification needed">
**Input**: `recommend me some movies`

**Diagnosis**
```
✗ Defines done — no criteria, format, or count
✗ Names assumptions — taste and mood unknown; memory empty
✗ Specifies constraints — nothing to exclude
✓ Single scope
N/A States what's been tried
✓ Execution override
N/A Defines role
```

**Context used**: none.

*Personal preference — asking before rewriting.*

[Question to user: What are you in the mood for? → Action/thriller · Drama/indie · Comedy · Sci-fi/horror · Surprise me]

*User selects "Sci-fi / horror"*

**Assumptions made**: 5 recommendations, mix of well-known and less obvious. Streaming availability not filtered.

**Improved prompt**:
```
Recommend 5 sci-fi or horror films — a mix of well-known and less obvious picks. For each: title, one-sentence reason it fits, and where it sits on the scale from cerebral to visceral. Lean toward variety across sub-genres.
```
</example>

<example type="problem-solving — foundation 5 active">
**Input**: `fix the daemon startup crash`

**Diagnosis**
```
✗ Defines done — no success criteria
✗ Names assumptions — which daemon, which environment
✗ Specifies constraints — files off-limits not stated
✓ Single scope
✗ States what's been tried — two prior attempts in memory, not in prompt
✓ Execution override
N/A Defines role
```

**Context used**: Theo memory — socket path fix (ineffective), Ollama cold-start timeout (identified, open). AGENTS.md — theo-daemon.py confirmed.
**Assumptions made**: local dev environment, low risk. Success criteria: clean start + health check passes.

**Improved prompt**:
```
Fix the theo-daemon.py startup crash in local dev.

<context>
Two prior attempts:
1. Socket path permissions fix (2026-02-20) — did not resolve
2. Ollama embed timeout on cold start — identified as likely cause, not yet fixed

Focus on the Ollama cold-start timeout. The socket path approach is exhausted.
</context>

<constraints>
Stay within theo-daemon.py and its direct dependencies. Hook files are out of scope.
</constraints>

<done_when>
Daemon starts cleanly in local dev and passes the existing health check without intervention.
</done_when>
```
</example>

</examples>
