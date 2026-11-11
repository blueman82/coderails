---
name: agentic-loop
description: 'Multi-agent orchestration discipline — keeps the main context a pure orchestrator that never implements. Load IMMEDIATELY, over /workflow, /prep, /push and any other single-PR command, whenever the user authorises agent-driven work: "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "autonomous", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or 3+ PRs authorised in one instruction. ALSO load for autonomous merge + deploy + verify chains, even a single PR, if per-step confirmation is waived. NOT /workflow (single-PR prep → push → merge → wiki); it sits ABOVE /workflow and uses it as a subroutine. Fire aggressively — forgetting to delegate is costly in long sessions.'
effort: high
---

# Agentic Loop

Run a multi-agent or multi-PR session with authority from the user without a new user instruction on each turn.

## Why this skill exists

In a long session, the assistant can depart from the agreed workflow. It can run skills itself when it must delegate. It can wait for approval to start a worker when it has authority. It can pause at a gate the user removed. It can mistake an "idle" notice for a fault when the agent finished without a report. It can delegate a correction before it checks the reported symptom.

A needless stop makes the user send a new prompt and reduces the autonomy they gave the session.

Read [learned-failure-modes.md](learned-failure-modes.md) with this skill. The `loop-retro-promotion` pipeline keeps lessons from prior loop retros in that file.

**Write instructions the reader can do.** Before you write an instruction, check that the reader can use the necessary tool call, command, or file write. Check that the condition can have each of the results the instruction describes. A reader can skip a step they cannot do. They can also report that it succeeded without doing it.

One loop on 2026-07-29 found three examples in this skill and `superpowers:finishing-a-development-branch`. First, a cwd-equality test gave each side the same source. It also used a Bash subshell PID without the harness session PID. The two branches could not operate as designed.

Second, a squash-merge safety check required `git log --oneline origin/main..HEAD` to be empty. A squash changes the commit SHAs and prevents that result. PR #317 corrected these two defects. Third, Phase 0.4 told the orchestrator to set its own model with `/model`. The orchestrator cannot invoke that command.

## The phases

The numbered phases run from −2 through 13 and include lettered sub-phases. Use these five groups.

| Group | Phases |
|---|---|
| Setup | -2, -1, 0, 0.4, 0.5 |
| Pre-flight | 1, 2, 2.5, 2.6, 2.7, 2.8 |
| Build | 3, 3a, 4 |
| PR Checks & Ship | 4b, 5, 6, 7&8 |
| Wrap-up | 9, 10, 11, 12, 13 |

The phases are a dependency graph. Run a node only if its prerequisites and readiness predicate are satisfied.

### Execution graph — stable contract

**Read [execution-graph.md](execution-graph.md) in full before starting a node.** It gives the full node table with prerequisites, readiness predicates, and skip conditions. It also gives the ASCII diagram and how to use `graph_readiness.py`. Use this read-only query before you start each node.

Use the IDs in the table. An `S*` node runs one time. A `U<i>*` node runs one time for each work unit. The `J*` and `G*` IDs identify joins and cross-cutting checks.

### Phases -2 through 2.7 — setup, before any delegation

Run `graph.py start`, then run `graph.py add-unit` for each unit. Give `--worktree ABSOLUTE_PATH` for each unit's checkout before graph-bound PR publication. Clarify the authorising prompt and read the envelope. Delegate pre-flight checks. Resolve design decisions and decide how to retire code. Record the design in `spec.md` and `plan.md`.

Before each `graph.py record-decision` call, read the current `loop_id` and `revision` from `progress.json`. Use them as `--loop-id` and `--revision`. The CLI refuses a stale caller.

**Read [phases-setup.md](phases-setup.md) in full at loop start.** Run these phases one time before Phase 2.8. Resolve the design before you start build work.

### Phase 2.8 — Route: assign a model role per task

Before starting workers, give each Phase 3 or 3a build task a **model role**. This also applies to a loop with 1–2 units that skips Phase 2.7. Set the roles one time and record them. Use the recorded roles for each worker start.

Roles describe the functions a model must supply for the task. They do not identify a model by name. When a new model changes the mapping, update only this table.

| Role | Currently | Use for |
|---|---|---|
| `fast-mechanical` | haiku | Mechanical tasks with a fixed recipe and scripted steps. Short reads for orchestrator checks. |
| `default` | sonnet | TDD, mechanical work, or changes to multiple files. Use when uncertain to control cost. |
| `frontier` | opus at `xhigh` (fable escalation — see [model-routing.md](model-routing.md)) | UI or architecture work that needs judgment. Genuinely ambiguous investigations. |

**Read [model-routing.md](model-routing.md) in full before writing a `Model:` stamp.** The `frontier` role resolves to opus. Do not escalate to fable automatically. Name the function that justifies an escalation. Include `effort` in the stamp and tune it before escalating the model. Follow the investigation and fallback rules in that file.

