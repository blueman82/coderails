---
name: agentic-loop
description: 'Multi-agent orchestration discipline — keeps the main context a pure orchestrator that never implements. Load IMMEDIATELY, over /workflow, /prep, /push and any other single-PR command, whenever the user authorises agent-driven work: "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or 3+ PRs authorised in one instruction. ALSO load for autonomous merge + deploy + verify chains, even a single PR, if per-step confirmation is waived. NOT /workflow (single-PR prep → push → merge → wiki); it sits ABOVE /workflow and uses it as a subroutine. Fire aggressively — forgetting to delegate is costly in long sessions.'
effort: high
---

# Agentic Loop

How to run an autonomous multi-agent / multi-PR session so the user doesn't have to manually instruct every turn.

## Why this skill exists

In long agentic sessions the assistant drifts back into bad habits: running skills in main context instead of delegating; asking "want me to spawn an agent for X?" when X is obviously in scope; holding at human gates the session already removed; trusting an "idle" notification as proof-of-failure when the agent often finished silently; spawning fix workers without disproving the symptom premise. Each unnecessary stall is a manual prompt the user has to write — a stalled loop loses the autonomy the session was authorised for.

Repo-agnostic lessons promoted from accumulated loop retros live in [learned-failure-modes.md](learned-failure-modes.md) — machine-maintained via the `loop-retro-promotion` pipeline; read it alongside this skill.

**Authoring rule — every instruction in this skill must name an action its reader can actually perform.** Before writing any directive, confirm the reader has a tool call, command, or file write that executes it, and that the condition it tests can actually come out both ways. An instruction the reader cannot carry out is not a weak instruction, it is a no-op: it gets silently skipped or reported as done without happening. Three instances of this defect class were found across this skill and its sibling `superpowers:finishing-a-development-branch` in a single loop on 2026-07-29 — a cwd-equality test whose two sides were assigned from the same source and whose pid was a bash subshell's, never the harness session's, so both branches were dead; a squash-merge safety predicate asserting `git log --oneline origin/main..HEAD` is empty, which a squash's SHA rewrite makes unsatisfiable (both fixed in PR #317); and Phase 0.4's instruction to pin the orchestrator's own model via `/model`, a command the orchestrator cannot invoke.

## The phases

Nineteen-plus numbered phases (−2 through 13, with lettered sub-phases) is too many to hold in mind cold. Group them into five stages before descending into per-phase detail:

| Stage | Phases |
|---|---|
| Setup | -2, -1, 0, 0.4, 0.5 |
| Pre-flight | 1, 2, 2.5, 2.6, 2.7, 2.8 |
| Build | 3, 3a, 4 |
| Review & Ship | 4b, 5, 6, 7&8 |
| Wrap-up | 9, 10, 11, 12, 13 |

The phases below are a dependency graph, not a queue. A node is ready only when
its prerequisites and readiness predicate are true — before dispatching any
candidate node, run the read-only readiness query
`${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/graph_readiness.sh <path-to-progress.json> <node-id>`
and dispatch only nodes it reports `ready` for. Its `blocked` output means "not
yet ready to dispatch" — it fail-closes the same way on missing or malformed
`progress.json` as on a real non-terminal predecessor, so it cannot distinguish
the two. Conversely, a node with no recorded incoming edges is vacuously
`ready` — register the candidate's node and edges before querying, not after.
Run ready independent nodes in one wave, but preserve every listed dependency.
The orchestrator is the only writer of `progress.json`: collect a wave's results, then do one
read-modify-write before releasing its join. Inside an authorised loop, the
`U*` lane below repeats per work-unit.

### Execution graph — stable contract

Node IDs are stable documentation identifiers. `S*` nodes run once; `U<i>*`
nodes run once per work-unit `i`; `J*` nodes are explicit joins. A skipped node
is still recorded as `skipped: <predicate>` in loop state; it is not a failed
node and cannot satisfy a prerequisite by omission.

```text
S-2 -> S-1 -> S0 -> S0.4 -> S0.5 -> S1 -> S2
                                      |       |
                                      |       +--> S2.5 --+
                                      |       +--> S2.6 --+--> J2 --> S2.7a --> S2.7b --+
                                      |       +--> S2.7c -------------------------------+
                                      |       +--> S2.7d[i] -----------------------------+--> S2.8 --> J2.8
                                      |       +--> S2.7e -------------------------------+
                                      |                                                    |
                                      +----------------------------------------------------+
                                                                                           v
                  +--> U3[i] --> U4[i] --> U4b-review[i] --> U5[i] --> U6[i] --> U7/8[i]
                  |       ^                 |                    |          |          |
J2.8 ------------+       |                 |                    +----------+----------+
                  |       |                 +--> U5-repair[i] --/           |
                  |       +-------------------- retry-until-green ----------+
                  |                                                            v
                  |                                                     U4b-merge-gate[i]
                  |                                                            |
                  +<-- U10-respawn[i] <---------------------------------------+
                                                                               v
                                                                        J12-all-units
                                                                               |
                                                                    S9-wiki -> S9-docs
                                                                               |
                                                                    S13-proof -> S13-retro
                                                                               |
                                                                        S13-complete
```

