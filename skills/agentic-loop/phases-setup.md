# Agentic loop — setup phases (-2 through 2.7)

Read this file in full at loop start. Use it to start `progress.json` with `graph.py start`, clarify the authorising prompt, and read the envelope. Then delegate pre-flight checks, resolve design and retirement decisions, and record the design in `spec.md` and `plan.md`. See SKILL.md for Phase 2.8 onward.

### `S-2` — Phase -2: Bootstrap a local repo, then start `progress.json`

Use `git rev-parse --show-toplevel` to check if the current directory is in a Git repo.
If it is not, make a local Git base to isolate worktrees:

```bash
git init -b main
git add -A
git commit --allow-empty -m "Initial project"
```

If one command fails, stop and report that command.
For example, Git can refuse the commit if author identity is not configured.
Do not add a remote, make a hosted repo, push, or open a PR.
Do this before the loop file so the path helper uses the Git repo as its key.

Before Phase -1, make the durable loop file with the controller.
This gives the `loop_state_guard` Stop hook a `progress.json` before the first stop.
The hook is a backstop for a skipped `start`.
Do not write or edit `progress.json` by hand.

**Get the path from the helper.**
The helper keys it to the repo's `git --git-common-dir`, or raw cwd if no repo.
A worktree change in the same repo gives the same path.

> `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.py"`

If `${CLAUDE_PLUGIN_ROOT}` is unset, do not guess the path.
Continue without `start`. The `loop_state_guard` hook blocks one time and gives you the path.

Put the authorising prompt verbatim in a file.
Then run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" start "$STATE" --session "$CLAUDE_CODE_SESSION_ID" --loop-id "<unique non-blank id>" --prompt-file "$PROMPT_FILE"`.
It writes schema 3 atomically with `in-progress`, revision 1, and an empty graph.
A second call for the same loop ID does nothing.
For a completed loop it re-arms, keeps `completed_marker`, and drops the completed loop’s `loop_stop_counts`.

If an unfinished loop owns the session, the command refuses with `[reason_code=...]`.
Continue that loop.

For each work unit, run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" add-unit "$STATE" --session "$CLAUDE_CODE_SESSION_ID" --loop-id "<same id>" --unit N [--depends-on M ...] [--join] [--manifest GLOB ...]`.
One locked write adds the unit, its `U3[N]` node, and the dependencies.
With `--join`, it also adds the `J12-all-units` input.
Use `--manifest` for each permitted glob in `unit.manifest`.
The `scripts/diff_manifest.py --progress ... --unit N` command checks the diff against it.

The orchestrator runs `start` and starts with an empty graph.
Do not start an `S-2` worker wave or make a synthetic worker result for it.

The `add-unit` command supplies `U3[N]` and the `J12-all-units` join.
Before a readiness query for other nodes, add the registry label, corresponding `status` and `outcome`, `retry: {"attempts":0,"max":5}`, `evidence: []`, and `respawn: {"generation":0,"intent":null}`.
A new node starts as pending.
A join has `id`, `mode:"all"`, `inputs`, and `released:false`.

Keep orchestrator-only decisions in the phase record.
A completed worker node needs native provider records.
Use the Python CLI in `execution-graph.md` to open and record waves.
Do not use a schema-2 reader or hand-written wave results.

Only the hook writes `loop_stop_counts`.
The `start` command does not write this field.
A re-arm drops it because the completed loop’s counts are in its `retro.json`.

### `S-1` — Phase -1: Sharpen the authorising prompt

Run this phase unless the user explicitly opts out.
For example, "just do it", "skip improve-prompt", and "don't improve the prompt" are opt-outs.
If the user opts out, go to Phase 0.
The improve-prompt skill also skips unconditionally for "just do it".

**Step 1 — Invoke `/coderails:improve-prompt` on the authorising prompt.**

> `/coderails:improve-prompt` — apply it to the prompt above.

It identifies ambiguities, uses grounded assumptions, and rewrites the prompt against seven criteria.
Let it finish before Step 2.