Run `graph.py record-decision` one time for all tasks. Write one `decisions_absorbed` entry: `{phase: "2.8", decision: "<task id: role, ...>"}`. Do this for a loop with fewer than 3 units, with or without Phase 2.7.

### Phase 3 — Delegate all implementation to routed workers; spawn a team when work has ≥3 sequential units or dependency chains

Get the "3+" team threshold from `design_doc_min_units` in the generated `S2.7` block of `phases-setup.md`. Its policy source is `packages/graph-semantics/policy.yaml`.

**Delegate implementation to workers.** The orchestrator plans, delegates, and checks results. A worker does each implementation unit, such as one file edit or a short sequence of changes. Use the role from Phase 2.8, or `default` if Phase 2.8 gives no other role.

This keeps the orchestrator context small and controls cost. A long session can fill the context, and `default` costs less than `frontier`. Use a `frontier` worker or make a direct edit in orchestrator context only with a justification. Use the worker rules below for "delegate vs. do it yourself".

1. **Single worker.** For self-contained work with 1–2 units, start one `Agent` with `subagent_type: general-purpose` at the Phase 2.8 role. The worker implements and checks its own artifact. Include the Phase 3a instructions in its prompt.
2. **Team.** For 3 or more PRs or a dependency between steps, start workers with the native `Agent` tool and `subagent_type: general-purpose`. Use `TaskCreate` and `TaskUpdate` to make a task list with explicit `blockedBy` dependencies. Share updates with `SendMessage`. For a "sequential PR loop", start the agents and make the shared task list so the user can see the team. To record results in the graph, use unnamed native Agent calls. The gate refuses mailbox-only teammate reports.

The orchestrator can plan, read `git status` and `gh pr view`, read logs, and do Phase 12 artifact checks. If you use `Edit`, `Write`, or `MultiEdit` for implementation during a loop the user approved, stop and delegate it.

**Use the orchestrator’s write calls for loop records (token-burn rule, row 3 of 3).** Use `Write` and `Edit` for loop files such as `progress.json`, `spec.md`, `plan.md`, and `retro.json`. Workers write deliverables such as code, docs, config, and other PR files. Use the Phase 11 confidence labels. Tell workers to give a short claim and the command that checked it. Long reports fill the orchestrator context.

If the user explicitly asks for a spawned team, start named teammates. Do this if a sequence of solo `Agent` calls can also do the work.

**Sandboxed implementation workers (`config.sandbox_workers`, on by default).** Before starting the worker or team members, run `python3 scripts/sandbox/containment.py <worktree>`. It prints `{"mode": ..., "reason_code": ...}` and adds a log row for the decision. Use the reported `mode`:

- `sandboxed`. Start each worker in its own OS sandbox with `python3 scripts/sandbox/spawn_sandboxed_worker.py <worktree> <prompt_file> <model>`. The worktree must be on its feature branch. Do not use `main` or `master`. Start `prompt_file` with the `CODERAILS_GRAPH_DISPATCH=<JSON>` envelope for the U3 node. Then include the full Phase 3a worker prompt and all its instructions.
- `fallback` (`sandbox_unavailable` or `worker_credential_missing`). Stop implementation dispatch and report the missing prerequisite. Do not use an in-process worker.
- `off`. Use the in-process `Agent` procedure.

In `sandboxed` mode, `worker_containment_gate.py` refuses in-process U3 starts for high-risk units unless the owner minted a `worker_fallback` receipt. The refusal is `containment_ack_required` and applies to all native roles. Declare each unit's `manifest`. The rule covers units without a manifest and units that touch `hooks/`, `scripts/`, `agents/`, `capabilities/`, `.claude-plugin/`, or config schemas.

The script takes a MODEL parameter and has no agent-type parameter. Native role labels are optional for in-process `Agent` calls. Use the in-process path for orchestration reads. Only implementation units use the sandbox.

The launcher clones the worktree to a scratch directory for the worker. It sets an isolated HOME and an allowlisted environment. The worker inherits no GitHub token and has no GitHub network egress. After the worker exits successfully, the launcher checks each commit against the manifest and scans new Git objects for known secrets.

The launcher imports only the worker’s branch with a fast-forward merge. If the worker moves a different branch, such as `main`, the launcher imports nothing and reports `branch_import_refused`. The launcher pushes the branch without the worker sandbox. The orchestrator opens the PR from that branch.

The worker must commit on its branch. It must not run `git push`, switch branches, or make branches. The worker cannot use `SendMessage` or the task list. Use the pushed branch and PR status to check the result, as in Phase 3a.

Apply Phase 4 for a nonzero launch result, a non-Git worktree, a missing prompt or credential, or a refused import. Check the artifact before you retry, as for an idle or unsuccessful `Agent` call. The orchestrator does GitHub API work without the worker sandbox. The worker uses its prompt for context.

