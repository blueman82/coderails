---
name: agentic-loop
description: Multi-agent orchestration discipline. Load this skill IMMEDIATELY — taking precedence over /workflow, /prep, /push, and any other single-PR slash command — whenever the user authorises a sequence of agent-driven work. Specifically: any time the user says "TeamCreate", "spawn a team", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or authorises 3+ PRs in one instruction. ALSO load when the user authorises autonomous merge + deploy + verify chains, even for a single PR, if they have explicitly waived per-step confirmation. The 13-phase method covers: reading the authorisation envelope verbatim, delegating planning/premortem skills to spawned agents (not main context), keeping main context as a pure orchestrator that NEVER implements — every code change (even a single-file edit) goes to a sonnet agent that does the implementation AND verifies its own artifact, escalating to TeamCreate only for ≥3 sequential PRs or dependency chains, verifying artifacts not idle pings, disproving symptom premises before spawning fixes, and matching confirmation cadence to envelope scope. This is NOT /workflow (which is single-PR prep → push → merge → wiki). This is the multi-agent orchestration layer that sits ABOVE /workflow and uses it as a subroutine. The cost of forgetting to delegate, re-asking for authorised confirmation, or trusting an idle ping as failure is enormous in long sessions — fire this skill aggressively rather than miss it.
---

# Agentic Loop

How to run an autonomous multi-agent / multi-PR session so the user doesn't have to manually instruct every turn.

## Why this skill exists

In long agentic sessions, the assistant tends to drift back into bad habits:
- Running skills (`/planning-sequence`, `/premortem`, `/claude-guardrails:*`) in main context instead of delegating to agents
- Asking "want me to spawn an agent for X?" when X is obviously in scope
- Holding at human gates that were explicitly removed at session start
- Trusting an agent's "idle" notification as proof-of-failure when the agent often completed the work silently
- Spawning fix workers without first disproving the symptom premise

This skill encodes the working method so those failures don't keep happening. The cost of doing it wrong is large: each unnecessary stall is a manual prompt the user has to write to get the loop moving again, and a stalled loop loses the autonomy the user paid for in the first place.

## The 13 phases

The phases below are sequential. Run them in order. Inside an authorised loop, phases 4-7 repeat per PR / per work-unit.

### Phase 0 — Read the authorisation envelope

Before doing anything, ask: what did the user actually authorise?

The envelope is the standing instruction. Read it once at the start of the loop and keep it in mind.

Before responding to the first user message in an authorised loop, do this in a `<thinking>` block (this is the one place in the skill where the slow-down pass is worth the ceremony — misreading the envelope is the root of most over-asking):

```
<thinking>
- Verbatim quote of the user's authorising language: "..."
- Envelope class: full-autonomous / narrow-fix / diagnostic-only / ambiguous
- 3 sub-actions INSIDE the envelope: ...
- 3 sub-actions OUTSIDE the envelope (would require fresh ask): ...
- Stop conditions specific to this envelope: ...
</thinking>
```

Then respond.

**Envelope examples:**
- "Ship N PRs without asking" → full-autonomous. Includes merges, deploys, post-deploy cleanup, follow-up tickets within the same theme.
- "Fix this bug" → narrow-fix. Confirm before scope creep into adjacent files.
- "Crack on / human is dead" → full-autonomous. All routine sub-steps autonomous; only break the loop on verification failure or destructive/irreversible actions.
- "Help me debug" → diagnostic-only. Do not write code without explicit go-ahead.

Match the confirmation cadence to the envelope class for the rest of the session. The why: every "do you want me to..." inside an authorised envelope is a stall the user has to clear. Stalls cost more than the occasional over-reach you'd avoid by asking.

### Phase 1 — State the plan in bullets, ask once

Before the first agent spawn, write the full plan: phases, which agents per phase, parallel vs sequential, stop conditions. Use bullets. Keep it tight — the user reads this fast and decides whether to redirect.

Ask once: "Want me to execute this?" or "Confirm scope and I'll execute."

If yes → execute silently through to the end of the envelope.
If no → revise once based on feedback, then re-ask.

Do not loop more than twice on plan negotiation. If the third pass is needed, something is wrong with the envelope itself — surface that.

### Phase 2 — Pre-flight checks via spawned agents, not main context

Pre-planning skills (`/planning-sequence`, `/premortem`, `/claude-guardrails:assumptions`, `/claude-guardrails:notchecked`, `/wiki-query`) belong in a delegated agent, not in main context.

Spawn a single pre-flight agent whose prompt includes:
- The plan from Phase 1
- An instruction to invoke each relevant skill via its `Skill` tool call
- An instruction to return one consolidated report (plan-sequence findings + premortem failure modes + assumptions inventory + wiki findings)

