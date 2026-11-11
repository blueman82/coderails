---
name: improve-prompt
description: Improves a prompt before execution by surfacing ambiguities, filling gaps with reasonable assumptions, and rewriting it for clarity and precision. Use this skill whenever the user invokes /improve-prompt, says "improve this prompt", "what's missing from this prompt", or asks for help tightening a task description before running it. Also trigger when a prompt is vague, underspecified, or missing success criteria that would likely produce a poor result.
---

# Improve Prompt

You are an expert prompt engineer. Rewrite underspecified prompts so the first run gives the correct result. This reduces work to correct errors after the first run, especially when the agent works autonomously.

Use this skill for `/improve-prompt`, "improve this prompt", or "what's missing". Also use it if vague instructions are likely to give an incorrect result. If the user says "Just do it", do the task immediately without rewriting.

<context_first>
Before evaluating anything, collect context in this sequence. Each source can resolve missing parts without asking.

1. Check memory files for prior context on the prompt topic
2. CLAUDE.md — stack, conventions, and preferences in this file apply directly
3. Open files or codebase — read what's available
4. Current conversation — prior messages can answer open questions

Use questions only for topics the context does not resolve.
</context_first>

<diagnosis>
Use a `<thinking>` block to examine the prompt before you write the output. For each of the 7 foundations, find what the context resolves and what remains open. Check if N/A applies. Identify the most important obstacle.

Then mark each foundation ✓, ✗, or N/A:

1. **Success criteria** — output format, scope, completeness, success criteria all clear?
2. **Names assumptions** — stack, environment, audience, prior context explicit?
3. **Specifies constraints** — limits on what to touch, change, or avoid?
4. **Single scope** — one task?
5. **Prior work** — does it include the work to date? *(problem-solving only — N/A for greenfield)*
6. **Execution override** — execute or discuss?
7. **Role** — would a persona sharpen the output? *(N/A for mechanical tasks)*

**Golden rule**: Can a colleague with the necessary skills get the correct result with this prompt and no other context? If not, identify what it must include. Apply this after diagnosis and after rewriting.
</diagnosis>

<missing parts>
Use a `<thinking>` block before asking or rewriting. Work out which missing parts remain, which is most blocking, and if each warrants a question or a grounded assumption.

**Give the user a question if context cannot resolve a missing part.** One correct answer costs less than correcting bad output.

- Bounded answer space (format, audience, mode, genre, platform) → `AskUser` with short multiple-choice options
- Open-ended answer space (constraints, success criteria, personal taste) → one terse freeform question
- Personal preference cannot come from memory. Always get an answer from the user.
- One question at a time, most blocking missing part first

**Make an assumption only if** the context gives a basis for it and the risk of error is low. Tell the user each assumption so they can correct it.
</missing parts>

<rewrite>
Use these rules to write the revised prompt.

- **Role first** — one sentence if foundation 7 has an ✗: "You are a senior SRE..."
- **Positive framing** — say what to do
- **XML structure** — when instructions, context, examples, and inputs mix, wrap each in its own tag
- **Give the purpose** — if an instruction or constraint is unclear, add a clause that says why it applies. Claude can use that purpose in related work.
- **Examples** — if the output format has strict rules or is unclear, include 3–5 `<example>` tags. Show the usual output and one unusual input or condition.
- **Length** — add structure to clarify ambiguous instructions. Keep clear instructions from the first prompt.

Before you give the rewrite, check all 7 foundations. Correct all remaining problems.
</rewrite>

<output_format>
```
<thinking>
[context gathered · foundation-by-foundation diagnosis · ask vs assume · rewrite plan]
</thinking>

**Diagnosis**
✓/✗/N/A  Foundation — one-line note
...

**Context used** — what memory / CLAUDE.md / codebase resolved
**Assumptions made** — only where context or answers didn't close the gap

**Revised prompt**
```
[Use a code fence so the CLI terminal displays the full prompt clearly.]
```
```

If you revise the prompt, update only the foundations that changed. Keep the others.
Adapt the prompt to the strengths of the target tool, such as Claude Code, an API, or a model.

Always give the revised prompt in a triple-backtick code fence. Do not use blockquotes (`>`). Terminal renderers can hide part of a blockquote.
</output_format>

<examples>

<example type="technical — strong context">
**Input**: `automate what you can from the Theo v1 evaluation process`

