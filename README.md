# coderails

Coderails ships two workflow plugins. The Claude Code plugin is at the repo root. The native Codex plugin is in `packages/codex/`.
Each plugin has its own skills, agents, and hooks. Each sends work to agents on its own provider.

- **Workflow** — the `prep → push → merge → wiki` command chain plus the
  agentic-loop, planning-sequence, premortem, and handoff skills.
- **Guardrails** — Claude marks claims `(verified)` or `(inferred)`. The Stop lints remind Claude to add and resolve `## Did Not Verify`. These lints are advisory. Other hooks block destructive Bash commands and commits when project tests do not succeed.
- **Integrity gate** — The local gate, root-owned attestor, and GitHub ruleset check PR reviewer and eval records. The gate blocks stale, missing, or malformed records. See [`docs/INTEGRITY-GATE.md`](./docs/INTEGRITY-GATE.md).

## Install

See [INSTALLATION.md](./INSTALLATION.md). Short version:

```bash
git clone https://github.com/blueman82/coderails.git ~/Documents/Github/coderails
cd ~/Documents/Github/coderails
python3 install.py --provider claude --dry-run
python3 install.py --provider claude
# close and start Claude Code, then:
#   /plugin marketplace add ~/Documents/Github/coderails
#   /plugin install coderails@coderails
#   /reload-plugins
```

For Codex, run `python3 install.py --provider codex`. The command adds the plugin to Codex and installs its agent definitions in `${CODEX_HOME:-~/.codex}/agents`.
After installation, start a new Codex session and run `/hooks`. Examine and trust the Coderails hooks. Codex skips plugin hooks until you trust them.

Python commands replace the owned shell entry points. The two providers accept only graph schema 3. Each install has a copy of the same pure graph semantics source. Each provider keeps its own dispatch, transcript records, and locks. See [INSTALLATION.md](./INSTALLATION.md) before you upgrade an installation with earlier commands or loop data.

For each project, run the init command one time. In Claude Code, use `/coderails:init`. In Codex, use `$coderails-codex:init`. These commands set up `.coderails/workflow.config.yaml` from [`examples/workflow.config.yaml`](./examples/workflow.config.yaml). Use this procedure for a new repo.

## Commands

| Command | What it does |
|---|---|
| `/workflow` | Run the full feature workflow: prep → code → push → PR checks → merge → wiki |
| `/coderails:init` | Set up `.coderails/workflow.config.yaml` for the current repo |
| `/prep` | Safety branch + feature branch + Jira ticket |
| `/push` | Add files to the Git index, commit, push, and open a PR with reviewers. Resolve the linked Jira issue automatically. |
| `/post-review` | Post SHA-bound reviewer records to the PR. The `/merge` gate requires them. |
| `/coderails:task-evals` (skill) | Freeze ungraded success evals before implementation. Then grade the results. |
| `/coderails:post-evals` | Post SHA-bound eval records to the PR. The `/merge` gate requires them. |
| `/merge` | Merge an approved PR, switch to `main`, and pull changes |
| `/coderails:authorise` | The user types this command to grant authority that expires and can be revoked. The word "autonomous" only prints the command. |
| `/assumptions` | List each assumption and mark it `verified` or `inferred` |
| `/coderails:cite-check` (skill) | Check a claim from sources without recall. `coderails:source-auditor` works without the context that produced the claim. Claude Code uses `/verify` for its own skill. |
| `/notchecked` | List claims you did not check |
| `/disconfirm` | Argue against your own most recent recommendation |
| `/test-gate-setup` | Find the test runner and write `.claude/test_command` |

## Skills

Coderails ships its own skills. Install `superpowers@claude-plugins-official` for planning, TDD, systematic debugging, code checks, and Git worktrees. Install `pr-review-toolkit@claude-plugins-official` for the PR check in `/workflow`.

Coderails ships 25 skills across three groups. For the full catalog, see [`docs/REFERENCE.md`](./docs/REFERENCE.md).

**Dependency for the skills below: `superpowers@claude-plugins-official`**