The diagram is a shape guide; the table is authoritative where a line would be
ambiguous.

| ID | Node / true prerequisites | Ready when | Conditional skip or join |
|---|---|---|---|
| `S-2` | Stub state | path helper returns the session-owned state path | never skipped |
| `S-1` | Improve prompt | prompt is adopted, revised, or explicit opt-out is recorded | full-autonomous auto-adopts; otherwise one bounded input point |
| `S0` | Read envelope | envelope class and stop conditions are recorded | never skipped |
| `S0.4` | Model-cost notice | notice emitted | never a gate; no model switch is performed by the orchestrator |
| `S0.5` | Operating rules | confidence, verification, and `LOOP-STOP` rules are active | never skipped |
| `S1` | Plan | work-unit list, dependencies, and success criteria exist | Phase 1 confirmation may be `awaiting-input` |
| `S2` | Plan | pre-flight agent result, wiki/theme intake, retro lessons, and clean-base check exist | never spawn implementation before this node |
| `S2.5` | `S2` | design scout returned a recommendation and flip-condition | skip when no unresolved design fork |
| `S2.6` | `S2` | disposition scout returned a result for every retirement unit | skip when no named existing path is retired |
| `J2` | `S2.5` and `S2.6` | all triggered scouts returned; orchestrator validated and absorbed both results in one state write | skipped branches contribute an explicit skip record |
| `S2.7a` | `J2` | durable `spec.md` exists | only if `work_units >= 3` or a cross-unit dependency exists |
| `S2.7b` | `S2.7a` | durable `plan.md` exists and matches the work-unit list | same predicate as `S2.7a`; `S2.7b` is sequential after it |
| `S2.7c` | `S2` plus authorising prompt | loop-scope evals are frozen before build | required for a Phase 2.7 loop or an irreversible-surface trigger |
| `S2.7d[i]` | `S2` plus each unit definition | PR-scope evals are frozen before that unit builds | skip only for a unit with no PR; required before its merge gate |
| `S2.7e` | `S2` plus executable-surface decision | blind `proof.json` exists, or explicit no-executable disposition is recorded | required for every executable loop; independent of `S2.7a/b` |
| `S2.8` | `S2` and `S2.7b` when triggered | every build unit has one recorded model role | may run beside independent evidence branches; never releases a unit without its required inputs |
| `J2.8` | `S2.8`, plus `S2.7d[i]`/`S2.7e` where required | all inputs for the first eligible unit are present | later units wait on their own true prerequisites |
| `U3[i]` | `J2.8`, unit dependencies, and required eval/proof inputs | worker produced the unit's committed artifact/OPEN PR terminal state | units with `blockedBy` dependencies wait; independent units may run in waves |
| `U4[i]` | `U3[i]` | artifact, worktree, PR, and worker report were checked by the orchestrator | idle is not failure; failed artifact check enters repair |
| `U4b-review[i]` | `U4[i]` | required review Skill, security/deploy review when triggered, and SHA-bound post-review artifact exist | review findings go to `U5[i]`; no merge on a missing artifact |
| `U5[i]` | `U4b-review[i]` or a verified reported regression | source-of-truth premise is confirmed and diagnosis is disconfirmed | premise disproven is a hard-stop; otherwise spawn the repair worker |
| `U5-repair[i]` | `U5[i]` | distinct fix attempt applied and locally verified | back to `U4[i]`; at most 5 distinct attempts per failure |
| `U6[i]` | current unit is verified and any in-scope confirmation decision is resolved | envelope permits autonomous continuation or required approval is granted | no extra ask inside the envelope |
| `U7/8[i]` | `U6[i]` | stack-specific push/deploy tactic completed, if applicable | skip when no push/deploy surface; these phases do not add generic policy |
| `U4b-merge-gate[i]` | `U4b-review[i]`, `U6[i]`, `U7/8[i]`, PR-scope eval, review artifact, and integrity attestation | exact-head review/eval/integrity checks and gate-time smoke pass; merge reports `MERGED` | any missing/stale/failing gate enters `U5-repair[i]` or hard-stop after retry bound |
| `U10-respawn[i]` | `U4[i]` artifact check shows dispatch failure/idle without artifact | new versioned worker name and fresh dispatch exist | not triggered by an idle ping alone; returns to `U4[i]` |
| `J12-all-units` | every unit's merge gate passed | each merged PR and dependent deployment evidence is freshly rechecked | no unit may be silently omitted |
| `G10` | any respawn path | every replacement worker name is versioned | cross-cutting Phase 10 guard; no standalone work |
| `G11` | every worker dispatch and report | prompts and reports carry confidence labels | cross-cutting Phase 11 guard; no standalone work |
| `G12` | every artifact boundary | the orchestrator freshly rechecks the artifact before releasing a dependent node | cross-cutting Phase 12 guard; `J12-all-units` is its final aggregate join |
| `S9-wiki` | `J12-all-units` | clustered wiki ingest and lint landed and were verified on `origin/main` | skip only when no wiki update is in scope; still record the skip |
| `S9-docs` | `S9-wiki` | one `/sync-docs` audit completed and findings triaged | pre-existing drift is reported, not folded into scope |
| `S13-proof` | `S9-docs` | every frozen proof command ran verbatim in the orchestrator session and passed | absent proof requires the recorded no-executable disposition |
| `S13-retro` | `S13-proof` | Phase 13 report, cost, decisions, artifacts, eval result, standing orders, and feedback are written | never a mid-loop checkpoint |
| `S13-complete` | `S13-retro` | final aggregate verification passes; `progress.json` is complete and `retro.json` is valid | terminal node; emits `LOOP-STOP: complete` |

