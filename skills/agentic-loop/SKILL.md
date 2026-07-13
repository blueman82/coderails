---
name: agentic-loop
description: 'Multi-agent orchestration discipline. Load this skill IMMEDIATELY, taking precedence over /workflow, /prep, /push, and any other single-PR slash command, whenever the user authorises a sequence of agent-driven work. Specifically: any time the user says "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or authorises 3+ PRs in one instruction. ALSO load when the user authorises autonomous merge + deploy + verify chains, even for a single PR, if they have explicitly waived per-step confirmation. This is NOT /workflow (single-PR prep → push → merge → wiki); it sits ABOVE /workflow and uses it as a subroutine. Keep main context a pure orchestrator that never implements: every change goes to a spawned sonnet agent that verifies its own artifact, escalating to a spawned team only for ≥3 sequential PRs or dependency chains. Verify artifacts not idle pings; disprove symptom premises before spawning fixes; match confirmation cadence to envelope scope. Fire this skill aggressively — forgetting to delegate is costly in long sessions.'
---

# Agentic Loop

How to run an autonomous multi-agent / multi-PR session so the user doesn't have to manually instruct every turn.

## Why this skill exists

In long agentic sessions, the assistant tends to drift back into bad habits:
- Running skills (`/planning-sequence`, `/premortem`, `/coderails:assumptions`, `/coderails:notchecked`) in main context instead of delegating to agents
- Asking "want me to spawn an agent for X?" when X is obviously in scope
- Holding at human gates that were explicitly removed at session start
- Trusting an agent's "idle" notification as proof-of-failure when the agent often completed the work silently
- Spawning fix workers without first disproving the symptom premise

This skill encodes the working method so those failures don't keep happening. Each unnecessary stall is a manual prompt the user has to write — a stalled loop loses the autonomy the session was authorised for.

Repo-agnostic lessons promoted from accumulated loop retros live in [learned-failure-modes.md](learned-failure-modes.md) — machine-maintained via the `loop-retro-promotion` pipeline; read it alongside this skill.

## The phases

Nineteen-plus numbered phases (−2 through 13, with lettered sub-phases) is too many to hold in mind cold. Group them into five stages before descending into per-phase detail:

| Stage | Phases |
|---|---|
| Setup | -2, -1, 0, 0.5 |
| Pre-flight | 1, 2, 2.5, 2.6, 2.7 |
| Build | 3, 3a, 4 |
| Review & Ship | 4b, 5, 6, 7&8 |
| Wrap-up | 9, 10, 11, 12, 13 |

The phases below are sequential. Run them in order. Inside an authorised loop, phases 4-6 repeat per PR / per work-unit.

### Phase -2 — Stub `progress.json` first (the literal first action)

Before Phase -1 — before anything else — write a `progress.json` stub. This guarantees the loop's durable state file exists before the first stop, so the `loop_state_guard` Stop hook never trips a compliant loop; the block degrades to a backstop for a skipped stub.

**Resolve the path — never compute it yourself.** A repo- or cwd-derived key cannot be reproduced by hand. Get the absolute path by running the path helper (the path is keyed to the repo's `git --git-common-dir` when your cwd is inside a git repo, falling back to the raw cwd otherwise — so a mid-loop worktree hop resolves to the SAME path as the checkout it came from). The helper is stateless and re-derives this key on every call, so a loop that changes its own cwd's repo-ness mid-session (e.g. `git init`s an until-then-non-git cwd) will see its key change too — a rare, self-inflicted edge case, not one the helper guards against:

> `bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.sh"`

It prints the absolute path. Write the stub there with the Write tool (it creates the parent directory). If `${CLAUDE_PLUGIN_ROOT}` is not set in your shell, do **not** guess the path — proceed without the stub; the `loop_state_guard` hook will block once on your first stop and hand you the exact path to use. Copy that path verbatim. Either way, the path comes from the helper (directly, or via the guard which also calls it) — never from your own derivation.

**The stub:**

```json
{
  "schema_version": 1,
  "session_id": "<this session's id>",
  "status": "initialising",
  "created": "<ISO8601 timestamp>",
  "authorising_prompt_raw": "<the user's authorising prompt, verbatim>",
  "completed_marker": <carry forward the prior file's completed_marker if one exists at this path, else 0>
}
```

If a `progress.json` already exists at the path from an earlier loop in this session, read its `completed_marker` and carry it forward into the new stub (do not reset it to 0) — this is what lets the guard tell a genuinely-finished loop from a new one that re-armed it (see the teardown rule below).

`loop_stop_counts` gets different treatment depending on the prior file's `status`, because it is HOOK-OWNED (see Context-window persistence below):
- Prior file `status != "complete"` (mid-loop re-stub, e.g. a recovery after a restart): carry `loop_stop_counts` forward verbatim into the new stub, so a mid-loop recovery doesn't silently reset the count the `loop_stall_guard` hook has been maintaining.
- Prior file `status == "complete"` (re-arming for a NEW loop): reset `loop_stop_counts` to `{}` (omit the field from the stub) — the completed loop's counts are already preserved in its own `retro.json`; carrying them forward would bleed the finished loop's stop counts into the new loop's Phase 13 report.

### Phase -1 — Sharpen the authorising prompt

**Run this phase UNLESS the user's prompt explicitly opts out.** Opt-out signals: "just do it", "skip improve-prompt", "don't improve the prompt", or any language that makes the directive unambiguous. On opt-out, skip directly to Phase 0. (Note: improve-prompt itself treats "just do it" as an unconditional skip — align with that.)

**Why this phase exists.** Phase 0 calls misreading the authorisation envelope "the root of most over-asking." Closing ambiguity once, up front, is cheaper than re-asking mid-loop. A sharpened authorising prompt is the cheapest input to a tighter envelope — it is the one intervention that improves every subsequent phase simultaneously.

**Step 1 — Invoke `/coderails:improve-prompt` on the authorising prompt.**

Run the improve-prompt skill against the user's authorising prompt:

> `/coderails:improve-prompt` — apply it to the prompt above.

The skill will surface ambiguities, fill gaps with grounded assumptions, and produce a rewritten prompt that passes its 7-foundation diagnosis. Let it run to completion before proceeding to Step 2.

**Step 2 — Ask the user how to proceed.**

**Delivery constraint — the improved prompt must be visible, not just asked-about.** Text emitted before a tool call is not rendered in the Claude Code terminal UI — only text with no trailing tool call, or content inside the tool call itself, reaches the user. This means "present the improved prompt as text, then call `AskUserQuestion`" silently drops the prompt: the user sees only the question, never the content it's asking about. Use one of two delivery mechanisms instead:
- (a) End the turn with the improved prompt as the final text — no trailing tool call — and issue the `AskUserQuestion` call in the *next* turn; or
- (b) Embed the improved prompt directly inside the `AskUserQuestion` call itself: its question text, option descriptions, or option preview fields. This renders regardless of turn-splitting.

Past failure: the improved prompt was presented as text immediately followed by an `AskUserQuestion` call, twice in the same run — invisible both times, because pre-tool-call text does not render.

After improve-prompt produces its output, deliver it via (a) or (b) above, then present three options through `AskUserQuestion`:

> "Here's the improved prompt. How do you want to proceed?
> A) Proceed with the improved prompt as the authorising envelope
> B) Tweak it — tell me what to adjust and I'll revise
> C) Use the original prompt as-is"

On **A**: the improved prompt becomes the authorisation envelope. Phase 0 reads it verbatim.
On **B**: apply the user's tweak, re-present the revised prompt via (a) or (b) again, and ask again (bounded to two revision passes — if a third is needed, something is wrong with the envelope itself; surface that).
On **C**: proceed with the original prompt unchanged; Phase 0 reads it verbatim.

On adopting an improved envelope (outcome **A** or **B**), update `progress.json.authorising_prompt_raw` to the adopted text so the field stays the canonical post-Phase-0 envelope. Outcome **C** needs no update — the Phase -2 stub already wrote the original prompt verbatim.

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
- Clean-break auto-demote authority explicitly granted? yes/no — if yes, quote the exact clause naming it (not inferred from a general full-autonomous classification)
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

