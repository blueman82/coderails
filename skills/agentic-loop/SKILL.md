---
name: agentic-loop
description: 'Multi-agent orchestration discipline. Load IMMEDIATELY, over /workflow, /prep, /push and any other single-PR command, whenever the user authorises agent-driven work: any time they say "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or authorise 3+ PRs in one instruction. ALSO load for autonomous merge + deploy + verify chains, even a single PR, if per-step confirmation is waived. NOT /workflow (single-PR prep → push → merge → wiki); it sits ABOVE /workflow and uses it as a subroutine. Keep main context a pure orchestrator that never implements: every change goes to a spawned worker that verifies its own artifact, escalating to a spawned team only for ≥3 sequential PRs or dependency chains. Verify artifacts not idle pings; disprove symptom premises before spawning fixes; match confirmation cadence to envelope scope. Fire aggressively — forgetting to delegate is costly in long sessions.'
---

# Agentic Loop

How to run an autonomous multi-agent / multi-PR session so the user doesn't have to manually instruct every turn.

## Why this skill exists

In long agentic sessions the assistant drifts back into bad habits: running skills in main context instead of delegating; asking "want me to spawn an agent for X?" when X is obviously in scope; holding at human gates the session already removed; trusting an "idle" notification as proof-of-failure when the agent often finished silently; spawning fix workers without disproving the symptom premise. Each unnecessary stall is a manual prompt the user has to write — a stalled loop loses the autonomy the session was authorised for.

Repo-agnostic lessons promoted from accumulated loop retros live in [learned-failure-modes.md](learned-failure-modes.md) — machine-maintained via the `loop-retro-promotion` pipeline; read it alongside this skill.

## The phases

Nineteen-plus numbered phases (−2 through 13, with lettered sub-phases) is too many to hold in mind cold. Group them into five stages before descending into per-phase detail:

| Stage | Phases |
|---|---|
| Setup | -2, -1, 0, 0.5 |
| Pre-flight | 1, 2, 2.5, 2.6, 2.7, 2.8 |
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
  "authorising_prompt_raw": "<the user's authorising prompt, verbatim — Phase -1 updates this if an improved prompt is adopted>",
  "completed_marker": <carry forward the prior file's completed_marker if one exists at this path, else 0>
}
```

If a `progress.json` already exists at the path from an earlier loop in this session, read its `completed_marker` and carry it forward into the new stub (do not reset it to 0) — this is what lets the guard tell a genuinely-finished loop from a new one that re-armed it (see the teardown rule below).

`loop_stop_counts` gets different treatment depending on the prior file's `status`, because it is HOOK-OWNED (see Context-window persistence below):
- Prior file `status != "complete"` (mid-loop re-stub, e.g. a recovery after a restart): carry `loop_stop_counts` forward verbatim into the new stub, so a mid-loop recovery doesn't silently reset the count the `loop_stall_guard` hook has been maintaining. Carry `authorising_prompt_raw` forward verbatim too — a re-stub refilled from conversation memory instead of the prior file's value would silently drift the eval author's canonical anchor.
- Prior file `status == "complete"` (re-arming for a NEW loop): reset `loop_stop_counts` to `{}` (omit the field from the stub) — the completed loop's counts are already preserved in its own `retro.json`; carrying them forward would bleed the finished loop's stop counts into the new loop's Phase 13 report.

### Phase -1 — Sharpen the authorising prompt

**Run this phase UNLESS the user's prompt explicitly opts out.** Opt-out signals: "just do it", "skip improve-prompt", "don't improve the prompt", or any language that makes the directive unambiguous. On opt-out, skip directly to Phase 0. (Note: improve-prompt itself treats "just do it" as an unconditional skip — align with that.)

**Step 1 — Invoke `/coderails:improve-prompt` on the authorising prompt.**

> `/coderails:improve-prompt` — apply it to the prompt above.

It surfaces ambiguities, fills gaps with grounded assumptions, and produces a rewritten prompt that passes its 7-foundation diagnosis. Let it run to completion before Step 2.

**Step 2 — Ask the user how to proceed.**

**Delivery constraint — the improved prompt must be visible, not just asked-about.** Text emitted before a tool call is not rendered in the Claude Code terminal UI — only text with no trailing tool call, or content inside the tool call itself, reaches the user. This means "present the improved prompt as text, then call `AskUserQuestion`" silently drops the prompt: the user sees only the question, never the content it's asking about. Use one of two delivery mechanisms instead:
- (a) End the turn with the improved prompt as the final text — no trailing tool call — and issue the `AskUserQuestion` call in the *next* turn; or
- (b) Embed the improved prompt directly inside the `AskUserQuestion` call itself: its question text, option descriptions, or option preview fields. This renders regardless of turn-splitting.

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

Match the confirmation cadence to the envelope class for the rest of the session — every "do you want me to..." inside an authorised envelope is a stall the user has to clear, and stalls cost more than the occasional over-reach you'd avoid by asking.

### Phase 0.5 — Orchestrator operating rules (the conductor obeys its own rules)

The orchestrator (main context) is subject to the same discipline it imposes on workers. Inside an active, incomplete loop, the two discipline Stop hooks — confidence-label and verify-loop — demote a would-be block to a model-visible warn (`additionalContext` on the Stop event) rather than stopping the turn outright; the discipline itself hasn't changed, the warn is the correction signal the orchestrator acts on next turn. Outside an active loop, and for worker output (SubagentStop), both hooks still block outright. Even at warn-level, a missed warn is still a cost — it's the cost this skill exists to keep to a minimum, just paid as a drifted transcript instead of a forced regeneration.

Main context must, in its own output (not just in spawned-agent prompts):
- Confidence-label every substantive status claim — `(verified)` / `(inferred)` / `(guess)` (same taxonomy as Phase 11).
- Pre-tag any `## Did Not Verify` bullet that genuinely can't be checked, in the same turn it's written — an untagged bullet blocks the stop outside a loop and for workers, and is the first thing the in-loop warn will name.
- Never narrate a claim about an artifact (PR merged, deploy live) without having run the check this turn (Phase 12).
- End any stopping turn inside an active loop with a LOOP-STOP declaration line — `LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>` — as the FINAL line of the turn, emitted in the SAME turn as the confidence-label and Did-Not-Verify requirements above — that ending-line position is the contract this skill defines and the hook's category accounting assumes: when a turn carries more than one LOOP-STOP-shaped line (e.g. a quoted example), `loop_stall_guard` counts only the last one, so the last line must be the declaration that reflects the turn's actual outcome. Bundling all three matters more, not less, in the warn era: the confidence-label and verify-loop hooks no longer block the orchestrator's in-loop Stop turns, so nothing else forces those labels and DNV tags into the transcript — the bundle is what keeps them present for post-hoc audit, and one composed ending beats clearing one stop hook only to trip another (`loop_stall_guard` still blocks). Declaring `complete` means the loop is done: also set `progress.json` `status: "complete"` and run the Phase 13 teardown. The declaration line is all that's required — `loop_stop_counts` is HOOK-OWNED: the `loop_stall_guard` hook itself increments the matching category on a valid declaration; never write or compute this field yourself.