`S0.5`, `U4`, `U4b-review`, `U6`, and `S13-complete` carry the Phase 11/12
confidence-label and fresh-evidence rules; they are guards on the nodes above,
not extra work. A review finding, failing eval, smoke failure, or verification
failure follows `U5 -> U5-repair -> U4` and consumes one distinct retry attempt.
After five diagnosed attempts for the same failure, the edge terminates at the
hard-stop rather than looping. Independent failure domains may use parallel
repair workers, each with its own bound, then join at `U4`.

### Phases -2 through 2.7 — setup, before any delegation

Stub `progress.json`, sharpen the authorising prompt, read the envelope, run
pre-flight checks via spawned agents, resolve design forks and disposition, and
commit the resolved design to `spec.md` and `plan.md`.

**Read [phases-setup.md](phases-setup.md) in full at loop start.** These phases
run once, before Phase 2.8 routes any work. Skipping them is how loops start on
an unresolved design.

### Phase 2.8 — Route: assign a model role per task

Every loop assigns a **model role** to every Phase 3/3a build task before any
worker spawns — even a 1-2 unit loop that skips Phase 2.7 entirely. Decide once,
up front, recorded; never re-litigate per spawn.

**Roles are capability verification levels, not model names.** A verification_level pinned to a named model
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

**Default: main context never implements.** It orchestrates — plans, delegates, verifies. Every implementation unit (even a single-file edit, even a tight sequential step) goes to a spawned worker at the role Phase 2.8 assigned it — the `default` role unless Phase 2.8 routed otherwise. The two reasons, in order: keep main context clean (frontier-verification_level context is scarce and fills fast in long sessions), and keep cost down (`default` does the typing, not `frontier`). Treat a `frontier`-role worker, or a file edit done directly in main context, as the exception that needs a reason, not the default.

The delegation decision is a two-rung ladder, not "delegate vs. do it yourself":

1. **Single routed `Agent` for impl + verify, `subagent_type: coderails:loop-worker`** — the default for any self-contained 1–2 unit of work (a bug fix, one PR, a single-file change), at the role Phase 2.8 assigned. One agent does the implementation *and* verifies its own artifact before reporting. A spawned team would be overkill here. See Phase 3a below for the prompt contract. **Do not substitute a generic agent for single-unit work.** Implementation units require tight test-first/verify-before-report discipline; a generic agent omits these constraints, trading off coverage for prompt brevity.
2. **Spawn a team, `subagent_type: coderails:loop-worker`** — when the loop has 3+ PRs or any cross-step dependency, spawn each worker as a named teammate via the `Agent` tool, build a task list with explicit `blockedBy` dependencies via `TaskCreate`/`TaskUpdate`, and coordinate with `SendMessage`. Don't just describe a "sequential PR loop" — actually spawn the named agents and create the task list, so the user can see each teammate and the task list becomes the shared source of truth. **Do not substitute a generic agent for team dispatch.** A generic agent won't register as a named teammate in the task graph or honour `blockedBy`/`SendMessage` coordination, so the orchestrator loses the shared source of truth the task list is meant to provide.

The only work that legitimately stays in main context: reading for orchestration decisions (git status, `gh pr view`, log reads, the Phase 12 artifact checks), and the planning/cadence the skill describes. If you catch yourself running `Edit`/`Write`/`MultiEdit` in main context inside an authorised loop, stop — that work belongs in a routed worker agent.