| Skill | Purpose |
|---|---|
| `superpowers:brainstorming` | Explore intent and requirements before implementation |
| `superpowers:dispatching-parallel-agents` | Give tasks that have no dependencies to agents in parallel |
| `superpowers:executing-plans` | Do the work in a written plan |
| `superpowers:finishing-a-development-branch` | Do the last checks before a merge |
| `superpowers:receiving-code-review` | Apply feedback from a code reviewer systematically |
| `superpowers:requesting-code-review` | Prepare a PR for a reviewer |
| `superpowers:subagent-driven-development` | Delegate implementation tasks to subagents |
| `superpowers:systematic-debugging` | Structured root-cause analysis |
| `superpowers:test-driven-development` | Red-green-refactor discipline |
| `superpowers:using-git-worktrees` | Work in parallel with Git worktrees |
| `superpowers:verification-before-completion` | Do the last verification before you report that the work is complete |
| `superpowers:writing-plans` | Write plans with steps from specs |
| `superpowers:writing-skills` | Scaffold new skills from scratch |

**coderails-original**

| Skill | Purpose |
|---|---|
| `agentic-loop` | Multi-agent orchestration: spawned teams, no-human-gates, multi-PR loops |
| `cite-check` | Check a claim from sources alone. Do not use recall or inference. `coderails:source-auditor` works without the context that produced the claim. |
| `dashboard` | Show live data for sessions, loops, PR gate status, runs, and memory operations |
| `execution-discipline` | High-autonomy, self-verifying work for non-trivial tasks |
| `handoff` | Give a new session structured memory and a prompt to continue |
| `improve-prompt` | Surfaces ambiguities and rewrites underspecified prompts |
| `docs-sync` | Runs nightly for Git-tracked docs. If the docs differ from the code, it edits, pushes, checks, and merges the correction through all gates. Use it on a schedule. |
| `loop-retro-promotion` | Runs on a schedule. If its condition is satisfied, it adds proven loop lessons to `learned-failure-modes.md` through all gates. |
| `memory-consolidation` | Check and consolidate a project's saved memory directory. Run it on demand or on a weekly schedule. |
| `planning-sequence` | Pre-Parade → Premortem → Red Team on a plan |
| `premortem` | Start from the assumption that the plan did not succeed. Identify causes that could give that result. |
| `sync-docs` | Check in-tree docs against the code and report differences |
| `task-evals` | Game-resistant success-eval generation: frozen `evals.json` with negative controls |
| `using-coderails` | At `SessionStart`, give Claude the instructions for Coderails |
| `verify-merged-pr` | Check a "PR is merged" claim against `origin` before you use it |
| `workflow-audit` | Find recurring tasks in transcripts that are good candidates for skills |

**Wiki**

| Skill | Purpose |
|---|---|
| `wiki-ingest` | Write or update wiki pages from a PR/decision |
| `wiki-init` | Scaffold the wiki vault and index |
| `wiki-lint` | Validate wiki structure and links |
| `wiki-query` | Answer questions from the wiki |

**Engineering principles**

| Skill | Purpose |
|---|---|
| `engineering-principles` | Apply YAGNI, KISS, DRY, Fail Fast, SSOT, and the Law of Demeter. Invoke the language skill. |
| `engineering-principles-python` | Python idioms and standards |
| `engineering-principles-go` | Go idioms and standards |
| `engineering-principles-ts` | TypeScript idioms and standards |
| `engineering-principles-bash` | Bash/shell idioms and standards |

## Agents

The plugin includes these optional native Claude agent definitions. The graph uses the role and task-name fields that the provider has to send work. Claude gets a native `subagent_type`. Codex gets the helper's `task_name`. It gets a native role only if its tool can accept one.

The orchestrator includes the agent's instructions in the dispatch. A custom Coderails label is optional. The label alone does not show that the instructions loaded.

`spec-reviewer` declares `tools: Read, Grep, Glob`, which gives it read-only access. `source-auditor` uses `Bash` to calculate numbers from source. It lists `Write` and `Edit` in `disallowedTools`. Its instructions tell it to use `Bash` for reads only. `pr-review-toolkit:code-reviewer` has no `tools:` key, so it has full tool access. Its instructions tell it to read only.