### Phase 1 — State the plan in bullets, ask once

Before the first agent spawn, write the full plan: phases, which agents per phase, parallel vs sequential, stop conditions. Use bullets. Keep it tight — the user reads this fast and decides whether to redirect.

Ask once: "Want me to execute this?" or "Confirm scope and I'll execute."

If yes → execute silently through to the end of the envelope.
If no → revise once based on feedback, then re-ask.

Do not loop more than twice on plan negotiation. If the third pass is needed, something is wrong with the envelope itself — surface that.

The harness choice itself — which loop skill drives this (`/coderails:agentic-loop` vs a flat loop vs a goal runner) — is part of the authorisation envelope (Phase 0), not a Phase 1 question. Resolve it once when reading the envelope and never re-surface it as "which approach do you want?".

### Phase 2 — Pre-flight checks via spawned agents, not main context

Pre-planning skills (`/coderails:planning-sequence`, `/coderails:premortem`, `/coderails:assumptions`, `/coderails:notchecked`, `/coderails:wiki-query`) belong in a delegated agent, not in main context.

Spawn a single pre-flight agent whose prompt includes:
- The plan from Phase 1
- An instruction to invoke each relevant skill via its `Skill` tool call
- An instruction to return one consolidated report (plan-sequence findings + premortem failure modes + assumptions inventory + wiki findings)

Include `/coderails:wiki-query` in the pre-flight agent's skill list, scoped to the **whole plan theme** (not per-PR). The query is something like: "What does the wiki cover about [overall theme of the agentic loop]? Identify cross-PR constraints, gaps, superseded decisions, and anything the plan assumes but isn't enforced in code." This pre-empts the per-PR `/coderails:wiki-query` that `/coderails:workflow` Phase 2 runs — see Phase 9 for why per-PR wiki steps are suppressed inside this loop.

**Retro intake.** The pre-flight agent additionally reads `standing-orders.md` at the repo-key dir (derive it as the grandparent of the path printed by `hooks/scripts/lib/agentic_loop_path.sh` — i.e. `dirname` of `dirname` of that path) and the last N=5 `retro.json` files under `<repo-key-dir>/*/retro.json` (mtime-sorted). It returns (a) premortem entries seeded from OBSERVED past failure modes and (b) a "carry into worker prompts" list of applicable lessons. Intake is additive-only: it may add cautions, assertions, and premortem entries; it may never relax a gate, skip a phase, or pre-justify an eval amendment. Gate changes remain human-owned. First-loop no-op: no retros + no overlay → skip silently, not an error.

**Primitive-contract read (mandatory when the plan calls a primitive in a non-standard way).** If the plan calls a lock, queue, transaction, or other shared primitive in any of: nested calls, recursion, parallel from same process, re-entered from the same caller — the pre-flight agent MUST read the primitive's source and document its contract: raise vs. return-bool semantics, reentrancy (PK collision behaviour), owner identity, expiry/steal logic. The schema may have been written before anyone read the primitive's internals. Past failure: a "wrap both sites with a DistributedLock" schema was impossible — the lock's `attribute_not_exists(PK)` semantics are non-reentrant and the sites were nested, not parallel; only reading the primitive's source caught it.

Spawn this pre-flight agent at the `default` role — it's running skills, not making architectural decisions, and `default` controls cost. (One of the two assignment sites Phase 2.8 doesn't cover — this agent runs before 2.8 exists in the sequence, so it gets its role inline, here.)

