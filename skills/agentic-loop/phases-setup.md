# Agentic loop — setup phases (-2 through 2.7)

Everything before routing and delegation: stubbing `progress.json`, sharpening the
authorising prompt, reading the envelope, pre-flight checks, resolving design forks
and disposition, and committing the design to `spec.md`/`plan.md`.

Read this in full at loop start. Phase 2.8 onward lives in SKILL.md.

### `S-2` — Phase -2: Stub `progress.json` first (the literal first action)

Before Phase -1 — before anything else — write a `progress.json` stub. This guarantees the loop's durable state file exists before the first stop, so the `loop_state_guard` Stop hook never trips a compliant loop; the block degrades to a backstop for a skipped stub.

**Resolve the path — never compute it yourself.** A repo- or cwd-derived key cannot be reproduced by hand. Get the absolute path by running the path helper (the path is keyed to the repo's `git --git-common-dir` when your cwd is inside a git repo, falling back to the raw cwd otherwise — so a mid-loop worktree hop resolves to the SAME path as the checkout it came from). The helper is stateless and re-derives this key on every call, so a loop that changes its own cwd's repo-ness mid-session (e.g. `git init`s an until-then-non-git cwd) will see its key change too — a rare, self-inflicted edge case, not one the helper guards against:

> `bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.sh"`

It prints the absolute path. Write the stub there with the Write tool (it creates the parent directory). If `${CLAUDE_PLUGIN_ROOT}` is not set in your shell, do **not** guess the path — proceed without the stub; the `loop_state_guard` hook will block once on your first stop and hand you the exact path to use. Copy that path verbatim. Either way, the path comes from the helper (directly, or via the guard which also calls it) — never from your own derivation.

**The stub:**

```json
{
  "schema_version": 2,
  "session_id": "<this session's id>",
  "loop_id": "<a unique non-blank id for this loop>",
  "revision": 1,
  "status": "initialising",
  "created": "<ISO8601 timestamp>",
  "authorising_prompt_raw": "<the user's authorising prompt, verbatim — Phase -1 updates this if an improved prompt is adopted>",
  "completed_marker": <carry forward the prior file's completed_marker if one exists at this path, else 0>,
  "graph": {
    "nodes": {"S-2": {"status": "running", "outcome": "running", "retry": {"attempts": 0, "max": 5}, "evidence": []}},
    "edges": [],
    "joins": {},
    "active_wave": {"wave_id": "wave-1", "revision": 1, "nodes": ["S-2"]}
  }
}
```

**Copy the stub verbatim — every field above is load-bearing.** `graph_executor_graph_valid`
(`hooks/scripts/lib/graph_executor.sh`) validates this shape, and the dispatch gate refuses every
Agent dispatch against a graph that fails it. Three fields are easy to "tidy" into a rejection:
- `revision` must be `1`, not `0` — the validator requires `revision > 0`, so a graph never has a
  revision of zero. Stubbing `S-2` as running IS the first wave, which is revision `1`.
- `S-2` carries an explicit `evidence: []`. An absent key reads as `null`, not as an empty array,
  and every node must have an array.
- `S-2` is `running` under the stub's own `active_wave`, and the two must agree exactly: the set of
  running nodes must equal `active_wave.nodes`. Do not "fix" `S-2` to `pending` — that leaves an
  `active_wave` naming a non-running node, which is equally invalid. `wave_id` is always
  `"wave-" + revision`, so revision `1` means `"wave-1"`.

**Close `S-2`'s own wave before your first real dispatch.** The stub opens `wave-1` with `S-2`
running, so the graph already has an `active_wave` — and `graph_dispatch_begin_wave` refuses
outright while one is open (it exits non-zero with **no error message**, so an unexplained `rc=1`
at your first wave means this, not a broken graph). Record `S-2` first, then begin the real wave:

> `graph_dispatch_record <path-to-progress.json> '{"wave_id":"wave-1","results":{"S-2":{"outcome":"done","evidence":["<what proves the stub was written>"]}}}'`

The `wave_id` and the `results` key-set must match the open `active_wave` **exactly** — `"wave-1"`
and exactly `S-2`, no more and no fewer — or the write errors with "results must exactly match the
active wave" and nothing changes. This clears `active_wave` and leaves `S-2` `done`; only then does
`begin_wave` succeed and return your first real wave.

The stub records `S-2` immediately; each later phase boundary adds its stable node and
dependency edges in the same orchestrator-owned write. Do not create a second scheduler or let
workers update `graph` directly.

If a `progress.json` already exists at the path from an earlier loop in this session, read its `completed_marker` and carry it forward into the new stub (do not reset it to 0) — this is what lets the guard tell a genuinely-finished loop from a new one that re-armed it (see the teardown rule below). A re-armed NEW loop always gets a new `loop_id` and resets `revision` to `1` (the stub's own first wave — never `0`, which the graph validator rejects); a mid-loop recovery preserves both values. Never omit or reuse the prior loop's `loop_id` for a new graph.

`loop_stop_counts` gets different treatment depending on the prior file's `status`, because it is HOOK-OWNED (see Context-window persistence below):
- Prior file `status != "complete"` (mid-loop re-stub, e.g. a recovery after a restart): carry `loop_stop_counts` forward verbatim into the new stub, so a mid-loop recovery doesn't silently reset the count the `loop_stall_guard` hook has been maintaining. Carry `authorising_prompt_raw` forward verbatim too — a re-stub refilled from conversation memory instead of the prior file's value would silently drift the eval author's canonical anchor.
- Prior file `status == "complete"` (re-arming for a NEW loop): reset `loop_stop_counts` to `{}` (omit the field from the stub) — the completed loop's counts are already preserved in its own `retro.json`; carrying them forward would bleed the finished loop's stop counts into the new loop's Phase 13 report.

### `S-1` — Phase -1: Sharpen the authorising prompt

**Run this phase UNLESS the user's prompt explicitly opts out.** Opt-out signals: "just do it", "skip improve-prompt", "don't improve the prompt", or any language that makes the directive unambiguous. On opt-out, skip directly to Phase 0. (Note: improve-prompt itself treats "just do it" as an unconditional skip — align with that.)

**Step 1 — Invoke `/coderails:improve-prompt` on the authorising prompt.**

> `/coderails:improve-prompt` — apply it to the prompt above.

It surfaces ambiguities, fills gaps with grounded assumptions, and produces a rewritten prompt that passes its 7-foundation diagnosis. Let it run to completion before Step 2.

**Step 2 — Adopt the improved prompt. Ask only outside a full-autonomous envelope.**

Step 2 has two paths. Which one applies is decided by the authorising prompt's envelope class (the same classification Phase 0 makes): "crack on", "human is dead", "ship N PRs without asking", "no human gates", or equivalent means full-autonomous.

**Full-autonomous envelope → auto-adopt, do not ask.** An `AskUserQuestion` here is a human gate, and a full-autonomous envelope has already withdrawn consent for gates. Do not resolve that contradiction by skipping Phase -1 — the improve-prompt output is worth more in autonomous operation, not less, because there is no human downstream to catch a vague envelope. Instead: run Step 1, auto-adopt outcome **A** without asking, and emit the improved prompt so it stays on the record. Concretely:

**Do the writes first, then emit the prompt last — the order matters.** Delivery mechanism (a) below means *ending the turn* with the improved prompt as final text and no trailing tool call. Any `progress.json` write issued after that text is a trailing tool call, which by the Delivery constraint below makes the prompt invisible. Emitting first and writing second therefore defeats the visibility this path exists to preserve. So:

1. Write the improved prompt to `progress.json.authorising_prompt_raw` as the canonical envelope.
2. Append `{phase: "-1", decision: "auto-adopted improved prompt as envelope; flip-condition: user names a divergence between the improved and original prompt"}` to `progress.json`'s `decisions_absorbed` array.
3. Emit the improved prompt as the turn's final text (delivery mechanism (a) below), with no tool call after it, so it stays visible. Auto-adoption must not make it invisible — the user has waived the gate, not the record.
4. Begin Phase 0 on the next turn, and note the auto-adoption at the next approval gate. Do not stall waiting for a reply — adopting a sharpened envelope is neither a verification failure nor a destructive action, so Phase 0's rule says the loop proceeds. The turn break here is a rendering requirement, not an approval gate: continue without any input.

This follows Phase 2.5's handling of the design fork in full-autonomous mode — auto-adopt, record, surface later, never stall — with one difference: Phase 2.5 writes only to a file and carries no render-as-final-text constraint, so it can finish inside one turn. Phase -1 must also show the prompt to the user, which costs the turn break in step 4.

The auto-adoption is bounded by the flip-condition: if the user later says the improved prompt drifted from what they meant, revert `authorising_prompt_raw` to the original and continue from there.

**Any other envelope class → ask, as below.**

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

The improved-and-approved prompt (or the original, if C was chosen; or the auto-adopted improved prompt, in a full-autonomous envelope) is what Phase 0 treats as the authorisation envelope. Phase 0's `<thinking>` block quotes it verbatim from here.

### `S0` — Phase 0: Read the authorisation envelope

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

### `S0.4` — Phase 0.4: Surface the orchestrator's model cost to the user at loop launch

**Token-burn rule (row 1 of 3).** The orchestrator cannot change its own model — `/model` is a user-typed slash command; nothing available to the orchestrator sets it. So the only executable action here is to tell the user. At loop launch — alongside Phase 0's envelope read, before Phase 1's plan — state once, in your own output, that this session's model bills every turn of the loop, and that switching it is theirs via `/model` before the loop gets long. Then continue; this is a notice, not a gate, never stall for a reply. Distinct from Phase 2.8's worker routing (spawned workers, not the orchestrator itself); given once at launch, not repeated per phase. See [model-routing.md](model-routing.md) for why the cost compounds.

### `S0.5` — Phase 0.5: Orchestrator operating rules (the conductor obeys its own rules)

The orchestrator (main context) is subject to the same discipline it imposes on workers. Inside an active, incomplete loop, the two discipline Stop hooks — confidence-label and verify-loop — demote a would-be block to a model-visible warn (`additionalContext` on the Stop event) rather than stopping the turn outright; the discipline itself hasn't changed, the warn is the correction signal the orchestrator acts on next turn. Outside an active loop, and for worker output (SubagentStop), both hooks still block outright. Even at warn-level, a missed warn is still a cost — it's the cost this skill exists to keep to a minimum, just paid as a drifted transcript instead of a forced regeneration.

Main context must, in its own output (not just in spawned-agent prompts):
- Confidence-label every substantive status claim — `(verified)` / `(inferred)` / `(guess)` (same taxonomy as Phase 11).
- Pre-tag any `## Did Not Verify` bullet that genuinely can't be checked, in the same turn it's written — an untagged bullet blocks the stop outside a loop and for workers, and is the first thing the in-loop warn will name.
- Never narrate a claim about an artifact (PR merged, deploy live) without having run the check this turn (Phase 12).
- End any stopping turn inside an active loop with a LOOP-STOP declaration line — `LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>` — as the FINAL line of the turn, emitted in the SAME turn as the confidence-label and Did-Not-Verify requirements above — that ending-line position is the contract this skill defines and the hook's category accounting assumes: when a turn carries more than one LOOP-STOP-shaped line (e.g. a quoted example), `loop_stall_guard` counts only the last one, so the last line must be the declaration that reflects the turn's actual outcome. Bundling all three matters more, not less, in the warn era: the confidence-label and verify-loop hooks no longer block the orchestrator's in-loop Stop turns, so nothing else forces those labels and DNV tags into the transcript — the bundle is what keeps them present for post-hoc audit, and one composed ending beats clearing one stop hook only to trip another (`loop_stall_guard` still blocks). Declaring `complete` means the loop is done: also set `progress.json` `status: "complete"` and run the Phase 13 teardown. The declaration line is all that's required — `loop_stop_counts` is HOOK-OWNED: the `loop_stall_guard` hook itself increments the matching category on a valid declaration; never write or compute this field yourself.

### `S1` — Phase 1: State the plan in bullets, ask once

Before the first agent spawn, write the full plan: phases, which agents per phase, parallel vs sequential, stop conditions. Use bullets. Keep it tight — the user reads this fast and decides whether to redirect.

Ask once: "Want me to execute this?" or "Confirm scope and I'll execute."

If yes → execute silently through to the end of the envelope.
If no → revise once based on feedback, then re-ask.

Do not loop more than twice on plan negotiation. If the third pass is needed, something is wrong with the envelope itself — surface that.

The harness choice itself — which loop skill drives this (`/coderails:agentic-loop` vs a flat loop vs a goal runner) — is part of the authorisation envelope (Phase 0), not a Phase 1 question. Resolve it once when reading the envelope and never re-surface it as "which approach do you want?".

### `S2` — Phase 2: Pre-flight checks via spawned agents, not main context

Pre-planning skills (`/coderails:planning-sequence`, `/coderails:premortem`, `/coderails:assumptions`, `/coderails:notchecked`, `/coderails:wiki-query`) belong in a delegated agent, not in main context.

Spawn a single pre-flight agent, `subagent_type: coderails:preflight-scout`, whose prompt includes:
- The plan from Phase 1
- An instruction to invoke each relevant skill via its `Skill` tool call
- An instruction to return one consolidated report (plan-sequence findings + premortem failure modes + assumptions inventory + wiki findings)

**Never substitute a generic agent here.** The pre-flight stage requires grounded risk identification from actual codebase state — a generic agent would re-derive the premortem and planning logic inline, fragmenting discipline across workers.

Include `/coderails:wiki-query` in the pre-flight agent's skill list, scoped to the **whole plan theme** (not per-PR). The query is something like: "What does the wiki cover about [overall theme of the agentic loop]? Identify cross-PR constraints, gaps, superseded decisions, and anything the plan assumes but isn't enforced in code." This pre-empts the per-PR `/coderails:wiki-query` that `/coderails:workflow` Phase 2 runs — see Phase 9 for why per-PR wiki steps are suppressed inside this loop.

**Retro intake.** The pre-flight agent additionally reads `standing-orders.md` at the repo-key dir (derive it as the grandparent of the path printed by `hooks/scripts/lib/agentic_loop_path.sh` — i.e. `dirname` of `dirname` of that path) and the last N=5 `retro.json` files under `<repo-key-dir>/*/retro.json` (mtime-sorted). It returns (a) premortem entries seeded from OBSERVED past failure modes and (b) a "carry into worker prompts" list of applicable lessons. Intake is additive-only: it may add cautions, assertions, and premortem entries; it may never relax a gate, skip a phase, or pre-justify an eval amendment. Gate changes remain human-owned. First-loop no-op: no retros + no overlay → skip silently, not an error.

**Primitive-contract read (mandatory when the plan calls a primitive in a non-standard way).** If the plan calls a lock, queue, transaction, or other shared primitive in any of: nested calls, recursion, parallel from same process, re-entered from the same caller — the pre-flight agent MUST read the primitive's source and document its contract: raise vs. return-bool semantics, reentrancy (PK collision behaviour), owner identity, expiry/steal logic. The schema may have been written before anyone read the primitive's internals. Past failure: a "wrap both sites with a DistributedLock" schema was impossible — the lock's `attribute_not_exists(PK)` semantics are non-reentrant and the sites were nested, not parallel; only reading the primitive's source caught it.

Spawn this pre-flight agent at the `default` role — it's running skills, not making architectural decisions, and `default` controls cost. (One of the two assignment sites Phase 2.8 doesn't cover — this agent runs before 2.8 exists in the sequence, so it gets its role inline, here.)

**Clean-base check (mandatory orchestrator action in main context, before ANY worker is spawned).** Run `git fetch origin` then `git log --oneline origin/main..main` and `git status --short` yourself. If local `main` carries commits `origin/main` does not, or has uncommitted/untracked files, the base is DIRTY — a parallel session (or an earlier uncommitted edit) has polluted it. When the base is dirty:
- NEVER let a worker branch off local `main`. Every worker MUST create its worktree via `superpowers:using-git-worktrees`, which accepts a declared base ref — the orchestrator must state one explicitly, by name, in the worker prompt: "Use the using-git-worktrees skill with base ref `origin/main` — not local `main`, not HEAD." This keeps worktree mechanics (native-tool detection, ignore-verification, directory selection) on the shared skill instead of Phase 3 reinventing them inline, while the `origin/main`-base requirement — a loop-specific safety invariant — travels through the skill's own declared-base-ref mechanism rather than being asserted outside it.
- Carry the foreign file names into worker prompts as an explicit "these are not yours — never stage, commit, or include them" exclusion list.

Do this check even when the base looks clean — two cheap git reads pre-empt a worker's PR silently inheriting another session's WIP from a dirty base, which otherwise only surfaces at the merge gate.

### `S2.5` — Phase 2.5: Resolve design forks before execution, not during it

`S2.5` and `S2.6` are sibling graph branches after `S2`: when both triggers
exist, dispatch their scouts in one wave. They reconverge at `J2`; the
orchestrator validates both results and performs the single state write before
releasing `S2.7a`.

If the plan contains an unresolved architectural choice (which primitive, which topology, which of several viable shapes), resolve it BEFORE entering Phase 3 — not through live back-and-forth once workers are spawning.

Spawn one design agent, `subagent_type: coderails:design-scout`, role assigned per Phase 2.8's table: `default` when the fork is a bounded choice between well-understood shapes; `frontier` from the start when the fork is a genuinely ambiguous investigation (Phase 2.8's "Investigations get frontier FIRST" states why). This agent runs before Phase 2.8's per-loop task routing, so it gets its role inline, here, using the same table. Its prompt requires:
- Read the actual code paths the alternatives touch — not assumptions about them.
- Build a head-to-head of the viable shapes with the real constraint each one hits.
- Return ONE recommended shape, the rejected alternatives with the reason each lost, and the single fact that would flip the recommendation.
- Apply `/superpowers:brainstorming`'s design-quality discipline *without* its human-approval gates: weigh the viable approaches against each other rather than taking the first that works, cut anything speculative (**YAGNI**), and prefer the shape whose units stay small and independently testable (**design-for-isolation**). The loop can't run brainstorming itself (its steps block on a human — see Phase 2.7); this reuses its *thinking*, not its control flow.