| Agent | Purpose | Tools |
|---|---|---|
| `coderails:source-auditor` | Checks a claim from durable sources only. Gives `PASS`, `FAIL`, or `UNSUPPORTED`. Works for `/coderails:cite-check`. | read and `Bash`. No `Write` or `Edit`. |
| `coderails:spec-reviewer` | Before planning, checks completeness, clarity, scope, and YAGNI. Checks that the parts of the spec agree. | read-only |
| `coderails:wiki-writer` | Writes and maintains LLM Wiki pages that follow the schema. Commits and opens PRs. | read and write |
| `coderails:loop-worker` | Does the work for one scoped task. Writes code and tests, commits, checks its work, and reports the results with sources. | read and write |
| `coderails:deploy-safety-reviewer` | Checks rollback risk, affected systems, migration and schema safety, feature flags, and deploy-time monitoring | read and `Bash`. No `Write` or `Edit`. |
| `coderails:design-scout` | Reads code paths for one open design decision. Gives one recommendation and the condition that could change it. Does not check existing documents. | read and `Bash`. No `Write` or `Edit`. |
| `coderails:disposition-scout` | Checks consumers and constraints to select `clean-break` or `preserve-compat` for each retirement unit in a Phase 1 plan | read and `Bash`. No `Write` or `Edit`. |
| `coderails:docs-auditor` | Runs `/sync-docs` against the merged code. Corrects only differences that the loop caused. Reports earlier differences to the user. | read, `Bash`, and `Edit`. No `Write`. |
| `coderails:preflight-scout` | Runs planning-sequence, premortem, assumptions, notchecked, wiki-query, and retro intake. Adds checks and does not relax a gate. | read and `Bash`. No `Write` or `Edit`. |
| `coderails:proof-author` | Writes frozen `proof.json` from `authorising_prompt_raw`, `session_id`, `loop_id`, and docs that the prompt names. Does not read the plan or dispatch conversation. Each proof stays `pending`. | read, `Bash`, and `Write` |

The required `pr-review-toolkit@claude-plugins-official` plugin supplies `code-reviewer`, `code-simplifier`, `comment-analyzer`, `pr-test-analyzer`, `silent-failure-hunter`, and `type-design-analyzer`. Coderails supplies other roles. For example, `deploy-safety-reviewer` checks deploy safety and leaves code-level error handling to `silent-failure-hunter`.

## Hooks

This section explains hook behavior. For the registration of each provider, see the generated table. Check this text against the code when behavior changes.

- **`inject_bootstrap.py` at `SessionStart`.**

  Silent. Adds the `using-coderails` skill to each new session.

- **`remember_inject_cap_guard.py` at `SessionStart`.**

  Gives warnings only by default. If the remember plugin has no `REMEMBER_INJECT_MAX_BYTES` limit (default 8000), the hook gives opt-in steps one time for each plugin version. Set `REMEMBER_INJECT_CAP_AUTOWRITE=1` in the `env` block of `settings.json` to let it apply and reapply the limit. In this mode it writes to the other plugin's directory at `~/.claude/plugins/cache/.../remember/<version>/scripts/`.

  It keeps one dated `.coderails-bak-*` copy. The patch applies to the `for MFILE` loop only. See `hooks/patches/README.md`.

- **`inject_context.py` at `UserPromptSubmit`.**

  Silent. Puts `[ctx]` (cwd, branch, date) before each prompt. It adds a reminder to tag claims (verified)/(inferred)/(guess) and add `## Did Not Verify` after file edits.

- **`autonomous_gate.py` at `UserPromptSubmit`.**

  Adds context only. If the raw prompt contains "autonomous", the hook prints the command `/coderails:authorise`. It gives no authority. It does not read the transcript or added context.

- **`check_confidence_labels.py` at `Stop` + `SubagentStop`.**

  Advisory in and out of loops. A reply with 200 or more characters with no `(verified)`, `(inferred)`, or `(guess)` label gets an `[discipline-advisory]` in `additionalContext`. The hook logs `would_block=1 demoted=1 blocked=0 reason_code=confidence_label_missing`. It adds an `outcome=demoted` telemetry row and exits with code 0.

  The user directed the demotion when the criteria were not met. See `docs/decisions/2026-10-04-not-in-gate-demotion.md`. No live check shows that the model gets this `additionalContext`. At `SubagentStop` the hook reads `last_assistant_message` directly.

  At `Stop` it skips the check and logs the skip if `CODERAILS_HEADLESS_RUN=1`.

- **`check_verify_loop.py` at `Stop` + `SubagentStop`.**

  Advisory only. Each bullet in `## Did Not Verify` needs the `(unverifiable: <reason>)` tag. The hook also checks for a missing section after a turn with three or more files. On a flag, it gives an `[discipline-advisory]` in `additionalContext` and logs `demoted=1 reason_code=verify_loop_missing`.

  It adds an `outcome=demoted` telemetry row and exits with code 0. At `SubagentStop` it reads `last_assistant_message` directly. At `Stop` it skips the check and logs the skip if `CODERAILS_HEADLESS_RUN=1`. A `claude -p` run from the dashboard has no interactive user to correct the turn for.