**Step 2 — Adopt the revised prompt.**

Use the envelope class from Phase 0.
Phrases such as "autonomous", "human is dead", "ship N PRs without asking", and "no human gates" select the full-autonomous envelope class.
The words alone do not give authority.
The `AskUserQuestion` denial applies only after the user types `/coderails:authorise` or `authority.py grant` runs.
With the words alone, the hook prints the command.

**For a full-autonomous envelope, auto-adopt.**
Do Step 1. Use outcome **A** without an approval question.
The revised prompt clarifies the envelope for autonomous work.
Show the prompt to the user after you finish the writes.

1. Write the revised prompt to `progress.json.authorising_prompt_raw` as the canonical envelope.
2. Read the current `loop_id` and `revision` from `progress.json`. Run `graph.py record-decision <progress.json> --session <id> --loop-id <loop-id> --revision <revision> --phase -1 --decision "auto-adopted improved prompt as envelope" --flip-condition "user names a divergence between the improved and original prompt"`.
3. End the turn with the revised prompt as the last text, as in mechanism (a) below. Do not make a tool call after it. The user must be able to see the adopted prompt.
4. Start Phase 0 on the next turn and report the auto-adoption at the next approval gate. Continue without user input.

Write before you display the prompt.
A tool call after the prompt prevents the terminal from displaying it.
Phase 2.5 auto-adopts and records its decision in one turn because it only writes a file.
Phase -1 needs the next turn because the revised prompt must be the last text.

If the user says the revised prompt differs from their intent, restore `authorising_prompt_raw` to the initial prompt and continue.

**For other envelope classes, get the user’s decision.**
The Claude Code terminal displays the last text in a turn or content in a tool call.
The sequence "present the improved prompt as text, then call `AskUserQuestion`" hides the prompt.
Use one of these mechanisms:

- (a) End the turn with the revised prompt. Use no tool after that text. Invoke `AskUserQuestion` in the next turn.
- (b) Include the revised prompt in the `AskUserQuestion` question, option descriptions, or option preview fields.

Use (a) or (b), then give the three options with `AskUserQuestion`:

```text
Here's the improved prompt. How do you want to proceed?
A) Proceed with the improved prompt as the authorising envelope
B) Tweak it — tell me what to adjust and I will revise
C) Use the initial prompt as-is
```

For **A**, use the revised prompt as the envelope.
For **B**, apply the user’s changes, show the prompt through (a) or (b), and ask again.
Limit this to two revisions. If a third is necessary, report the problem with the envelope.
For **C**, keep the initial prompt.

For **A** and **B**, update `progress.json.authorising_prompt_raw` with the adopted prompt.
For **C**, keep the value `graph.py start` wrote in Phase -2.
Phase 0 quotes the adopted envelope verbatim in its `<thinking>` block.

### `S0` — Phase 0: Read the authorisation envelope

Before other work, identify the authority the user gave.
Read the standing envelope one time at loop start and use it for the loop.

Before the first response in a loop with user authority, use this `<thinking>` block:

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

Then give your response.

**Envelope examples:**

- "Ship N PRs without asking" gives full-autonomous. It includes deploys, cleanup after deploy, and follow-up tickets for the same theme. A merge needs live authority, an owner-signed receipt, and an available slot in `max_prs`. Use `authority.py grant --max-prs N` and `action_receipt_cli.py approve-action`. The envelope class grants no authority or receipt. Without authority, or with `max_prs` 0, prepare the PR and tell the owner to mint a receipt.
- "Fix this bug" gives narrow-fix. Check scope before changing nearby files.
- "Autonomous / human is dead" gives full-autonomous. Do the usual steps without pauses. Stop on a verification error, an irreversible or destructive step, or a refusal to merge or push to `main`. The authority and receipt codes include `authority_denied`, `max_prs_exceeded`, and `no_receipt`.
- "Help me debug" gives diagnostic-only. Do not write code without explicit permission.

Use the envelope class to identify when to get confirmation.
Do not stop for "do you want me to..." if the envelope gives authority for the step.