**Orchestrator never authors deliverable files inline (token-burn rule, row 3 of 3).** The orchestrator's own `Write`/`Edit` calls are for loop-state only — `progress.json`, `spec.md`, `plan.md`, `retro.json`, and the like. Every deliverable artifact (code, docs, config, any file that ends up in a PR) is authored by a spawned worker, never typed inline in main context. Workers report back structured, confidence-labelled verdicts (Phase 11) — a short claim plus the command that verified it — not long narrative prose; a verbose report re-inflates the same context this rule is trying to keep small.

If the user has explicitly asked for a spawned team in their prompt, it is non-negotiable — spawn named teammates even if a flat sequence of solo `Agent` calls would technically work.

**Sandboxed dispatch (`config.sandbox_workers: true`).** When set, implementation-unit workers (rung 1 and each teammate in rung 2) dispatch as a separate OS-sandboxed process instead of an in-process `Agent` call: `scripts/sandbox/spawn-sandboxed-worker.sh <worktree> <prompt_file> <model>` (worktree must already exist; `prompt_file` holds the same self-contained worker prompt Phase 3a requires — every travel-rule bullet still applies, just written to a file instead of passed as an `Agent` prompt string).  **Note: this script takes a MODEL parameter but has NO agent-type parameter — the `coderails:loop-worker` type naming above applies to the in-process `Agent` path only; sandboxed workers cannot carry a type at dispatch.** Orchestration reads (git status, `gh pr view`, log reads) stay in-process regardless — only implementation units route through the sandbox. Trade-off: a sandboxed worker is a separate process, so it has no `SendMessage`/task-list coordination — reporting is artifact-terminal only (PR state), same terminal-state discipline as Phase 3a's own contract. Seam: a spawn failure (non-zero rc, non-git worktree, missing prompt file) is a failed dispatch — treat it exactly like an idle/failed `Agent` call under Phase 4, re-derive from the artifact, don't retry blindly. In the sandboxed path, push with plain `git push origin <branch>` — no `-u` (concurrency hygiene: parallel sandboxed workers would otherwise race to write `branch.*` into one shared primary `.git/config`; on this pinned srt version `-u` also silently fails its config write while still exiting 0, a partial-failure mode this contract avoids rather than depends on). Any in-worker GitHub API call must use curl, not `gh` — `gh`'s Go/trustd TLS verification does not work inside the sandbox on this pinned version.

Each task description must be **self-contained** so the spawned agent can act without re-reading the conversation. Every bullet of Phase 3a's prompt contract applies to each teammate's task description — role verbatim, construction method and discipline, the self-run verify step, manifest + pre-push scope assertion, disposition, lessons, terminal state, report-back contract, and the hook-seam. A task-list entry is not a substitute for any of them: anything absent from the prompt does not exist for the worker. Add, on top of that contract:
- Worktree path and branch name
- JIRA ticket
- Verified state from prior tasks (deployed version, test counts, what's already wired)
- Exact step-by-step sub-steps

Include this line in every agent prompt:
> "Don't go silently idle — send a completion message via SendMessage. Past agents have failed this way."

### Phase 3a — Single routed agent for impl + verify (the spawned-team-is-overkill case)

For self-contained work that doesn't justify a team — a bug fix, one PR, a single-file change, a tight sequence of steps with shared context — spawn **one** `Agent`, `subagent_type: coderails:loop-worker`, at the role Phase 2.8 assigned, that owns both the implementation **and** the verification, then reports back a confidence-labelled result. Main context stays the orchestrator; it does not make the edit itself.

One agent does both impl and verify (not two) because verification output is dense — exactly the kind that fills main context. The agent self-verifies; main context spot-checks only at dependency boundaries (Phase 12) or when the artifact check is cheap and the stakes are high.

The agent's prompt must be self-contained (it can't re-read the conversation) and include:
- **The Phase 2.8-assigned role, verbatim, including any fallback valve** — copied from the plan's `Model:` stamp (`superpowers:writing-plans`), or from Phase 2.8's recorded assignment for a below-plan.md-threshold loop. A role recorded in `progress.json`/`plan.md` but absent from this prompt does not exist for the worker — same travel rule as disposition and lessons. `default` is the floor absent a routing reason; `frontier` is the exception that needs one.
- The exact change to make, with file paths and the success criteria stated as something testable.
- **Construction method (when the deliverable is code).** If the change adds or alters a function, method, or branch that *can* carry a test, the worker builds it test-first via `/superpowers:test-driven-development`: write the failing test, watch it fail for the right reason, then the minimal code to pass, then refactor green — even if the PR also touches non-code files. For pure docs/config/prose with no testable code, there is no failing test to write first; the verify step below is by inspection instead. For the full worker-prompt construction contract (implementer/reviewer prompt templates + the per-task review loop), see `/superpowers:subagent-driven-development`.
- **Construction discipline.** The agent holds itself to `superpowers:verification-before-completion` throughout implementation, not only at the report-back step: no "should work now" framing on any intermediate claim, run the actual check before asserting a sub-step is done. Additive to the report-back contract below, not a replacement for it.
- **A verify step the agent runs itself before reporting** — run the test / lint / build, read back the diff, hit the endpoint or read the log. State which one. "Implement X, then verify by running `Y`, and only report success if `Y` passes."
- **Report-back contract:** return a confidence-labelled summary (Phase 11), state what was run to verify (the command + its result, not just "verified"), and "don't go silently idle — send a completion message" (Phase 4 — workers go idle without reporting regardless of role).
- If the work writes to git, the worktree/branch and a "commit your work" instruction so the artifact is durable for the orchestrator's Phase 4 check.
- **Shared-checkout isolation — applies to ANY target checkout the agent will write into, not just the loop's own code repo (an external wiki vault, a docs repo, any other git checkout another session might also have open).** The decidable test: is the target checkout already a linked worktree (`superpowers:using-git-worktrees` Step 0's `GIT_DIR != GIT_COMMON`)? If not, the dispatch prompt must instruct the agent to create one via `superpowers:using-git-worktrees` — "before making any edits, confirm or create worktree isolation for `<target checkout path>` via the superpowers:using-git-worktrees skill; do not write directly onto that checkout's current branch" — using the same base-ref phrasing as Phase 2's clean-base check ("base ref `origin/main` — not local `main`, not HEAD"). Before dispatch, the orchestrator itself runs `git -C <abs target path> worktree list` and `git -C <abs target path> log --oneline origin/main..HEAD` (absolute path, not `cd` — see `learned-failure-modes.md` on cwd drift across worktrees) to know about any pre-existing unpushed work on that checkout first. Root incident: an unisolated wiki-writer dispatch committed straight onto a shared vault checkout's local `main`, interleaving with a concurrent session's unpushed commits there — nothing was lost, but a routine push became a manual untangling job. This is dispatch discipline, not a hook: there is no reliable signal for "another session is using this checkout right now," so it cannot be enforced mechanically and must travel in the prompt every time.
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