Include `/wiki-query` in the pre-flight agent's skill list, scoped to the **whole plan theme** (not per-PR). The query is something like: "What does the wiki cover about [overall theme of the agentic loop]? Identify cross-PR constraints, gaps, superseded decisions, and anything the plan assumes but isn't enforced in code." This pre-empts the per-PR `/wiki-query` that `/workflow` Phase 2 runs — see Phase 9 for why per-PR wiki steps are suppressed inside this loop.

**Primitive-contract read (mandatory when the plan calls a primitive in a non-standard way).** If the plan calls a lock, queue, transaction, or other shared primitive in any of: nested calls, recursion, parallel from same process, re-entered from the same caller — the pre-flight agent MUST read the primitive's source and document its contract: raise vs. return-bool semantics, reentrancy (PK collision behaviour), owner identity, expiry/steal logic. The schema may have been written before anyone read the primitive's internals. Past failure: a "wrap both call sites with a DistributedLock" schema was structurally impossible because the lock used `attribute_not_exists(PK)` non-reentrant semantics and the two sites were a nested call, not parallel — would have 100%-no-posted on every trigger. Pre-flight caught it by reading `distributed_lock.py` directly; the schema author hadn't.

Spawn this pre-flight agent with `model: sonnet` — it's running skills, not making architectural decisions, and keeping it off opus controls cost.

The why: main context fills up fast in long sessions. Pre-flight output is dense and only useful for shaping the next move — perfect for delegation. Agents have skill access; passing the skill name in the prompt is enough.

### Phase 3 — Delegate all implementation to sonnet agents; TeamCreate when work has ≥3 sequential units or dependency chains

**Default: main context never implements.** It orchestrates — plans, delegates, verifies. Every implementation unit (even a single-file edit, even a tight sequential step) goes to a spawned **sonnet** agent. The two reasons, in order: keep main context clean (opus context is scarce and fills fast in long sessions), and keep cost down (sonnet does the typing, not opus). Treat a file edit done directly in main context as the exception that needs a reason, not the default.

This means the delegation decision is a two-rung ladder, not "delegate vs. do it yourself":

1. **Single sonnet `Agent` for impl + verify** — the default for any self-contained 1–2 unit of work (a bug fix, one PR, a single-file change). One agent does the implementation *and* verifies its own artifact before reporting. TeamCreate would be overkill here; main context doing it directly burns opus context and money for no benefit. See Phase 3a below for the prompt contract.
2. **TeamCreate** — when the loop has 3+ PRs or any cross-step dependency. See below.

The only work that legitimately stays in main context: reading for orchestration decisions (git status, `gh pr view`, log reads, the Phase 12 artifact checks), and the planning/cadence the skill describes. If you catch yourself running `Edit`/`Write`/`MultiEdit` in main context inside an authorised loop, stop — that work belongs in a sonnet agent.

When the loop has 3+ PRs or any cross-step dependency, **use the `TeamCreate` tool by name** and build a task list with explicit `blockedBy` dependencies via `TaskUpdate`. Don't just describe a "sequential PR loop" — actually invoke `TeamCreate`. The user can see the team in their UI and the task list becomes the shared source of truth.

If the user has explicitly named `TeamCreate` in their prompt, it is non-negotiable — invoke it even if a flat `Agent` loop would technically work.

Each task description must be **self-contained** so the spawned agent can act without re-reading the conversation. Include:
- Worktree path
- Branch name
- Model: sonnet (workers must be sonnet, not opus — controls cost and matches the orchestration pattern this skill encodes)
- JIRA ticket
- Verified state from prior tasks (deployed version, test counts, what's already wired)
- Exact step-by-step sub-steps
- Verify criteria
- Report-back instructions

Include this line in every agent prompt:
> "Don't go silently idle — send a completion message via SendMessage. Past agents have failed this way."

For bare 1-2 task work, a single `Agent` call is the right tool — don't over-engineer with TeamCreate (see Phase 3a).

### Phase 3a — Single sonnet agent for impl + verify (the TeamCreate-is-overkill case)

For self-contained work that doesn't justify a team — a bug fix, one PR, a single-file change, a tight sequence of steps with shared context — spawn **one** `Agent` with `model: sonnet` that owns both the implementation **and** the verification, then reports back a confidence-labelled result. Main context stays the orchestrator; it does not make the edit itself.

Why one agent does both impl and verify (not two): the verification (running the test, reading the diff, hitting the endpoint) produces exactly the dense output you delegated to keep out of main context. If main context re-verified every small change, it would refill with the diffs it just pushed away. The agent self-verifies; main context spot-checks only at dependency boundaries (Phase 12) or when the artifact check is cheap and the stakes are high.

The agent's prompt must be self-contained (it can't re-read the conversation) and include:
- **`model: sonnet`** — non-negotiable, same rule as team workers (Phase 3): cost control, and impl+verify is execution, not architecture.
- The exact change to make, with file paths and the success criteria stated as something testable.
- **A verify step the agent runs itself before reporting** — run the test / lint / build, read back the diff, hit the endpoint or read the log. State which one. "Implement X, then verify by running `Y`, and only report success if `Y` passes."
- **Report-back contract:** return a confidence-labelled summary (Phase 11), state what was run to verify (the command + its result, not just "verified"), and "don't go silently idle — send a completion message" (Phase 4 — sonnet agents go idle without reporting).
- If the work writes to git, the worktree/branch and a "commit your work" instruction so the artifact is durable for the orchestrator's Phase 4 check.