### `S0.4` — Phase 0.4: Surface the orchestrator's model cost to the user at loop launch

**Token-burn rule (row 1 of 3).** Only the user can change the orchestrator's model with `/model`. At launch, tell the user that this model bills each turn of the loop and that they can change it with `/model`. Give this notice one time during Phase 0 before the Phase 1 plan. Continue without a reply.

Phase 2.8 assigns worker models. See [model-routing.md](model-routing.md) for how the cost grows.

### `S0.5` — Phase 0.5: Orchestrator operating rules (the conductor obeys its own rules)

Use the same reporting rules for the orchestrator and workers. The confidence-label and verify-loop hooks can give advice through `additionalContext` on Stop or SubagentStop. Correct the issue on the next turn. Without a stop row, the `loop_stall_guard` hook can block.

- Apply `(verified)`, `(inferred)`, or `(guess)` to each substantive status claim as in Phase 11.
- Tag each `## Did Not Verify` bullet you cannot check in the same turn as the bullet. Use `(unverifiable: <reason>)`.
- Run the Phase 12 check before you claim a merge, live deploy, or other artifact in that turn.
- Before an active loop stops, run `graph.py stop --category <hard-stop|approval-gate|awaiting-input|complete> --reason-code <code> --reason "<why>" <state> --session <id>`. Record it in the same turn. The Stop hook requires the row and blocks with `stop_row_missing` without it.

Give the confidence labels and Did-Not-Verify content before the last line: `LOOP-STOP: <category> — <reason>`. The last line is for the user. The hook reads the row. Give the three parts together for the audit.

For `complete`, follow the Phase 13 teardown to set `progress.json` `status: "complete"`. The `loop_stall_guard` hook increments the matching category in `loop_stop_counts` when it consumes the row. Do not write or calculate the counts.

### `S1` — Phase 1: State the plan in bullets, ask once

Before you start an agent, give a short plan in bullets. Name the phases and their agents, what runs in parallel or in sequence, and when work stops. The user can redirect the plan.

Use one confirmation question: "Want me to execute this?" or "Confirm scope and I'll execute." If the user approves, continue through the envelope without more confirmation. If the user refuses, revise the plan one time and give the question again. Do not negotiate more than two times. If a third is necessary, report the problem with the envelope.

Select the loop harness from the Phase 0 envelope, such as `/coderails:agentic-loop`, a flat loop, or a goal runner. Do this one time when you read the envelope. Do not send "which approach do you want?" in Phase 1.

### `S2` — Phase 2: Pre-flight checks via spawned agents, not main context

Delegate the pre-planning skills: `/coderails:planning-sequence`, `/coderails:premortem`, `/coderails:assumptions`, `/coderails:notchecked`, and `/coderails:wiki-query`.

Start one agent with `subagent_type: coderails:preflight-scout`. The role uses guard checks. The gate refuses `general-purpose` with `role_mismatch`. Paste the `begin-wave` envelope and sections first. Then include:

- The Phase 1 plan.
- An instruction to invoke each applicable skill with the `Skill` tool.
- An instruction to give one report with planning results, premortem problems, assumptions, and wiki results.

Use the `default` role here, before Phase 2.8. This controls cost for work that runs skills and makes no architecture decisions. The guarded scout must check the actual code for risks. Do not use a generic agent.

Include `/coderails:wiki-query` for the full plan theme. For example, use "What does the wiki cover about [overall theme of the agentic loop]? Identify cross-PR constraints, gaps, superseded decisions, and anything the plan assumes but isn't enforced in code." This supplies the wiki read from Phase 2 of `/coderails:workflow` for the full loop. See Phase 9 for the rule that skips individual PR wiki steps.

**Read the retros.** Read the `standing-orders.md` view or run `lessons.py query` at the repo-key directory. Use `dirname` of `dirname` of the path from `hooks/scripts/lib/agentic_loop_path.py`. Read the last N=5 `retro.json` files at `<repo-key-dir>/*/retro.json` by mtime. Give observed problems for the premortem and a "carry into worker prompts" list of applicable lessons.