**Clean-base check (mandatory orchestrator action in main context, before ANY worker is spawned).** Run `git fetch origin` then `git log --oneline origin/main..main` and `git status --short` yourself. If local `main` carries commits `origin/main` does not, or has uncommitted/untracked files, the base is DIRTY — a parallel session (or an earlier uncommitted edit) has polluted it. When the base is dirty:
- NEVER let a worker branch off local `main`. Every worker MUST create its worktree via `coderails:using-git-worktrees`, which accepts a declared base ref — the orchestrator must state one explicitly, by name, in the worker prompt: "Use the using-git-worktrees skill with base ref `origin/main` — not local `main`, not HEAD." This keeps worktree mechanics (native-tool detection, ignore-verification, directory selection) on the shared skill instead of Phase 3 reinventing them inline, while the `origin/main`-base requirement — a loop-specific safety invariant — travels through the skill's own declared-base-ref mechanism rather than being asserted outside it.
- Carry the foreign file names into worker prompts as an explicit "these are not yours — never stage, commit, or include them" exclusion list.

Do this check even when the base looks clean — two cheap git reads pre-empt a worker's PR silently inheriting another session's WIP from a dirty base, which otherwise only surfaces at the merge gate.

### Phase 2.5 — Resolve design forks before execution, not during it

If the plan contains an unresolved architectural choice (which primitive, which topology, which of several viable shapes), resolve it BEFORE entering Phase 3 — not through live back-and-forth once workers are spawning.

Spawn one design agent, role assigned per Phase 2.8's table: `default` when the fork is a bounded choice between well-understood shapes; `frontier` from the start when the fork is a genuinely ambiguous investigation (Phase 2.8's "Investigations get frontier FIRST" states why). This agent runs before Phase 2.8's per-loop task routing, so it gets its role inline, here, using the same table. Its prompt requires:
- Read the actual code paths the alternatives touch — not assumptions about them.
- Build a head-to-head of the viable shapes with the real constraint each one hits.
- Return ONE recommended shape, the rejected alternatives with the reason each lost, and the single fact that would flip the recommendation.
- Apply `/coderails:brainstorming`'s design-quality discipline *without* its human-approval gates: weigh the viable approaches against each other rather than taking the first that works, cut anything speculative (**YAGNI**), and prefer the shape whose units stay small and independently testable (**design-for-isolation**). The loop can't run brainstorming itself (its steps block on a human — see Phase 2.7); this reuses its *thinking*, not its control flow.