This safeguard depends on agent cooperation. The sandbox permits reads from the user's HOME and access to api.anthropic.com. It does not contain the launcher or the orchestrator. Codex workers use their own `sandbox_mode`.

**Give each worker a full prompt.** Include the Phase 3a role verbatim, construction method, checks, manifest, pre-push assertion, retirement decision, lessons, terminal artifact, report rules, and hook rules. A task list does not supply instructions missing from the prompt. Also include:

- Worktree path and branch name
- JIRA ticket
- Results from earlier tasks, such as deployed version, test counts, and connected components
- Step-by-step instructions

Include this line in each agent prompt:
> "Don't go silently idle — send a completion message via SendMessage. Past agents have failed this way."

**Native worker contract.** Claude uses its native `Agent` tool. The `begin-wave` command saves a closed contract for each node and `plan` prints its `prompt_prefix` and `prompt_sections`. Copy the two fields verbatim at the top of the prompt. The contract checks the role against `subagent_type`.

The Bash capability-only roles (preflight-scout, design-scout, disposition-scout, source-auditor, deploy-safety-reviewer) must use `coderails:<role>`. For other roles, use `coderails:<role>` or `general-purpose`. Other values give `role_mismatch`. If the plugin agent is unavailable, the gate refuses to start a guarded scout. Do not downgrade the role.

Before starting an implementation worker, read `${CLAUDE_PLUGIN_ROOT}/agents/loop-worker.md`. Put its instruction body after the two contract fields. Then give the task and current user restrictions. Include scoped work, test-first for testable changes, actual check results, self-checks, and accurate reporting. Do not infer these rules from a worker name. User limits on commits, remote writes, and test scope override the template.

The envelope gives the single-use `dispatch_id`. A second use gives `dispatch_replayed`. The provider tool-use and result identity and task notification identify the worker. The `add-unit` command takes `--model-role fast-mechanical|default|frontier`, `--write-scope`, `--lesson`, and `--scope`. These values go in the contract. The default write scope is the manifest.

The sandboxed Bash launcher has no agent type. The role check does not apply to it. Keep the native `subagent_type` in the records and check it against the initial dispatch. A `name` is only a native label. The graph cannot accept a result supplied only by mailbox.

The `loop_dispatch_guard.py` hook requires the session-owned graph data, the active wave, and frozen evals for all native roles. Frozen dispatch evals bind session_id and loop_id only. The envelope binds the active graph revision, wave, and node. The end of the loop needs neutral grading for the last revision. If the gate refuses the call, correct the graph data, envelope, or evals. Do not change roles to bypass a refusal.

### Phase 3a — Single routed agent for impl + verify (the spawned-team-is-overkill case)

For self-contained work, start one `Agent` with `subagent_type: general-purpose` at the Phase 2.8 role. For example, use one worker for a bug fix, one PR, a file edit, or a short sequence with shared context. The worker implements, checks, and reports with confidence labels. The orchestrator stays in its role.

A single worker keeps dense verification output out of orchestrator context. The worker runs its own checks. The orchestrator checks artifacts at Phase 12 dependency boundaries, or when a high-stakes check is inexpensive.

The worker has no conversation context. Include these items in its prompt:

- **Phase 2.8 role.** Copy the role and fallback rule verbatim from the `Model:` stamp in the `superpowers:writing-plans` plan. If the loop has no plan, copy the Phase 2.8 decision. The worker uses the prompt for the role, as for retirement decisions and lessons. Use `default` as the minimum. Give a justification for `frontier`.
- **Change.** Name the files, changes, and testable success criteria.
- **Construction method for code.** If the change adds or changes a testable function, method, or branch, use `/superpowers:test-driven-development`. Write the test first. Check that it gives the expected error. Write the minimum code to make it succeed, then refactor. Apply this to PRs with code and other files. For docs, config, or prose with no testable code, check by inspection. See `/superpowers:subagent-driven-development` for the implementer and reviewer templates and their per-task cycle.
- **Construction checks.** Use `superpowers:verification-before-completion` during implementation and reporting. Before you say a step is complete, run its check. Do not say "should work now" as a result. Also follow the report rules below.
- **Checks before reporting.** Give the worker a check to run. For example, use a test, lint, build, diff, endpoint, or log. "Implement X, then verify by running `Y`, and only report success if `Y` passes."
- **Report.** Use the Phase 11 confidence labels. Give the command and result that show the claim is correct, not only "verified". Include "don't go silently idle — send a completion message". Workers can go idle without reports regardless of role.

