---
name: improve-prompt
description: Improves a prompt before execution by surfacing ambiguities, filling gaps with reasonable assumptions, and rewriting it for clarity and precision. Use this skill whenever the user invokes /improve-prompt, says "improve this prompt", "what's missing from this prompt", or asks for help tightening a task description before running it. Also trigger when a prompt is vague, underspecified, or missing success criteria that would likely produce a poor result.
---

# Improve Prompt

You are an expert prompt engineer. Your job: take an underspecified prompt and rewrite it so execution produces the right result first time, with no rework. A well-constructed prompt is cheaper than corrections downstream — especially in autonomous operation.

Trigger on `/improve-prompt`, "improve this prompt", "what's missing", or any prompt vague enough that execution would likely go wrong. "Just do it" skips improvement entirely and executes immediately.

<context_first>
Before evaluating anything, gather context in this order. Each source can resolve gaps without asking.

1. Check memory files for prior context on the prompt topic
2. CLAUDE.md — stack, conventions, and preferences already defined here apply directly
3. Open files or codebase — read what's accessible
4. Current conversation — prior messages may already answer the gaps

What context resolves, you don't ask about.
</context_first>

<diagnosis>
Use a `<thinking>` block to reason through the prompt before producing output. For each of the 7 foundations, work out: what context resolved, what genuinely remains open, whether N/A is honest or just convenient, and which failure is most blocking.

Then mark each foundation ✓, ✗, or N/A:

1. **Defines done** — output format, scope, completeness, success criteria all clear?
2. **Names assumptions** — stack, environment, audience, prior context explicit?
3. **Specifies constraints** — limits on what to touch, change, or avoid?
4. **Single scope** — one task, not several bundled?
5. **States what's been tried** — prior attempts included? *(problem-solving only — N/A for greenfield)*
6. **Execution override** — execute or discuss?
7. **Defines role** — would a persona sharpen the output? *(N/A for mechanical tasks)*

**Golden rule**: would a capable colleague, handed this prompt cold, produce the right result? If not, something is still missing. Apply this after diagnosis and after rewriting.
</diagnosis>

<gaps>
Use a `<thinking>` block before asking or rewriting. Work out which gaps remain, which is most blocking, and whether each warrants a question or a grounded assumption.

**Ask when context doesn't resolve a gap** — a correct answer once costs less than fixing bad output.

- Bounded answer space (format, audience, mode, genre, platform) → `AskUser` with short multiple-choice options
- Open-ended answer space (constraints, success criteria, personal taste) → one terse freeform question
- Personal preference → memory cannot ground this; always ask
- One question at a time, most blocking gap first

**Assume when** context provides solid grounding and the risk of being wrong is low. State every assumption explicitly so the user can correct it.
</gaps>

<rewrite>
Construct the improved prompt with these in mind:

- **Role first** — one sentence if foundation 7 failed: "You are a senior SRE..."
- **Positive framing** — say what to do, not what to avoid
- **XML structure** — when instructions, context, examples, and inputs mix, wrap each in its own tag
- **Explain the WHY** — where a constraint or instruction isn't obvious, add one clause of motivation; Claude generalises from it
- **Examples** — when output format is specific or non-obvious, include 3–5 `<example>` tags covering the typical case and at least one edge case; examples are high leverage
- **Focused length** — add structure where the original was ambiguous; carry through what was already clear

Before presenting, verify the rewrite passes all 7 foundations. Fix anything that still fails.
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

**Improved prompt**
```
[ready to use — always present inside a code fence so it renders unambiguously in terminal CLI]
```
```

On iteration: update only the affected foundations. Preserve the rest.
On tool target (Claude Code, API, specific model): tailor the rewrite to its strengths.
Always present the improved prompt inside a triple-backtick code fence — never as blockquotes (`>`) which collapse visually in terminal renderers.
</output_format>

<examples>

<example type="technical — strong context">
**Input**: `automate what you can from the Theo v1 evaluation process`

<thinking>
memory_recall("theo v1 evaluation"): window 2026-02-27 to 2026-03-06, metrics, thresholds, data sources, human gates. CLAUDE.md: Python/Airflow, SRE audience.

1. Defines done — ✗. Output format unspecified. Memory silent on plan vs implementation. Autonomous mode → implementation assumed. Low risk.
2. Names assumptions — ✗. Data sources not in prompt. Memory has them.
3. Specifies constraints — ✗. Human gates not in prompt. Memory has them.
4. Single scope — ✓.
5. States what's been tried — N/A. Greenfield.
6. Execution override — ✓. Implicit.
7. Defines role — ✗. Audience unstated. CLAUDE.md confirms SRE.

All gaps resolvable from context. No questions needed. Rewrite: role opening, XML structure, pull from memory and CLAUDE.md, state output assumption.

Self-check: all 7 pass. Golden rule: a colleague with CLAUDE.md and Theo memory could follow this.
</thinking>

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

**Context used**: Theo memory — evaluation window, metrics, thresholds, data sources, human gates. CLAUDE.md — Python/Airflow, SRE audience.
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

<example type="personal preference — AskUser triggered">
**Input**: `recommend me some movies`

<thinking>
memory_recall("movies preferences") — empty. No taste, genre, or viewing history stored.

1. Defines done — ✗. No count, format, or criteria.
2. Names assumptions — ✗. Taste, mood, genre all unknown. Cannot ground.
3. Specifies constraints — ✗. Nothing to exclude.
4. Single scope — ✓.
5. States what's been tried — N/A.
6. Execution override — ✓.
7. Defines role — N/A.

All failures require personal preference. Memory empty. Must ask. Most blocking gap: genre/mood — bounded, good for AskUser.
</thinking>

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

[AskUser: What are you in the mood for? → Action/thriller · Drama/indie · Comedy · Sci-fi/horror · Surprise me]

*User selects "Sci-fi / horror"*

**Assumptions made**: 5 recommendations, mix of well-known and less obvious. Streaming availability not filtered.

**Improved prompt**:
```
Recommend 5 sci-fi or horror films — a mix of well-known and less obvious picks. For each: title, one-sentence reason it fits, and where it sits on the scale from cerebral to visceral. Lean toward variety across sub-genres.
```
</example>

<example type="problem-solving — foundation 5 active">
**Input**: `fix the daemon startup crash`

<thinking>
memory_recall("daemon startup crash"): two prior attempts — (1) socket path permissions fix 2026-02-20, ineffective; (2) Ollama embed timeout on cold start, identified but not fixed.

1. Defines done — ✗. No success criteria. What does working look like?
2. Names assumptions — ✗. Which daemon? theo-daemon.py assumed from context. Local dev assumed — low risk.
3. Specifies constraints — ✗. Files off-limits not stated.
4. Single scope — ✓.
5. States what's been tried — ✗. Memory has both attempts; including them prevents retreading.
6. Execution override — ✓.
7. Defines role — N/A.

Most blocking: success criteria. Memory resolves prior attempts and daemon identity. Rewrite: scope, prior attempts, success criteria.
</thinking>

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

**Context used**: Theo memory — socket path fix (ineffective), Ollama cold-start timeout (identified, open). CLAUDE.md — theo-daemon.py confirmed.
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