You can add cautions, assertions, and premortem entries. Do not relax a gate, skip a phase, or pre-justify an eval change. Only the user can change gates. If there are no retros or overlay for the first loop, skip this read without an error.

**Check the contract of a shared primitive.** If the plan nests calls, recurses, uses parallel in-process calls, or re-enters from the same caller, read the primitive's source. This applies to locks, queues, transactions, and other shared primitives. Record if it throws an error or gives a Boolean. Record reentrancy and PK collision behavior, owner identity, expiry, and steal logic.

A previous plan said to "wrap both sites with a DistributedLock". Its `attribute_not_exists(PK)` semantics prevented reentrancy, and the calls were nested. The source showed the defect.

**Check the base before starting workers.** The orchestrator checks if `origin` is available. If so, run `git fetch origin`, then `git log --oneline origin/main..main` and `git status --short`. Use `origin/main` as the base ref. Without `origin`, run `git log --oneline main..HEAD` and `git status --short`. Use `main` as the base ref.

The checkout is dirty if the current branch has commits missing from the base, or files that are uncommitted or untracked. Check it regardless of how it looks. If it is dirty:

- Do not let a worker branch from the current checkout. Use `superpowers:using-git-worktrees`. Give the selected ref by name in the worker prompt: `origin/main` with `origin`, or `main` without it. Do not use HEAD. Use the skill's declared-base-ref, native-tool, ignore, and directory checks.
- List other work as "these are not yours — never stage, commit, or include them". Name the files in the worker prompt.

### `S2.5` — Phase 2.5: Resolve design forks before execution, not during it

`S2.5` and `S2.6` are siblings after `S2`.
If the two conditions apply, start the scouts in one wave.
Their results go to `J2`.
The orchestrator checks the two results and writes the loop data in one step before it releases `S2.7a`.

If the plan has an open decision about the primitive, topology, or design shape, resolve it before Phase 3.
Start one guarded `subagent_type: coderails:design-scout`.
Paste its `begin-wave` envelope and sections first.
Use the Phase 2.8 table to set the role here.
Use `default` for a bounded decision between known designs.
Use `frontier` from the start for a genuinely ambiguous investigation, as in "Investigations get frontier FIRST".

Include the design-scout instructions in the prompt and use an available native role. Tell the scout to:

- Read the actual code paths that each design changes.
- Compare viable designs against the constraints each one has.
- Recommend one design. Name the alternatives and why they did not win. Give the one fact that can change the recommendation.
- Apply the design checks in `/superpowers:brainstorming` without its approval gates. Compare the designs. Remove speculative work (YAGNI). Prefer small units that you can test independently (design-for-isolation).

Check the scout’s code reads and tradeoffs. A role label alone does not show that the scout did it.

**Stop on scout spawn refusal.** If the design scout or a reviewer cannot start, do not use an orchestrator or worker read as the scout.
If capacity or a stale scout ID prevents the call, retry with a new `Agent` call. Claude has no `task_name` binding.
If the call is refused again, record the node as `failed` with `graph.py record-wave`.

If no scout can do the check independently, stop the loop and wait for the user.
A `non_independent` fallback needs explicit user approval.

After you record the refused scout call, send the owner this question verbatim:
`Coderails: Approve a non-independent design-scout fallback for loop <loop_id>, node S2.5, attempt <next_attempt>? Reply approve or deny.`
Replace the two placeholders with the current values. The next direct user reply must be `approve`.
The native record command checks the two transcript messages. It refuses a missing or different reply.

Only after that reply, record `S2.5` as `skipped` with an `evidence` prefix of `non_independent: human approved`.
Run `graph.py record-decision` with that phase and decision text.
Read the current loop ID and revision and give `--loop-id` and `--revision`.
A `non_independent` read cannot count as a check by a different agent or as `done`.