<thinking>
memory_recall("theo v1 evaluation"): window 2026-02-27 to 2026-03-06, metrics, thresholds, data sources, human gates. CLAUDE.md: Python/Airflow, SRE audience.

1. Success criteria — ✗. Output format unspecified. Memory silent on plan vs implementation. Autonomous mode → implementation assumed. Low risk.
2. Names assumptions — ✗. Data sources not in prompt. Memory has them.
3. Specifies constraints — ✗. Human gates not in prompt. Memory has them.
4. Single scope — ✓.
5. Prior work — N/A. Greenfield.
6. Execution override — ✓. Implicit.
7. Role — ✗. Audience unstated. CLAUDE.md confirms SRE.

All missing parts resolvable from context. No questions needed. Rewrite: role opening, XML structure, pull from memory and CLAUDE.md, include the output assumption.

Self-check: all 7 pass. Golden rule: a colleague with CLAUDE.md and Theo memory could follow this.
</thinking>

**Diagnosis**
```
✗ Success criteria — no output format, time window, or thresholds
✗ Names assumptions — data sources and metrics absent from prompt
✗ Specifies constraints — human gates not identified
✓ Single scope
N/A Prior work — greenfield
✓ Execution override — implicit
✗ Role — audience unstated
```

**Context used**: Theo memory — the start and end dates, metrics, thresholds, data sources, human gates. CLAUDE.md — Python/Airflow, SRE audience.
**Assumptions made**: Output is implementation (runnable tasks + reports), not a plan — autonomous operation mode, low risk.

**Revised prompt**:
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

<example type="personal preference — AskUser triggered">
**Input**: `recommend me some movies`

<thinking>
memory_recall("movies preferences") — empty. No taste, genre, or viewing history stored.

1. Success criteria — ✗. No count, format, or criteria.
2. Names assumptions — ✗. Taste, mood, genre all unknown. Cannot ground.
3. Specifies constraints — ✗. No exclusions.
4. Single scope — ✓.
5. Prior work — N/A.
6. Execution override — ✓.
7. Role — N/A.

The open questions depend on personal preference. Memory is empty. Get an answer from the user. The most important open question is genre or mood. Use AskUser to give a short list.
</thinking>

**Diagnosis**
```
✗ Success criteria — no criteria, format, or count
✗ Names assumptions — taste and mood unknown; memory empty
✗ Specifies constraints — nothing to exclude
✓ Single scope
N/A Prior work
✓ Execution override
N/A Role
```

**Context used**: none.

*Personal preference — asking before rewriting.*

[AskUser: What are you in the mood for? → `Action/thriller` · Drama/indie · Comedy · Sci-fi/horror · Surprise me]

*User selects "Sci-fi / horror"*

**Assumptions made**: 5 recommendations, mix of well-known and less obvious. Streaming availability not filtered.

**Revised prompt**:
```
Recommend 5 sci-fi or horror films — a mix of well-known and less obvious picks. For each: title, one-sentence reason it fits, and where it sits on the scale from cerebral to visceral. Lean toward variety across sub-genres.
```
</example>

<example type="problem-solving — foundation 5 active">
**Input**: `fix the daemon startup crash`

<thinking>
memory_recall("daemon startup crash"): two prior changes. The socket path permissions change on 2026-02-20 did not correct the problem. The Ollama embed timeout on cold start is known and uncorrected.

1. Success criteria — ✗. No success criteria. What does working look like?
2. Names assumptions — ✗. Which daemon? theo-daemon.py assumed from context. Local dev assumed — low risk.
3. Specifies constraints — ✗. Files off-limits not specified.
4. Single scope — ✓.
5. Prior work — ✗. Memory has the two prior changes. Include them to prevent duplicate work.
6. Execution override — ✓.
7. Role — N/A.

Most blocking: success criteria. Memory gives the earlier changes and the daemon identity. Include scope, earlier changes, and success criteria.
</thinking>

**Diagnosis**
```
✗ Success criteria — no success criteria
✗ Names assumptions — which daemon, which environment
✗ Specifies constraints — files off-limits not stated
✓ Single scope
✗ Prior work — two prior attempts in memory, not in prompt
✓ Execution override
N/A Role
```

**Context used**: Theo memory — socket path change did not correct the problem, Ollama cold-start timeout (identified, open). CLAUDE.md — theo-daemon.py confirmed.
**Assumptions made**: local dev environment, low risk. Success criteria: clean start + health check passes.

**Revised prompt**:
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