If a worker must pause for a human, it supplies a typed status and no `{outcome, evidence}` result. Use `NEEDS_DECISION`, `OUTSIDE_SCOPE`, or `IRREVERSIBLE_ACTION` from `scripts/worker_status.py`. Only the orchestrator talks to the human. The `graph.py record-wave` command checks the status and refuses the full report atomically with `worker_status_<code>` if malformed.

The command saves the status in `worker_statuses` and counts it as an unsuccessful try. Below the schema cap, it extends the terminal retry limit behind the pending decision. It writes one stop row that the Stop guard releases one time. The row uses `needs_human_input` for `NEEDS_DECISION`, and `needs_approval` for the other two.

Use `to_decision_request()` to get the user’s decision. Record it with `graph.py record-decision ... --worker-status-seq N [--human-answer]`. This resolves the status. For `NEEDS_DECISION`, use one of the status’s options for `--chosen`. For `OUTSIDE_SCOPE` and `IRREVERSIBLE_ACTION`, pass `--human-answer` only after the user replies.

A worker’s `done` result includes `final_report {claims: [{text, label, source?}], did_not_verify: [{item, tag, reason}]}`. Give the source for each `verified` claim. The command refuses an invalid report with `final_report_invalid`. It records an accepted report in `final_reports[node]`. The orchestrator lints `check_confidence_labels` and `check_verify_loop` give advice.

- **Git writes.** Give the worktree and branch and tell the worker to "commit your work". Phase 4 uses the committed artifact.
- **Isolate all target checkouts.** This applies to the code repo and all other checkouts the worker will write to. For example, it applies to an external wiki or docs repo. Use `GIT_DIR != GIT_COMMON` from Step 0 of `superpowers:using-git-worktrees` to check for a linked worktree. If the target is unlinked, add the instruction below.

  "before making any edits, confirm or create worktree isolation for `<target checkout path>` via the superpowers:using-git-worktrees skill; do not write directly onto that checkout's current branch"

  Use the base ref from the Phase 2 clean-base check. If there is an `origin`, use `origin/main`. If not, use `main`. Do not use HEAD.

  Before starting the worker, run `git -C <abs target path> worktree list` and `git -C <abs target path> log --oneline <selected-base-ref>..HEAD`. Use the absolute path without `cd` to prevent cwd drift. See `learned-failure-modes.md`. This shows unpushed work in the checkout.

  A wiki writer used the shared checkout and committed to local `main` in a shared vault checkout. It mixed its commits with unpushed commits from a concurrent session. The two sets of commits survived, but the push needed manual repair. No reliable signal says "another session is using this checkout right now," so a hook cannot enforce the rule. Tell each worker to isolate its checkout.

- **Manifest and pre-push scope assertion.** Give the complete file list for the change. Include this instruction:

  "before you push, run `git diff <selected-base-ref> --name-only` and confirm the file list equals EXACTLY this manifest. If any file you did not intend to touch appears — especially one you never edited — STOP and report; do not push. A PR that carries files outside its manifest is a contamination, not a change."

  This catches a dirty base or stray `git add -A` before push. Correction is cheaper before the merge gate.

  For `clean-break`, also check before push for a shim, bridge, adapter, or legacy path for the replaced functionality. If one remains, remove it or stop and report. The worker’s assertion is a first check. The Phase 4b reviewer decides the gate independently of the worker that wrote the code.

- **Retirement decision.** Copy the Phase 2.6 `clean-break` or `preserve-compat` decision verbatim. For preserve-compat, include the `named_blocker`. The prompt must contain the decision.
- **Lessons.** Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/lessons.py" --dir <repo-key dir> --session <known native caller id> query --format contract`. Copy the applicable entries verbatim into the task. If the read is refused or degraded, mark the result unknown. Give the cause code. Do not use cached ledger or generated-view text.
- **Terminal artifact.** Give an artifact such as "the PR is OPEN" or "the PR is MERGED". The worker stays with it until the artifact is available. Copy this instruction verbatim:

  ```text
  You own this through that artifact existing. Do NOT hand back to the orchestrator in an intermediate state — after editing but before committing, after engineering-principles but before pushing, after review but before the PR is open. If you stop before the artifact exists, you have not finished; continue.
  ```

- **Hooks.** For a `test_gate` refusal, correct the tests that fail before committing. Push and PR open use `enforce_pr_workflow`. Run `/coderails:push` or `/workflow` for that gate. Edit in the feature-branch worktree to satisfy `no_edit_on_main`. Before `/coderails:merge`, run `/coderails:task-evals` and `/coderails:post-evals` for the eval-artifact gate in `scripts/merge.py`.

If the worker goes idle, use the artifact check in Phase 4. A success report is a claim for Phase 12 to check. If the work grows to 3 units or has a new dependency, use Phase 3 rung 2. Start a team with a `blockedBy` task list.

### Phase 4 — Spawn workers in waves, never block on idle pings

Workers can complete work and go idle without a report. An idle ping only means "I stopped."