The orchestrator (main context) is subject to the same discipline it imposes on workers. Inside an active, incomplete loop, the two discipline Stop hooks — confidence-label and verify-loop — demote a would-be block to a model-visible warn (`additionalContext` on the Stop event) rather than stopping the turn outright; the discipline itself hasn't changed, the warn is the correction signal the orchestrator acts on next turn. Outside an active loop, and for worker output (SubagentStop), both hooks still block outright. Even at warn-level, a missed warn is still a cost — it's the cost this skill exists to keep to a minimum, just paid as a drifted transcript instead of a forced regeneration.

Main context must, in its own output (not just in spawned-agent prompts):
- Confidence-label every substantive status claim — `(verified)` / `(inferred)` / `(guess)` (same taxonomy as Phase 11).
- Pre-tag any `## Did Not Verify` bullet that genuinely can't be checked, in the same turn it's written — an untagged bullet blocks the stop outside a loop and for workers, and is the first thing the in-loop warn will name.
- Never narrate a claim about an artifact (PR merged, deploy live) without having run the check this turn (Phase 12).
- End any stopping turn inside an active loop with a LOOP-STOP declaration line — `LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>` — as the FINAL line of the turn, emitted in the SAME turn as the confidence-label and Did-Not-Verify requirements above — that ending-line position is the contract this skill defines and the hook's category accounting assumes: when a turn carries more than one LOOP-STOP-shaped line (e.g. a quoted example), `loop_stall_guard` counts only the last one, so the last line must be the declaration that reflects the turn's actual outcome. Bundling all three matters more, not less, in the warn era: the confidence-label and verify-loop hooks no longer block the orchestrator's in-loop Stop turns, so nothing else forces those labels and DNV tags into the transcript — the bundle is what keeps them present for post-hoc audit, and one composed ending beats clearing one stop hook only to trip another (`loop_stall_guard` still blocks). Declaring `complete` means the loop is done: also set `progress.json` `status: "complete"` and run the Phase 13 teardown. The declaration line is all that's required — `loop_stop_counts` is HOOK-OWNED: the `loop_stall_guard` hook itself increments the matching category on a valid declaration; never write or compute this field yourself.

The why: Phase 11 disciplines the workers; Phase 0.5 disciplines the orchestrator — because a conductor that ignores its own warns drifts the loop just as surely as a worker that trips a hard block. Past failure: loop f87a0a2e forced ~69 turn regenerations in one crack-on loop (49 confidence-label blocks + 20 verify-loop blocks) — the incident that motivated demoting these two hooks to warn-level inside an active loop.

### Phase 1 — State the plan in bullets, ask once

Before the first agent spawn, write the full plan: phases, which agents per phase, parallel vs sequential, stop conditions. Use bullets. Keep it tight — the user reads this fast and decides whether to redirect.

Ask once: "Want me to execute this?" or "Confirm scope and I'll execute."

If yes → execute silently through to the end of the envelope.
If no → revise once based on feedback, then re-ask.

Do not loop more than twice on plan negotiation. If the third pass is needed, something is wrong with the envelope itself — surface that.

The harness choice itself — which loop skill drives this (`/coderails:agentic-loop` vs a flat loop vs a goal runner) — is part of the authorisation envelope (Phase 0), not a Phase 1 question. Resolve it once when reading the envelope and never re-surface it as "which approach do you want?". Past failure: a run re-asked "select your approach" 4× because harness choice leaked out of the envelope into plan negotiation.

### Phase 2 — Pre-flight checks via spawned agents, not main context

Pre-planning skills (`/coderails:planning-sequence`, `/coderails:premortem`, `/coderails:assumptions`, `/coderails:notchecked`, `/coderails:wiki-query`) belong in a delegated agent, not in main context.

Spawn a single pre-flight agent whose prompt includes:
- The plan from Phase 1
- An instruction to invoke each relevant skill via its `Skill` tool call
- An instruction to return one consolidated report (plan-sequence findings + premortem failure modes + assumptions inventory + wiki findings)

Include `/coderails:wiki-query` in the pre-flight agent's skill list, scoped to the **whole plan theme** (not per-PR). The query is something like: "What does the wiki cover about [overall theme of the agentic loop]? Identify cross-PR constraints, gaps, superseded decisions, and anything the plan assumes but isn't enforced in code." This pre-empts the per-PR `/coderails:wiki-query` that `/coderails:workflow` Phase 2 runs — see Phase 9 for why per-PR wiki steps are suppressed inside this loop.

**Retro intake.** The pre-flight agent additionally reads `standing-orders.md` at the repo-key dir (derive it as the grandparent of the path printed by `hooks/scripts/lib/agentic_loop_path.sh` — i.e. `dirname` of `dirname` of that path) and the last N=5 `retro.json` files under `<repo-key-dir>/*/retro.json` (mtime-sorted). It returns (a) premortem entries seeded from OBSERVED past failure modes and (b) a "carry into worker prompts" list of applicable lessons. Intake is additive-only: it may add cautions, assertions, and premortem entries; it may never relax a gate, skip a phase, or pre-justify an eval amendment. Gate changes remain human-owned. First-loop no-op: no retros + no overlay → skip silently, not an error.

**Primitive-contract read (mandatory when the plan calls a primitive in a non-standard way).** If the plan calls a lock, queue, transaction, or other shared primitive in any of: nested calls, recursion, parallel from same process, re-entered from the same caller — the pre-flight agent MUST read the primitive's source and document its contract: raise vs. return-bool semantics, reentrancy (PK collision behaviour), owner identity, expiry/steal logic. The schema may have been written before anyone read the primitive's internals. Past failure: a "wrap both sites with a DistributedLock" schema was impossible — the lock's `attribute_not_exists(PK)` semantics are non-reentrant and the sites were nested, not parallel; only reading the primitive's source caught it.

Spawn this pre-flight agent with `model: sonnet` — it's running skills, not making architectural decisions, and keeping it off opus controls cost.

**Clean-base check (mandatory orchestrator action in main context, before ANY worker is spawned).** Run `git fetch origin` then `git log --oneline origin/main..main` and `git status --short` yourself. If local `main` carries commits `origin/main` does not, or has uncommitted/untracked files, the base is DIRTY — a parallel session (or an earlier uncommitted edit) has polluted it. When the base is dirty:
- NEVER let a worker branch off local `main`. Every worker MUST create its worktree via `coderails:using-git-worktrees`, which accepts a declared base ref — the orchestrator must state one explicitly, by name, in the worker prompt: "Use the using-git-worktrees skill with base ref `origin/main` — not local `main`, not HEAD." This keeps worktree mechanics (native-tool detection, ignore-verification, directory selection) on the shared skill instead of Phase 3 reinventing them inline, while the `origin/main`-base requirement — a loop-specific safety invariant — travels through the skill's own declared-base-ref mechanism rather than being asserted outside it.
- Carry the foreign file names into worker prompts as an explicit "these are not yours — never stage, commit, or include them" exclusion list.

Do this check even when the base looks clean — it is two cheap git reads and it pre-empts the single most expensive failure mode in a parallel-session loop: a worker's PR silently inheriting another session's WIP from a dirty base, which otherwise only surfaces at the merge gate. Past failure: a removal PR silently carried two unrelated docs inherited from a polluted local `main`; it surfaced only at the merge gate and cost a full close-and-rebuild cycle.

The why: main context fills up fast in long sessions. Pre-flight output is dense and only useful for shaping the next move — perfect for delegation. Agents have skill access; passing the skill name in the prompt is enough.

### Phase 2.5 — Resolve design forks before execution, not during it

If the plan contains an unresolved architectural choice (which primitive, which topology, which of several viable shapes), resolve it BEFORE entering Phase 3 — not through live back-and-forth once workers are spawning.

