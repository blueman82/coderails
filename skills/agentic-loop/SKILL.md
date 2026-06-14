---
name: agentic-loop
description: Multi-agent orchestration discipline. Load this skill IMMEDIATELY — taking precedence over /workflow, /prep, /push, and any other single-PR slash command — whenever the user authorises a sequence of agent-driven work. Specifically: any time the user says "TeamCreate", "spawn a team", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or authorises 3+ PRs in one instruction. ALSO load when the user authorises autonomous merge + deploy + verify chains, even for a single PR, if they have explicitly waived per-step confirmation. The phased method covers: reading the authorisation envelope verbatim, delegating planning/premortem skills to spawned agents (not main context), keeping main context as a pure orchestrator that NEVER implements — every code change (even a single-file edit) goes to a sonnet agent that does the implementation AND verifies its own artifact, escalating to TeamCreate only for ≥3 sequential PRs or dependency chains, verifying artifacts not idle pings, disproving symptom premises before spawning fixes, and matching confirmation cadence to envelope scope. This is NOT /workflow (which is single-PR prep → push → merge → wiki). This is the multi-agent orchestration layer that sits ABOVE /workflow and uses it as a subroutine. The cost of forgetting to delegate, re-asking for authorised confirmation, or trusting an idle ping as failure is enormous in long sessions — fire this skill aggressively rather than miss it.
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

## The phases

The phases below are sequential. Run them in order. Inside an authorised loop, phases 4-7 repeat per PR / per work-unit.

### Phase -1 — Sharpen the authorising prompt

**Run this phase UNLESS the user's prompt explicitly opts out.** Opt-out signals: "just do it", "skip improve-prompt", "don't improve the prompt", or any language that makes the directive unambiguous. On opt-out, skip directly to Phase 0. (Note: improve-prompt itself treats "just do it" as an unconditional skip — align with that.)

**Why this phase exists.** Phase 0 calls misreading the authorisation envelope "the root of most over-asking." Closing ambiguity once, up front, is cheaper than re-asking mid-loop. A sharpened authorising prompt is the cheapest input to a tighter envelope — it is the one intervention that improves every subsequent phase simultaneously.

**Step 1 — Invoke `/coderails:improve-prompt` on the authorising prompt.**

Run the improve-prompt skill against the user's authorising prompt:

> `/coderails:improve-prompt` — apply it to the prompt above.

The skill will surface ambiguities, fill gaps with grounded assumptions, and produce a rewritten prompt that passes its 7-foundation diagnosis. Let it run to completion before proceeding to Step 2.

**Step 2 — Ask the user how to proceed.**

After improve-prompt produces its output, use the `AskUserQuestion` tool to present three options:

> "Here's the improved prompt. How do you want to proceed?
> A) Proceed with the improved prompt as the authorising envelope
> B) Tweak it — tell me what to adjust and I'll revise
> C) Use the original prompt as-is"

On **A**: the improved prompt becomes the authorisation envelope. Phase 0 reads it verbatim.
On **B**: apply the user's tweak, re-present the revised prompt, and ask again (bounded to two revision passes — if a third is needed, something is wrong with the envelope itself; surface that).
On **C**: proceed with the original prompt unchanged; Phase 0 reads it verbatim.

The improved-and-approved prompt (or the original, if C was chosen) is what Phase 0 treats as the authorisation envelope. Phase 0's `<thinking>` block quotes it verbatim from here.

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

### Phase 0.5 — Orchestrator operating rules (the conductor obeys its own rules)

The orchestrator (main context) is subject to the same discipline it imposes on workers. In long sessions the orchestrator itself trips the user's stop hooks — confidence-label and verify-loop blocks — and every block is a stall that costs a manual turn to clear, exactly the cost this skill exists to remove.