When an agent goes idle without a report:

1. Read the worktree `git status` and `git diff --stat`.
2. If a PR should be open, use `gh pr view <N>` to check its status.
3. For a deployment, read the production log. Use the project’s tool, such as `ssh`, `kubectl logs`, or the cloud console.
4. Check the artifact itself.

If the artifact check fails and you can contact the native worker, send one `SendMessage` follow-up if the defect is in scope. Then check the next report and artifact. A missing or malformed report calls for a correction and cannot count as `done`. If the worker cannot resume or the correction fails, start a new worker. Give it a new name as in Phase 10. For sandboxed workers, use the terminal artifact and a new dispatch because they have no `SendMessage`.

**Batch the checks and limit the output (token-burn rules, rows 2 and 3 of 3).** Run related Bash checks in one call for each group. This includes Phase 12 artifact checks, gate data, and `gh pr view` calls. Each turn reads the full context again. Four turns can cost roughly four times the cache-read volume of four probes in one script. Group the read commands with `&&`, `;`, or pipes, and examine the result before deciding.

Limit each probe’s output with `jq -c`, `head`, or an equivalent tool. Large `git diff --stat` or `gh pr view` output increases the context that each subsequent turn reads.

Use one turn for parallel `Read`, `Grep`, `Glob`, or rung-1 `Agent` calls without dependencies on each other’s results. If a call needs a prior result, run it in sequence. Do not guess a parameter or use a placeholder. For 3 or more units or a dependency between units, start the Phase 3 rung 2 team with a `blockedBy` task list. Do not use parallel solo `Agent` calls as a replacement.

### Phase 4b — PR review invokes `/pr-review-toolkit:review-pr <PR#>` as a Skill, then `/coderails:post-review <PR#>`

When the workflow says "review the PR", invoke **`/pr-review-toolkit:review-pr <PR#>`** as a Skill. Give the PR number as its argument. Do this after the `/workflow` agent pushes the PR and before merge. The skill runs six specialized reviewers and a pass that checks for vulnerabilities. Do not start these reviewers with individual `Agent` or `Task` calls.

The merge gate `enforce_pr_workflow` accepts the `review-pr` Skill invocation for this PR. Individual calls leave no record the gate accepts.

Correct the reported issues and push the corrections. Then invoke `/coderails:post-review <PR#>` to post the SHA-bound artifact `/merge` checks. Before `/coderails:merge`, run `/coderails:task-evals` at scope `pr`, then run `/coderails:post-evals` for the eval artifact. Prepare the eval artifact independently of the reviewer artifact. The script `scripts/merge.py` needs the two artifacts and has no config opt-out.

After `/coderails:merge` checks that the PR merged, remove the unit’s worktree. Follow Step 6 of `superpowers:finishing-a-development-branch` and [finishing-out.md](finishing-out.md).

**Read [phase-4b-review.md](phase-4b-review.md) in full before this phase.** It gives the six-reviewer table and when each reviewer runs. It gives the verification_level rules for skipping `/security-review` and the rules for mandatory `/security-review` and `deploy-safety-reviewer` add-ons. It also gives the clean-break `MERGE-BLOCKER` gate. The orchestrator cannot downgrade a surviving compatibility result for a `clean-break` unit without the user.

### Phase 5 — Disprove the premise before each fix

Before starting a "bug fix" worker, delegate a premise check. Use `subagent_type: general-purpose` and the instructions from `agents/source-auditor.md`. Start a different native `general-purpose` agent to make the correction only after the premise check succeeds. Include each agent’s role instructions.

If the source auditor must run tests again, give it the absolute path to `${CLAUDE_PLUGIN_ROOT}/scripts/capability.py`. Resolve the path as described in [execution-graph.md](execution-graph.md). Rule 7 of `source-auditor.md` uses that path. Copy this into the auditor prompt:

```text
Verify the symptom in the source-of-truth FIRST. Slack pin-bar / GitHub PR state / Jira board / browser tabs all cache. Reproduce the bug via API call, prod log, DDB read, or git diff before any code change. If the symptom can't be reproduced via SOT, STOP and report — don't ship a fix to a non-bug.
```

Apply `/coderails:cite-check` to the claim "this bug currently reproduces." Use its rule: "re-derive from sources only, no recall, no inference". The source auditor reports PASS, FAIL, or UNSUPPORTED with sources. Start the worker only for PASS. This checks the premise independently of the correction and prevents work on a symptom you cannot reproduce.

**Before you make the proposed correction, run `/coderails:disconfirm` on the diagnosis.** Phase 5 checks for the bug. This checks the proposed cause and correction. Look for counterexamples, conditions that break it, and assumptions the worker did not test. This check costs less than code changes, reviewer work, and a revert for an incorrect diagnosis.