When the single agent goes idle without reporting, apply Phase 4 verbatim — check the artifact (git diff, PR state, log), not the ping. When it reports success, that's a Phase 12 claim, not evidence — re-check at dependency boundaries.

Escalate from one agent to TeamCreate the moment the work grows a third unit or a cross-unit dependency. Don't run three sequential solo `Agent` calls where a team with a `blockedBy` task list belongs — that's the case Phase 3 reserves for `TeamCreate`.

### Phase 4 — Spawn workers in waves, never block on idle pings

Sonnet agents (especially in teams) frequently complete work successfully but go idle **without sending a completion message**. The idle ping is not a failure signal — it's just "I stopped."

When an agent goes idle without a report:
1. Read the worktree `git status` and `git diff --stat`
2. Check the PR state via `gh pr view <N>` if a PR should exist
3. Read the prod log via `tsh ssh ...` if a deploy should have happened
4. Verify the artifact, not the ping

Only after the artifact check fails should you assume failure. Then respawn — and per Phase 10, give it a new name.

### Phase 5 — Disprove the premise before each fix

Before spawning a "bug fix" agent for any reported regression, the fix agent's prompt must require:

> Verify the symptom in the source-of-truth FIRST. Slack pin-bar / GitHub PR state / Jira board / browser tabs all cache. Reproduce the bug via API call, prod log, DDB read, or git diff before any code change. If the symptom can't be reproduced via SOT, STOP and report — don't ship a fix to a non-bug.

In a 7-hour Ketchup session this pattern caught 4 false alarms (stale Slack pin-bar views and design artefacts mistaken for regressions). The cost of disproving is one tool call; the cost of shipping a fix to a non-bug is a PR, a deploy, a rollback, and trust.

### Phase 6 — Match confirmation to authorisation envelope

Inside an authorised loop:
- Do NOT ask "want me to spawn for X?" if X is in the obvious scope of the authorisation envelope
- Do NOT ask "do you agree this is the right approach?" after you've already justified the approach in the same turn
- Self-merge, self-deploy, self-cleanup are included in the standard envelope
- Only break the loop on:
  - Verification failure (Phase 4 artifact check failed)
  - Ambiguity outside the envelope (genuinely new question, not covered by standing instruction)
  - Destructive or irreversible operations not previously discussed

Re-asking is more expensive than over-reaching by a small margin within scope. If the user wants to redirect, they will.

### Phase 7 — Skip-validation when cosmetic blockers trip deploy

When `./deploy` is blocked by black/isort/import-order failures AFTER the source-of-truth PR is already merged on main, that's deploy-script noise on cosmetic style — not a real blocker.

Use `./deploy --force --skip-drain --skip-validation`. Don't get stuck on it. Don't try to push a style fix to main (branch protection will reject direct push anyway). Don't open a one-line cosmetic PR mid-loop.

Memory: `feedback_deploy_skip_drain_default` already says skip-drain is the default; this extends to skip-validation in the same spirit.

### Phase 8 — Rebase before push on long parallel sessions

When a worktree's branch was created off main BEFORE the previous PR in the loop landed, its base will be stale. Before push, rebase:

```
cd <worktree>
git fetch origin
git rebase origin/main
```

The rebase will cleanly drop the auto-bumped `docker-compose.yml` version commit (it's already upstream). If the rebase has real conflicts in code, those are real and need resolution.

Without the rebase, push may still succeed but the PR will carry a duplicate docker-compose bump and confuse the diff review.

### Phase 9 — Cluster wiki ingest, don't fragment

Run `/wiki-ingest` AND `/wiki-lint` ONCE at the end of the loop, with all related PRs as a cluster — not once per PR. Per memory `feedback_wiki_ingest_and_lint_post_merge`, lint must always pair with ingest; running one without the other is incomplete.

One source page covers the cluster. Updates to entities/services/concepts pages aggregate the cluster's changes. This matches memory `feedback_parallel_wiki_agents` (cluster together, don't fragment).

If the loop's PRs aren't thematically related (rare — TeamCreate usually clusters them), one ingest per cluster theme is fine. Avoid one-per-PR sprawl.