Main context must, in its own output (not just in spawned-agent prompts):
- Confidence-label every substantive status claim — `(verified)` / `(inferred)` / `(guess)` (same taxonomy as Phase 11).
- Pre-tag any `## Did Not Verify` bullet that genuinely can't be checked, in the same turn it's written — an untagged bullet blocks the stop hook.
- Never narrate a claim about an artifact (PR merged, deploy live) without having run the check this turn (Phase 12).

The why: a factory whose conductor keeps tripping the wires it strung for the workers is not autonomous — it stalls on itself. Phase 11 disciplines the workers; Phase 0.5 disciplines the orchestrator. Past failure: in a real run the orchestrator tripped ~8 confidence-label / verify-loop blocks, each one a manual turn the user had to clear.

### Phase 1 — State the plan in bullets, ask once

Before the first agent spawn, write the full plan: phases, which agents per phase, parallel vs sequential, stop conditions. Use bullets. Keep it tight — the user reads this fast and decides whether to redirect.

Ask once: "Want me to execute this?" or "Confirm scope and I'll execute."

If yes → execute silently through to the end of the envelope.
If no → revise once based on feedback, then re-ask.

Do not loop more than twice on plan negotiation. If the third pass is needed, something is wrong with the envelope itself — surface that.

The harness choice itself — which loop skill drives this (`/agentic-loop` vs a flat loop vs a goal runner) — is part of the authorisation envelope (Phase 0), not a Phase 1 question. Resolve it once when reading the envelope and never re-surface it as "which approach do you want?". Past failure: a real run re-asked "select your approach: /agentic-loop /loop /goal" four times because harness selection leaked out of the envelope and into plan negotiation.

### Phase 2 — Pre-flight checks via spawned agents, not main context

Pre-planning skills (`/planning-sequence`, `/premortem`, `/claude-guardrails:assumptions`, `/claude-guardrails:notchecked`, `/wiki-query`) belong in a delegated agent, not in main context.

Spawn a single pre-flight agent whose prompt includes:
- The plan from Phase 1
- An instruction to invoke each relevant skill via its `Skill` tool call
- An instruction to return one consolidated report (plan-sequence findings + premortem failure modes + assumptions inventory + wiki findings)

Include `/wiki-query` in the pre-flight agent's skill list, scoped to the **whole plan theme** (not per-PR). The query is something like: "What does the wiki cover about [overall theme of the agentic loop]? Identify cross-PR constraints, gaps, superseded decisions, and anything the plan assumes but isn't enforced in code." This pre-empts the per-PR `/wiki-query` that `/workflow` Phase 2 runs — see Phase 9 for why per-PR wiki steps are suppressed inside this loop.

**Primitive-contract read (mandatory when the plan calls a primitive in a non-standard way).** If the plan calls a lock, queue, transaction, or other shared primitive in any of: nested calls, recursion, parallel from same process, re-entered from the same caller — the pre-flight agent MUST read the primitive's source and document its contract: raise vs. return-bool semantics, reentrancy (PK collision behaviour), owner identity, expiry/steal logic. The schema may have been written before anyone read the primitive's internals. Past failure: a "wrap both call sites with a DistributedLock" schema was structurally impossible because the lock used `attribute_not_exists(PK)` non-reentrant semantics and the two sites were a nested call, not parallel — would have 100%-no-posted on every trigger. Pre-flight caught it by reading `distributed_lock.py` directly; the schema author hadn't.

Spawn this pre-flight agent with `model: sonnet` — it's running skills, not making architectural decisions, and keeping it off opus controls cost.

**Clean-base check (mandatory orchestrator action in main context, before ANY worker is spawned).** Run `git fetch origin` then `git log --oneline origin/main..main` and `git status --short` yourself. If local `main` carries commits `origin/main` does not, or has uncommitted/untracked files, the base is DIRTY — a parallel session (or an earlier uncommitted edit) has polluted it. When the base is dirty:
- NEVER let a worker branch off local `main`. Every worker MUST create its worktree off freshly-fetched `origin/main` (`git worktree add <path> -b <branch> origin/main`), and the orchestrator must state this explicitly, by name, in the worker prompt.
- Carry the foreign file names into worker prompts as an explicit "these are not yours — never stage, commit, or include them" exclusion list.