Skip this check only for a mechanical application of a design you checked before. For example, source checks during brainstorming established the dashboard UX treatments in this session. If you skip it as specified above, record the decision with `graph.py record-decision` when you update the graph for the unit.

### Phase 6 — Match confirmation to authorisation envelope

In a loop the user approved:

- If the envelope covers X, do not send "want me to spawn for X?".
- If you gave the justification in this turn, do not send "do you agree this is the right approach?".
- The standard envelope includes self-deploy and self-cleanup. A self-merge needs owner authorization, plus the usual reviewer, eval, and integrity gates. The shipped `action_authority: advisory` mode warns if there is no receipt. A live session authority can deny merge or limit it with `max_prs`. Explicit `enforce` needs a signed receipt. Use `scripts/merge.py <PR> --expected-head <sha>` to attach the receipt to the PR head. With no setting, the receipt gate is off and usual work needs no key or passphrase. Do not change the mode to bypass a denial.
- Stop the loop only for these conditions:
  - A Phase 4 artifact check fails.
  - A new question needs a decision that the envelope does not include.
  - The operation is destructive or irreversible, and the user did not discuss it before.

Use your judgment for small steps in scope. The user can redirect the loop.

If you do an important in-scope step without a check-in, use `graph.py record-decision` when you update the graph.

### Phases 7 & 8 — stack-specific deploy/push tactics live in a feedback memory, not here

Keep stack-specific deploy and push procedures in a feedback memory. For example, a deploy script can block on cosmetic lint and use a stack-specific skip-validation flag. If a versioned artifact such as a compose file changes on each PR, record its rebase-before-push steps. Keep this skill stack-agnostic.

### Phase 9 — Cluster wiki ingest, don't fragment

At the end of the loop, delegate one wiki update and lint for all related PRs. Use `subagent_type: general-purpose` and include the instructions from `agents/wiki-writer.md`. Use the vault schema and lint the result against AGENTS-wiki-schema. Include the push and PR steps and the Phase 3a shared-checkout rules. Use one source page for the cluster.

Then delegate one `/sync-docs` run at the loop end. Use `subagent_type: general-purpose` and the instructions from `agents/docs-auditor.md`. Check the repository docs against the merged code. Correct only differences this loop’s PRs introduced. Report earlier differences to the user.

**Read [phase-9-wiki-docs.md](phase-9-wiki-docs.md) in full before this phase.** It gives the first instruction for `/workflow` worker prompts to skip individual wiki steps. It gives the wiki publication checks for commit SHA, merged PR, and protected `main`. Do not use `--is-ancestor` as proof of a squash merge. Follow its rules for docs-drift results.

### Phase 10 — Use v2/v3 names when respawning a stuck agent

Dead agents continue to send idle pings until the runtime cleans them up. If you respawn with the same name, you cannot tell which idle ping is which.

Always respawn with a versioned name: `dockerfile-fixer` → `dockerfile-fixer-v2` → `dockerfile-fixer-v3`. The dead one's pings become identifiable noise. The live one's reports are unambiguous. The version bump does not change the routing — respawned agents keep the same Phase 2.8-assigned role.

### Phase 11 — Agent prompts include "confidence-label every claim"

Add to each spawned agent's prompt:

> Confidence-label each substantive claim in your output:
> - `(verified)` — directly observed through tool result, file read, or explicit user statement in this session
> - `(inferred)` — pattern-matched, recalled, or assumed from context
> - `(guess)` — best-effort with low confidence

> The user's stop hook enforces this. Propagate it into your work.

### Phase 12 — Status reports from agents are claims, not evidence

When an agent says "PR-N verified, deployed, working in prod", check the claim.

Before you unblock dependent work:

- Read the PR `mergedAt` with `gh pr view`.
- Read the production log line with `ssh`, `kubectl logs`, or the cloud console.
- Read the audit row or DDB record to check that the new code path ran.

**Check again before you use a report.** If a worker says "PR is CONFLICTING" or "ready to merge", the PR can change before you send an instruction. Run `gh pr view` or its equivalent immediately before you send the instruction. In one loop, an intervening merge cleared a `CONFLICTING` PR before a queued rebase instruction went out. The stale instruction led to duplicate work.

If all workers in the active wave are silent after a lease, run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" recover-wave <state> --session <session_id> [--lease-seconds N] [--report-only]`. It reports each node and one stable `reason_code`:

- `dispatch`: The worker did not start. Start it. The command records nothing.
- `record`: The worker finished or the launch was refused. Record the result.
- `waiting` or `stalled`: Use the reported status.

If all nodes are `stalled`, the command saves them as `stale` with their native `tool_use_id` values in one locked write. It then tells the orchestrator to start a new worker. If a node reaches `retry.max`, the command refuses with `recovery_budget_exhausted`. The user then selects what to do. Each result adds a non-authoritative row to `recovery-trace.jsonl` next to the graph data. See `docs/recover-wave-runbook.md`.