- **`voice_announce.py` at `Stop`.**

  Uses macOS `say` in the background to speak a loop notice (`complete`, `waiting-on-human`, `stopped`, or `stall`). It does not block. It stays silent if the loop is not active or the text is empty. It sets a minimum interval between notices of the same type.

  It runs first in the Stop array.

- **`loop_state_guard.py` at `Stop`.**

  Blocks an active agentic loop with no session-owned `progress.json`. It gives this block only one time for the same session and invocation count. For a loop with one or more work units, it checks loop-scope `evals.json` before `complete`. It blocks if there is no file or the grade is `NO-GO`.

  For a `GO` or `VERIFICATION_LEVEL0` grade, it checks for `verification_justification` and a correct grading stamp.

- **`loop_stall_guard.py` at `Stop`.**

  Blocks an unfinished loop without a stop row from `graph.py stop`. It does not read the `LOOP-STOP` text. It uses the grace for missing `progress.json` from `loop_state_guard.py`. An unresolved graph asks for human approval one time and suppresses duplicate notices.

  Codex `graph_completion_guard.py` gives the same escalation and blocks if it cannot give output. For a `complete` stop, it checks for a well-formed `retro.json` for Phase 13 and checks that all work units finished. If a sibling `proof.json` has a proof without a transcript run or its last run did not succeed, the hook blocks.

- **`unregistered_loop_guard.py` at `Stop`.**

  Gives a nudge if the session has three or more Agent-dispatch turns, no `progress.json`, and no agentic-loop Skill invocation. It does not block.

- **`offload_push_guard.py` at `Stop` + `SubagentStop`.**

  Gives a nudge if the last reply names a `git push` to `main` or `master` and tells the user to do it. Example cues are a leading `! ` or "run this yourself". It gives at most one nudge in a session and does not block.

- **`destructive_bash_gate.py` at `PreToolUse` (Bash).**

  Blocks destructive commands and reads or writes of a literal `.env` path. See [the hook guide](docs/HOOK-BEHAVIOR.md) for the command list and `docs/REFERENCE.md` for path matching and its limits. It also blocks Bash edits to source files on `main` and `master`. It rejects backticks, `$(...)`, `<(...)`, and `>(...)` in free-text arguments to `push.py`, `merge.py`, `post_review.py`, and `post_evals.py`.

- **`enforce_pr_workflow.py` at `PreToolUse` (Bash).**

  Blocks `gh pr create` without `/coderails:push`. For `gh pr merge <N>` or `scripts/merge.py <N>`, it checks `/pr-review-toolkit:review-pr <N>` and a SHA-bound `GO` eval artifact. The check uses the current PR head and accepts a `verification_level` of 0 with `GO`. The hook blocks if a check does not succeed.

  It consumes the check for this PR at use. It also checks `review-pr` for `git merge` or `git push` to `main` or `master`. It reads subagent transcripts.

- **`test_gate.py` at `PreToolUse` (Bash).**

  Blocks `git commit` if tests fail. Turn it on for each repo. Keep full command logs and report measurements and the command to read the logs.

- **`verification_volume_ceiling.py` at `PreToolUse` (Bash).**

  Blocks the third and subsequent calls to `hooks/scripts/tests/run_all.py` or `scripts/post_evals.py validate-structure` for a work unit (branch). The limit has no override.