Do this check even when the base looks clean — it is two cheap git reads and it pre-empts the single most expensive failure mode in a parallel-session loop: a worker's PR silently inheriting another session's WIP from a dirty base, which otherwise only surfaces at the merge gate. Past failure: a removal PR's file list silently included two unrelated docs (`durable-queue-design.md` and an architecture-review doc) inherited from a polluted local `main` via the worker branching off it. Phase 12 caught it at the merge gate, but the fix cost a full close-and-rebuild cycle — new branch off `origin/main`, cherry-pick the real commits, reopen the PR, close the contaminated one. A clean-base check at loop start would have forced origin/main-based worktrees from the first spawn and avoided the rebuild entirely.

The why: main context fills up fast in long sessions. Pre-flight output is dense and only useful for shaping the next move — perfect for delegation. Agents have skill access; passing the skill name in the prompt is enough.

### Phase 2.5 — Resolve design forks before execution, not during it

If the plan contains an unresolved architectural choice (which primitive, which topology, which of several viable shapes), resolve it BEFORE entering Phase 3 — not through live back-and-forth once workers are spawning.

Spawn one design agent (`model: sonnet` for the recon; escalate the synthesis to opus only if the tradeoff is genuinely close) whose prompt requires:
- Read the actual code paths the alternatives touch — not assumptions about them.
- Build a head-to-head of the viable shapes with the real constraint each one hits.
- Return ONE recommended shape, the rejected alternatives with the reason each lost, and the single fact that would flip the recommendation.