**Do not substitute a generic agent for `coderails:design-scout` here.** Design forks need deep code-path reading and tradeoff weighting; a generic agent cannot self-verify it read the actual paths instead of guessing.

What happens with that recommendation depends on the envelope class (Phase 0) — this phase resolves the fork, it does NOT add a new human gate:
- **Full-autonomous ("crack on / ship N PRs without asking"):** auto-adopt the design agent's recommendation, record the chosen shape and the flip-condition in `progress.json` — append `{phase: "2.5", decision: "<chosen shape + flip-condition>"}` to `progress.json`'s `decisions_absorbed` array — and note it at the next approval-gate. Do NOT stall for sign-off — a design fork is neither a verification failure nor a destructive action, so Phase 0 says the loop proceeds.
- **Narrow-fix / diagnostic / ambiguous envelope:** surface the one recommendation as a single decision — "here's the shape, here's why, approve or redirect" — bounded like Phase 1 (ask once, don't loop), then enter Phase 3.

Either way the fork is closed by ONE design artifact before building starts — the loop does not start half-built while the design is still being argued turn by turn.

**Where the design artifact is written — never onto local `main`.** Any phase that produces a file — a design investigation page, a recon note, a `progress.json` — writes it *outside the code repo's working tree*: to the wiki vault (`config.wiki_path`) if it is wiki-bound, otherwise a temp dir outside the repo. It is promoted into the PR worktree only at build time (Phase 3); it never lands on local `main`, where an untracked file silently pollutes the base every worker branches from — exactly the contamination the Phase 2 clean-base check then has to catch downstream. The recon/design phase is logically read-only with respect to the code repo; keep it literally so.

### `S2.6` — Phase 2.6: Resolve disposition before replacement work (clean-break vs preserve-compat)

When the Phase 1 plan contains a work-unit that **retires an existing code path** — there is a *named thing being replaced* (a function, module, endpoint, schema, or flag the change removes from use) — resolve its **disposition** once, up front, before the first spawn. This is the migration analogue of Phase 2.5's design fork: asked once, not re-litigated.

When triggered, run the disposition scout as the `S2.6` sibling of `S2.5`,
giving it the Phase 1 plan and named retirement paths. It returns one result per
retirement unit and writes no loop state. If no path is retired, record the
conditional skip and let `J2` release without this branch.

**Trigger precisely.** The fork fires only when an existing path is being *retired*, not merely when new code calls or wraps old code. If nothing is being removed from use, there is no disposition question. A concrete "what named thing does this remove?" test is deliberately harder to self-exempt from than a vague "is this a migration?".

**The fork, asked once:**
- **clean-break** — the old path is removed in the same unit. No shims, bridges, adapters, or compatibility flags remain.
- **preserve-compat** — the old path is kept behind a shim, justified by a **specific named blocker**: a named consumer still on the old path that cannot migrate in this unit. A generic justification ("safer", "less risky", "to avoid breakage") is NOT sufficient and must be rejected — name the consumer or choose clean-break.

**clean-break is the default recommendation for a retirement.** Recommend clean-break unless a specific named blocker exists. This is deliberate: the model's untold prior leans toward preserving the old path because removal feels destructive, and that prior is exactly what silently doubles migration work. Requiring a named blocker stops the prior being laundered into the human's explicit approval — where it would become invisible to the Phase 13 counter.

**What happens with the answer depends on the envelope class (Phase 0)** — this resolves the fork, it does NOT add a human gate:
- **Full-autonomous:** adopt clean-break by default, record it, proceed. Surface a preserve-compat choice (with its named blocker) at the next approval-gate; do not stall.
- **Narrow-fix / diagnostic / ambiguous:** surface the disposition as one decision — "clean-break recommended, here's why" — bounded like Phase 1 (ask once, don't loop).

**Record** per work-unit in `progress.json`: `disposition`, and when `preserve-compat`, the `named_blocker` and a mandatory `removal_ticket`. The disposition decision also appends `{phase: "2.6", decision: "<clean-break or preserve-compat, with named_blocker if applicable>"}` to `progress.json`'s `decisions_absorbed` array.

### `S2.7` — Phase 2.7: Commit the resolved design to durable `spec.md` and `plan.md`

The **2.7a/2.7b** design-doc sub-steps fire ONLY when the loop has **≥3 work-units or a cross-unit dependency** — the same line Phase 3 draws to choose a spawned team over a single agent. A 1–2-unit fix that Phase 3 routes to a single agent needs no separate design docs: the envelope (Phase 0) + `progress.json` + the one self-contained task description already carry everything. If the loop is below that threshold, skip 2.7a/2.7b.

**2.7c and 2.7e carry their own independent triggers and are NOT gated by the ≥3-work-unit threshold above** — a loop can skip 2.7a/2.7b entirely and still owe 2.7c and/or 2.7e. 2.7c fires on either of its own two stated triggers (verification_level-2-eligibility on work-unit count, or an irreversible-surface trigger, independently of each other and of 2.7a/2.7b). 2.7e fires for ANY loop with an executable surface, whatever its unit count, even when the rest of Phase 2.7 is skipped.

When 2.7a/2.7b fire, `J2` first joins the triggered Phase 2.5 and 2.6
results. The orchestrator validates both and performs one state update; a
skipped branch is recorded as skipped. Then run 2.7a and 2.7b in order. The
independent evidence branches 2.7c, 2.7d, and 2.7e may run in the same wave
when their own inputs are ready:

**2.7a — write `spec.md`.** Write a durable `spec.md` to the loop-state dir — the path printed by the loop-state path helper (`hooks/scripts/lib/agentic_loop_path.sh`, run at Phase -2), next to `progress.json`, outside the code repo, **not committed** (loop state, not a PR deliverable). This is a **commit of design the loop has already resolved**, not interactive brainstorming — a loop cannot brainstorm with itself; the forks were closed at 2.5 and 2.6. Record:
- the authorisation envelope verbatim (Phase 0);
- the design-fork decision and its flip-condition (Phase 2.5);
- the disposition decision(s) and any named blocker (Phase 2.6);
- the success criteria — what "done" means for the whole loop;
- the high-level work-unit boundaries (the detailed decomposition is Phase 2.7b's plan).

The `spec.md` is loop state, keyed to this orchestrator's run, exactly like `progress.json` — not a shareable design record. When ad-hoc loop work genuinely needs handing to a human, that is what `/coderails:handoff` is for.

**2.7b — write `plan.md` via `/superpowers:writing-plans`.** Produce a durable `plan.md` in the loop-state dir (next to `spec.md` and `progress.json`, outside the repo, not committed) by invoking **`/superpowers:writing-plans`** — the same one-line skill-reference idiom Phase 3/3a use for `/superpowers:test-driven-development`.

`plan.md` is the **static SSOT** for the decomposition; `progress.json` is the **dynamic position** against it. The plan is **consumed, not write-only**, in both directions:
- **Phase 3 builds its task list directly from `plan.md`** — the shared task list (`TaskCreate`/`TaskUpdate`) and the Phase 3/3a worker descriptions derive from the plan's tasks, so the two are consistent by construction rather than re-derived from conversation.
- **After any compaction the orchestrator re-reads `plan.md` to recover *scope* (what to build)** the same way it re-reads `progress.json` to recover *position* (where we are).

**2.7c — generate and freeze loop-scope evals via `/coderails:task-evals`.** Alongside `spec.md`/`plan.md`, invoke **`/coderails:task-evals`** (scope: `loop`) to produce a frozen `evals.json` defining the loop's end-state success evals. This sub-step fires for EVERY loop, regardless of unit count — it is NOT gated behind 2.7a/2.7b's ≥3-work-unit-or-cross-unit-dependency threshold, and does not wait on "reaching Phase 2.7" in that sense: `loop_dispatch_guard`/`loop_state_guard` gate every loop with **work_units >= 1** on a frozen/graded loop-scope `evals.json`, so a 1–2-unit loop must run 2.7c even when it skips 2.7a/2.7b entirely, or its first worker dispatch deadlocks against a gate that never got a chance to be satisfied. Two triggers fire this sub-step, stated explicitly because they're independent: (1) verification_level-2-eligibility on work-unit count alone, which applies to any loop with **work_units >= 1** (2.7c itself is required starting at that same floor); (2) an irreversible-surface trigger (publish, deploy, migration, data deletion, external send), independently of unit count. The frozen `evals.json` (scope: `loop`) lives beside `progress.json`/`spec.md`/`plan.md` in the loop-state dir — same "never committed, outside the repo" rule as those two files. Grading this file at loop end is `post_evals.sh grade-loop`'s job, not the orchestrator's — see Phase 13. **The frozen-and-ungraded file is itself checked at dispatch**: `loop_dispatch_guard` refuses every `coderails:loop-worker` dispatch in a **>=1-unit** loop until a loop-scope `evals.json` exists that is owned by this session and loop, carries a non-blank `verification_justification`, and holds at least one P0 in an array-typed `.evals` — the FROZEN state. It does **not** demand a grade at dispatch, and must not: at freeze time every P0 is still `pending` with empty evidence, so `grade-loop` correctly refuses the file (`validate_structure` check 5). Do not run `grade-loop` early to satisfy the dispatch gate — a suite graded before the build is either a refusal or a rigged pass. Completion is the opposite: Phase 13, `loop_state_guard`, and `loop_stall_guard` accept only a genuinely graded GO (or a graded verification_level-0 exemption), so a FROZEN suite opens dispatch and still blocks `complete`. The eval author anchors goal state on `progress.json`'s `authorising_prompt_raw`, per `task-evals`'s oracle-independence rule.

**2.7d — freeze a PR-scope `evals.json` per work-unit, in the same invocation.** The same `/coderails:task-evals` run ALSO produces one **frozen** PR-scope `evals.json` (scope: `pr`) for every work-unit that will carry a PR. This is a **separate artifact** from 2.7c's loop-scope file, not a view of it, and freezing 2.7c alone does not satisfy it: `scripts/merge.sh` hard-gates every merge on a SHA-bound **pr-scope** eval comment with `result=GO` — fail-closed, no config opt-out. A loop that freezes only loop-scope evals passes Phase 3 and Phase 4b unimpeded and then meets an unsatisfiable merge gate, with the implementation already built.

Each unit's PR-scope eval ref then travels into its worker prompt the same way disposition travels under Phase 3's existing "Disposition — ... copied **verbatim** into the task description" bullet: a ref recorded only in `progress.json`/`plan.md` and absent from the worker prompt does not exist for the worker.

**The timing cannot be recovered later, which is why it is a freeze and not a to-do.** Freeze-before-build is `task-evals`' rule 1; a pr-scope suite authored at merge time cannot honour it, because its author already knows what the implementation does. When it has been missed, the only honest repair is: author them late, stamp `frozen_at` at the **real** authoring time (never backdate — a backdated freeze is the one edit that turns a disclosed gap into a rigged gate), disclose the gap in `verification_justification`, and report it at Phase 13. The GO then rests on evidence the suite genuinely discriminates — an executed negative control, or a run that actually failed against a real defect — never on the timestamp. That repair is a **disclosed gap, not a pass**; its availability is not a licence to skip the freeze.

Past failure (loop 0d3fb487, 2026-07-16): this sub-step was a trailing sentence under a heading that said "loop-scope", carrying no freeze obligation, no timing, and no mention of the merge gate. The loop froze loop-scope evals at its Task 1 — correctly, pre-build — and never registered that the pr-scope half was missing until `merge.sh` refused the merge, by which point the work was built, merged-ready, and live-fired. The gate caught what the process missed; that is the gate working, not the process working.

**2.7e — freeze `proof.json` beside `evals.json`, authored by a separate blind agent, `subagent_type: coderails:proof-author`.** For every loop with an executable surface, spawn a SEPARATE agent whose input is `authorising_prompt_raw` plus `session_id` and `loop_id` (all three verbatim from `progress.json`, passed as explicit dispatch inputs — not a grant to read `progress.json` itself) plus any pre-implementation docs that prompt itself references — never the plan, spec, design decisions, or this conversation. By Phase 2.7c the orchestrator has already seen the plan, so its blind spot already exists; this generalises `task-evals`' grader-independence to the AUTHOR, not just the grading. That agent writes `proof.json` (schema `{"schema_version":1,"session_id","loop_id","frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`) beside `progress.json`/`evals.json` — same "never committed, outside the repo" rule.

**Do not substitute a generic agent for proof authoring.** Proof authoring has a strict blind-input contract (envelope only, no plan) that a generic agent cannot self-enforce — a named proof-author type embeds this constraint at dispatch.

Each `cmd` must be a single self-contained shell command, runnable verbatim as its own Bash call BY THE ORCHESTRATOR in its own session (never a worker), in the FOREGROUND (never `run_in_background` — the gate's transcript miner excludes backgrounded launches, since their immediate result is not a pass/fail outcome), using absolute paths, exiting 0 on success (beware grep-style non-zero-on-no-match), with no command substitution mixed into a gated script's own invocation line and no destructive pattern. This is unconditional for every loop with an executable surface, even when the rest of Phase 2.7 is skipped (2.7a/2.7b's ≥3-work-unit threshold does not gate 2.7e); a loop with nothing executable writes no `proof.json` and records that choice in `decisions_absorbed` **and** sets `progress.json`'s `proof_disposition` to `"none: <reason>"` (e.g. `"none: no executable surface"`) — write `progress.json` at `schema_version` 2 to get this enforced: the `loop_stall_guard` proof gate requires that recorded disposition before allowing an absent `proof.json` through at `schema_version` >= 2 (grandfathered to the old unconditional fail-open at `schema_version` < 2), so skipping it is a visible, mechanically-required decision, not a silent gap.

The `status` field is written `"pending"` but is present, never consulted — the gate's jq program never reads `.status` at all, so the field cannot grade itself even by accident. The `loop_stall_guard` hook's `als_gate_proofs_on_complete` mines THIS session's own transcript for a matching Bash tool_use/tool_result pair per proof; only an actually-executed, non-erroring command satisfies a proof, never the `status` string. See [loop-state.md](loop-state.md) for the full field contract and honest boundary.