- **`reviewer_bash_allowlist.py` at `PreToolUse` (Bash).**

  Applies to `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, and `source-auditor`. It lets the role run only one read-only command from the allowlist. It denies chaining, redirection, substitution, interpreters, and options `--output`, `--pre`, or `--ext-diff`. It does nothing if there is no `agent_type` or the type is different.

  These roles have MCP tools and do not list `Bash`. See the command list and limits in [docs/decisions/e2-reviewer-bash-allowlist.md](docs/decisions/e2-reviewer-bash-allowlist.md).

- **`subagent_identity_gate.py` at `PreToolUse` (Bash).**

  The hook checks `progress.json` for `graph` and the current session ID. In that session it blocks a Bash call with a nonblank `agent_id` if `agent_type` has no text, is not a string, or is unavailable. It reports `bash_agent_type_absent` in the discipline log and telemetry. It does not block other calls.

  The safeguard works only if Claude Code fills in `agent_id`. Codex does not supply `agent_type` or `agent_id` at `PreToolUse`. Codex uses `shell_tool = false` role files and contained role sessions. See [the tool access guide](docs/CAPABILITIES.md).

- **`action_authority_gate.py` at `PreToolUse` (Bash).**

  With `action_authority: enforce`, `merge.py` needs a signed owner receipt and an expected head SHA. This mode is the default with no config. Invalid config denies operations that the hook checks. Set `advisory` to get warnings.

  Set `off` to turn off this receipt gate. The owner approves each operation at a terminal. Passphrases are optional. The PR reviewer, eval, and integrity checks continue to apply.

  See [the authority decision](docs/decisions/e3-authority-object.md).

- **`autonomous_gate.py` at `PreToolUse` (AskUserQuestion).**

  Blocks only `AskUserQuestion` while the session has live autonomous authority. Continue autonomously. The authority expires after 24 hours. To revoke it, run `python3 scripts/authority.py revoke --session <id>`.

  The hook does not block prose questions or agentic-loop `LOOP-STOP` declarations.

- **`agent_only_gate.py` at `PreToolUse` (Bash/Edit/Write/MultiEdit/Read/Grep/Glob/WebFetch/NotebookEdit).**

  Nudges the top-level orchestrator away from inline work. Set `AGENT_ONLY_GATE_ENFORCE=1` to block. It stays silent for calls from a dispatched subagent or for an allowed full workflow command. The allowed commands use `gh`, `git`, `scripts/push.py`, `scripts/merge.py`, `scripts/post_review.py`, or `scripts/post_evals.py`.

- **`agent_model_routing_nudge.py` at `PreToolUse` (Agent).**

  Gives advice only if the dispatch has no `model`. If the description or prompt matches mechanical words, it suggests `haiku`. For complex or architectural words it suggests `opus`. It does not block.

- **`loop_dispatch_guard.py` at `PreToolUse` (Agent).**

  Checks graph schema 3, session and loop ownership, revision, wave, node, and `CODERAILS_GRAPH_DISPATCH` against the `begin-wave` record. Use the record one time. Include the rendered contract sections verbatim. The hook checks `subagent_type` against the record.

  Scout roles with a guard need `coderails:<role>`. Other roles also accept `general-purpose`. A different role gives `role_mismatch`. If the roster has work units, implementation work needs owned frozen or graded evals that meet the checks.

  Frozen evals bind the session and loop without binding the graph revision. The hook skips this eval check for nodes that prepare the work. Without graph data it blocks marked or custom-worker dispatches. If the graph belongs to a different session, it blocks all Agent calls.

  The Python sandbox launcher calls the same guard before it sets up scratch space.

- **`no_edit_on_main.py` at `PreToolUse` (Write/Edit/MultiEdit).**

  On `main` or `master`, the allowlist has `.md`, `.txt`, and `.rst`. It also has `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, `.cfg`, `.gitignore`, and `LICENSE`. It blocks other files and plugin-source Markdown (`skills/*/SKILL.md` and `commands/*.md`). On all branches it also blocks edits to `.claude/settings.json` and `.claude/settings.local.json`.

  These files can change permissions to bypass the gates.

- **`comment_citation_gate.py` at `PreToolUse` (Write/Edit/MultiEdit).**

  Blocks new comments that use session-artifact labels. Examples are `E#:`, `F# fix`, `CHANGE B#`, `C#`, `Task A#`, `TA-I#`, "reviewer finding", and "per the plan". Write the constraint that the code enforces. The hook skips `.md` files and fails open.

- **`wiki_taxonomy_gate.py` at `PreToolUse` (Write/Edit/MultiEdit).**

  The hook needs `.coderails/workflow.config.yaml` at the plugin root. On a new clone, run `/coderails:init` to set up this file. The write's Git root must be the directory at `wiki_path`. Resolve a relative `wiki_path` from `CLAUDE_PLUGIN_ROOT`.

  Two or more of the directories from "## Page types" must be on disk. The hook reads the section from the plugin's `AGENTS.md` and blocks writes to top-level directories that the section does not list. It reads the taxonomy at run time. It lets the write continue if the schema, config, section, or directory check is unavailable or does not succeed.

  It also lets the write continue if the vault is not a Git repo or the wiki path does not resolve. It lets writes to a different vault continue.