What happens with that recommendation depends on the envelope class (Phase 0) — this phase resolves the fork, it does NOT add a new human gate:
- **Full-autonomous ("crack on / ship N PRs without asking"):** auto-adopt the design agent's recommendation, record the chosen shape and the flip-condition in `progress.json` — append `{phase: "2.5", decision: "<chosen shape + flip-condition>"}` to `progress.json`'s `decisions_absorbed` array — and note it at the next approval-gate. Do NOT stall for sign-off — a design fork is neither a verification failure nor a destructive action, so Phase 0 says the loop proceeds.
- **Narrow-fix / diagnostic / ambiguous envelope:** surface the one recommendation as a single decision — "here's the shape, here's why, approve or redirect" — bounded like Phase 1 (ask once, don't loop), then enter Phase 3.

Either way the fork is closed by ONE design artifact before building starts — the loop does not start half-built while the design is still being argued turn by turn.

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

**2.7d — freeze a PR-scope `evals.json` per work-unit, in the same invocation.** The same `/coderails:task-evals` run ALSO produces one **frozen** PR-scope `evals.json` (scope: `pr`) for every work-unit that will carry a PR. This is a **separate artifact** from 2.7c's loop-scope file, not a view of it, and freezing 2.7c alone does not satisfy it: `scripts/merge.sh` hard-gates every merge on a SHA-bound **pr-scope** eval comment with `result=GO` — fail-closed, no config opt-out. A loop that freezes only loop-scope evals passes Phase 3 and Phase 4b unimpeded and then meets an unsatisfiable merge gate, with the implementation already built.

Each unit's PR-scope eval ref then travels into its worker prompt the same way disposition travels under Phase 3's existing "Disposition — ... copied **verbatim** into the task description" bullet: a ref recorded only in `progress.json`/`plan.md` and absent from the worker prompt does not exist for the worker.

**The timing cannot be recovered later, which is why it is a freeze and not a to-do.** Freeze-before-build is `task-evals`' rule 1; a pr-scope suite authored at merge time cannot honour it, because its author already knows what the implementation does. When it has been missed, the only honest repair is: author them late, stamp `frozen_at` at the **real** authoring time (never backdate — a backdated freeze is the one edit that turns a disclosed gap into a rigged gate), disclose the gap in `tier_justification`, and report it at Phase 13. The GO then rests on evidence the suite genuinely discriminates — an executed negative control, or a run that actually failed against a real defect — never on the timestamp. That repair is a **disclosed gap, not a pass**; its availability is not a licence to skip the freeze.

Past failure (loop 0d3fb487, 2026-07-16): this sub-step was a trailing sentence under a heading that said "loop-scope", carrying no freeze obligation, no timing, and no mention of the merge gate. The loop froze loop-scope evals at its Task 1 — correctly, pre-build — and never registered that the pr-scope half was missing until `merge.sh` refused the merge, by which point the work was built, merged-ready, and live-fired. The gate caught what the process missed; that is the gate working, not the process working.

### Phase 2.8 — Route: assign a model role per task

Every loop assigns a **model role** to every Phase 3/3a build task before any
worker spawns — even a 1-2 unit loop that skips Phase 2.7 entirely. Decide once,
up front, recorded; never re-litigate per spawn.

**Roles are capability tiers, not model names.** A tier pinned to a named model
goes stale the moment a new model ships. The table below is the only thing a
model release touches; the roles themselves are durable.

| Role | Currently | Use for |
|---|---|---|
| `fast-mechanical` | haiku | Exact-recipe mechanical tasks with scripted ceremony; orchestrator verification micro-reads |
| `default` | sonnet | TDD / mechanical / multi-file work; the fallback when uncertain (cost control) |
| `frontier` | opus at `xhigh` effort (fable escalation — see [model-routing.md](model-routing.md)) | Design-judgement UI/architecture units; genuinely ambiguous investigations |

**`frontier` resolves to opus, never automatically to fable** — escalating to fable needs a named
capability reason in the stamp. **Effort is part of the stamp:** every `Model:` stamp names role
AND effort (`frontier` → opus at `xhigh`; `default` → sonnet at `high`; `fast-mechanical` →
haiku), and tuning effort is the first lever, model escalation the second. **Investigations get
`frontier` FIRST**, not escalated-to — the one place `default`-first cost control does not apply.
**Fallback valves live in the stamp, never improvised by a worker.** Full escalation rules, the
effort table, and the inline-spawn sites at other phases: see [model-routing.md](model-routing.md).

**Record the assignment set once.** Append one `decisions_absorbed` entry covering
every task's role assignment for this loop — `{phase: "2.8", decision: "<task id:
role, ...>"}` — not one entry per task. A `<3`-unit loop still writes this entry
even when it skipped Phase 2.7.

### Phase 3 — Delegate all implementation to routed workers; spawn a team when work has ≥3 sequential units or dependency chains

**Default: main context never implements.** It orchestrates — plans, delegates, verifies. Every implementation unit (even a single-file edit, even a tight sequential step) goes to a spawned worker at the role Phase 2.8 assigned it — the `default` role unless Phase 2.8 routed otherwise. The two reasons, in order: keep main context clean (frontier-tier context is scarce and fills fast in long sessions), and keep cost down (`default` does the typing, not `frontier`). Treat a `frontier`-role worker, or a file edit done directly in main context, as the exception that needs a reason, not the default.

The delegation decision is a two-rung ladder, not "delegate vs. do it yourself":

1. **Single routed `Agent` for impl + verify** — the default for any self-contained 1–2 unit of work (a bug fix, one PR, a single-file change), at the role Phase 2.8 assigned. One agent does the implementation *and* verifies its own artifact before reporting. A spawned team would be overkill here. See Phase 3a below for the prompt contract.
2. **Spawn a team** — when the loop has 3+ PRs or any cross-step dependency, spawn each worker as a named teammate via the `Agent` tool and build a task list with explicit `blockedBy` dependencies via `TaskCreate`/`TaskUpdate`; coordinate with `SendMessage`. Don't just describe a "sequential PR loop" — actually spawn the named agents and create the task list, so the user can see each teammate and the task list becomes the shared source of truth.

The only work that legitimately stays in main context: reading for orchestration decisions (git status, `gh pr view`, log reads, the Phase 12 artifact checks), and the planning/cadence the skill describes. If you catch yourself running `Edit`/`Write`/`MultiEdit` in main context inside an authorised loop, stop — that work belongs in a routed worker agent.

If the user has explicitly asked for a spawned team in their prompt, it is non-negotiable — spawn named teammates even if a flat sequence of solo `Agent` calls would technically work.

Each task description must be **self-contained** so the spawned agent can act without re-reading the conversation. Every bullet of Phase 3a's prompt contract applies to each teammate's task description — role verbatim, construction method and discipline, the self-run verify step, manifest + pre-push scope assertion, disposition, lessons, terminal state, report-back contract, and the hook-seam. A task-list entry is not a substitute for any of them: anything absent from the prompt does not exist for the worker. Add, on top of that contract:
- Worktree path and branch name
- JIRA ticket
- Verified state from prior tasks (deployed version, test counts, what's already wired)
- Exact step-by-step sub-steps

Include this line in every agent prompt:
> "Don't go silently idle — send a completion message via SendMessage. Past agents have failed this way."

### Phase 3a — Single routed agent for impl + verify (the spawned-team-is-overkill case)

For self-contained work that doesn't justify a team — a bug fix, one PR, a single-file change, a tight sequence of steps with shared context — spawn **one** `Agent`, at the role Phase 2.8 assigned, that owns both the implementation **and** the verification, then reports back a confidence-labelled result. Main context stays the orchestrator; it does not make the edit itself.

One agent does both impl and verify (not two) because verification output is dense — exactly the kind that fills main context. The agent self-verifies; main context spot-checks only at dependency boundaries (Phase 12) or when the artifact check is cheap and the stakes are high.

The agent's prompt must be self-contained (it can't re-read the conversation) and include:
- **The Phase 2.8-assigned role, verbatim, including any fallback valve** — copied from the plan's `Model:` stamp (`coderails:writing-plans`), or from Phase 2.8's recorded assignment for a below-plan.md-threshold loop. A role recorded in `progress.json`/`plan.md` but absent from this prompt does not exist for the worker — same travel rule as disposition and lessons. `default` is the floor absent a routing reason; `frontier` is the exception that needs one.
- The exact change to make, with file paths and the success criteria stated as something testable.
- **Construction method (when the deliverable is code).** If the change adds or alters a function, method, or branch that *can* carry a test, the worker builds it test-first via `/coderails:test-driven-development`: write the failing test, watch it fail for the right reason, then the minimal code to pass, then refactor green — even if the PR also touches non-code files. For pure docs/config/prose with no testable code, there is no failing test to write first; the verify step below is by inspection instead. For the full worker-prompt construction contract (implementer/reviewer prompt templates + the per-task review loop), see `/coderails:subagent-driven-development`.
- **Construction discipline.** The agent holds itself to `coderails:verification-before-completion` throughout implementation, not only at the report-back step: no "should work now" framing on any intermediate claim, run the actual check before asserting a sub-step is done. Additive to the report-back contract below, not a replacement for it.
- **A verify step the agent runs itself before reporting** — run the test / lint / build, read back the diff, hit the endpoint or read the log. State which one. "Implement X, then verify by running `Y`, and only report success if `Y` passes."
- **Report-back contract:** return a confidence-labelled summary (Phase 11), state what was run to verify (the command + its result, not just "verified"), and "don't go silently idle — send a completion message" (Phase 4 — workers go idle without reporting regardless of role).
- If the work writes to git, the worktree/branch and a "commit your work" instruction so the artifact is durable for the orchestrator's Phase 4 check.
- **A manifest — the exact set of files this change should touch — plus a pre-push scope assertion.** Require: "before you push, run `git diff origin/main --name-only` and confirm the file list equals EXACTLY this manifest. If any file you did not intend to touch appears — especially one you never edited — STOP and report; do not push. A PR that carries files outside its manifest is a contamination, not a change." This catches a dirty base or a stray `git add -A` at push time, one stage before the orchestrator's merge gate, where it is far cheaper to fix.
  When the unit's disposition is `clean-break`, the assertion also covers compat: before push, confirm no compatibility shim, bridge, adapter, or legacy code path for the replaced functionality remains. If one does, clean-break is not finished — remove it or STOP and report. This worker assertion is a **first-pass smell test, not the gate** — the independent reviewer (Phase 4b) is the gate, because the worker that wrote a shim is the party least able to see it as one.
- **The disposition, verbatim** — for a retirement unit, the `clean-break`/`preserve-compat` decision from Phase 2.6 and (if preserve-compat) the `named_blocker`. The single agent cannot re-read the conversation; the decision must travel in its prompt or it does not exist for the worker.
- Lessons — applicable standing-orders entries copied verbatim into the task description (same travel rule and rationale as disposition: a lesson absent from the prompt does not exist for the worker).
- **A terminal state stated as a concrete artifact, with no mid-task hand-backs.** The done-condition is an artifact that exists ("the PR is OPEN" or "the PR is MERGED"), never a sub-step. Add to the prompt: "You own this through that artifact existing. Do NOT hand back to the orchestrator in an intermediate state — after editing but before committing, after engineering-principles but before pushing, after review but before the PR is open. If you stop before the artifact exists, you have not finished; continue."
- **Hook-seam —** commits hit `test_gate` (resolution: fix the failing tests), pushes and PR-creates hit `enforce_pr_workflow` (satisfied by the `/coderails:push` / `/workflow` you run), edits stay on the feature-branch worktree so `no_edit_on_main` won't fire, merges hit the eval-artifact gate in `scripts/merge.sh` (satisfied by running `/coderails:task-evals` + `/coderails:post-evals` before `/coderails:merge`)

If the agent goes idle, apply Phase 4 (check the artifact, not the ping); if it reports success, that's a Phase 12 claim, not evidence. Escalate to a spawned team (Phase 3, rung 2) the moment the work grows a third unit or a cross-unit dependency — never three sequential solo `Agent` calls where a `blockedBy` task list belongs.

### Phase 4 — Spawn workers in waves, never block on idle pings

Workers (especially in teams) frequently complete work successfully but go idle **without sending a completion message**. The idle ping is not a failure signal — it's just "I stopped."

When an agent goes idle without a report:
1. Read the worktree `git status` and `git diff --stat`
2. Check the PR state via `gh pr view <N>` if a PR should exist
3. Read the prod log via your prod log access (`ssh`, `kubectl logs`, cloud console — whatever the project uses) if a deploy should have happened
4. Verify the artifact, not the ping

Only after the artifact check fails should you assume failure. Then respawn — and per Phase 10, give it a new name.

### Phase 4b — PR review invokes `/pr-review-toolkit:review-pr <PR#>` as a Skill, then `/coderails:post-review <PR#>`

When a phase reaches "review the PR" (after a `/workflow` agent has pushed a PR, before merge), invoke the **`/pr-review-toolkit:review-pr <PR#>`** Skill — passing the PR number as the argument — which itself fans out the six specialised reviewers plus a security pass. Do NOT hand-roll the reviewers as separate `Agent` or `Task` spawns; use the Skill invocation.

**Invoking `/pr-review-toolkit:review-pr <PR#>` with the PR number is REQUIRED to satisfy the merge gate, because `enforce_pr_workflow` only accepts the `review-pr` Skill (with the PR number in args) as merge evidence — a manually-spawned agent fanout leaves no evidence the gate recognises and the merge will block.** The gate also recognises `scripts/merge.sh <PR#>` invocations (not just raw `gh pr merge`) as the same merge subcommand, so a hand-rolled review cannot merge through the wrapper script either.

**Review tier ladder.** All tiers — regardless of the PR's own eval-artifact tier (a separate, orthogonal check) — invoke `/pr-review-toolkit:review-pr <PR#>` (the toolkit self-scales its reviewer fan-out by change shape) plus `/coderails:post-review <PR#>`. Only at tier 0 MAY the separate `/security-review` pass below be skipped, and only after checking the actual diff file list (`gh pr diff <PR#> --name-only` or `git diff origin/main...HEAD --name-only`): any path under `hooks/` or `scripts/`, or any change touching auth/exec/network-fetch code, FORCES the security pass regardless of declared tier. The override keys off the diff, never the self-assigned tier label. Tier 1/2 PRs run the full Phase 4b unchanged, security pass included.

**After `review-pr` completes and all applied findings (blocking and worthwhile) are committed and pushed, invoke `/coderails:post-review <PR#>`.** This posts the SHA-bound review artifact — a machine-marked GitHub comment — that the `/merge` gate requires before merging. Loop symmetry: this is the same artifact gate that `/coderails:workflow`'s Phase 3 wires in for non-loop use. Both paths produce the same artifact; `/merge` checks both the same way. Run `post-review` after findings are applied and the follow-up commit is pushed, so the artifact is stamped against the final head SHA.

Before `/coderails:merge`, the loop must also produce a second, independent artifact: run `/coderails:task-evals` (scope: `pr`; docs-only/single-unit PRs that meet its tier-0 predicate get the lightweight exemption path) then `/coderails:post-evals`. `scripts/merge.sh` hard-gates on this eval artifact separately from the review artifact above — same fail-closed posture, no config opt-out.

**Worktree teardown, immediately after `/coderails:merge` confirms this work-unit's PR is merged.** A work-unit's worktree (created per the `origin/main`-based instruction above) is scoped to that one PR — once it's merged, the worktree has no further purpose and must not be left to accumulate across a multi-work-unit loop. Clean up the worktree using `coderails:finishing-a-development-branch`'s Step 6 mechanics — the commands, provenance check, and cwd-pinned-worktree caveat are in [finishing-out.md](finishing-out.md). (The PR is already merged via `/coderails:merge` at this point, so this is the Step 6 cleanup only, not the skill's push/PR outcome-selection.) This runs per-work-unit at this point in Phase 4b — not deferred to Phase 9/13's loop-level teardown, which handles wiki/retro artifacts, not worktrees.

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

**Plus the native `/security-review` pass.** Alongside the six agents, run Claude Code's built-in `/security-review` on the same branch diff as part of this gate — it is a dedicated security review (auth/authz surfaces, injection, secret leakage, unsafe deserialisation, SSRF) that the six general reviewers do not specialise in. Run it in the worktree so it sees the branch's pending changes. Fold its findings into the same Critical / Important / Suggestion aggregation; any security MERGE-BLOCKER blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not row 6's default report-only suggestions. **The orchestrator cannot downgrade this finding unilaterally.** Its only two moves: (a) fix it — remove the compat path, or (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason. If a fully-unattended envelope cannot tolerate ever hard-stopping here, the human must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never something the orchestrator grants itself mid-run. The why: letting the orchestrator grade an independent reviewer's finding reintroduces the same self-attestation loophole one level up.

**Do not substitute the generic `architect-review` + `debugger` + `ai-engineer` trio here.** That trio is a separate general-purpose adversarial pattern for design stress-tests before a thing is built — it is NOT the PR-review step. The canonical review step is `/pr-review-toolkit:review-pr all` = the six agents above.

### Phase 5 — Disprove the premise before each fix

Before spawning a "bug fix" agent for any reported regression, the fix agent's prompt must require:

> Verify the symptom in the source-of-truth FIRST. Slack pin-bar / GitHub PR state / Jira board / browser tabs all cache. Reproduce the bug via API call, prod log, DDB read, or git diff before any code change. If the symptom can't be reproduced via SOT, STOP and report — don't ship a fix to a non-bug.

This is a specific application of `/coderails:verify` — the same "re-derive from sources only, no recall, no inference" discipline, applied to one claim: "this bug currently reproduces." Point the fix agent at `/coderails:verify` (claim: the reported symptom) rather than re-deriving the sources-only instruction inline each time.

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

One source page covers the cluster; updates to entities/services/concepts pages aggregate the cluster's changes. If the loop's PRs aren't thematically related (rare — a spawned team's task list usually clusters them), one ingest per cluster theme is fine. Avoid one-per-PR sprawl.

**Suppressing per-PR wiki steps in spawned `/coderails:workflow` agents:** place the following line as the **FIRST instruction** in every spawned agent's prompt inside this loop (not buried mid-section, not under the task-specific scope, not after the workflow steps — first):

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/coderails:wiki-query` and Phase 5 `/coderails:wiki-ingest`/`/coderails:wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

**Why first-line, not just "include":** workers shortcut past mid-section process notes and treat anything that appears to constrain the workflow steps as "optional polish." **Scope-suppression instructions go above scope-additive instructions in worker prompts.**

The orchestrator handles both ends: Phase 2 (plan-level wiki read before coding starts) and Phase 9 (cluster ingest+lint after all PRs are merged).

**Wiki commits are artifacts too — verify they reached `origin/main`, and deliver them the way *this* repo accepts.** A delegated wiki agent reports a *commit SHA*, not a merged PR — and a commit is not a push. Close two failure modes at the loop boundary: (1) the agent commits to **local `main`** and never pushes — work stranded; (2) the agent pushes wiki files **direct to `main`**, which a branch-protection ruleset rejects.

**Delivery is repo-specific.** If `main` is ruleset-protected, the wiki agent must deliver via a branch + PR off freshly-fetched `origin/main`, merged like any other change. Only where a repo *deliberately* permits direct wiki commits (e.g. a wiki dir gated behind a bypass env var) is a direct push acceptable — and even then it must be verified to have landed.

**Then verify, after `git fetch origin`:** confirm the content is on `origin/main` via the wiki PR's `mergedAt` or `git show origin/main:<wiki-file>`. Do **not** confirm a merge with `git merge-base --is-ancestor <agent-sha> origin/main` — a squash-merge rewrites the SHA, so the agent's commit is never an ancestor even when its content landed (`--is-ancestor` is the right probe only for *detecting* an unpushed commit before merge). A committed-but-unpushed SHA is a textbook false-success; the "committed" ping is a claim, not evidence (Phase 12).

**Docs-drift check — run `/sync-docs` at the loop boundary**

After the cluster wiki ingest+lint, the orchestrator runs `/sync-docs` ONCE at the loop boundary. Wiki ingest updates the external knowledge base; `/sync-docs` is the complement — it audits the repo's own in-tree docs (e.g. README.md, AGENTS.md, docs/REFERENCE.md) for drift against the just-merged code.

Run it even without Serena (the `--semantic` backend) — omit `--semantic` for the traditional file-comparison audit, which still catches drift. Do not skip `/sync-docs` just because Serena isn't installed.

Delegate it to a spawned agent at the `default` role, same as the wiki ingest+lint agent — both inline-assigned (like Phase 2's; Phase 2.8 routes build tasks only) — to keep orchestrator context clean.

**Disposition of findings:** `/sync-docs` surfaces drift; the orchestrator must triage. Fix only drift the loop's own PRs introduced. Surface pre-existing drift to the user rather than silently folding unrelated doc fixes into the loop — that is scope creep. This mirrors the loop's finding-triage discipline.

### Phase 10 — Use v2/v3 names when respawning a stuck agent

Dead agents continue to emit idle pings until the runtime cleans them up. If you respawn with the same name, you can't tell which idle ping is which.

Always respawn with a versioned name: `dockerfile-fixer` → `dockerfile-fixer-v2` → `dockerfile-fixer-v3`. The dead one's pings become identifiable noise; the live one's reports are unambiguous. The version bump doesn't change the routing — respawned agents keep the same Phase 2.8-assigned role.

### Phase 11 — Agent prompts include "confidence-label every claim"

Add to every spawned agent's prompt:

> Confidence-label every substantive claim in your output:
> - `(verified)` — directly observed via tool result, file read, or explicit user statement in this session
> - `(inferred)` — pattern-matched, recalled, or assumed from context
> - `(guess)` — best-effort with low confidence
>
> The user's stop hook enforces this. Propagate it into your work.

### Phase 12 — Status reports from agents are claims, not evidence

When an agent says "PR-N verified, deployed, working in prod" — treat that as a hypothesis, not a fact.

Before unblocking the next dependent task in the chain:
- Read the PR `mergedAt` via `gh pr view`
- Read the prod log line via your prod log access (`ssh`, `kubectl logs`, cloud console)
- Read the audit row or DDB record that confirms the new code path executed

**Re-check at the moment of action, not at the moment the report arrived.** State changes in the gap. If the worker says "PR is CONFLICTING" or "ready to merge" and you queue a corrective instruction (rebase, redo, wait), the artifact may have moved by the time the message lands. Always re-run `gh pr view` (or equivalent) at the moment you act on the report, not when you first read it. Past failure: a CONFLICTING state self-healed via an intervening merge before the queued rebase instruction landed — stale on arrival, it triggered redundant work. One extra `gh pr view` between report and instruction is cheap.

The cost of one extra tool call before unblocking the next phase is small. The cost of unblocking on a false report is hours.

### Phase 13 — Confirm the factory actually ran (terminal self-audit)

**This phase is mandatory and singular, not optional and not repeatable mid-loop.** It runs exactly once, only at the very end of the loop, immediately before the `complete` LOOP-STOP declaration — never as a mid-loop check-in, never skipped because the loop "felt straightforward." A loop that reaches `complete` without this report has not actually finished; the `loop_stall_guard` hook's `retro.json` requirement (see the teardown contract below) is what makes skipping it structurally hard, not just discouraged. The report is a summary, not a checkpoint — it does not pause for approval and does not ask the human anything; it tells them what happened.

At the end of the loop, before declaring done, the orchestrator audits its own autonomy from the `progress.json` counters and reports raw, unscored facts — no pass/fail scorecard. The human is the only party positioned to judge "should I have been asked about that?"; hand them the raw list rather than have the process pre-grade itself. Report: **`LOOP-STOP` category counts** (HOOK-OWNED — read as-is, never compute or edit), **decisions absorbed** (copied VERBATIM from `progress.json`, never reconstructed from memory), **artifacts produced** (each with its Phase 12 verifying check), **loop cost** (printed with a price-staleness age, not merely written to disk), **disposition violations**, and the **loop-scope eval result** (graded via `post_evals.sh grade-loop`, never hand-written). For the last two, "no record found" is an **audit failure, not a pass**. Per-field detail: [teardown.md](teardown.md).

This is the factory's own audit — raw facts for the human to judge, not a self-issued verdict.

**Teardown write contract — ordered, and it runs BEFORE the `complete` declaration.** The `loop_stall_guard` hook blocks a `complete` declaration when `retro.json` is absent, malformed, or below `schema_version` 1 — so the retro must be written before the declaration. Run these four steps in order, per the field spec and mechanics in [teardown.md](teardown.md):

1. **Assemble `retro.json` (`schema_version` 2) beside `progress.json`** — envelope, `loop_stop_counts` and `decisions_absorbed` copied verbatim from `progress.json` (never recomputed or reconstructed from memory), disposition record, evals, artifacts, hook blocks, `models_used`, and `cost`. The schema has **no `verdict` field** — raw and unscored is structural: the retro records what happened, it does not grade it. Mine cost via `dc_mine_token_usage` (fail-open: it never blocks teardown), and price once — nothing downstream re-prices.
2. **Update `standing-orders.md` (at the repo-key dir).** Match this loop's failure modes against existing entries (match resets `loops_since_recurrence` to 0; new modes append), increment non-matched entries, and MOVE an entry to `standing-orders-decayed.md` at K=5 — a tombstone, **never a delete**. Additive-or-recurrence-only: no metric-based removal anywhere.
3. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
4. **Only then** set `progress.json` `status: "complete"` and declare `LOOP-STOP: complete`. First apply `coderails:verification-before-completion` to the orchestrator's own completion claim, per [finishing-out.md](finishing-out.md).

## Context-window persistence

Do not stop work early because the context window is filling or a token budget is approaching. Context will compact and the session will continue — treat that as a non-event, not a stop condition. Never artificially truncate a task or declare "done" mid-loop because of token pressure. If a genuine stop condition (see below) is not met, keep going.

**Loop state lives in a durable artifact, not in the conversation.** Maintain a single `progress.json` at the path printed by the loop-state path helper — resolve it by running the helper (Phase -2), never compute it yourself. Overwrite it (never append) at every phase boundary, recording the authorisation envelope verbatim, the current phase, work-unit states, and each phase's absorbed decisions. Field-by-field schema, the stub→enrich→teardown lifecycle, the hook-owned `loop_stop_counts` carry-forward rule, and the concurrency/ownership rules: see [loop-state.md](loop-state.md).

After any compaction, drift, or "wait, where are we" moment, the orchestrator RE-READS `progress.json` — never the conversation — to re-orient. If the user ever has to remind the loop that it's mid-loop, the artifact wasn't being maintained. Git remains the authoritative checkpoint for code (commit all in-progress work before compaction); `progress.json` is the authoritative checkpoint for loop position.

**The guard catches absence, not neglect.** `loop_state_guard` guarantees the file exists and is this session's — not that its content is faithful. Keeping it current is still your job. `retro.json`, `sdd-ledger.md`, and the repo-keyed `standing-orders.md` are durable siblings, not conversation state ([loop-state.md](loop-state.md)).

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

Model an approval-gate as "pause-then-proceed", never as "do not start" — it is a pause point inside the envelope, not the edge of it.

**Loop complete:**
5. All authorised work done and all gates passed — run Phase 13, then stop.

**Declaring the stop (the LOOP-STOP contract).** Whichever class applies, a stop inside an active loop must be declared, or the `loop_stall_guard` Stop hook blocks it. The declaration line must be the FINAL line of the stopping turn — that ending-line position is the contract this skill defines and the hook's category accounting assumes: when a turn carries more than one LOOP-STOP-shaped line, `loop_stall_guard` counts only the last one, so the last line must be the declaration that reflects the turn's actual outcome, coming after the confidence-label and Did-Not-Verify content required by Phase 0.5. End the stopping turn with:

> `LOOP-STOP: <category> — <reason>`

where `<category>` is exactly one of:
- `hard-stop` — one of the four hard-stop conditions above.
- `approval-gate` — a named risk boundary awaiting sign-off (pause-then-proceed).
- `awaiting-input` — a planned interaction point inside the loop (the Phase -1 improve-prompt ask, the Phase 1 plan confirmation). Use this sparingly: Phase 13 reports the raw `awaiting-input` count as part of its `LOOP-STOP` breakdown.
- `complete` — all authorised work done. Declaring `complete` is the teardown: also set `progress.json` `status: "complete"` and run Phase 13 in the same turn, or the guards keep treating the loop as active. `retro.json` must exist beside `progress.json` **before** a `complete` declaration — the `loop_stall_guard` hook blocks the declaration when it is absent, malformed, or below `schema_version` 1 (the hook accepts `schema_version >= 1`) — and Phase 13's teardown write contract is what writes it, currently at `schema_version` 2.

The hook checks the declaration is present with a valid category; it cannot check the reason is honest (same boundary as the verify-loop hook). The Phase 13 category counts are the audit on that.

## A note on cadence

The user does not want a running narration of "now spawning X, now waiting for Y." They want:
- Brief status when a phase boundary is crossed
- Evidence when claiming success
- Clear stop on failure with the smallest readable summary

Idle pings from teammates are noise unless the artifact check (Phase 4) confirms a real failure. Don't react to every idle ping with a status update — match the cadence to the user's pull, not the runtime's push.