What happens with that recommendation depends on the envelope class (Phase 0) — this phase resolves the fork, it does NOT add a new human gate:
- **Full-autonomous ("crack on / ship N PRs without asking"):** auto-adopt the design agent's recommendation, record the chosen shape and the flip-condition in `progress.json`, and note it at the next approval-gate. Do NOT stall for sign-off — a design fork is neither a verification failure nor a destructive action, so Phase 0 says the loop proceeds.
- **Narrow-fix / diagnostic / ambiguous envelope:** surface the one recommendation as a single decision — "here's the shape, here's why, approve or redirect" — bounded like Phase 1 (ask once, don't loop), then enter Phase 3.

Either way the fork is closed by ONE design artifact before building starts — the loop does not start half-built while the design is still being argued turn by turn.

The why: a factory closes design questions at one decision point with evidence, not across twenty conversational turns while half-built — and on a full-autonomous envelope it closes them without a human round-trip at all. Past failure: a real run spent ~20 turns debating queue-vs-lease-vs-hybrid as ad-hoc Q&A interleaved with the build — that decision should have been one design-agent artifact resolved once, before any PR work began.

**Where the design artifact is written — never onto local `main`.** Any phase that produces a file — a design investigation page, a recon note, a `progress.json` — writes it *outside the code repo's working tree*: to the wiki vault (`config.wiki_path`) if it is wiki-bound, otherwise a temp dir outside the repo. It is promoted into the PR worktree only at build time (Phase 3); it never lands on local `main`, where an untracked file silently pollutes the base every worker branches from — exactly the contamination the Phase 2 clean-base check then has to catch downstream. The recon/design phase is logically read-only with respect to the code repo; keep it literally so.

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
- Manifest — the exact set of files this unit should touch, with the pre-push scope assertion (see Phase 3a)
- Terminal state — the concrete artifact that means done (PR open / merged); no mid-task hand-backs (see Phase 3a)
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
- **A manifest — the exact set of files this change should touch — plus a pre-push scope assertion.** Require: "before you push, run `git diff origin/main --name-only` and confirm the file list equals EXACTLY this manifest. If any file you did not intend to touch appears — especially one you never edited — STOP and report; do not push. A PR that carries files outside its manifest is a contamination, not a change." This catches a dirty base or a stray `git add -A` at push time, one stage before the orchestrator's merge gate, where it is far cheaper to fix. Past failure: a worker pushed a PR whose file list silently included two files from a polluted base; nobody asserted scope before push, so it surfaced only at the merge gate and forced a rebuild.
- **A terminal state stated as a concrete artifact, with no mid-task hand-backs.** The done-condition is an artifact that exists ("the PR is OPEN" or "the PR is MERGED"), never a sub-step. Add to the prompt: "You own this through that artifact existing. Do NOT hand back to the orchestrator in an intermediate state — after editing but before committing, after strictcode but before pushing, after review but before the PR is open. If you stop before the artifact exists, you have not finished; continue." Past failure: workers repeatedly stopped after running strictcode or an inline review and 'handed back to the orchestrator to push the PR', leaving the work uncommitted with no PR and forcing a resume cycle each time. Stating the terminal state as the artifact, not the sub-step, removes the premature hand-back.

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

### Phase 4b — PR review uses the six `pr-review-toolkit` agents plus `/security-review`, in parallel

When a phase reaches "review the PR" (after a `/workflow` agent has pushed a PR, before merge), the review is `/pr-review-toolkit:review-pr all` — fan out these **six specialised reviewers in parallel, in a single message with six `Agent` blocks**, each against the branch diff (`git -C <worktree> diff origin/main...HEAD`):

| # | `subagent_type` | Reviews | Spawn when |
|---|---|---|---|
| 1 | `pr-review-toolkit:code-reviewer` | General quality + CLAUDE.md compliance, bugs | always |
| 2 | `pr-review-toolkit:pr-test-analyzer` | Behavioural test coverage, mock-tautology, critical gaps | test files changed (almost always) |
| 3 | `pr-review-toolkit:silent-failure-hunter` | Swallowed exceptions, message-loss, spurious-success error paths | error handling / catch blocks / queue-delete semantics changed |
| 4 | `pr-review-toolkit:type-design-analyzer` | Protocol/type invariants, illegal-states-unrepresentable | new/changed types or protocol surfaces |
| 5 | `pr-review-toolkit:comment-analyzer` | Comment/docstring accuracy, comment rot | comments/docstrings added or behaviour-changing extractions |
| 6 | `pr-review-toolkit:code-simplifier` | Dead code from extractions, duplication, over-engineering (report-only, no edits) | always (polish pass) |

Skip a reviewer only when its trigger genuinely doesn't apply (e.g. no type changes → no type-design-analyzer). Default is all six. Spawn `model: sonnet`, read-only, and carry the Phase 11 confidence-label instruction into each prompt. Collect all reports, aggregate into Critical / Important / Suggestion, and feed any MERGE-BLOCKER back to a fix agent (Phase 5/10) BEFORE merge.

**Plus the native `/security-review` pass.** Alongside the six agents, run Claude Code's built-in `/security-review` on the same branch diff as part of this gate — it is a dedicated security review (auth/authz surfaces, injection, secret leakage, unsafe deserialisation, SSRF) that the six general reviewers do not specialise in. Run it in the worktree so it sees the branch's pending changes. Fold its findings into the same Critical / Important / Suggestion aggregation; any security MERGE-BLOCKER blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Do not substitute the generic `architect-review` + `debugger` + `ai-engineer` trio here.** That three-agent set is a separate general-purpose adversarial pattern (CLAUDE.md `feedback_three_parallel_adversarial_agents`) for design/architecture stress-tests — it is NOT the PR-review step. The canonical review step is `/pr-review-toolkit:review-pr all` = the six agents above. Past failure: spawned the architect/debugger/ai-engineer trio at PR-review time; corrected to the toolkit six.

### Phase 5 — Disprove the premise before each fix

Before spawning a "bug fix" agent for any reported regression, the fix agent's prompt must require:

> Verify the symptom in the source-of-truth FIRST. Slack pin-bar / GitHub PR state / Jira board / browser tabs all cache. Reproduce the bug via API call, prod log, DDB read, or git diff before any code change. If the symptom can't be reproduced via SOT, STOP and report — don't ship a fix to a non-bug.

In a long multi-agent session this pattern caught false alarms (stale Slack pin-bar views and design artefacts mistaken for regressions). The cost of disproving is one tool call; the cost of shipping a fix to a non-bug is a PR, a deploy, a rollback, and trust.

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

This rebase handles *staleness* (a base that fell behind as the loop's own PRs landed). It does NOT handle *pollution* (a local `main` carrying another session's commits) — that is the Phase 2 clean-base check's job, and the fix there is to branch workers off `origin/main`, not to rebase a polluted base onto itself. Staleness rebases away; pollution must never enter the worker's base in the first place.

### Phase 9 — Cluster wiki ingest, don't fragment

Run `/wiki-ingest` AND `/wiki-lint` ONCE at the end of the loop, with all related PRs as a cluster — not once per PR. Per memory `feedback_wiki_ingest_and_lint_post_merge`, lint must always pair with ingest; running one without the other is incomplete.

One source page covers the cluster. Updates to entities/services/concepts pages aggregate the cluster's changes. This matches memory `feedback_parallel_wiki_agents` (cluster together, don't fragment).