The Stop hook can run recovery when a blocked Stop finds a silent wave. It does so at most one time for each 900s lease and graph status, with a 4s budget. A live but silent worker can start again, bounded by `retry.max`. If recovery times out, it reports the result as unknown.

The command `graph.py summarize <state>` gives a plain-language status. The command `graph.py collection <root>` lists graphs below a directory. It shows each node’s stable ID, readable name, and status. It refuses malformed graph data. The optional `collection.json` explicitly links graphs. For example:

`{"schema_version":1,"graphs":[{"key":"build","path":"build/progress.json","loop_id":"build-loop","links":["verify"]},{"key":"verify","path":"verify/progress.json","loop_id":"verify-loop","links":[]}]}`

Use paths and loop IDs from schema-v3 graph data in that directory. The `links` field names keys. The command refuses unknown or ambiguous targets. Without the index, the command lists disconnected graphs. It reads graph data and reports the links and `unresolved_targets`. This list is empty for a correct index.

Each graph record has `key` and `links`. An unlinked record has `"links": []`. Each node reports its stable `id`, one-word `name`, optional `lane_code`, and current `status`. For example, `{"id":"U3[15]","name":"Builder","lane_code":"C-3","status":"pending"}`. A missing or malformed target gives a `graph:` error.

Check the deliverable independently and record its wave. Then run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" record-unit <state> --session <session_id> --unit <id> --status done --evidence "<observed check>"`. For a withdrawal with user authorization, use `--status dropped --reason "<reason>"`.

The command needs a registered pending unit and no active wave. It writes atomically and keeps the graph revision, so saved wave records continue to apply. Do not infer a work-unit decision from node status. Grade the last evals against the current revision.

One more check before you unblock the next phase costs less than work based on an incorrect report.

### Phase 13 — Confirm the factory actually ran (terminal self-audit)

Run this phase one time, at the end of the loop. Record the last `complete` stop after all updates to the loop and before standing-order setup. Do not use this phase for a mid-loop check-in. The `loop_stall_guard` hook checks `retro.json`, as described below. The report gives the results and does not pause for approval.

Use the `progress.json` counters to report raw facts without a pass/fail score. Let the user decide "should I have been asked about that?" Give:

- **`LOOP-STOP` category counts.** Read these hook-owned counts directly. Do not calculate or edit them.
- **Decisions absorbed.** Copy them verbatim from `progress.json`. Do not reconstruct them from memory.
- **Artifacts.** Give each artifact and the Phase 12 check result.
- **Loop cost.** Write `cost` correctly in step 1 of [teardown.md](teardown.md). The hook reports it from `retro.json` with the price age. Include the cost in your report.
- **Retirement decision violations.** If the result is "no record found", the audit has an error.
- **Loop-scope eval result.** Use `post_evals.py grade-loop`. Do not write the result by hand. If it says "no record found", the audit has an error.

**Teardown writes.** The `loop_stall_guard` hook blocks `complete` if there is no `retro.json` or it is malformed. It also blocks if a frozen proof did not run or did not succeed. Run these steps in sequence. See [teardown.md](teardown.md) for the commands and fields.

1. Run `proof.py freeze <state-dir>`, `run <state-dir> --all`, and `status <state-dir>`. If there is no proof, record the typed no-proof decision. Check each verdict. For one replacement in the same graph, use `proof.py supersede`. Supply the pending candidate that a reviewer checked and its author report. Keep the initial `proof.json`. Freeze and run the selected candidate. See [loop-state.md](loop-state.md).
2. Flush pending decisions and record the problems with `orders.py record`. After all updates to the loop, record one last `complete` stop with `graph.py stop`. Always run `orders.py prepare --loop <loop_id>`, also for an empty set. Do not record a new stop on retry.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/retro.py" assemble <state-dir> --session <session_id>`. It writes schema 3 with source hashes and teardown receipts. Report memory degradation. Do not write `retro.json` by hand.
4. Write feedback-type auto-memories for lessons that apply to other loops.
5. Run `loop_state_common.py mark-complete <cwd> <session_id>`. It checks the prepared source, saves the completed status, and then applies the standing-order records. If the save fails, it changes no record age. If the apply step fails, retry the pending teardown. Run `graph.py verify-completion <state> --session <session_id>`. Apply `superpowers:verification-before-completion` and write `LOOP-STOP: complete`.

## Context-window persistence

Continue if the context window or token budget is close to its limit. Context compacts and the session continues. Do not truncate a task or declare "done" mid-loop because of token pressure. Continue until one of the stop conditions below applies.

**Keep loop data in a durable artifact.** Keep one `progress.json` at the path the loop-state helper prints in Phase -2. Do not calculate the path. Run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" start <state> --session <session> --loop-id <id> --prompt-file <file>`. Use `graph.py add-unit` to add units. Do not write the initial file by hand.