If there is no design fork, record `no_design_fork: <reason>` before a scout call.
If no path retires, use `no_retired_path: <reason>` for the sibling.
The skip records let `J2` release.

**Agent limit.** Each agent thread uses a slot until the provider closes it. This includes completed and idle threads.
Before you start a scout, close completed threads with the provider's close tool where one exists.
If the tool cannot free a slot, report that limit and stop.

Use the envelope class from Phase 0:

- **Full-autonomous ("autonomous / ship N PRs without asking").** Auto-adopt the recommendation. Read the loop ID and revision. Run `graph.py record-decision` with `--loop-id`, `--revision`, and phase `2.5`. Give the design as `--decision` and its flip condition as `--flip-condition`. Report it at the next approval gate. Continue without waiting for sign-off, as in Phase 0.
- **Narrow-fix, diagnostic, or ambiguous.** Give one decision: "here's the shape, here's why, approve or redirect". Limit the discussion as in Phase 1, then go to Phase 3.

Use one design artifact to resolve the fork before build work.
Write a wiki-bound artifact to the vault in `config.wiki_path`.
For other design or recon files, use a temporary directory that is not in the repo’s working tree.
Do not write those files to local `main`, where an untracked file can change a worker’s base.
Move a PR deliverable into its worktree only in Phase 3.
Keep recon and design read-only for the code repo.

### `S2.6` — Phase 2.6: Resolve disposition before replacement work (clean-break vs preserve-compat)

If a unit retires a named function, module, endpoint, schema, or flag, decide how to retire it one time before the first worker.
Use `subagent_type: coderails:disposition-scout` as the guarded sibling of `S2.5`.
Give it the Phase 1 plan and named paths.
It gives one result for each retirement unit and does not write loop data.
If no path retires, record the skip and let `J2` release without this branch.

Use this check only if a named path goes out of use.
A call to a previous path or a wrapper for it does not retire it.
Use "what named thing does this remove?" as the test. "is this a migration?" is too broad.

Use one of these decisions:

- **`clean-break`.** Remove the previous path in the same unit. Keep no shim, bridge, adapter, or compatibility flag.
- **`preserve-compat`.** Keep the path behind a shim only for a named consumer that cannot migrate in this unit. "safer", "less risky", and "to avoid breakage" do not name a consumer. Name the consumer or use `clean-break`.

Recommend `clean-break` by default.
A model can keep a previous path because removing it feels destructive.
This can double migration work.
The named blocker keeps that decision in view for Phase 13.

Use the envelope class from Phase 0:

- **Full-autonomous.** Use `clean-break` by default. Record it and continue. If you select `preserve-compat`, report the named blocker at the next approval gate. Do not wait for sign-off.
- **Narrow-fix, diagnostic, or ambiguous.** Give one decision: "clean-break recommended, here's why". Limit discussion as in Phase 1.

Record each unit with `graph.py add-unit ... --disposition clean-break` or `--disposition preserve-compat --named-blocker <consumer> --removal-ticket <ticket>`.
The CLI refuses an unfinished preserve-compat record.
The `graph.py disposition-audit` command checks it again.

Read the current loop ID and revision.
Use `graph.py record-decision` with `--loop-id`, `--revision`, phase `2.6`, the decision, and `--unit`.
It appends one hash-chained row.
Do not write to `decisions_absorbed` by hand.

### `S2.7` — Phase 2.7: Commit the resolved design to durable `spec.md` and `plan.md`

The command `python3 scripts/gen_graph_docs.py` reads the thresholds from `packages/graph-semantics/policy.yaml`. Edit the policy to change the table.