**Orchestrator probe discipline — batch the battery, cap the output on a tool-output diet (token-burn rules, rows 2 and 3 of 3).** The four checks above (and any similar verification battery — Phase 12's artifact checks, gate-state reads, `gh pr view` sequences) go in ONE compound Bash call per battery, not one call per check. Each orchestrator turn re-reads the full, growing context accumulated so far; running 4 probes as 4 separate turns costs roughly 4x the cache-read volume of the same 4 probes chained in one script (`&&`/`;`-joined, or piped) and read once. Compound the reads, not the decisions — still stop and reason once the battery's combined output is in hand. Additionally, cap what each probe returns before it enters context — pipe through `jq -c`, `head`, or an equivalent limiter — so a large `git diff --stat` or `gh pr view` payload doesn't sit in the transcript re-inflating every subsequent turn's re-read for the rest of the loop.

The same rationale applies beyond Bash: independent non-Bash tool calls — `Read`, `Grep`, `Glob`, a rung-1 `Agent` call — that don't depend on each other's output also belong in one turn, emitted in parallel, not spread across sequential turns. Two constraints this doesn't override: if a call's parameters depend on a previous call's output, sequence it instead — never fill in a placeholder or guess a missing parameter to force it into the same batch; and parallel emission never substitutes for Phase 3 rung 2 — the moment the work is 3+ units or has a cross-unit dependency, spawn the named-teammate team with a `blockedBy` task list instead of firing more solo `Agent` calls in parallel.

### Phase 4b — PR review invokes `/pr-review-toolkit:review-pr <PR#>` as a Skill, then `/coderails:post-review <PR#>`

When a phase reaches "review the PR" (after a `/workflow` agent has pushed a PR, before merge), invoke the **`/pr-review-toolkit:review-pr <PR#>`** Skill — passing the PR number as the argument — which itself fans out the six specialised reviewers plus a security pass. Do NOT hand-roll the reviewers as separate `Agent` or `Task` spawns; use the Skill invocation.

**Invoking `/pr-review-toolkit:review-pr <PR#>` with the PR number is REQUIRED to satisfy the merge gate, because `enforce_pr_workflow` only accepts the `review-pr` Skill (with the PR number in args) as merge evidence — a manually-spawned agent fanout leaves no evidence the gate recognises and the merge will block.** The gate also recognises `scripts/merge.sh <PR#>` invocations (not just raw `gh pr merge`) as the same merge subcommand, so a hand-rolled review cannot merge through the wrapper script either.

**Review verification_level ladder.** All verification levels — regardless of the PR's own eval-artifact verification_level (a separate, orthogonal check) — invoke `/pr-review-toolkit:review-pr <PR#>` (the toolkit self-scales its reviewer fan-out by change shape) plus `/coderails:post-review <PR#>`. Only at verification_level 0 MAY the separate `/security-review` pass below be skipped, and only after checking the actual diff file list (`gh pr diff <PR#> --name-only` or `git diff origin/main...HEAD --name-only`): any path under `hooks/` or `scripts/`, or any change touching auth/exec/network-fetch code, FORCES the security pass regardless of declared verification_level. The override keys off the diff, never the self-assigned verification_level label. Verification level 1/2 PRs run the full Phase 4b unchanged, security pass included.

**After `review-pr` completes and all applied findings (blocking and worthwhile) are committed and pushed, invoke `/coderails:post-review <PR#>`.** This posts the SHA-bound review artifact — a machine-marked GitHub comment — that the `/merge` gate requires before merging. Loop symmetry: this is the same artifact gate that `/coderails:workflow`'s Phase 3 wires in for non-loop use. Both paths produce the same artifact; `/merge` checks both the same way. Run `post-review` after findings are applied and the follow-up commit is pushed, so the artifact is stamped against the final head SHA.

Before `/coderails:merge`, the loop must also produce a second, independent artifact: run `/coderails:task-evals` (scope: `pr`; docs-only/single-unit PRs that meet its verification_level-0 predicate get the lightweight exemption path) then `/coderails:post-evals`. `scripts/merge.sh` hard-gates on this eval artifact separately from the review artifact above — same fail-closed posture, no config opt-out.

**Worktree teardown, immediately after `/coderails:merge` confirms this work-unit's PR is merged.** A work-unit's worktree (created per the `origin/main`-based instruction above) is scoped to that one PR — once it's merged, the worktree has no further purpose and must not be left to accumulate across a multi-work-unit loop. Clean up the worktree using `superpowers:finishing-a-development-branch`'s Step 6 mechanics — the commands, provenance check, and cwd-pinned-worktree caveat are in [finishing-out.md](finishing-out.md). When the worktree is the orchestrator's own cwd, teardown uses the native exit-worktree tool (e.g. `ExitWorktree`) rather than `git worktree remove` — see finishing-out.md for the lock-case split. (The PR is already merged via `/coderails:merge` at this point, so this is the Step 6 cleanup only, not the skill's push/PR outcome-selection.) This runs per-work-unit at this point in Phase 4b — not deferred to Phase 9/13's loop-level teardown, which handles wiki/retro artifacts, not worktrees.

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