Spawn one design agent (`model: sonnet` for the recon; escalate the synthesis to opus only if the tradeoff is genuinely close) whose prompt requires:
- Read the actual code paths the alternatives touch — not assumptions about them.
- Build a head-to-head of the viable shapes with the real constraint each one hits.
- Return ONE recommended shape, the rejected alternatives with the reason each lost, and the single fact that would flip the recommendation.
- Apply `/coderails:brainstorming`'s design-quality discipline *without* its human-approval gates: weigh the viable approaches against each other rather than taking the first that works, cut anything speculative (**YAGNI**), and prefer the shape whose units stay small and independently testable (**design-for-isolation**). The loop can't run brainstorming itself (its steps block on a human — see Phase 2.7); this reuses its *thinking*, not its control flow.

What happens with that recommendation depends on the envelope class (Phase 0) — this phase resolves the fork, it does NOT add a new human gate:
- **Full-autonomous ("crack on / ship N PRs without asking"):** auto-adopt the design agent's recommendation, record the chosen shape and the flip-condition in `progress.json` — append `{phase: "2.5", decision: "<chosen shape + flip-condition>"}` to `progress.json`'s `decisions_absorbed` array — and note it at the next approval-gate. Do NOT stall for sign-off — a design fork is neither a verification failure nor a destructive action, so Phase 0 says the loop proceeds.
- **Narrow-fix / diagnostic / ambiguous envelope:** surface the one recommendation as a single decision — "here's the shape, here's why, approve or redirect" — bounded like Phase 1 (ask once, don't loop), then enter Phase 3.

Either way the fork is closed by ONE design artifact before building starts — the loop does not start half-built while the design is still being argued turn by turn.

The why: design forks resolved mid-build cost twenty turns of interleaved debate; resolved once up front they cost one. On a full-autonomous envelope, no human round-trip is needed. Past failure: a run spent ~20 turns debating queue-vs-lease-vs-hybrid as ad-hoc Q&A interleaved with the build — it should have been one design artifact resolved before any PR work.

**Where the design artifact is written — never onto local `main`.** Any phase that produces a file — a design investigation page, a recon note, a `progress.json` — writes it *outside the code repo's working tree*: to the wiki vault (`config.wiki_path`) if it is wiki-bound, otherwise a temp dir outside the repo. It is promoted into the PR worktree only at build time (Phase 3); it never lands on local `main`, where an untracked file silently pollutes the base every worker branches from — exactly the contamination the Phase 2 clean-base check then has to catch downstream. The recon/design phase is logically read-only with respect to the code repo; keep it literally so.

### Phase 2.6 — Resolve disposition before replacement work (clean-break vs preserve-compat)

When the Phase 1 plan contains a work-unit that **retires an existing code path** — there is a *named thing being replaced* (a function, module, endpoint, schema, or flag the change removes from use) — resolve its **disposition** once, up front, before the first spawn. This is the migration analogue of Phase 2.5's design fork: asked once, not re-litigated.

**Trigger precisely.** The fork fires only when an existing path is being *retired*, not merely when new code calls or wraps old code. If nothing is being removed from use, there is no disposition question. A concrete "what named thing does this remove?" test is deliberately harder to self-exempt from than a vague "is this a migration?".

**The fork, asked once:**
- **clean-break** — the old path is removed in the same unit. No shims, bridges, adapters, or compatibility flags remain.
- **preserve-compat** — the old path is kept behind a shim, justified by a **specific named blocker**: a named consumer still on the old path that cannot migrate in this unit. A generic justification ("safer", "less risky", "to avoid breakage") is NOT sufficient and must be rejected — name the consumer or choose clean-break.

**clean-break is the default recommendation for a retirement.** Recommend clean-break unless a specific named blocker exists. This is deliberate: the model's untold prior leans toward preserving the old path because removal feels destructive, and that prior is exactly what silently doubles migration work. Requiring a named blocker stops the prior being laundered into the human's explicit approval — where it would become invisible to the Phase 13 counter.

**What happens with the answer depends on the envelope class (Phase 0)** — this resolves the fork, it does NOT add a human gate:
- **Full-autonomous:** adopt clean-break by default, record it, proceed. Surface a preserve-compat choice (with its named blocker) at the next approval-gate; do not stall.
- **Narrow-fix / diagnostic / ambiguous:** surface the disposition as one decision — "clean-break recommended, here's why" — bounded like Phase 1 (ask once, don't loop).

**Record** per work-unit in `progress.json`: `disposition`, and when `preserve-compat`, the `named_blocker` and a mandatory `removal_ticket`. The disposition decision also appends `{phase: "2.6", decision: "<clean-break or preserve-compat, with named_blocker if applicable>"}` to `progress.json`'s `decisions_absorbed` array.

The why: an unresolved disposition defaults silently to preserve-compat — the cautious answer that keeps a path the change was meant to remove, forcing a redo. Clean-break as the default, closed once before execution, prevents the doubled work. Past failure: a migration kept legacy shims because the model assumed the human wanted them; it had to be re-run with "remove the shims" — double the work.

### Phase 2.7 — Commit the resolved design to durable `spec.md` and `plan.md`

This phase fires ONLY when the loop has **≥3 work-units or a cross-unit dependency** — the same line Phase 3 draws to choose a spawned team over a single agent. A 1–2-unit fix that Phase 3 routes to a single agent needs no separate design docs: the envelope (Phase 0) + `progress.json` + the one self-contained task description already carry everything. If the loop is below that threshold, skip 2.7 (both sub-steps) entirely.

When it fires, run both sub-steps in order:

**2.7a — write `spec.md`.** Write a durable `spec.md` to the loop-state dir — the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`, run at Phase -2), next to `progress.json`, outside the code repo, **not committed** (loop state, not a PR deliverable). This is a **commit of design the loop has already resolved**, not interactive brainstorming — a loop cannot brainstorm with itself; the forks were closed at 2.5 and 2.6. Record:
- the authorisation envelope verbatim (Phase 0);
- the design-fork decision and its flip-condition (Phase 2.5);
- the disposition decision(s) and any named blocker (Phase 2.6);
- the success criteria — what "done" means for the whole loop;
- the high-level work-unit boundaries (the detailed decomposition is Phase 2.7b's plan).

The `spec.md` is loop state, keyed to this orchestrator's run, exactly like `progress.json` — not a shareable design record. When ad-hoc loop work genuinely needs handing to a human, that is what `/coderails:handoff` is for.

**2.7b — write `plan.md` via `/coderails:writing-plans`.** Produce a durable `plan.md` in the loop-state dir (next to `spec.md` and `progress.json`, outside the repo, not committed) by invoking **`/coderails:writing-plans`** — the same one-line skill-reference idiom Phase 3/3a use for `/coderails:test-driven-development`.

`plan.md` is the **static SSOT** for the decomposition; `progress.json` is the **dynamic position** against it. The plan is **consumed, not write-only**, in both directions:
- **Phase 3 builds its task list directly from `plan.md`** — the shared task list (`TaskCreate`/`TaskUpdate`) and the Phase 3/3a worker descriptions derive from the plan's tasks, so the two are consistent by construction rather than re-derived from conversation.
- **After any compaction the orchestrator re-reads `plan.md` to recover *scope* (what to build)** the same way it re-reads `progress.json` to recover *position* (where we are).

**2.7c — generate and freeze loop-scope evals via `/coderails:task-evals`.** Alongside `spec.md`/`plan.md`, invoke **`/coderails:task-evals`** (scope: `loop`) to produce a frozen `evals.json` defining the loop's end-state success evals. Two triggers fire this sub-step, stated explicitly because they're independent: (1) a loop that reaches Phase 2.7 at all is tier-2-eligible on work-unit count alone (2.7 itself only fires at ≥3 work-units); (2) an irreversible-surface trigger (publish, deploy, migration, data deletion, external send) can independently apply even to a <3-unit loop that still reached 2.7 via the cross-unit-dependency clause. The frozen `evals.json` (scope: `loop`) lives beside `progress.json`/`spec.md`/`plan.md` in the loop-state dir — same "never committed, outside the repo" rule as those two files. Grading this file at loop end is `post_evals.sh grade-loop`'s job, not the orchestrator's — see Phase 13. The eval author anchors goal state on `progress.json`'s `authorising_prompt_raw`, per `task-evals`'s oracle-independence rule.

The same `/coderails:task-evals` invocation also produces per-work-unit PR-scope eval refs (scope: `pr`, one per work-unit). These travel into worker prompts the same way disposition travels under Phase 3's existing "Disposition — ... copied **verbatim** into the task description" bullet: a ref recorded only in `progress.json`/`plan.md` and absent from the worker prompt does not exist for the worker — identical framing to the disposition rule above.

(This is the one place the `plan.md`↔`progress.json` relationship is named. It is stated here, standalone, on purpose — the `## Context-window persistence` section, which describes `progress.json`, is not edited.)

### Phase 3 — Delegate all implementation to sonnet agents; spawn a team when work has ≥3 sequential units or dependency chains

**Default: main context never implements.** It orchestrates — plans, delegates, verifies. Every implementation unit (even a single-file edit, even a tight sequential step) goes to a spawned **sonnet** agent. The two reasons, in order: keep main context clean (opus context is scarce and fills fast in long sessions), and keep cost down (sonnet does the typing, not opus). Treat a file edit done directly in main context as the exception that needs a reason, not the default.

This means the delegation decision is a two-rung ladder, not "delegate vs. do it yourself":

1. **Single sonnet `Agent` for impl + verify** — the default for any self-contained 1–2 unit of work (a bug fix, one PR, a single-file change). One agent does the implementation *and* verifies its own artifact before reporting. A spawned team would be overkill here; main context doing it directly burns opus context and money for no benefit. See Phase 3a below for the prompt contract.
2. **Spawn a team** — named teammates via the `Agent` tool, coordinated through a shared task list (`TaskCreate`/`TaskUpdate` with `blockedBy` dependencies) and `SendMessage`, when the loop has 3+ PRs or any cross-step dependency. See below.

The only work that legitimately stays in main context: reading for orchestration decisions (git status, `gh pr view`, log reads, the Phase 12 artifact checks), and the planning/cadence the skill describes. If you catch yourself running `Edit`/`Write`/`MultiEdit` in main context inside an authorised loop, stop — that work belongs in a sonnet agent.

When the loop has 3+ PRs or any cross-step dependency, spawn each worker as a named teammate via the `Agent` tool and build a task list with explicit `blockedBy` dependencies via `TaskCreate`/`TaskUpdate`. Don't just describe a "sequential PR loop" — actually spawn the named agents and create the task list. The user can see each teammate and the task list becomes the shared source of truth; use `SendMessage` to coordinate between them.

If the user has explicitly asked for a spawned team in their prompt, it is non-negotiable — spawn named teammates even if a flat sequence of solo `Agent` calls would technically work.

Each task description must be **self-contained** so the spawned agent can act without re-reading the conversation. Include:
- Worktree path
- Branch name
- Model: sonnet (workers must be sonnet, not opus — controls cost and matches the orchestration pattern this skill encodes)
- JIRA ticket
- Verified state from prior tasks (deployed version, test counts, what's already wired)
- Exact step-by-step sub-steps
- Construction method — when the deliverable is code (the change adds or alters a function, method, or branch that *can* carry a test), instruct the worker to build it test-first via `/coderails:test-driven-development` (failing test → minimal code → refactor). This holds even if the unit also touches non-code files. For pure docs/config/prose with no testable code, there is no test to write first — keep the verify-your-artifact contract. For the full worker-prompt construction contract (implementer/reviewer prompt templates + the per-task review loop), see `/coderails:subagent-driven-development`.
- Construction discipline — the worker holds itself to `coderails:verification-before-completion` while working, not only at hand-off: no "should work now"/"tests probably pass" framing mid-task, run the actual check before claiming any sub-step done. This is additive to, not a substitute for, the end-of-task artifact gate (Phase 4b) — the artifact gate proves the deliverable exists and passes; this discipline stops premature success claims *before* that artifact is even produced.
- Verify criteria
- Manifest — the exact set of files this unit should touch, with the pre-push scope assertion (see Phase 3a)
- Disposition — for a retirement unit, the `clean-break`/`preserve-compat` decision from Phase 2.6 copied **verbatim** into the task description, plus (if preserve-compat) the `named_blocker`. The worker acts only on its own prompt; a disposition recorded in `progress.json` but absent from the prompt silently reverts the unit to the model's preserve-default — the exact failure this discipline exists to stop.
- Lessons — applicable standing-orders entries copied verbatim into the task description (same travel rule and rationale as disposition: a lesson absent from the prompt does not exist for the worker).
- Terminal state — the concrete artifact that means done (PR open / merged); no mid-task hand-backs (see Phase 3a)
- Report-back instructions
- Hook-seam — commits hit `test_gate` (resolution: fix the failing tests), pushes and PR-creates hit `enforce_pr_workflow` (satisfied by the `/coderails:push` / `/workflow` you run), edits stay on the feature-branch worktree so `no_edit_on_main` won't fire, merges hit the eval-artifact gate in `scripts/merge.sh` (satisfied by running `/coderails:task-evals` + `/coderails:post-evals` before `/coderails:merge`)

Include this line in every agent prompt:
> "Don't go silently idle — send a completion message via SendMessage. Past agents have failed this way."

For bare 1-2 task work, a single `Agent` call is the right tool — don't over-engineer with a spawned team (see Phase 3a).

### Phase 3a — Single sonnet agent for impl + verify (the spawned-team-is-overkill case)

For self-contained work that doesn't justify a team — a bug fix, one PR, a single-file change, a tight sequence of steps with shared context — spawn **one** `Agent` with `model: sonnet` that owns both the implementation **and** the verification, then reports back a confidence-labelled result. Main context stays the orchestrator; it does not make the edit itself.

Why one agent does both impl and verify (not two): the verification output is dense — exactly the kind that fills main context. The agent self-verifies; main context spot-checks only at dependency boundaries (Phase 12) or when the artifact check is cheap and the stakes are high.

The agent's prompt must be self-contained (it can't re-read the conversation) and include:
- **`model: sonnet`** — non-negotiable, same rule as team workers (Phase 3): cost control, and impl+verify is execution, not architecture.
- The exact change to make, with file paths and the success criteria stated as something testable.
- **Construction method (when the deliverable is code).** If the change adds or alters a function, method, or branch that *can* carry a test, the worker builds it test-first via `/coderails:test-driven-development`: write the failing test, watch it fail for the right reason, then the minimal code to pass, then refactor green — even if the PR also touches non-code files. For pure docs/config/prose with no testable code, there is no failing test to write first; the verify step below is by inspection instead.
- **Construction discipline.** The agent holds itself to `coderails:verification-before-completion` throughout implementation, not only at the report-back step: no "should work now" framing on any intermediate claim, run the actual check before asserting a sub-step is done. Additive to the report-back contract below, not a replacement for it.
- **A verify step the agent runs itself before reporting** — run the test / lint / build, read back the diff, hit the endpoint or read the log. State which one. "Implement X, then verify by running `Y`, and only report success if `Y` passes."
- **Report-back contract:** return a confidence-labelled summary (Phase 11), state what was run to verify (the command + its result, not just "verified"), and "don't go silently idle — send a completion message" (Phase 4 — sonnet agents go idle without reporting).
- If the work writes to git, the worktree/branch and a "commit your work" instruction so the artifact is durable for the orchestrator's Phase 4 check.
- **A manifest — the exact set of files this change should touch — plus a pre-push scope assertion.** Require: "before you push, run `git diff origin/main --name-only` and confirm the file list equals EXACTLY this manifest. If any file you did not intend to touch appears — especially one you never edited — STOP and report; do not push. A PR that carries files outside its manifest is a contamination, not a change." This catches a dirty base or a stray `git add -A` at push time, one stage before the orchestrator's merge gate, where it is far cheaper to fix. Past failure: a worker pushed a PR carrying two files from a polluted base — no pre-push scope assertion, so it surfaced only at the merge gate and forced a rebuild.
  When the unit's disposition is `clean-break`, the assertion also covers compat: before push, confirm no compatibility shim, bridge, adapter, or legacy code path for the replaced functionality remains. If one does, clean-break is not finished — remove it or STOP and report. This worker assertion is a **first-pass smell test, not the gate** — the independent reviewer (Phase 4b) is the gate, because the worker that wrote a shim is the party least able to see it as one.
- **The disposition, verbatim** — for a retirement unit, the `clean-break`/`preserve-compat` decision from Phase 2.6 and (if preserve-compat) the `named_blocker`. The single agent cannot re-read the conversation; the decision must travel in its prompt or it does not exist for the worker.
- Lessons — applicable standing-orders entries copied verbatim into the task description (same travel rule and rationale as disposition: a lesson absent from the prompt does not exist for the worker).
- **A terminal state stated as a concrete artifact, with no mid-task hand-backs.** The done-condition is an artifact that exists ("the PR is OPEN" or "the PR is MERGED"), never a sub-step. Add to the prompt: "You own this through that artifact existing. Do NOT hand back to the orchestrator in an intermediate state — after editing but before committing, after engineering-principles but before pushing, after review but before the PR is open. If you stop before the artifact exists, you have not finished; continue." Past failure: workers stopped after engineering-principles and "handed back to push the PR", leaving work uncommitted with no PR — stating the terminal state as the artifact removes the premature hand-back.
- **Hook-seam —** commits hit `test_gate` (resolution: fix the failing tests), pushes and PR-creates hit `enforce_pr_workflow` (satisfied by the `/coderails:push` / `/workflow` you run), edits stay on the feature-branch worktree so `no_edit_on_main` won't fire, merges hit the eval-artifact gate in `scripts/merge.sh` (satisfied by running `/coderails:task-evals` + `/coderails:post-evals` before `/coderails:merge`)

When the single agent goes idle without reporting, apply Phase 4 verbatim — check the artifact (git diff, PR state, log), not the ping. When it reports success, that's a Phase 12 claim, not evidence — re-check at dependency boundaries.

Escalate from one agent to a spawned team the moment the work grows a third unit or a cross-unit dependency. Don't run three sequential solo `Agent` calls where a set of named teammates with a `blockedBy` task list belongs — that's the case Phase 3 reserves for spawning a team.

### Phase 4 — Spawn workers in waves, never block on idle pings

Sonnet agents (especially in teams) frequently complete work successfully but go idle **without sending a completion message**. The idle ping is not a failure signal — it's just "I stopped."

When an agent goes idle without a report:
1. Read the worktree `git status` and `git diff --stat`
2. Check the PR state via `gh pr view <N>` if a PR should exist
3. Read the prod log via your prod log access (`ssh`, `kubectl logs`, cloud console — whatever the project uses) if a deploy should have happened
4. Verify the artifact, not the ping

Only after the artifact check fails should you assume failure. Then respawn — and per Phase 10, give it a new name.

### Phase 4b — PR review invokes `/pr-review-toolkit:review-pr <PR#>` as a Skill, then `/coderails:post-review <PR#>`

When a phase reaches "review the PR" (after a `/workflow` agent has pushed a PR, before merge), invoke the **`/pr-review-toolkit:review-pr <PR#>`** Skill — passing the PR number as the argument — which itself fans out the six specialised reviewers plus a security pass. Do NOT hand-roll the reviewers as separate `Agent` or `Task` spawns; use the Skill invocation.

**Invoking `/pr-review-toolkit:review-pr <PR#>` with the PR number is REQUIRED to satisfy the merge gate, because `enforce_pr_workflow` only accepts the `review-pr` Skill (with the PR number in args) as merge evidence — a manually-spawned agent fanout leaves no evidence the gate recognises and the merge will block.** The gate also recognises `scripts/merge.sh <PR#>` invocations (not just raw `gh pr merge`) as the same merge subcommand, so a hand-rolled review cannot merge through the wrapper script either.

**Review tier ladder.** All tiers — regardless of the PR's own eval-artifact tier (Phase 4b's eval gate above is a separate, orthogonal check) — invoke `/pr-review-toolkit:review-pr <PR#>` (the toolkit self-scales its reviewer fan-out by change shape; see its "Determine Applicable Reviews" step) plus `/coderails:post-review <PR#>`. Only at tier 0 MAY the separate `/security-review` pass below be skipped, and only after checking the actual diff file list (`gh pr diff <PR#> --name-only` or `git diff origin/main...HEAD --name-only`): any path under `hooks/` or `scripts/`, or any change touching auth/exec/network-fetch code, FORCES the security pass regardless of the declared tier. The override keys off the diff, never the self-assigned tier label — reusing the self-assigned tier alone to gate a security control would be the same self-exemption shape the task-evals tier rules exist to resist. Tier 1/2 PRs run the full Phase 4b unchanged, security pass included.

**After `review-pr` completes and all applied findings (blocking and worthwhile) are committed and pushed, invoke `/coderails:post-review <PR#>`.** This posts the SHA-bound review artifact — a machine-marked GitHub comment — that the `/merge` gate requires before merging. Loop symmetry: this is the same artifact gate that `/coderails:workflow`'s Phase 3 wires in for non-loop use. Both paths produce the same artifact; `/merge` checks both the same way. Run `post-review` after findings are applied and the follow-up commit is pushed, so the artifact is stamped against the final head SHA.

Before `/coderails:merge`, the loop must also produce a second, independent artifact: run `/coderails:task-evals` (scope: `pr`; docs-only/single-unit PRs that meet its tier-0 predicate get the lightweight exemption path) then `/coderails:post-evals`. `scripts/merge.sh` hard-gates on this eval artifact separately from the review artifact above — same fail-closed posture, no config opt-out.

**Worktree teardown, immediately after `/coderails:merge` confirms this work-unit's PR is merged.** A work-unit's worktree (created per the `origin/main`-based instruction above) is scoped to that one PR — once it's merged, the worktree has no further purpose and must not be left to accumulate across a multi-work-unit loop. Run the same cleanup mechanics as `coderails:finishing-a-development-branch`'s Step 6 (`cd` to main repo root, `git worktree remove <path>`, `git worktree prune`), gated by the same provenance check: only remove worktrees the loop itself created (under `.worktrees/`/`worktrees/`), never a harness-owned workspace. This runs per-work-unit at this point in Phase 4b — not deferred to Phase 9/13's loop-level teardown, which handles wiki/retro artifacts, not worktrees.

The six review dimensions the Skill covers:

| # | Reviewer | Reviews | Runs when |
|---|---|---|---|
| 1 | `code-reviewer` | General quality + CLAUDE.md compliance, bugs | always |
| 2 | `pr-test-analyzer` | Behavioural test coverage, mock-tautology, critical gaps | test files changed (almost always) |
| 3 | `silent-failure-hunter` | Swallowed exceptions, message-loss, spurious-success error paths | error handling / catch blocks / queue-delete semantics changed |
| 4 | `type-design-analyzer` | Protocol/type invariants, illegal-states-unrepresentable | new/changed types or protocol surfaces |
| 5 | `comment-analyzer` | Comment/docstring accuracy, comment rot | comments/docstrings added or behaviour-changing extractions |
| 6 | `code-simplifier` | Dead code from extractions, duplication, over-engineering (report-only, no edits) | always (polish pass) |

Collect all reports, aggregate into Critical / Important / Suggestion, and feed any MERGE-BLOCKER back to a fix agent (Phase 5/10) BEFORE merge.

The `silent-failure-hunter` row earns its keep even on tiny diffs: on the one-function PR #142 fix, it caught a real swallowed-crash-payload bug pre-merge. This is why the tier ladder above never drops the toolkit review itself — only the separate `/security-review` pass at tier 0.

**Plus the native `/security-review` pass.** Alongside the six agents, run Claude Code's built-in `/security-review` on the same branch diff as part of this gate — it is a dedicated security review (auth/authz surfaces, injection, secret leakage, unsafe deserialisation, SSRF) that the six general reviewers do not specialise in. Run it in the worktree so it sees the branch's pending changes. Fold its findings into the same Critical / Important / Suggestion aggregation; any security MERGE-BLOCKER blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not the report-only suggestions row 6 produces by default. **The orchestrator cannot downgrade this finding unilaterally.** Its only two moves: (a) actually fix it — remove the compat path, or (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason. If a fully-unattended envelope genuinely cannot tolerate ever hard-stopping at this gate, the human must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never something the orchestrator grants itself mid-run. The why: clean-break enforced by worker self-assertion alone is self-attestation by the party with motive to keep the path — and letting that SAME party (the orchestrator) also grade the independent reviewer's finding reintroduces the identical loophole one level up. Past failure: the original shim rework happened because no independent check hunted the compat the author had rationalised as necessary.

**Do not substitute the generic `architect-review` + `debugger` + `ai-engineer` trio here.** That three-agent set (`architect-review` + `debugger` + `ai-engineer`) is a separate general-purpose adversarial pattern for design/architecture stress-tests, used elsewhere for pressure-testing a proposed design before it's built — it is NOT the PR-review step. The canonical review step is `/pr-review-toolkit:review-pr all` = the six agents above. Past failure: spawned the architect/debugger/ai-engineer trio at PR-review time; corrected to the toolkit six.

### Phase 5 — Disprove the premise before each fix

Before spawning a "bug fix" agent for any reported regression, the fix agent's prompt must require:

> Verify the symptom in the source-of-truth FIRST. Slack pin-bar / GitHub PR state / Jira board / browser tabs all cache. Reproduce the bug via API call, prod log, DDB read, or git diff before any code change. If the symptom can't be reproduced via SOT, STOP and report — don't ship a fix to a non-bug.

This is a specific application of `/coderails:verify` — the same "re-derive from sources only, no recall, no inference" discipline, applied to one claim: "this bug currently reproduces." Point the fix agent at `/coderails:verify` (claim: the reported symptom) rather than re-deriving the sources-only instruction inline each time.

Past failure: this pattern caught false alarms — stale Slack pin-bar views and design artefacts mistaken for regressions. The cost of disproving is one tool call; the cost of shipping a fix to a non-bug is a PR, a deploy, a rollback, and trust.

**Once a fix is diagnosed, before implementing it, run `/coderails:disconfirm` on the diagnosis.** Phase 5 checks whether the bug exists; this checks whether the proposed fix is actually right, before code gets written against it. Argue against the diagnosis — what would falsify it, what edge case breaks it, what did the fix agent assume away. This is cheap (one more tool call) relative to implementing, reviewing, and reverting a fix for the wrong root cause. Skip this step only when the fix is a direct, mechanical application of an already-verified design (e.g. this session's dashboard UX findings — each treatment was already confirmed against source during brainstorming, so there is no fresh diagnosis left to disconfirm). A consciously absorbed disconfirm-skip is an in-scope decision — append it to `progress.json`'s `decisions_absorbed` at the same phase boundary where `progress.json` is already being updated for this work-unit.

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

A notable in-scope action taken without a check-in under this phase is also a consciously absorbed decision — append it to `progress.json`'s `decisions_absorbed` at the phase boundary where `progress.json` is already updated.

### Phases 7 & 8 — stack-specific deploy/push tactics live in a feedback memory, not here

Deploy and push gotchas tied to a particular stack — skip-validation flags when a deploy script blocks on cosmetic lint, rebase-before-push when a versioned artifact (e.g. a compose file) bumps on every PR — belong in your own feedback memory for that stack, not in this general skill. Keep this skill stack-agnostic.

### Phase 9 — Cluster wiki ingest, don't fragment

Run `/coderails:wiki-ingest` AND `/coderails:wiki-lint` ONCE at the end of the loop, with all related PRs as a cluster — not once per PR. Lint must always pair with ingest — running one without the other leaves the wiki either unverified (ingest with no lint) or unrefreshed (lint with no ingest); treat the two as one step, not two optional ones.

One source page covers the cluster. Updates to entities/services/concepts pages aggregate the cluster's changes. Clustering related updates into one pass keeps the wiki's per-topic pages coherent; running one wiki agent per PR instead fragments a single theme across many small, redundant edits.

If the loop's PRs aren't thematically related (rare — a spawned team's task list usually clusters them), one ingest per cluster theme is fine. Avoid one-per-PR sprawl.

**Suppressing per-PR wiki steps in spawned `/coderails:workflow` agents:** place the following line as the **FIRST instruction** in every spawned agent's prompt inside this loop (not buried mid-section, not under the task-specific scope, not after the workflow steps — first):

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/coderails:wiki-query` and Phase 5 `/coderails:wiki-ingest`/`/coderails:wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

**Why first-line, not just "include":** workers shortcut past mid-section process notes and treat anything that appears to constrain the workflow steps as "optional polish." Past failure: a worker shipped a per-PR wiki PR because the suppression instruction sat below the workflow steps; moving it to the top fixed it. **Scope-suppression instructions go above scope-additive instructions in worker prompts.**

The orchestrator handles both ends: Phase 2 (plan-level wiki read before coding starts) and Phase 9 (cluster ingest+lint after all PRs are merged). Per-PR wiki steps inside `/coderails:workflow` would duplicate Phase 2's context query on stale partial state and fragment Phase 9's cluster ingest into one-per-PR sprawl.

**Wiki commits are artifacts too — verify they reached `origin/main`, and deliver them the way *this* repo accepts.** A delegated wiki agent reports a *commit SHA*, not a merged PR — and a commit is not a push. Close two failure modes at the loop boundary: (1) the agent commits to **local `main`** and never pushes — work stranded; (2) the agent pushes wiki files **direct to `main`**, which a branch-protection ruleset rejects.

**Delivery is repo-specific.** If `main` is ruleset-protected, the wiki agent must deliver via a branch + PR off freshly-fetched `origin/main`, merged like any other change. Only where a repo *deliberately* permits direct wiki commits (e.g. a wiki dir gated behind a bypass env var) is a direct push acceptable — and even then it must be verified to have landed.

**Then verify, after `git fetch origin`:** confirm the content is on `origin/main` via the wiki PR's `mergedAt` or `git show origin/main:<wiki-file>`. Do **not** confirm a merge with `git merge-base --is-ancestor <agent-sha> origin/main` — a squash-merge rewrites the SHA, so the agent's commit is never an ancestor even when its content landed (`--is-ancestor` is the right probe only for *detecting* an unpushed commit before merge). A committed-but-unpushed SHA is a textbook false-success; the "committed" ping is a claim, not evidence (Phase 12).

Past failure: a wiki agent reported two commits "done" that were unpushed on local `main` (ruleset-protected, so a direct push was rejected); the origin check caught it before the docs were stranded.

**Docs-drift check — run `/sync-docs` at the loop boundary**

After the cluster wiki ingest+lint, the orchestrator runs `/sync-docs` ONCE at the loop boundary. Wiki ingest updates the external knowledge base; `/sync-docs` is the complement — it audits the repo's own in-tree docs (e.g. README.md, AGENTS.md, docs/REFERENCE.md) for drift against the just-merged code.

Run it even without Serena (the `--semantic` backend) — omit `--semantic` for the traditional file-comparison audit, which still catches drift. Do not skip `/sync-docs` just because Serena isn't installed.

Delegate it to a spawned agent, same as the wiki step, to keep orchestrator context clean.

**Disposition of findings:** `/sync-docs` surfaces drift; the orchestrator must triage. Fix only drift the loop's own PRs introduced. Surface pre-existing drift to the user rather than silently folding unrelated doc fixes into the loop — that is scope creep. This mirrors the loop's finding-triage discipline.

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
- Read the prod log line via your prod log access (`ssh`, `kubectl logs`, cloud console)
- Read the audit row or DDB record that confirms the new code path executed

**Re-check at the moment of action, not at the moment the report arrived.** State changes in the gap. If the worker says "PR is CONFLICTING" or "ready to merge" and you queue a corrective instruction (rebase, redo, wait), the artifact may have moved by the time the message lands. Always re-run `gh pr view` (or equivalent) at the moment you act on the report, not when you first read it. Past failure: a CONFLICTING state self-healed via an intervening merge before the queued rebase instruction landed — stale on arrival, it triggered redundant work. One extra `gh pr view` between report and instruction is cheap.

This is more rigorous than checking the idle ping (Phase 4) — it's specifically the "next phase blocker" check. Past failure: an agent reported PR-2 verified, PR-3 was unblocked, then PR-2 proved broken (race surfaced on the 2nd restart) — PR-3 stacked on a bad base.

The cost of one extra tool call before unblocking the next phase is small. The cost of unblocking on a false report is hours.

### Phase 13 — Confirm the factory actually ran (terminal self-audit)

**This phase is mandatory and singular, not optional and not repeatable mid-loop.** It runs exactly once, only at the very end of the loop, immediately before the `complete` LOOP-STOP declaration — never as a mid-loop check-in, never skipped because the loop "felt straightforward." A loop that reaches `complete` without this report has not actually finished; the `loop_stall_guard` hook's `retro.json` requirement (see the teardown contract below) is what makes skipping it structurally hard, not just discouraged. The report is a summary, not a checkpoint — it does not pause for approval and does not ask the human anything; it tells them what happened.

At the end of the loop, before declaring done, the orchestrator audits its own autonomy from the `progress.json` counters and reports two raw, unscored facts — no numeric pass/fail scorecard, no "target: approaching zero" framing. The human is the only party positioned to judge "should I have been asked about that?"; hand them the raw list rather than have the process pre-grade itself:

- **`LOOP-STOP` category counts, broken down by type** — the per-category counts of this loop's `LOOP-STOP` declarations (`progress.json` `loop_stop_counts`: `hard-stop`, `approval-gate`, `awaiting-input`, `complete`). This field is HOOK-OWNED — the `loop_stall_guard` hook increments it on every valid declaration; read it as-is, do not compute or edit it yourself. Report the raw breakdown with no verdict attached — already artifact-backed from the declared stops, hard to fake. A high `awaiting-input` count is worth the human's attention, but this section states the count, not a judgement on it.
- **Decisions absorbed** — a flat, unscored list of in-scope decisions the loop made autonomously without asking (e.g. a Phase 2.5 design-fork auto-adopted, a Phase 2.6 disposition defaulted to clean-break, a Phase 5 disconfirm-skip, a Phase 6 in-scope action taken without a check-in). No self-justification text attached to each entry, no automated "this looks calibrated" stamp — just what was decided and where (phase/work-unit). This list is COPIED VERBATIM from `progress.json`'s `decisions_absorbed` array, chronological (oldest first) — never reconstructed from conversation memory, which is exactly the kind of after-the-fact self-report this phase exists to avoid.

Also report, unscored, alongside the two facts above:
- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the report reads "clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.
- **Loop-scope eval result** — graded via `post_evals.sh grade-loop` (never hand-written into `evals.json`), the loop's final `evals.json` `result` (`GO`/`NO-GO`/a tier-0-exemption-with-justification), reported unscored, and any `amendments` entries (post-freeze eval edits with recorded reasons) — an amendment made after a grader verdict must carry its fresh re-grade (`regraded_by` recorded; `grade-loop` refuses otherwise): a verdict flipped by an orchestrator-written status is an audit failure, not a pass, the same way the "Decisions absorbed" bullet above reports the Phase 2.5/2.6 forks — unscored, no self-issued verdict. Distinguish this explicitly, mirroring the disposition-violation framing above: **"no `evals.json` record found" for a ≥3-work-unit loop is an audit failure, not a pass** — distinguish it from a genuine `GO` the same way this section already distinguishes "0 disposition violations" from "no disposition record found".

This is the factory's own audit — raw facts for the human to judge, not a self-issued verdict. A clean-looking scorecard is more dangerous than an honest unscored list because it is more likely to be trusted uncritically; the two facts above can only be gamed by omission, and omission from a flat list is easier for a human to spot than a fabricated pass on a scorecard.

**Teardown write contract — ordered, and it runs BEFORE the `complete` declaration.** The `loop_stall_guard` hook blocks a `complete` declaration when `retro.json` is absent, malformed, or not `schema_version` 1 — so the retro must be written before the declaration. Run these four steps in order:

1. **Assemble `retro.json` (`schema_version` 1) beside `progress.json`.** Fields: `session_id`, `created`, `loop_ordinal` (= `completed_marker` after the Phase 13 bump), `envelope` (verbatim from `progress.json`), `loop_stop_counts` (copied **verbatim** from `progress.json` — HOOK-OWNED, never recomputed), `decisions_absorbed` (copied **verbatim** from `progress.json`'s array, not reconstructed from conversation memory — same rule as the Phase 13 bullet above), `disposition_record` (distinguish "0 violations" from "no-record", same framing as the self-audit above), `evals` (`result`/`amendments`/unresolved P1s), `artifacts` (PRs + the verifying check), `hook_blocks` (via `bash -c 'source "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/discipline_common.sh" && dc_mine_hook_blocks "<session_id>"'`), `review_themes`, `raw_notes`. The schema has **no `verdict` field** — raw and unscored is structural, not an oversight: the retro records what happened, it does not grade it.
2. **Update `standing-orders.md` (at the repo-key dir).** Match this loop's retro failure modes against existing entries: a match resets that entry's `loops_since_recurrence` to 0, updates `last_recurred`, and appends evidence; a genuinely new failure mode appends a new entry (fields: `id`, `created`, `failure_mode`, `lesson`, `evidence`, `last_recurred`, `loops_since_recurrence`). Increment `loops_since_recurrence` on every non-matched surviving entry. When an entry's `loops_since_recurrence` reaches K=5 (a constant stated here, not config), MOVE it to `standing-orders-decayed.md` — a tombstone, **never a delete**; the graduation predicate's "one clean decay" is checked against this file. This step is additive-or-recurrence-only: no metric-based removal anywhere.
3. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
4. **Only then** set `progress.json` `status: "complete"` and declare `LOOP-STOP: complete`.

## Context-window persistence

Do not stop work early because the context window is filling or a token budget is approaching. Context will compact and the session will continue — treat that as a non-event, not a stop condition.

**Loop state lives in a durable artifact, not in the conversation.** Maintain a single `progress.json` at the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`) — outside the code repo, keyed to the repo (or cwd outside a repo) **and this session's id**, so it survives this session's own restart/compaction, never pollutes the base every worker branches from, and never collides with another session's file in the same directory. Resolve the path by running the helper (Phase -2); never compute it yourself. The helper reads `$CLAUDE_CODE_SESSION_ID` (set in every Bash tool call) when no session_id argument is given, so you normally don't need to pass one explicitly. It is overwritten (not appended) on every phase boundary and holds: the authorisation envelope verbatim, the current phase, a `work_units` field (a JSON object keyed by unit id, each entry carrying at least a `status`: `pending`/`in-progress`/`done`/`blocked` with `blockedBy`) — the loop-scope evals gate (`loop_state_guard`) reads `.work_units | length` off this field to decide whether the ≥3-work-unit eval threshold applies, failing open (no block) when the field is absent, so keep it populated whenever the loop tracks ≥1 work-unit — verified state carried between units (deployed version, test counts), per-category `loop_stop_counts` (`{hard-stop, approval-gate, awaiting-input, complete}`) for Phase 13 — **HOOK-OWNED**: written solely by the `loop_stall_guard` hook on each valid `LOOP-STOP` declaration; the orchestrator never writes or increments it, and on any wholesale rewrite of this file must re-read the existing `progress.json` first and carry `loop_stop_counts` forward according to the same conditional as the Phase -2 stub rule above (verbatim on a mid-loop rewrite, reset to `{}` when the prior file's `status` was `"complete"`) — and, for any work-unit that retires an existing code path, its `disposition` (`clean-break` | `preserve-compat`), plus, when `preserve-compat`, the `named_blocker` (the specific consumer still on the old path that justifies keeping it) and the `removal_ticket` tracking the deferred removal — and `decisions_absorbed`, the chronological (oldest-first) array of `{phase, decision}` entries appended at each phase boundary that absorbs an in-scope decision (Phases 2.5, 2.6, 5, 6). A single overwritten JSON object — read the whole file in one shot to know current state. Do not use an append-log (`.jsonl`) that has to be replayed to derive position, and that can leave a torn tail line after a crash.

**Lifecycle, enforced by the `loop_state_guard` Stop hook (presence + ownership).** The file moves through a fixed lifecycle, and the guard blocks any stop where an active loop has no session-owned file:
- **Stub-first (Phase -2):** `status: "initialising"`, stamped with this `session_id`.
- **Enrich at Phase 0:** record the envelope verbatim; `status: "in-progress"`.
- **Update at each phase boundary:** current phase, work-unit states, Spec A's disposition fields, `last_updated` — carry `loop_stop_counts` forward per the same conditional as the Phase -2 stub rule (never computed or edited by the orchestrator; see above).
- **Teardown at Phase 13:** `status: "complete"`, and set `completed_marker` to the number of agentic-loop loops run in this session so far — i.e. the prior `completed_marker` (default 0) **plus 1**. Because this skill is invoked once per loop, that ordinal matches the guard's count of agentic-loop invocations, which is how the guard distinguishes a finished loop from a new one.

**Recency — a second loop is not masked by a stale `complete`.** This skill supports multiple loops in one long session. A prior loop's `status: "complete"` must not silence the guard for a later loop. When a new loop starts, Phase -2's stub-first overwrites the file (`status` back to `initialising`), which is the primary re-arm signal. The `completed_marker` is the backstop: if a new loop skips its stub, the guard still sees that the current invocation count exceeds the recorded `completed_marker` and blocks, forcing a re-initialisation. This is why teardown must bump `completed_marker` and stub-first must carry it forward.

**Honest boundary.** The guard guarantees the file *exists* and is *this session's* — not that its content is faithfully maintained (the same limit `check_verify_loop.sh` documents). Keeping the file current is still your job; the guard only catches its absence.

After any compaction, drift, or "wait, where are we" moment, the orchestrator RE-READS `progress.json` — never the conversation — to re-orient. If the user ever has to remind the loop that it's mid-loop, the artifact wasn't being maintained. Git remains the authoritative checkpoint for code (commit all in-progress work before compaction); `progress.json` is the authoritative checkpoint for loop position.

**Concurrent loops in one directory.** `progress.json` is keyed by repo (or cwd outside a repo) *and* session_id (Phase -2), so two `agentic-loop` sessions running concurrently against the same repo each get their own file — no race, no last-writer-wins — regardless of which worktree of that repo each session's cwd happens to be in: worktrees of the same repo now resolve to the SAME progress.json directory by design (that is the fix), and `session_id` remains the sole isolating key within it, exactly as it already was for two sessions sharing one literal directory. This relies on Claude Code's `session_id` staying stable for the life of one continuous conversation (across its own compaction/restart), while differing between genuinely separate conversations. `loop_state_guard.sh`'s session-mismatch check still fails closed if a file's own path disagrees with the session_id recorded inside it (a copied or hand-edited file) — a corruption signal, unchanged in what it compares; repo-keying only widens which cwds share a directory. A loop that must not let another session see its working-tree changes still wants a separate git worktree — that isolation is about the working tree, not about `progress.json`, which is shared on purpose across a repo's worktrees.

Never artificially truncate a task or declare "done" mid-loop because of token pressure. If a genuine stop condition (see below) is not met, keep going.

When a work-unit delegates to `subagent-driven-development`, that skill's own `sdd-ledger.md` lives as a sibling file in this same session-keyed directory alongside `progress.json`, written by its own workspace helper rather than by this skill.

**Retro and standing-orders are durable loop-state siblings of `progress.json`, not conversation state.** `retro.json` is session-keyed — it lives beside `progress.json` in the same session dir, written once by the Phase 13 teardown contract. `standing-orders.md` and `standing-orders-decayed.md` are repo-keyed — one dir up (the repo-key dir, the grandparent of the `progress.json` path), shared across every session and loop against that repo, not per-session. This asymmetry is deliberate: a retro belongs to the loop that produced it, but a lesson is meant to outlive any single loop. The overlay write-race residual: two concurrent loops updating `standing-orders.md` at once is last-writer-wins, and this is self-correcting rather than a data-loss risk — a lesson lost to the race simply re-adds itself the next time its failure mode recurs (step 2 of the teardown contract), so the cost of the race is a delayed re-entry, not a permanently missing lesson.

## Stop conditions for the loop

Stop conditions come in two classes. The agent must not collapse them into one — a gate is not a wall.

**Retry-until-green (not a stop condition — applies BEFORE hard-stop #1 below).** A single failing test, lint error, or verification check is not, by itself, a reason to stop and ask — diagnose, fix, re-verify in a bounded cycle (default 5 distinct attempts) before escalating. Full mechanics, the multiple-independent-failures parallel-dispatch case, and the cause-not-obvious systematic-debugging case: see [retry-until-green.md](retry-until-green.md).

**Hard-stop (abort the loop, wait for the human):**
1. Verification failure that survives the bounded retry-until-green cycle above without resolving
2. Premise disproven (Phase 5 — symptom can't be reproduced via SOT)
3. Genuinely ambiguous decision outside the authorisation envelope
4. Destructive/irreversible operation not previously authorised

These four hard-stops are the floor, not a preference — they exist to stop an autonomous loop from pushing through a broken test suite, force-pushing, or taking an irreversible action with nobody watching. Retry-until-green narrows how often #1 fires; it does not remove it, and #2–4 are not narrowed by anything in this skill.

On a hard-stop: report current state with confidence labels, propose the next move (don't just stop silently), and wait.

**Approval-gate (pause, surface a one-screen summary, PROCEED on yes):**
A named risk boundary the envelope flagged for human sign-off — e.g. a prod cutover / enable step. This is NOT a hard-stop and NOT a wall. The loop runs autonomously right up to the gate, then pauses, presents a single summary (what's about to happen, the artifacts behind it, what's irreversible about it), and proceeds the moment the human approves — without re-planning or re-asking the steps before it.

Model an approval-gate as "pause-then-proceed", never as "do not start". Past failure: a run relabelled a prod-enable gate as "do not start / hard wall" and took two human turns to correct. The gate is a pause point inside the envelope, not the edge of it.

**Loop complete:**
5. All authorised work done and all gates passed — run Phase 13, then stop.

**Declaring the stop (the LOOP-STOP contract).** Whichever class applies, a stop inside an active loop must be declared, or the `loop_stall_guard` Stop hook blocks it. The declaration line must be the FINAL line of the stopping turn — that ending-line position is the contract this skill defines and the hook's category accounting assumes: when a turn carries more than one LOOP-STOP-shaped line, `loop_stall_guard` counts only the last one, so the last line must be the declaration that reflects the turn's actual outcome, coming after the confidence-label and Did-Not-Verify content required by Phase 0.5. End the stopping turn with:

> `LOOP-STOP: <category> — <reason>`

where `<category>` is exactly one of:
- `hard-stop` — one of the four hard-stop conditions above.
- `approval-gate` — a named risk boundary awaiting sign-off (pause-then-proceed).
- `awaiting-input` — a planned interaction point inside the loop (the Phase -1 improve-prompt ask, the Phase 1 plan confirmation). Use this sparingly: Phase 13 reports the raw `awaiting-input` count as part of its `LOOP-STOP` breakdown.
- `complete` — all authorised work done. Declaring `complete` is the teardown: also set `progress.json` `status: "complete"` and run Phase 13 in the same turn, or the guards keep treating the loop as active. `retro.json` must exist beside `progress.json` **before** a `complete` declaration — the `loop_stall_guard` hook blocks the declaration when it is absent, malformed, or not `schema_version` 1 — and Phase 13's teardown write contract is what writes it.

The hook checks the declaration is present with a valid category; it cannot check the reason is honest (same boundary as the verify-loop hook). The Phase 13 category counts are the audit on that.

## A note on cadence

The user does not want a running narration of "now spawning X, now waiting for Y." They want:
- Brief status when a phase boundary is crossed
- Evidence when claiming success
- Clear stop on failure with the smallest readable summary

Idle pings from teammates are noise unless the artifact check (Phase 4) confirms a real failure. Don't react to every idle ping with a status update — match the cadence to the user's pull, not the runtime's push.