<!-- START GENERATED graph-spec:thresholds -->
| Policy key | Value | Meaning |
|---|---|---|
| `design_doc_min_units` | `3` | Run `S2.7a` and `S2.7b` if the loop has this number of units or more, or if units depend on each other. Phase 3 uses the same conditions to select one agent or a team. |
| `loop_evals_min_units` | `1` | Run the `S2.7c` loop evals if the loop has this number of work units or more. `loop_dispatch_guard` and `loop_state_guard` use a fixed minimum of 1. No hook reads this key. |
| `retry_max` | `5` | Default limit for retries for one node. The graph core sets a maximum of 5. |
| `repair_attempts_max` | `5` | Limit for different repairs to try for each problem in `U5-repair[i]`. |
| `graph.profile` | `full` | `graph.py instantiate` uses this value if you do not specify `--profile`. `units-only` includes `U3[i]` and `J12-all-units`. `full` includes all nodes and joins in the table. Each guard has its own condition. |
<!-- END GENERATED graph-spec:thresholds -->

Run **2.7a and 2.7b** only if the loop has `design_doc_min_units` units or more, or a cross-unit dependency. Phase 3 uses the same threshold for a team. For 1–2 units with one agent, the envelope, `progress.json`, and the full task prompt carry the design. Skip 2.7a and 2.7b below the threshold.

Run **2.7c** if the unit count or an irreversible surface triggers it. Run **2.7e** for a loop with an executable surface. These conditions apply if the loop skips 2.7a and 2.7b too.

For 2.7a and 2.7b, first release `J2` with the Phase 2.5 and 2.6 results. Check the two results and update the graph in one write. Record a skipped branch as skipped. Then run 2.7a followed by 2.7b. Run 2.7c, 2.7d, and 2.7e in the same wave if their inputs allow it.

**2.7a — Write `spec.md`.** Write it next to `progress.json` in the loop directory that `hooks/scripts/lib/agentic_loop_path.py` prints in Phase -2. This directory is external to the code repo. Do not commit the file. Record the design from Phases 2.5 and 2.6. Include:

- The authorisation envelope verbatim (Phase 0).
- The design decision and its flip condition (Phase 2.5).
- Each retirement decision and its named blocker, if applicable (Phase 2.6).
- The success criteria for "done" for the loop.
- The boundaries of each work unit. Phase 2.7b gives the task steps.

The file belongs to this orchestrator’s run, like `progress.json`. Use `/coderails:handoff` if the user needs to continue the work.

**2.7b — Write `plan.md` with `/superpowers:writing-plans`.** Write the plan next to `spec.md` and `progress.json` in the loop directory. Do not commit it. Invoke the skill explicitly, as Phase 3 or 3a invokes `/superpowers:test-driven-development`.

Use `plan.md` as the fixed source for how to divide the work. Use `progress.json` for the current position.

- In Phase 3, make the task list with `TaskCreate` and `TaskUpdate` from `plan.md`. Use the same tasks for the worker descriptions in Phases 3 and 3a. Do not derive them again from the conversation.
- After compaction, read `plan.md` for scope and `progress.json` for position.

**2.7c — Freeze the loop evals with `/coderails:task-evals`.** Use scope `loop`. Make a frozen `evals.json` that defines the success conditions at loop end. Run it for `work_units >= 1`, the unit floor for verification_level-2 eligibility. Run it for an irreversible surface regardless of count. Examples are publish, deploy, migration, data deletion, or external send.

Run 2.7c for 1–2 units if the design steps do not apply. Do not wait for "reaching Phase 2.7" through the design-doc steps. Without 2.7c, `loop_dispatch_guard` blocks the first graph-bound implementation call. Keep this file next to `progress.json`, `spec.md`, and `plan.md` in the loop directory. Apply the "never committed, outside the repo" rule. At loop end, use `post_evals.py grade-loop` as in Phase 13.

For dispatch, `loop_dispatch_guard` checks the frozen but ungraded file for loops with one or more work units. It checks all native worker roles. The file must belong to this session and loop. It must have a non-blank `verification_justification` and one or more P0 entries in an array `.evals`.

At freeze, each P0 is `pending` with empty `evidence`. This can open dispatch. Do not run `grade-loop` before build. The `validate_structure` check 5 refuses a pending suite. For `complete`, Phase 13, `loop_state_guard`, and `loop_stall_guard` need a grader’s verdict of `GO` or a graded verification_level-0 exemption. The eval author derives the goal from `authorising_prompt_raw` in `progress.json` as specified by `task-evals`.