- **`quality_feedback.py` at `PostToolUse` (Write/Edit/MultiEdit).**

  Adds quality feedback to `PostToolUse` context. It always exits with success and cannot block a write.

### Generated hook registration

This table lists the hooks in each installed provider. Run `python3 scripts/gen_hooks.py --check` to check the generated files.

<!-- hook-registry:start -->
Claude protocol: Exit with code 0 and JSON, or with code 2 to block.
Codex protocol: Exit with code 0 and a JSON decision.

| Provider | When | Matcher | Hook | Options | Mode | Default | Category | Step | On error | Limit |
|---|---|---|---|---|---|---|---|---|---|---|
| claude | SessionStart | `startup` or `resume` or `clear` or `compact` | `inject_bootstrap.py` | `async=False` | `silent` | Runs on its provider trigger | add bootstrap context | Check the plugin root and hook registration if there is no context. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | SessionStart | `startup` or `resume` or `clear` or `compact` | `remember_inject_cap_guard.py` | `async=False` | `advisory` | Gives a warning by default. Set REMEMBER_INJECT_CAP_AUTOWRITE=1 to write the patch. | remember inject cap guard | Set the limit for added memory text or use the documented opt-in patch. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | UserPromptSubmit | `all` | `inject_context.py` | `timeout=5` | `silent` | Runs on its provider trigger | add prompt context | Check the prompt hook registration if there is no context. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | UserPromptSubmit | `all` | `autonomous_gate.py` | `timeout=5` | `block` | The phrase gives no authority. A live typed authority can block questions. | autonomous input gate | Use the typed authority command, or continue after the authority expires. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `voice_announce.py` | `timeout=15, async=True` | `observe` | Runs on its provider trigger | voice announce | Read the loop status if you did not get a spoken notice. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `check_confidence_labels.py` | `timeout=15` | `advisory` | Runs on its provider trigger | check confidence labels | Add the correct confidence label to each claim that needs one. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `check_verify_loop.py` | `timeout=15` | `advisory` | Runs on its provider trigger | check verify loop | Complete the verification section and mark each unresolved check. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `loop_state_guard.py` | `timeout=15` | `block` | Runs on its provider trigger | check for loop status | Put the owned graph and graded loop eval records back. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `loop_stall_guard.py` | `timeout=15` | `block` | Runs on its provider trigger | loop stall guard | Record the required stop and complete unresolved graph work. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `unregistered_loop_guard.py` | `timeout=15` | `nudge` | Runs on its provider trigger | unregistered loop guard | Record the active agentic loop graph before you send more work. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | Stop | `all` | `offload_push_guard.py` | `timeout=15` | `nudge` | Runs on its provider trigger | offload push guard | Keep the push in the authorised workflow. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | SubagentStop | `all` | `check_confidence_labels.py` | `timeout=15` | `advisory` | Runs on its provider trigger | check confidence labels | Add the correct confidence label to each claim that needs one. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | SubagentStop | `all` | `check_verify_loop.py` | `timeout=15` | `advisory` | Runs on its provider trigger | check verify loop | Complete the verification section and mark each unresolved check. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | SubagentStop | `all` | `offload_push_guard.py` | `timeout=15` | `nudge` | Runs on its provider trigger | offload push guard | Keep the push in the authorised workflow. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `destructive_bash_gate.py` | `timeout=5` | `block` | Runs on its provider trigger | destructive bash gate | Use a safe command that avoids the blocked operation. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `enforce_pr_workflow.py` | `timeout=10` | `block` | Off without workflow config | PR workflow gate | Run `review-pr`. Post the records for the current PR head. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `test_gate.py` | `timeout=180` | `block` | off unless test commands are configured | test gate | Correct the tests with errors before you commit. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `verification_volume_ceiling.py` | `timeout=5` | `block` | Runs on its provider trigger | verification volume ceiling | Use focused tests after the allowed full-suite runs. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `reviewer_bash_allowlist.py` | `timeout=5` | `block` | Runs on its provider trigger | reviewer bash allowlist | Use an allowed read-only command or a tool that your grant permits. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `subagent_identity_gate.py` | `timeout=5` | `block` | Runs on its provider trigger | subagent identity gate | Start the agent with a native type that the graph can identify. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` | `action_authority_gate.py` | `timeout=10` | `block` | Default mode is `enforce`. Mode `advisory` gives a warning. Set `off` in the config to disable. | operation authority gate | Use the authority path set in config for this operation and session. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `AskUserQuestion` | `autonomous_gate.py` | `timeout=5` | `block` | The phrase gives no authority. A live typed authority can block questions. | autonomous input gate | Use the typed authority command, or continue after the authority expires. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Bash` or `Edit` or `Write` or `MultiEdit` or `Read` or `Grep` or `Glob` or `WebFetch` or `NotebookEdit` | `agent_only_gate.py` | `timeout=5` | `nudge` | Default mode gives a nudge. AGENT_ONLY_GATE_ENFORCE=1 blocks. | agent only gate | Send source work to an agent or use the allowed workflow command. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Agent` | `agent_model_routing_nudge.py` | `timeout=5` | `nudge` | Runs on its provider trigger | agent model routing nudge | Select a model role that fits the task when the suggestion is useful. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Agent` | `loop_dispatch_guard.py` | `timeout=10` | `block` | Runs on its provider trigger | loop dispatch guard | Use the current owned graph dispatch envelope and role. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Agent` | `worker_containment_gate.py` | `timeout=10` | `block` | Runs on its provider trigger | worker containment gate | Use the required containment acknowledgement or a low-risk path. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Write` or `Edit` or `MultiEdit` | `no_edit_on_main.py` | `timeout=5` | `block` | Runs on its provider trigger | primary branch edit gate | Move the source edit to a feature branch. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Write` or `Edit` or `MultiEdit` | `comment_citation_gate.py` | `timeout=5` | `block` | Runs on its provider trigger | comment citation gate | Write the durable rule in the comment without a session label. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PreToolUse | `Write` or `Edit` or `MultiEdit` | `wiki_taxonomy_gate.py` | `timeout=5` | `block` | Runs only with workflow config and a resolved wiki path | wiki taxonomy gate | Write the page in a directory that the wiki schema permits. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| claude | PostToolUse | `Write` or `Edit` or `MultiEdit` | `quality_feedback.py` | `timeout=10` | `advisory` | Runs on its provider trigger | quality feedback | Read the quality result and correct the source problems it lists. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| codex | SessionStart | `startup` or `resume` or `clear` or `compact` | `inject_bootstrap.py` | `timeout=10, additionalContextLimit=1200` | `silent` | Runs on its provider trigger | add bootstrap context | Check the plugin root and hook registration if there is no context. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| codex | UserPromptSubmit | `all` | `inject_context.py` | `timeout=10, additionalContextLimit=500` | `silent` | Runs on its provider trigger | add prompt context | Check the prompt hook registration if there is no context. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| codex | UserPromptSubmit | `all` | `autonomous_gate.py` | `timeout=10` | `block` | The phrase gives no authority. A live typed authority can block questions. | autonomous input gate | Use the typed authority command, or continue after the authority expires. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | Stop | `all` | `graph_completion_guard.py` | `timeout=10` | `block` | Runs on its provider trigger | check for graph closeout | Resolve the graph status and record a stop result that meets the rules. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | Stop | `all` | `check_confidence_labels.py` | `timeout=10` | `advisory` | Runs on its provider trigger | check confidence labels | Add the correct confidence label to each claim that needs one. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| codex | SubagentStop | `all` | `check_confidence_labels.py` | `timeout=10` | `advisory` | Runs on its provider trigger | check confidence labels | Add the correct confidence label to each claim that needs one. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^Bash$` | `destructive_bash_gate.py` | `timeout=10` | `block` | Runs on its provider trigger | destructive bash gate | Use a safe command that avoids the blocked operation. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^Bash$` | `test_gate.py` | `timeout=180` | `block` | off unless test commands are configured | test gate | Correct the tests with errors before you commit. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^Bash$` | `verification_volume_ceiling.py` | `timeout=10` | `block` | Runs on its provider trigger | verification volume ceiling | Use focused tests after the allowed full-suite runs. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^Bash$` | `pr_publication_gate.py` | `timeout=60` | `block` | Applies to Codex publication commands that the gate checks | pr publication gate | Complete the required `review-pr` and eval steps for this PR head. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^Bash$` | `action_authority_gate.py` | `timeout=10` | `block` | Default mode is `enforce`. Mode `advisory` gives a warning. Set `off` in the config to disable. | operation authority gate | Use the authority path set in config for this operation and session. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^request_user_input$` | `autonomous_gate.py` | `timeout=10` | `block` | The phrase gives no authority. A live typed authority can block questions. | autonomous input gate | Use the typed authority command, or continue after the authority expires. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^(?:spawn_agent\|collaborationspawn_agent)$` | `loop_dispatch_guard.py` | `timeout=10` | `block` | Runs on its provider trigger | loop dispatch guard | Use the current owned graph dispatch envelope and role. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^apply_patch$` | `no_edit_on_main.py` | `timeout=10` | `block` | Runs on its provider trigger | primary branch edit gate | Move the source edit to a feature branch. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^apply_patch$` | `comment_citation_gate.py` | `timeout=10` | `block` | Runs on its provider trigger | comment citation gate | Write the durable rule in the comment without a session label. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PreToolUse | `^apply_patch$` | `wiki_taxonomy_gate.py` | `timeout=10` | `block` | Runs only with workflow config and a resolved wiki path | wiki taxonomy gate | Write the page in a directory that the wiki schema permits. | Deny or block and show why | Runs in the caller's trust domain. Server policy controls release. |
| codex | PostToolUse | `^apply_patch$` | `quality_feedback.py` | `timeout=15, additionalContextLimit=1000` | `advisory` | Runs on its provider trigger | quality feedback | Read the quality result and correct the source problems it lists. | Continue and record the error | Runs in the caller's trust domain. Server policy controls release. |
<!-- hook-registry:end -->