**Plus `subagent_type: coderails:deploy-safety-reviewer` when the change has a runtime/production surface.** This is a coderails repo agent, not one of the six `pr-review-toolkit` reviewers above, and does not substitute for the `review-pr` Skill invocation the merge gate requires. Spawn it as a separate `Agent` call, alongside the six and the security pass, for any change with a runtime/production surface — not just schema/migration or flag/infra-config diffs, but any change that ships to production (matching the agent's own wrong-agent tripwire, which returns NOT APPLICABLE for docs-only/comment-only/test-only diffs). It reviews rollback risk, blast radius, deploy-time observability coverage, and migration/rollout safety, none of which the six reviewers or `/security-review` cover. Fold its findings into the same Critical / Important / Suggestion aggregation; a DO NOT SHIP verdict blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not row 6's default report-only suggestions. **The orchestrator cannot downgrade this finding unilaterally.** Its only two moves: (a) fix it — remove the compat path, or (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason. If a fully-unattended envelope cannot tolerate ever hard-stopping here, the human must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never something the orchestrator grants itself mid-run. The why: letting the orchestrator grade an independent reviewer's finding reintroduces the same self-attestation loophole one level up.

**Do not substitute the generic `architect-review` + `debugger` + `ai-engineer` trio here.** That trio is a separate general-purpose adversarial pattern for design stress-tests before a thing is built — it is NOT the PR-review step. The canonical review step is `/pr-review-toolkit:review-pr all` = the six agents above. PR review is a specialised gate requiring knowledge of the codebase's review culture and the PR's own change shape; a generic agent cannot carry that context.

### Phase 5 — Disprove the premise before each fix

Before spawning a "bug fix" agent for any reported regression, use a two-agent split: spawn `subagent_type: coderails:source-auditor` FIRST to disprove-the-premise, THEN `subagent_type: coderails:loop-worker` for the fix. **Do not substitute a generic agent for either half of this split.** A generic agent collapses the split back into one step, so the premise never gets independently disproved and a fix can ship against a bug that doesn't reproduce.

**Disprove-the-premise agent, `subagent_type: coderails:source-auditor`, always first:** this agent's prompt must require:

> Verify the symptom in the source-of-truth FIRST. Slack pin-bar / GitHub PR state / Jira board / browser tabs all cache. Reproduce the bug via API call, prod log, DDB read, or git diff before any code change. If the symptom can't be reproduced via SOT, STOP and report — don't ship a fix to a non-bug.

This is a specific application of `/coderails:cite-check` — the same "re-derive from sources only, no recall, no inference" discipline, applied to one claim: "this bug currently reproduces." The source-auditor returns a sourced PASS / FAIL / UNSUPPORTED verdict. **Spawn the fix agent (`coderails:loop-worker`) only when the auditor returns PASS.** This split prevents fix work on non-existent bugs and keeps premise verification independent of the fixer.

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

Delegate wiki ingest and lint to a spawned agent, `subagent_type: coderails:wiki-writer`, once at the end of the loop, with all related PRs as a cluster — not once per PR. Lint must always pair with ingest — running one without the other leaves the wiki either unverified (ingest with no lint) or unrefreshed (lint with no ingest); treat the two as one step, not two optional ones. **Do not substitute a generic agent for wiki operations.** Wiki authoring requires schema-aware vault ingestion and self-linting against the AGENTS-wiki-schema, which the named `wiki-writer` type carries; the push/PR sequence itself is not part of the type — it must travel in the task brief and repo config, same as for any other agent, so state it explicitly rather than assuming the type name covers it. The wiki vault is an external checkout another session may have open concurrently — Phase 3a's shared-checkout isolation bullet applies to this dispatch too; carry it into the wiki-writer's prompt the same way.

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

Delegate it to a spawned agent, `subagent_type: coderails:docs-auditor`, at the `default` role, same as the wiki-writer agent — both inline-assigned (like Phase 2's; Phase 2.8 routes build tasks only) — to keep orchestrator context clean. **Do not substitute a generic agent for docs auditing.** In-tree documentation has repo-specific structure and conventions; a docs-auditor type knows to check against the actual repo's doc architecture, not generic drift categories.

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

At the end of the loop, before declaring done, the orchestrator audits its own autonomy from the `progress.json` counters and reports raw, unscored facts — no pass/fail scorecard. The human is the only party positioned to judge "should I have been asked about that?"; hand them the raw list rather than have the process pre-grade itself. Report: **`LOOP-STOP` category counts** (HOOK-OWNED — read as-is, never compute or edit), **decisions absorbed** (copied VERBATIM from `progress.json`, never reconstructed from memory), **artifacts produced** (each with its Phase 12 verifying check), **loop cost** (`loop_stall_guard`'s `als_report_cost_on_complete` now prints this mechanically from `retro.json` on every `complete` declaration, with a price-staleness age — the hook is the floor, not a reason to omit it from your own report; it reports what you wrote, so writing `cost` correctly at step 1 is still yours), **disposition violations**, and the **loop-scope eval result** (graded via `post_evals.sh grade-loop`, never hand-written). For the last two, "no record found" is an **audit failure, not a pass**. Per-field detail: [teardown.md](teardown.md).

This is the factory's own audit — raw facts for the human to judge, not a self-issued verdict.

**Teardown write contract — ordered, and it runs BEFORE the `complete` declaration.** The `loop_stall_guard` hook blocks a `complete` declaration when `retro.json` is absent, malformed, or below `schema_version` 1, and separately blocks when any frozen `proof.json` proof is unexecuted-in-transcript or last-failed — so both must be satisfied before the declaration. Run these five steps in order, per the field spec and mechanics in [teardown.md](teardown.md):

1. **If `proof.json` exists, run every one of its `cmd`s VERBATIM as its own single Bash call in THIS (the orchestrator's) session, in the foreground (never `run_in_background`), and confirm each exits 0.** Do this BEFORE assembling the retro — a proof run inside a dispatched worker's session, or launched in the background, never appears (as an outcome) in this transcript and cannot satisfy the gate. If a proof still fails, fix the underlying issue and re-run that proof's `cmd` (not a modified version of it) until it passes, or the `complete` declaration blocks below.
2. **Assemble `retro.json` (`schema_version` 2) beside `progress.json`** — envelope, `loop_stop_counts` and `decisions_absorbed` copied verbatim from `progress.json` (never recomputed or reconstructed from memory), disposition record, evals, artifacts, hook blocks, `models_used`, and `cost`. The schema has **no `verdict` field** — raw and unscored is structural: the retro records what happened, it does not grade it. Mine cost via `dc_mine_token_usage` (fail-open: it never blocks teardown, though a caller-error — no/unresolvable session id — returns a self-describing `{"error":...}` object instead of `{}`; check `.error` before treating the result as an empty mine), and price once — nothing downstream re-prices.
3. **Update `standing-orders.md` (at the repo-key dir).** Match this loop's failure modes against existing entries (match resets `loops_since_recurrence` to 0; new modes append), increment non-matched entries, and MOVE an entry to `standing-orders-decayed.md` at K=5 — a tombstone, **never a delete**. Additive-or-recurrence-only: no metric-based removal anywhere.
4. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
5. **Only then** call `als_mark_complete <cwd> <session_id>` (from `lib/loop_state_common.sh`) to set `progress.json` `status: "complete"` and stamp `completed_marker` together — never a bare write of `status: "complete"`, which leaves `completed_marker` unstamped and false-positives `loop_state_guard` on later turns (see [teardown.md](teardown.md) step 5). Then declare `LOOP-STOP: complete`. First apply `superpowers:verification-before-completion` to the orchestrator's own completion claim, per [finishing-out.md](finishing-out.md). The `loop_stall_guard` proof gate blocks the declaration itself when any proof is unexecuted-in-transcript or last-failed — it does not need a separate manual check here, but the declaration will bounce back with the offending proof id(s) named if step 1 was skipped or incomplete.

## Context-window persistence

Do not stop work early because the context window is filling or a token budget is approaching. Context will compact and the session will continue — treat that as a non-event, not a stop condition. Never artificially truncate a task or declare "done" mid-loop because of token pressure. If a genuine stop condition (see below) is not met, keep going.

**Loop state lives in a durable artifact, not in the conversation.** Maintain a single `progress.json` at the path printed by the loop-state path helper — resolve it by running the helper (Phase -2), never compute it yourself. Overwrite it (never append) at every phase boundary, recording the authorisation envelope verbatim, the `graph` node states, work-unit states, and each phase's absorbed decisions. Field-by-field schema, the stub→enrich→teardown lifecycle, the hook-owned `loop_stop_counts` carry-forward rule, and the concurrency/ownership rules: see [loop-state.md](loop-state.md).

After any compaction, drift, or "wait, where are we" moment, the orchestrator RE-READS `progress.json` — never the conversation — to re-orient. If the user ever has to remind the loop that it's mid-loop, the artifact wasn't being maintained. Git remains the authoritative checkpoint for code (commit all in-progress work before compaction); `progress.json` is the authoritative checkpoint for loop position.

**The guard catches absence, not neglect.** `loop_state_guard` guarantees the file exists and is this session's — not that its content is faithful. Keeping it current is still your job. `retro.json`, `sdd-ledger.md`, and the repo-keyed `standing-orders.md` are durable siblings, not conversation state ([loop-state.md](loop-state.md)).

## Stop conditions for the loop

Stop conditions come in two classes. The agent must not collapse them into one — a gate is not a wall.

**Retry-until-green (not a stop condition — applies BEFORE hard-stop #1 below).** A single failing test, lint error, or verification check is not, by itself, a reason to stop and ask — diagnose, fix, re-verify in a bounded cycle (default 5 distinct attempts) before escalating. Full mechanics, the multiple-independent-failures parallel-dispatch case, and the cause-not-obvious `superpowers:systematic-debugging` case: see [retry-until-green.md](retry-until-green.md).

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
- `awaiting-input` — a planned interaction point inside the loop (the Phase -1 improve-prompt ask, which does NOT occur in a full-autonomous envelope since Phase -1 auto-adopts there; the Phase 1 plan confirmation). Use this sparingly: Phase 13 reports the raw `awaiting-input` count as part of its `LOOP-STOP` breakdown.
- `complete` — all authorised work done. Declaring `complete` is the teardown: also set `progress.json` `status: "complete"` and run Phase 13 in the same turn, or the guards keep treating the loop as active. `retro.json` must exist beside `progress.json` **before** a `complete` declaration — the `loop_stall_guard` hook blocks the declaration when it is absent, malformed, or below `schema_version` 1 (the hook accepts `schema_version >= 1`) — and Phase 13's teardown write contract is what writes it, currently at `schema_version` 2. If a `proof.json` was frozen at Phase 2.7e, the same hook separately blocks the declaration when any of its proofs is unexecuted-in-this-session's-transcript or last-failed — Phase 13's teardown step 1 (run every proof `cmd` verbatim, in the orchestrator's own session) is what clears this before the declaration. If NO `proof.json` was frozen, write `progress.json` at `schema_version` 2 with `proof_disposition` set to `"none: <reason>"` before declaring — at `schema_version` >= 2 the same hook blocks an absent `proof.json` with no recorded disposition (see `loop-state.md`'s Fields table).

The hook checks the declaration is present with a valid category; it cannot check the reason is honest (same boundary as the verify-loop hook). The Phase 13 category counts are the audit on that.

## A note on cadence

The wanted cadence, stated directly rather than as a correction to any particular habit:
- **Before the first tool call of a step**, one sentence stating what you're about to do.
- **While working**, an update only when something important is found or the direction changes — not a running turn-by-turn narration.
- **When finishing**, lead with the outcome: the first sentence answers "what happened" or "what did you find," supporting detail after.

Idle pings from teammates are noise unless the artifact check (Phase 4) confirms a real failure. Don't react to every idle ping with a status update — match the cadence to the user's pull, not the runtime's push.

**Orchestrator responses stay concise.** Keep caveats and disclaimers short, spend the response on the substance, and give a high-level summary unless the user has specifically asked for depth.