**2.7d — Freeze PR evals for each work unit in the same invocation.** For each unit with a PR, make a frozen `evals.json` at scope `pr`. This file differs from the loop-scope file in 2.7c. The `scripts/merge.py` gate checks each merge for a SHA-bound PR eval comment with `result=GO`. It blocks without that comment and has no config opt-out. Loop evals alone let Phases 3 and 4b start but cannot clear the merge gate.

Copy the PR eval pointer verbatim into the worker prompt, as for the "Disposition — ... copied **verbatim** into the task description" rule. Do not keep it only in `progress.json` or `plan.md`.

Freeze the PR suite before build as required by `task-evals` rule 1. A suite written at merge time cannot meet that rule because the author knows the implementation. If you missed the freeze, write the suite and set `frozen_at` to the actual time of writing. Do not backdate it. Disclose the late freeze in `verification_justification` and Phase 13.

Use a negative control that ran or a run that found a defect. The grade `GO` comes from a test that distinguishes correct and incorrect results. Disclose that the freeze came after build. Do not use it as permission to skip the freeze.

In loop 0d3fb487 on 2026-07-16, a sentence at the end of "loop-scope" did not specify the PR freeze, timing, or merge gate. Task 1 froze the loop evals before build. The loop did not freeze the PR evals. The loop found this only when `merge.py` refused. At that point the work was built, the other merge checks were clear, and it had run live.

**2.7e — Freeze `proof.json` with a different author.** For each loop with an executable surface, start a different `subagent_type: general-purpose` agent with the instructions from `agents/proof-author.md`. Give it `authorising_prompt_raw`, `session_id`, and `loop_id` verbatim as explicit inputs. Do not give it access to read `progress.json`. Give only the pre-implementation docs that the prompt itself cites. Do not give it the plan, spec, design decisions, or conversation.

At Phase 2.7c, the orchestrator has read the plan. This uses the `task-evals` rule for a grader that works independently and also applies it to the author. A role label does not show which inputs the agent got. Put the proof-author instructions and only the permitted inputs in the native worker prompt.

The agent writes `proof.json` next to `progress.json` and `evals.json` in the loop directory. Do not commit it. Use schema `{"schema_version":2,"session_id","loop_id","frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`.

Each `cmd` is a self-contained shell command. The controller runs it unchanged through `proof.py run` in a private copy of committed `HEAD`. The controller refuses a committed tree with a symlink. Use relative paths for repo files. The proof cannot read the initial checkout. It can read other host files, write only in its new `TMPDIR`, and use no network.

Put temporary files in `TMPDIR`. Do not use command substitution in gated script invocation lines. Do not use destructive patterns. Apply this to each loop with an executable surface, regardless of the design threshold.

For a loop with no executable surface, do not write `proof.json`. First use `record-decision` to record why in `decisions_absorbed`. Get the current revision from `inspect`. Then run:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/agentic-loop/scripts/graph.py" \
  record-proof-disposition "$STATE" --session "$SESSION" \
  --loop-id "$LOOP" --revision "$REVISION" \
  --disposition none --reason "no executable surface"
```

The command saves `none: no executable surface` with the graph lock held. It refuses a different owner, stale revision, active wave, proof file on disk, or duplicate decision. With no `proof.json`, `loop_stall_guard` checks the saved no-proof explanation.

Use the schema 2 `expect` object `{"exit_code":0,"stdout_contains":[...],"stdout_not_contains":[...]}` and optional `timeout_s`. The `proof.py freeze` command refuses schema 1. Write `"pending"` in `status`. The controller does not read that field.

At teardown Step 1, run `python3 scripts/lib/proof.py freeze <state-dir>`, then `run <state-dir> --all`. The `loop_stall_guard` hook’s `loop_proofs.validate_proofs` and the Codex `graph_artifacts` gate read only `proof_results.jsonl`. See [loop-state.md](loop-state.md) for the field contract and limits.