The test gate keeps full stdout and stderr for all runs in `~/.coderails/test-output/`. Set `CODERAILS_TEST_OUTPUT_DIR` to use a different directory. If a test run does not succeed, the notice gives the log path.

Use the provider's `test_output.py` to read the full log, read a range of lines, or find literal text. By default it gives metadata and guidance. The agent can then read more of the log.

The gate compresses logs when runs end. The compressed log budget is 1 GiB by default. To change it, set `CODERAILS_TEST_LOG_BUDGET_BYTES`. The earliest completed logs expire first. The gate keeps active runs and the most recent run, so the total can be more than the budget.

The gate keeps compact metrics and expiry records apart from the logs. The byte count does not show what the model got. See [reader examples and measurement limits](docs/REFERENCE.md#retained-test-gate-output).

Source measurement notes cover [graph dispatch](docs/graph-dispatch-measurement.md),
[typed records](docs/typed-records-measurement.md),
[workflow gates](docs/workflow-gates-measurement.md), and
[session observations](docs/OBSERVATION-REPORT.md). Each note identifies source checks, installation checks, and live observations. A local test does not prove that an installed provider used a control.

## Sandboxed workers

With `sandbox_workers: true` (the default), the Claude implementation launcher uses the pinned `@anthropic-ai/sandbox-runtime` in a scratch clone. It uses the OS sandbox, `npx`, and a dedicated Claude worker credential. If a component is unavailable, the graph does not send implementation work.

The graph driver prepares execution checkout C before authorization. It checks a fixed uncommitted proposal before it copies the proposal into reserved root checkout D. The root checks and publishes the proposal. When work continues after a stop, the driver keeps the edits that the root made after the copy. The orchestrator runs without the sandbox.

Codex native `spawn_agent` inherits the parent sandbox. The Codex dispatch hook refuses native implementation work if containment is on. The OAuth graph driver binds issued dispatches to sealed records from the worker. See [driver recovery](docs/RUNBOOK-DRIVER.md).

The standalone helper in `packages/codex/scripts/codex_worker.py` keeps its direct interface. It runs with `workspace-write`, explicit ChatGPT login, and the OpenAI provider. The graph cannot use its output or telemetry to mark work complete. These two paths use no API key.
See [worker containment](docs/WORKER-CONTAINMENT.md) for recovery steps, counters, and limits.

## Requirements

- Python 3.9 or newer. The Python runtime uses only the standard library.
- Claude Code 2.1.x for the root plugin, or the Codex CLI for `packages/codex/`
- `gh` and `git` for the workflow commands. The runtime has no `jq` dependency.
- For `/push` and `/merge`, use a GitHub repo and authenticate `gh` with `gh auth login`. These commands use GitHub through `gh`.
- `pr-review-toolkit@claude-plugins-official` for the PR check in `/workflow`.
- `superpowers@claude-plugins-official` for planning, TDD, debugging, code checks, and worktrees.
- For Claude sandboxed workers: `node`/`npx`, macOS or Linux/WSL2

## Uninstall Claude

```bash
python3 ~/Documents/Github/coderails/uninstall.py
# then: /plugin uninstall coderails
```

MIT. Gary Harrison.