If the loop's PRs aren't thematically related (rare — TeamCreate usually clusters them), one ingest per cluster theme is fine. Avoid one-per-PR sprawl.

**Suppressing per-PR wiki steps in spawned `/workflow` agents:** place the following line as the **FIRST instruction** in every spawned agent's prompt inside this loop (not buried mid-section, not under the task-specific scope, not after the workflow steps — first):

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/wiki-query` and Phase 5 `/wiki-ingest`/`/wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

**Why first-line, not just "include":** workers comply with whatever sits at the top of their prompt and tend to shortcut past mid-section process notes — they treat the workflow steps as authoritative and treat anything that appears to constrain those steps as "optional polish" if it isn't load-bearing in the prompt structure. Past failure: a worker shipped a per-PR wiki PR despite the suppression instruction being present, because the instruction was below the workflow steps. The next worker, with the same instruction moved to the top of their prompt, complied cleanly. **Scope-suppression instructions go above scope-additive instructions in worker prompts.**

The orchestrator handles both ends: Phase 2 (plan-level wiki read before coding starts) and Phase 9 (cluster ingest+lint after all PRs are merged). Per-PR wiki steps inside `/workflow` would duplicate Phase 2's context query on stale partial state and fragment Phase 9's cluster ingest into one-per-PR sprawl.

**Wiki commits are artifacts too — verify they reached `origin/main`, and deliver them the way *this* repo accepts.** A delegated wiki agent reports a *commit SHA*, not a merged PR — and a commit is not a push. Close two failure modes at the loop boundary: (1) the agent commits to **local `main`** and never pushes — work stranded; (2) the agent pushes wiki files **direct to `main`**, which a branch-protection ruleset rejects (the protection Phase 7 already notes).

**Delivery is repo-specific.** If `main` is ruleset-protected, the wiki agent must deliver via a branch + PR off freshly-fetched `origin/main`, merged like any other change. Only where a repo *deliberately* permits direct wiki commits (e.g. a wiki dir gated behind a bypass env var) is a direct push acceptable — and even then it must be verified to have landed.

**Then verify, after `git fetch origin`:** confirm the content is on `origin/main` via the wiki PR's `mergedAt` or `git show origin/main:<wiki-file>`. Do **not** confirm a merge with `git merge-base --is-ancestor <agent-sha> origin/main` — a squash-merge rewrites the SHA, so the agent's commit is never an ancestor even when its content landed (`--is-ancestor` is the right probe only for *detecting* an unpushed commit before merge). A committed-but-unpushed SHA is a textbook false-success; the "committed" ping is a claim, not evidence (Phase 12).

Past failure: a wiki agent reported two commits "done"; they were on local `main`, unpushed, and `main` was ruleset-protected so a direct push was rejected. The orchestrator's origin check caught it; the fix was SHA-push → branch → PR → squash-merge → non-destructive `main` restore. Trusting the "committed" ping would have stranded the docs locally and left the next loop on a polluted base.

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

