---
name: improve-prompt
description: Improves a prompt before execution by surfacing ambiguities, filling gaps with reasonable assumptions, and rewriting it for clarity and precision. Use this skill whenever the user invokes /improve-prompt, says "improve this prompt", "what's missing from this prompt", or asks for help tightening a task description before running it. Also trigger when a prompt is vague, underspecified, or missing success criteria that would likely produce a poor result.
---

# Improve Prompt

Rewrite an unclear prompt to give the task a clear target. Use the target to get the result the user wants on the first try.

Use this skill for `/improve-prompt`, "improve this prompt", or "what's missing".
Also use it if a vague prompt is likely to cause an incorrect result.
"Just do it" skips this skill and starts the task.

<context_first>
Collect context in this sequence. Use it to answer open questions first.

1. Check memory files for earlier context on the prompt topic.
2. Read AGENTS.md for the stack, conventions, and preferences that apply.
3. Read available open files or the codebase.
4. Read earlier messages in the current conversation for answers.

Do not put a question to the user if the context answers it.
</context_first>

<diagnosis>
Use a `<thinking>` block for analysis before you write output.
For each of the 7 foundations, identify what the context answers and what stays open.
Check if N/A is accurate. Identify the problem that prevents the most work.

Then mark each foundation ✓, ✗, or N/A:

1. **`Defines done`** — output format, scope, completeness, success criteria all clear?
2. **Names assumptions** — stack, environment, audience, prior context explicit?
3. **Specifies constraints** — limits on what to read, change, or keep out of scope?
4. **Single scope** — only one task?
5. **`States what's been tried`** — what work did the user do before this? *(Problem-solving only. N/A for new projects.)*
6. **Execution override** — do the work or discuss it?
7. **`Defines role`** — can a persona improve the output? *(N/A for mechanical tasks.)*

**Last check:** Can a colleague with the necessary skills get the intended result with this prompt and no earlier context?
Check after diagnosis and again after you rewrite it.
</diagnosis>

<questions>
Use a `<thinking>` block before you put a question to the user or rewrite the prompt.
Identify the open questions and which one prevents the most work. Select a question or an assumption grounded in context for each.

**Put a question to the user when context cannot answer it.**

- Bounded answer space (format, audience, mode, genre, platform) → `AskUser` with short multiple-choice options
- Open-ended answer space (constraints, success criteria, personal taste) → one terse freeform question
- Get personal preferences from the user. Memory cannot establish them
- Give one question at a time. Start with the one that prevents the most work

**Use an assumption when** context gives strong grounds for it and the risk of error is low.
Name each assumption so the user can correct it.
</questions>

<rewrite>
Write the improved prompt using these instructions:

- **Role first** — if foundation 7 has a ✗, give a one-sentence role: "You are a senior SRE..."
- **Positive framing** — say what to do
- **XML structure** — if the prompt contains instructions, context, examples, and inputs, put each in its own tag
- **Give the purpose** — if a constraint or instruction is not obvious, give its purpose in one clause. Codex can apply it to related work
- **Examples** — if the output has a strict or non-obvious format, give 3–5 `<example>` tags.
  Include the usual condition and a minimum of one unusual condition
- **Length** — add structure where the initial prompt was ambiguous. Keep what it makes clear

Before you give the prompt, check it against all 7 foundations. Correct results that do not satisfy them.
</rewrite>

<output_format>
```
<thinking>
[context gathered · foundation-by-foundation diagnosis · ask vs assume · rewrite plan]
</thinking>

**Diagnosis**
✓/✗/N/A  Foundation — one-line note
...

**Context used** — what memory / AGENTS.md / codebase resolved
**Assumptions made** — only where context or answers didn't close the gap

**Improved prompt**
```
[Put the prompt in a code fence so it displays clearly in the terminal CLI]
```
```

On a new iteration, update only foundations with a change. Keep the other foundations.
For a named tool target (Codex, API, or a model), write a prompt that uses its strengths.
Always put the improved prompt in a triple-backtick code fence. Blockquotes (`>`) collapse in terminal renderers, so do not use them.
</output_format>

<examples>

<example type="technical — strong context">
**Input**: `automate what you can from the Theo v1 evaluation process`

<thinking>
memory_recall("theo v1 evaluation"): window 2026-02-27 to 2026-03-06, metrics, thresholds, data sources, human gates. AGENTS.md: Python/Airflow, SRE audience.

1. `Defines done` — ✗. The prompt gives no output format. Memory gives no plan or implementation preference. Infer implementation from autonomous mode. Low risk.
2. Names assumptions — ✗. Data sources not in prompt. Memory has them.
3. Specifies constraints — ✗. Human gates not in prompt. Memory has them.
4. Single scope — ✓.
5. `States what's been tried` — N/A. Greenfield.
6. Execution override — ✓. Implicit.
7. `Defines role` — ✗. Audience unstated. AGENTS.md confirms SRE.

The context answers all questions. Use an opening role and XML structure. Use memory and AGENTS.md. Name the assumption about output.

Self-check: all 7 pass. Golden rule: a colleague with AGENTS.md and Theo memory could follow this.
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

**Context used**: Theo memory gives the dates, metrics, thresholds, data sources, and human gates. AGENTS.md gives Python/Airflow and the SRE audience.
**Assumptions made**: Output is implementation with runnable tasks and reports. Autonomous operation mode, low risk.

**`Improved prompt`**:
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

1. `Defines done` — ✗. No count, format, or criteria.
2. Names assumptions — ✗. Taste, mood, genre all unknown. Cannot ground.
3. Specifies constraints — ✗. No exclusions in the prompt.
4. Single scope — ✓.
5. `States what's been tried` — N/A.
6. Execution override — ✓.
7. `Defines role` — N/A.

Each open question depends on personal preference. Memory has no related information.
Get the user's genre or mood first. Use AskUser because the answer can be a selection.
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

[AskUser: What are you in the mood for? → `Action/thriller` · Drama/indie · Comedy · Sci-fi/horror · Surprise me]

*User selects "Sci-fi / horror"*

**Assumptions made**: 5 recommendations, mix of well-known and less obvious. Streaming availability not filtered.

**`Improved prompt`**:
```
Recommend 5 sci-fi or horror films — a mix of well-known and less obvious picks. For each: title, one-sentence reason it fits, and where it sits on the scale from cerebral to visceral. Lean toward variety across sub-genres.
```
</example>

<example type="problem-solving — foundation 5 active">
**Input**: `fix the daemon startup crash`

<thinking>
memory_recall("daemon startup crash"): two earlier tries.
The 2026-02-20 change to socket path permissions did not correct the problem. The Ollama embed timeout on cold start remains open.

1. `Defines done` — ✗. No success criteria. What result shows that the daemon works?
2. Names assumptions — ✗. Which daemon? theo-daemon.py assumed from context. Local dev assumed — low risk.
3. Specifies constraints — ✗. The prompt does not name files out of scope.
4. Single scope — ✓.
5. `States what's been tried` — ✗. Memory has the two earlier tries. Include them so the next session does not do the same work again.
6. Execution override — ✓.
7. `Defines role` — N/A.

Success criteria are the most important open question. Memory identifies the daemon and the two earlier tries.
Write the scope, earlier tries, and success criteria.
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

**Context used**: Theo memory identifies the socket path change that did not help and the open Ollama cold-start timeout. AGENTS.md confirms theo-daemon.py.
**Assumptions made**: local dev environment, low risk. Success criteria: clean start + health check passes.

**`Improved prompt`**:
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