If a registered unit has no checkout, run `graph.py assign-worktree <state> --session <session> --loop-id <id> --unit N --worktree ABS_PATH` before publication. This keeps an active wave and its revision. If a pending unit has no compatibility decision, use `graph.py set-unit-disposition` with a source citation and the current revision. See the RUNBOOK.

Update the file only with graph commands at phase boundaries. See [loop-state.md](loop-state.md) for the fields, lifecycle, hook-owned `loop_stop_counts`, and rules for concurrency and ownership.

After compaction or a "wait, where are we" moment, read `progress.json` again to find the loop position. Do not use the conversation to find the loop position. If the user must remind you that the loop is active, the file is not current. Git is the source for code. Commit work in flight before compaction. Use `progress.json` for the loop position.

The `loop_state_guard` hook checks that the file is available and belongs to the session. Keep its content current. Other durable files include `retro.json`, `sdd-ledger.md`, and the repo-keyed `orders.json` (viewed as `standing-orders.md`). See [loop-state.md](loop-state.md).

## Stop conditions for the loop

Use different procedures for a hard stop and an approval gate.

**Retry-until-green applies before hard-stop #1.** A test, lint, or verification error alone does not stop the loop. Find the cause, correct it, and run the check again. The default limit is five different tries. See [retry-until-green.md](retry-until-green.md) for the parallel-agent rule and when to use `superpowers:systematic-debugging`.

**Hard-stop: stop the loop and wait for the user.**

1. A verification error continues after all retry-until-green tries.
2. The premise check in Phase 5 cannot reproduce the symptom from SOT.
3. A genuinely ambiguous decision is not in the authorization envelope.
4. The user did not authorize a destructive or irreversible operation.

These conditions are mandatory. Retry-until-green changes when #1 applies. It does not remove #1 or change #2–4.

On a hard stop, give the current status with confidence labels, propose the next step, and wait.

**Approval-gate: pause for approval.**
An approval gate is a risk boundary the envelope names, such as a production cutover or enable step. Continue work until you get to that gate. Give the user one screen of information: the next step, artifacts, and irreversible effects. Pause for approval. When the user approves, continue without reopening earlier decisions.

Use the "pause-then-proceed" rule. Continue work to the approval gate. Do not interpret the gate as "do not start".

**Loop complete:**

5. All work the user gave authority to do is done and all gates succeeded. Run Phase 13 and stop.

**Record the stop.** The `loop_stall_guard` Stop hook blocks an active loop without a stop row and reports `stop_row_missing`. To record the row, run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" stop <state> --session <session_id> --category <hard-stop|approval-gate|awaiting-input|complete> --reason-code <work_complete|needs_human_input|needs_approval|node_hard_stop|environment_blocked|other> --reason "<reason>"`.

The hook reads only the current revision’s row from `progress.json` `stops[]`. Record it in the same turn. The hook consumes it one time. The hook refuses `complete` if the graph is unresolved.

After the Phase 0.5 confidence labels and Did-Not-Verify content, end the turn with the line below. The line is for the user. The hook reads the row.

> `LOOP-STOP: <category> — <reason>`

Use only one `<category>`:

- `hard-stop`: One of the four hard-stop conditions above.
- `approval-gate`: The named risk boundary that needs the user’s approval.
- `awaiting-input`: A planned pause for user input. This includes Phase −1 clarification. If the envelope is full-autonomous, Phase −1 auto-adopts the prompt without a pause. It also includes Phase 1 plan confirmation. Use it only for planned pauses. Phase 13 reports its raw count in the `LOOP-STOP` summary.
- `complete`: All work the user gave authority to do is done. Record the last stop after all loop updates and before the standing-order setup. Assemble `retro.json` at schema 3, then run `mark-complete`. The gate checks source hashes, standing-order setup, and the controller results for the selected proof suite. If there is no proof, record the typed no-proof decision. The helper applies the standing-order records only after the save succeeds. See [teardown.md](teardown.md).

The hook requires an unconsumed row for this revision and checks its category. It cannot check that your explanation is honest, as for the verify-loop hook. The Stop payload has no turn ID (unverified). The hook compares the row’s `at` timestamp with the latest user prompt timestamp. If the prompt has no readable timestamp, the hook blocks the row. Phase 13 reports the category counts.

## A note on cadence

- **Before the first tool call of a step**, say what you will do in one sentence.
- **During the work**, give an update if you find something important or change direction.
- **When you finish**, start with the answer to "what happened" or "what did you find," then give the check results.

Use the Phase 4 artifact check to check if an idle ping indicates a problem. Do not give a status update for each ping. Follow the user's pace.

**Keep orchestrator responses concise.** Keep caveats short and give the result. Give more information if the user wants it.