### Phase 13 — Confirm the factory actually ran (terminal self-audit)

At the end of the loop, before declaring done, the orchestrator audits its own autonomy from the `progress.json` counters and reports:
- **Human turns inside the envelope** — how many times the human had to intervene on work that was already authorised. Target: approaching zero. These are stalls the factory should have absorbed.
- **Genuine gates vs avoidable stalls** — split those human turns into (a) legitimate approval-gates and hard-stops (the factory working as designed) and (b) avoidable stalls: re-asks inside scope, orchestrator hook-blocks, design forks litigated live, re-orientation prompts. Only (b) counts against the factory.
- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.

This is the factory's own KPI. It makes "are we a factory yet?" measurable per run instead of asserted, and the avoidable-stall list is the input to the next iteration of this skill. A run with zero avoidable stalls and one approval-gate is the target shape; anything else names exactly what to fix.

## Context-window persistence

Do not stop work early because the context window is filling or a token budget is approaching. Context will compact and the session will continue — treat that as a non-event, not a stop condition.

**Loop state lives in a durable artifact, not in the conversation.** Maintain a single `progress.json` in the worktree as the source of truth for where the loop is. It is overwritten (not appended) on every phase boundary and holds: the authorisation envelope verbatim, the current phase, each work-unit's status (`pending`/`in-progress`/`done`/`blocked` with `blockedBy`), verified state carried between units (deployed version, test counts), and the human-turn counters for Phase 13. A single overwritten JSON object — read the whole file in one shot to know current state. Do not use an append-log (`.jsonl`) that has to be replayed to derive position, and that can leave a torn tail line after a crash.

After any compaction, drift, or "wait, where are we" moment, the orchestrator RE-READS `progress.json` — never the conversation — to re-orient. If the user ever has to remind the loop that it's mid-loop, the artifact wasn't being maintained. Git remains the authoritative checkpoint for code (commit all in-progress work before compaction); `progress.json` is the authoritative checkpoint for loop position.

Never artificially truncate a task or declare "done" mid-loop because of token pressure. If a genuine stop condition (see below) is not met, keep going.

## Stop conditions for the loop

Stop conditions come in two classes. The agent must not collapse them into one — a gate is not a wall.

**Hard-stop (abort the loop, wait for the human):**
1. Verification failure that can't be auto-recovered (Phase 4 or Phase 12 artifact check fails)
2. Premise disproven (Phase 5 — symptom can't be reproduced via SOT)
3. Genuinely ambiguous decision outside the authorisation envelope
4. Destructive/irreversible operation not previously authorised

On a hard-stop: report current state with confidence labels, propose the next move (don't just stop silently), and wait.

**Approval-gate (pause, surface a one-screen summary, PROCEED on yes):**
A named risk boundary the envelope flagged for human sign-off — e.g. a prod cutover / enable step. This is NOT a hard-stop and NOT a wall. The loop runs autonomously right up to the gate, then pauses, presents a single summary (what's about to happen, the artifacts behind it, what's irreversible about it), and proceeds the moment the human approves — without re-planning or re-asking the steps before it.

Model an approval-gate as "pause-then-proceed", never as "do not start". Past failure: a real run relabelled a prod-enable gate as "do not start / hard wall", which mis-stated its own terminal state and took two human turns to correct. The gate is a pause point inside the envelope, not the edge of it.

**Loop complete:**
5. All authorised work done and all gates passed — run Phase 13, then stop.

## A note on cadence

The user does not want a running narration of "now spawning X, now waiting for Y." They want:
- Brief status when a phase boundary is crossed
- Evidence when claiming success
- Clear stop on failure with the smallest readable summary

Idle pings from teammates are noise unless the artifact check (Phase 4) confirms a real failure. Don't react to every idle ping with a status update — match the cadence to the user's pull, not the runtime's push.