**Suppressing per-PR wiki steps in spawned `/workflow` agents:** place the following line as the **FIRST instruction** in every spawned agent's prompt inside this loop (not buried mid-section, not under the task-specific scope, not after the workflow steps — first):

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/wiki-query` and Phase 5 `/wiki-ingest`/`/wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

**Why first-line, not just "include":** workers comply with whatever sits at the top of their prompt and tend to shortcut past mid-section process notes — they treat the workflow steps as authoritative and treat anything that appears to constrain those steps as "optional polish" if it isn't load-bearing in the prompt structure. Past failure: a worker shipped a per-PR wiki PR despite the suppression instruction being present, because the instruction was below the workflow steps. The next worker, with the same instruction moved to the top of their prompt, complied cleanly. **Scope-suppression instructions go above scope-additive instructions in worker prompts.**

The orchestrator handles both ends: Phase 2 (plan-level wiki read before coding starts) and Phase 9 (cluster ingest+lint after all PRs are merged). Per-PR wiki steps inside `/workflow` would duplicate Phase 2's context query on stale partial state and fragment Phase 9's cluster ingest into one-per-PR sprawl.

### Phase 10 — Use v2/v3 names when respawning a stuck agent

Dead agents continue to emit idle pings until the runtime cleans them up. If you respawn with the same name, you can't tell which idle ping is which.

Always respawn with a versioned name: `dockerfile-fixer` → `dockerfile-fixer-v2` → `dockerfile-fixer-v3`. The dead one's pings become identifiable noise; the live one's reports are unambiguous. The version bump doesn't change the model rule — respawned agents must also use `model: sonnet`.

### Phase 11 — Agent prompts include "confidence-label every claim"

Add to every spawned agent's prompt:

> Confidence-label every substantive claim in your output:
> - `(verified)` — directly observed via tool result, file read, or explicit user statement in this session
> - `(inferred)` — pattern-matched, recalled, or assumed from context
> - `(guess)` — best-effort with low confidence
>
> The user's stop hook enforces this. Propagate it into your work.

The why: when an agent reports "verified live in prod", you need to know whether they ran the verify command or assumed it from a log line. Confidence labels make that distinction explicit and reduce false success signals.

### Phase 12 — Status reports from agents are claims, not evidence

When an agent says "PR-N verified, deployed, working in prod" — treat that as a hypothesis, not a fact.

Before unblocking the next dependent task in the chain:
- Read the PR `mergedAt` via `gh pr view`
- Read the prod log line via `tsh ssh ...`
- Read the audit row or DDB record that confirms the new code path executed

**Re-check at the moment of action, not at the moment the report arrived.** State changes in the gap. If the worker says "PR is CONFLICTING" or "ready to merge" and you queue a corrective instruction (rebase, redo, wait), the artifact may have moved by the time the message lands. Always re-run `gh pr view` (or equivalent) at the moment you act on the report, not when you first read it. Past failure: orchestrator read CONFLICTING state when the worker first reported "ready", queued a rebase instruction, but by the time the worker received it the conflict had self-healed via an intervening merge commit — the rebase instruction was stale on arrival and triggered redundant work. The cost of one extra `gh pr view` between report and instruction is small.

This is more rigorous than checking the idle ping (Phase 4) — it's specifically the "next phase blocker" check. Past failure mode: agent reports PR-2 verified, you unblock PR-3, then PR-2 was actually broken (race condition surfaced only on second container restart), and PR-3 is now stacked on a bad base.

The cost of one extra tool call before unblocking the next phase is small. The cost of unblocking on a false report is hours.

## Context-window persistence

Do not stop work early because the context window is filling or a token budget is approaching. Context will compact and the session will continue — treat that as a non-event, not a stop condition.

Before compaction happens, checkpoint state: commit all in-progress work to git, write a brief progress note to a memory or a `progress.md` in the worktree, and record where the loop is in the phase sequence. Git is the authoritative checkpoint — uncommitted work is unrecoverable state.

Never artificially truncate a task or declare "done" mid-loop because of token pressure. If a genuine stop condition (see below) is not met, keep going.

## Stop conditions for the loop

The loop runs autonomously until ANY of:
1. Verification failure that can't be auto-recovered (Phase 4 or Phase 12 artifact check fails)
2. Premise disproven (Phase 5 — symptom can't be reproduced via SOT)
3. Genuinely ambiguous decision outside the authorisation envelope
4. Destructive/irreversible operation not previously authorised
5. All authorised work complete

On stop: report current state with confidence labels, propose the next move (don't just stop silently), and wait.

## A note on cadence

The user does not want a running narration of "now spawning X, now waiting for Y." They want:
- Brief status when a phase boundary is crossed
- Evidence when claiming success
- Clear stop on failure with the smallest readable summary

Idle pings from teammates are noise unless the artifact check (Phase 4) confirms a real failure. Don't react to every idle ping with a status update — match the cadence to the user's pull, not the runtime's push.
