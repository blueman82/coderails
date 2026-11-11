# coderails Component Reference

This catalog lists Coderails skills, hooks, commands, and scripts. It gives their purpose, conditions for use, and dependencies.
The mandatory `superpowers@claude-plugins-official` plugin supplies general skills for planning, TDD, debugging, code inspection, and worktrees.
The entries come from the source files. See README for an overview.

---

## Table of Contents

1. [Skills](REFERENCE-SKILLS.md#skills)
2. [Agents](REFERENCE-AGENTS.md#agents)
3. [Hook Activation Matrix](#hook-activation-matrix)
4. [Commands](#commands)
5. [Scripts and Libraries](#scripts-and-libraries)
6. [Locations of artifacts and loop data](#artifact-and-state-locations)

---

## Skills

See [the skills catalogue](REFERENCE-SKILLS.md).

## Agents

See [the agents catalogue](REFERENCE-AGENTS.md).

## Hook Activation Matrix

The [hook map in AGENTS.md](../AGENTS.md#hook-event-map-hookshooksjson) and [hooks.json](../hooks/hooks.json) give the hook registrations.
Claude and Codex each have their own Python hook entry points. Stop denials exit with code 2. PreToolUse denials give native permission JSON and exit with code 0.
Payload reads have a five-second deadline. The deadline also applies if only part of the input arrives.

The test gate keeps the full output. When the test command fails, the notice gives measurements and a reader command.
Local hooks redirect and audit an agent that follows the rules. Their files and transcripts stay in the local trust domain.
The trusted GitHub workflow and mandatory GitHub status give the server-side boundary. See [INTEGRITY-GATE.md](INTEGRITY-GATE.md).

### Retained test-gate output

Each execution of the configured test command is one **run**. One run can have many individual tests.
The two providers execute the first line of their configured command through `/bin/bash -c`. The command trust rules continue to apply.
Claude reads `.claude/test_command`. Codex reads the worktree's trusted Git-internal `coderails/test_command`.

If the command succeeds, the gate lets the commit continue. An unsuccessful command makes the gate deny the commit.
The denial gives the run identity, byte and line measurements, full log path, and a quoted reader command.
The gate does not select an automatic tail or byte cap when the platform output budget is unknown.

Each run captures the combined stdout and stderr bytes without changes. This includes runs that succeed and runs with no output.
Each run uses its own directory: `~/.coderails/test-output/<provider>/<project-command-hash>/<run-id>/output.log`.

Completed logs rotate to `output.log.gz` automatically. The cleanup skips active logs.
Compression keeps all captured bytes. The reader can read compressed logs directly.

The sibling `run.json` records the run identity, provider, project, command, exit status, and measurements.
`CODERAILS_TEST_OUTPUT_DIR` overrides the storage root. The default compressed-log budget is 1 GiB across that root.
Set `CODERAILS_TEST_LOG_BUDGET_BYTES` to select a different byte budget.

The cleanup expires the oldest completed logs first. It skips active runs, logs in use by a writer or reader, and its caller's current run.

File locks release automatically when their owner exits. A subsequent cleanup can expire completed logs after their locks release.
Kept content can use more space than the budget. The `run.json` file records `retention.remaining_compressed_bytes` and `retention.over_budget`.

Run metadata, retrieval metrics, and observations of tool transport have their own files.
The cleanup keeps `retention.json` expiry records when it removes log content.
The budget applies to compressed logs only. A metadata-only notification does not prove that the log is empty or expired.

The reader reports an error if the log expired. Its metadata stays available in `run.json`, reader call records, and `retention.json`.

Each provider installation has the same bytes for the helper. Use the helper from the same installation as the hook.
In this checkout, use `hooks/scripts/test_output.py` for Claude or `packages/codex/hooks/scripts/test_output.py` for Codex.
The examples use the Claude helper. Replace the quoted directory with the directory in the denial. Use the Codex path for a Codex run.

```sh
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --all
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --start 2 --end 12
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --search "AssertionError" --before 3 --after 5
python3 hooks/scripts/test_output.py read "/path/to/run-directory"
```

Line ranges start at 1 and include the endpoints. The reader looks for literal text with the context the caller selects.
The reader does not infer the test framework's error syntax.
Full, range, and search reads give JSON with the text, selected source ranges, source and text byte measurements, omitted line count, and `policy_truncated: false`.
The reader can give only the selected text without policy truncation.

Decoding into JSON text can change the byte count, especially if the source bytes are not correct UTF-8.
The captured bytes in the log are authoritative until the content expires.

Without selection flags, the reader gives metadata and instructions only. This also applies after an earlier explicit read.
To get more data, examine a literal search result, ask for more context, or read the full log.
The reader does not predict positions from previous runs because line positions can change.
The compact measurements let someone audit retrieval. Fewer calls or no follow-up calls cannot prove that the agent got sufficient data or used the best policy.

Each reader call writes one compact record. It records the selection, input and output measurements, and response bytes sent by the reader.
It does not duplicate the selected log text. The transport result starts as unknown. Bytes sent by the reader do not prove that a model got them.
Use this command to add a downstream observation to the record for that reader call:

```sh
python3 hooks/scripts/test_output.py observe "/path/to/request-file" --delivered-bytes 420 --truncated yes --source "reported tool transport observation"
```

Replace the example measurements with the values from the observation. Do not infer them from file length or reader success.
The reader keeps observations in different files from the call measurements.
Reads of `output.log` with `cat` or a file-read tool do not use this telemetry. Their transport result is **unobserved**.

If retrieval fails, the log stays. Disposable local fixtures can test these hooks and readers without installed provider accounts.

### Hook library files

| Module | Responsibility |
|---|---|
| `hooks/scripts/hook_common.py` | Bounded payload reads and native hook responses. `read_payload` fails open on host exhaustion (logged).`read_payload_strict` raises `HostResourceError` and is used only by the gates that deny on it (`action_authority_gate`, `destructive_bash_gate`, `enforce_pr_workflow`, `no_edit_on_main`). |
| `hooks/scripts/lib/agentic_loop_path.py` | Resolve the path to loop data for the repository and session. |
| `hooks/scripts/lib/hook_telemetry.py` | Content-free, fail-open JSONL hook telemetry (`hook_telemetry.jsonl`): exit cause, elapsed time, open fds, native-signal children, `deny` vs `ok` cause (set by `deny()`). The copy in `packages/codex/hooks/scripts/lib/` has the same bytes. |
| `hooks/scripts/lib/discipline_common.py` | Read native Claude transcript tools, last text and edited-file count. |
| `hooks/scripts/lib/loop_state_common.py` | Loop detection, ownership, and atomic updates with the `dir_lock` mkdir lock. Live end marker. |
| `hooks/scripts/lib/dir_lock.py` | Stdlib-only mkdir lock with owner pid and start time. Steals a dead owner's lock atomically (see `docs/graph-alignment-measurement.md`, stale-lock policy). |
| `hooks/scripts/lib/loop_evals.py` | Frozen dispatch authority and checksum-bound neutral verdicts for loop end. |
| `hooks/scripts/lib/loop_completion.py`, `loop_proofs.py`, `loop_cost.py` | Standalone checks for work units, the retrospective, proofs from `proof_results.jsonl`, and dated costs. |
| `hooks/scripts/lib/graph_executor.py` | Provider-local lock around the installed pure schema-3 semantic operations. |
| `hooks/scripts/lib/graph_dispatch.py` | Current native ownership envelopes, instruction-source plan, wave collection, and artifact gates for loop end. |
| `hooks/scripts/lib/graph_evidence.py` | Actual parent calls and results, confined native transcript paths, child attribution, and notifications from the harness itself. |
| `hooks/scripts/lib/graph_evidence_bind.py`, `graph_evidence_revalidate.py` | Find and check native child identities and tries. Reject caller provenance, reuse of children, and echoed declarations that work finished. |

The sole source for the pure semantics is `packages/graph-semantics/graph_semantics.py`.
The installer copies the same bytes into each provider. Each adapter keeps its own dispatch, transcript, lock, and artifact behavior.
There are no schema-2 readers or shell fallback writers.

See [execution-graph.md](../skills/agentic-loop/execution-graph.md) for native CLI commands, full-wave collection, and retry and respawn rules.
IDs in the graph identify work. Provider-native labels identify workers. The prompt has explicit worker instructions.
The `work_units` value has no dependency on `graph.nodes`.

## Commands

Claude or the user can invoke these slash commands through `/coderails:<name>`. They give advisory workflow instructions.
Claude must select the command to invoke. Only hooks can apply their controls automatically.

| Command | Description | Key dependencies |
|---|---|---|
| `/coderails:workflow` | Run the full feature workflow: `prep → code → push → review → merge → wiki-ingest → wiki-lint`. It pauses at two points, for the code and iteration loop and for authorization to ship. | Uses the other commands and reads `workflow.config.yaml`. The inspection step uses `pr-review-toolkit`. |
| `/coderails:prep` | Make a safety branch, a feature or bug branch, and optionally a Jira ticket. | Uses `git worktree` and reads `workflow.config.yaml`. It skips Jira if `config.jira` is null or Jira MCP is unavailable. |
| `/coderails:push` | Add changes to the Git index, commit them, and push. Make a PR. Run the engineering-principles pre-flight if the config has `config.engineering_principles_paths`. | Runs `scripts/push.py` and reads `workflow.config.yaml`. A GitHub remote is mandatory. |
| `/coderails:post-review` | Post the SHA-bound inspection artifact as a GitHub PR comment. Check the summary structure, then post a comment with a machine marker. The `/merge` gate refuses if it cannot find the artifact for the current head SHA. | Runs `scripts/post_review.py` and the Python marker CLI. Uses `gh api` to get the comment URL. It does not use `gh pr comment`. It tries to cache the artifact if it finds `progress.json`. |
| `/coderails:post-evals` | Check and post the SHA-bound eval summary as a GitHub PR comment. Read this PR's `evals.json` from `/coderails:task-evals` and calculate `GO` or `NO-GO` in code. Post the result with a machine marker. The `/merge` gate also checks this artifact for the current head SHA. It refuses if an artifact check fails. | Runs `scripts/post_evals.py` and the Python eval marker CLI. |
| `/coderails:authorise` | Only the user types this command (`disable-model-invocation: true`). It runs `scripts/authority.py grant --session ${CLAUDE_SESSION_ID} ...` first. This writes an authority object with `granted_by: command` that can expire or be revoked. The word "autonomous" only prints the command. It grants nothing. An agent with shell access can also run `authority.py grant`. | Runs `scripts/authority.py`. Merge approval stays mandatory. |
| `/coderails:merge` | Merge an approved PR, switch to `main`, and pull the latest commit. The current head SHA must have a Coderails inspection artifact and eval artifact. With `wiki_debt_epoch_pr` and `wiki_path`, `has_wiki_ingest_for_merged_prs` checks the wiki vault's `origin/main` for each PR merged after the epoch. | Runs `scripts/merge.py` with a GitHub remote. It checks PR approval if branch protection is on. It fetches live PR comments for the two artifact checks. |
| `/coderails:init` | Make or migrate a `workflow.config.yaml` for the current project. Writes to `$(pwd)/.coderails/`. See Config resolution for directory lookup. | Uses `git rev-parse` and the Write tool. It gets confirmation before it overwrites a file. |
| `/coderails:test-gate-setup` | Configure the test gate for the current project. Finds the test runner (npm, cargo, pytest, go test, etc.) and writes `.claude/test_command`. | Write tool. Opt-in gate for `test_gate.py` hook |
| `/coderails:assumptions` | List all assumptions about the task, codebase, environment, and data. Mark each `(verified)` or `(inferred)`. | None |
| `/coderails:disconfirm` | Challenge the most recent recommendation. Find the strongest argument that it is incorrect. | None |
| `/coderails:cite-check` (skill at `skills/cite-check/`, not a `commands/` file) | Check a claim from durable sources only (file contents, git output, and new command output). Use no recall or inference. Runs `context: fork` into `coderails:source-auditor` with `background: false`. The auditor cannot read the conversation that gave the claim, which prevents self-verification. The name `cite-check` avoids a collision with the Claude Code bundled skill `/verify`. A project skill named `verify` would override it. | Uses the `coderails:source-auditor` agent. |
| `/coderails:notchecked` | Read recent responses and list each non-trivial claim for which there is no verification. | None |

### Config resolution (`workflow`, `prep`, and `push`) and init scope

Command frontmatter runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`.
Workflow gates use the same `config_path(start_dir)` function. It checks from the cwd to the Git root and selects the nearest `.coderails/workflow.config.yaml`.
If it finds no file, it gives `NO_CONFIG`. The runtime does not use a legacy fallback or merge config files.

Init checks the config before it moves legacy files to Trash. It does not overwrite user values without notice.

### Workflow config keys

The source for `.coderails/workflow.config.yaml` is `config.schema.json` in the repo root. The Codex copy is `packages/codex/config.schema.json`.
The function `load_config(path)` in `scripts/lib/config.py` applies defaults, converts types, and reports results with codes.
The codes are `config_unknown_key` with a suggestion, `config_bad_type`, and `config_unreadable`.
Controlled operations reject an incorrect config. Other readers report their results.

The parser accepts the documented one-level mapping, nested fields, and scalar values. It accepts only that part of YAML 1.2.
If the value must be a string, quote a number or Boolean word.
The command `python3 scripts/lib/config.py resolve-config --json` prints `{path, values, defaults_applied, unknown_keys, findings}`.
Plain `resolve-config` output is unchanged.

The status shows who reads a key. The possible values are `enforced_by_code`, `read_by_prose_only`, and `unused`.
For `read_by_prose_only`, skills and commands read the resolve-config text. Scripts do not read the key.
Regenerate the table with `python3 scripts/lib/config_schema_docs.py --write`.

<!-- config-schema:start -->
| Key | Type | Default | Control ON value | Status | Description |
|---|---|---|---|---|---|
| `project` | string/null | `null` | - | read_by_prose_only | The `/coderails:init` command writes the project name. Only command instructions read this value. |
| `wiki_path` | string/null | `null` | - | enforced_by_code | LLM wiki vault directory (relative to the project dir, or absolute). null disables the wiki gate and the wiki-debt merge gate. |
| `wiki_stale_days` | integer | `30` | - | enforced_by_code | The number of days before a wiki page becomes a staleness candidate. The `scripts/wiki_lint.py stale` command reads it. Without comparable repo sources, the command uses only the date to mark a candidate stale. |
| `wiki_supervision` | string/null | `"discuss"` | - | read_by_prose_only | The wiki-ingest mode is `discuss` or `autonomous`. The `discuss` mode pauses before a write. |
| `wiki_git_worktree` | boolean/null | `true` | - | read_by_prose_only | Use `true` for the PR workflow for wiki commits. Use `false` to commit directly to the vault. |
| `wiki_git_bypass_flag` | string/null | `null` | - | read_by_prose_only | Environment setting for wiki PR creation and merge, for example `BYPASS_REVIEW=1`. |
| `wiki_git_pull_path` | string/null | `null` | - | read_by_prose_only | Source repo pulled after a wiki PR merges. |
| `wiki_debt_epoch_pr` | integer | `null` | - | enforced_by_code | First PR number that the wiki-ingest debt merge gate checks. Without the key, the gate is off. It refuses an empty value or `null`. |
| `worktree_base` | string/null | `null` | - | read_by_prose_only | Parent directory for sibling worktrees. |
| `worktree_script` | string/null | `null` | - | read_by_prose_only | Project script that makes a worktree. |
| `jira` | object/null | `null` | - | read_by_prose_only | Jira settings: `project`, `epic`, `component_name`, `component_id`, `epic_field`, `points_field`, `fix_version`, `mcp_namespace`, and `transitions`. The schema does not check the types of nested keys. |
| `engineering_principles_paths` | array/null | `null` | - | read_by_prose_only | Glob patterns that start the engineering-principles pre-flight in `/coderails:push`. |
| `engineering_principles_skill` | string/null | `"/engineering-principles-python"` | - | read_by_prose_only | The slash command that the pre-flight runs. The value `null` skips it. |
| `sandbox_workers` | boolean/null | `true` | `true` | enforced_by_code | The default is ON. Claude `graph_dispatch.plan()` reports `sandboxed` or `in-process-fallback:<reason>` for U3 nodes. While ON, Codex refuses native U3 spawns. Use the OAuth graph driver and its sealed worker records. Output from a standalone worker cannot complete a graph node. OFF explicitly permits use of the parent sandbox behavior. |
| `subagent_identity_gate` | string | `"on"` | `"on"` | enforced_by_code | The default `on` denies an untyped Bash subagent in a graph-bound Claude session. Use `off` to disable that hook. |
| `action_authority` | string/null | `"enforce"` | `"enforce"` | enforced_by_code | The default `enforce` makes signed receipts mandatory for guarded merges and pushes. Use `advisory` for warnings or `off` to disable this receipt gate. The check refuses an incorrect configuration. |
| `diff_manifest` | string/null | `"enforce"` | `"enforce"` | enforced_by_code | Diff-manifest publication gate for `push.py`, `merge.py`, and direct-merge hooks. The default `enforce` uses the policy in the plugin. Strict config readers refuse incorrect values. |
| `review_passes` | string | `"enforce"` | - | enforced_by_code | The publication gate checks the reviewer rules in `policy/review_policy.json`. The default is `enforce`. The value `off` skips the check. All other values apply it. |
| `eval_level` | string | `"enforce"` | - | enforced_by_code | The publication gate checks derived eval level and suite integrity with `policy/surface_policy.json`. The default is `enforce`. The value `off` skips the check. All other values apply it. |
| `diff_manifest_policy` | string/null | `null` | - | enforced_by_code | Path to the diff-manifest policy JSON. If there is no key or its value is `null`, the reader uses `policy/diff-policy.default.json`. |
| `integrity_review` | object/null | `null` | - | enforced_by_code | Integrity attestation settings. |
| `integrity_review.enabled` | boolean/null | `false` | - | enforced_by_code | After the server rule is active, `true` makes the `integrity-review` status from `github-actions[bot]` mandatory on the current PR head. |
| `integrity_review.machine_user` | string/null | `null` | - | enforced_by_code | Deprecated. If `enabled` is not `true`, local checks accept only the nonempty legacy login as the status author. |
| `evals` | object/null | `{"require_signatures": true}` | - | enforced_by_code | Eval settings. |
| `evals.require_signatures` | boolean/null | `true` | `true` | enforced_by_code | The default `true` makes eval artifact signatures mandatory. The signer makes a local key on first use. It refuses to sign without `ssh-keygen`. Use `false` to opt out. |
| `memory` | object/null | `null` | - | enforced_by_code | Typed-memory settings. |
| `memory.backend` | string/null | `"muninn"` | - | enforced_by_code | The default `muninn` uses Muninn as the authoritative typed-memory store. If Muninn is unavailable or refuses an operation, the adapter gives a cause code. Use `off` to disable typed memory. The adapter logs `memory_backend_off` and does not read or write Markdown. It refuses other values with `memory_backend_invalid`. |
<!-- config-schema:end -->

## Scripts and Libraries

| Entrypoint/module | Responsibility |
|---|---|
| `scripts/push.py`, `merge.py` | Git index, commit, and PR workflow. Merge gates for inspection, eval, integrity, and wiki debt on the current head. |
| `scripts/post_review.py`, `post_evals.py` | Inspection grammar and cache, eval structure checks, neutral grading, and recorded smoke execution. |
| `scripts/lib/git_common.py` | GitHub repository and PR operations. Selects the newest trusted artifact for the specified head. A `github.com` remote is mandatory. |
| `scripts/lib/{config,review_artifact,eval_artifact,artifact_io}.py` | Shared root-provider config and structured artifact operations. |
| `scripts/lib/memory_adapter.py`, `memory_request.py`, `memory_current.py`, `memory_support.py` (+ byte-identical Codex mirrors) | Consumers of decisions, standing instructions, lessons, and handoffs use task calls, receipts for those calls, and the corresponding current Notes. Full validation keeps revision, body, conditions, expiry, and selected E-id/ref/hash/quote mappings. Privacy class is unknown. Physical scope, redaction, and authority checks are explicit. See [memory adapter limits](#memory-adapter-limits). |
| `scripts/lib/proof.py`, `scripts/lib/proof_results.py` (+ byte-identical `packages/codex/scripts/lib/` mirrors) | The controller uses `proof.py freeze`, `proof.py run`, `proof.py status`, and `proof.py disposition`. It runs each frozen `cmd` verbatim through `/bin/bash -c` and appends hash-chained rows to `proof_results.jsonl`. The two gates for loop end use `proof_results.verify`. See `docs/RUNBOOK.md`, "Proof gate blocked a `complete` declaration". |
| `scripts/lib/decision_record.py` (+ byte-identical Codex mirror) | Append a hash-chained local decision with the graph lock. Release the lock before calling or examining Muninn. Patch only the row with the same session, loop, and hash. Keep the R-id, window, and project. Do not write pending, unknown, or no-change data. See [record-decision entry point](#record-decision-entry-point) for recovery and hashing. |
| `scripts/lib/{retro,retro_check,teardown_steps}.py` (+ byte-identical `packages/codex/scripts/lib/` mirrors) | `retro.py assemble <state-dir> --session S [--free-file F]` builds schema-3 `retro.json` from loop data, eval, proof, cost, diagnostic log, and teardown sources. See [retrospective assembly](#retrospective-assembly). |
| `scripts/lib/handoff_derive.py` (+ byte-identical Codex mirror) | Read-only skeleton from the current graph, local decisions bound to a call, other verified current decisions for the same task, lessons, and proofs. Decision and lesson records keep revision, quote, conditions, expiry, and verification metadata. Discovery of more calls reads bounded global metadata. It selects by project and task before it reads the records and joins on the same K-id and revision in the receipt. Pending, unknown, and degraded rows stay explicit. It does not send or retry a memory call or write an import. |
| `scripts/lib/{eval_validation,eval_execution}.py` | Eval criteria and command/control verification. Gate smoke runs in a detached worktree at the trusted SHA. |
| `scripts/sandbox/spawn_sandboxed_worker.py` | Check dispatch before making a scratch directory. Run an isolated Claude worker through pinned srt and keep its exit status. |
| `scripts/sandbox/{render_settings,sandbox_probe}.py` | Make the explicit write containment settings and check which filesystem writes can succeed. |
| `.github/workflows/integrity-review.yml`, `scripts/integrity-gate/integrity_actions.py` | Trusted GitHub workflow checks inspection records, evals, and diffs. It uses the built-in token and runs no PR code. |
| `scripts/integrity-gate/setup.py` | Preview and activate the ruleset bound to the GitHub app after a live candidate status. |
| `install.py`, `uninstall.py` | Install or remove each provider on its own. Keep user data, run preflight checks, and offer a read-only dry run. |
| `launchd/*_routines.py`, `*_dashboard_agent.py` | Install launch agents at literal paths and check unload and removal. |
| `scripts/quality/check.py` | Strict checks for source, format, typing, length, and files that the installer makes. |
| `hooks/scripts/tests/run_all.py` | Find native Python suites, report skips, and fail if all suites skip. |

### Memory adapter limits

The standalone adapter CLI can use only retired numeric-K/schema-v2 normal-only operations.
Shared transport, backend, cause codes, and the Markdown view writer stay available. There is no Markdown fallback. See `docs/RUNBOOK.md`.

### Retrospective assembly

The receipt sequence is `proof_run < decisions_flushed < orders_prepared < retro_assembled`.
Flush pending decisions before the last step that prepares the standing instructions. Then assemble the retro.
The D4 `orders.py prepare` command records `{repo_dir,state_dir,session_id,loop_id,revision,progress_sha256}` and binds the planned records in `orders-prepared-<sha256(loop_id)>.json`.

The native gate for loop end calculates the source hashes again and checks the source-bound records from the step that prepared the standing instructions.
The `orders_ticked` observation occurs after durable loop end and stays out of the frozen hashes.
Exit 0 means assembled, 2 refused, and 3 assembled with a report of memory degradation.
See `docs/RUNBOOK.md`, "Retro rejected at completion, or a handoff printed `degraded`".

## Artifact and State Locations

| Artifact | Location | Committed? | Use |
|---|---|---|---|
| `workflow.config.yaml` | First `.coderails/workflow.config.yaml` from the cwd to the Git root (`$(pwd)/.coderails/` for `/init`) | No. Git ignores this local project setup. | Config for the project's Jira, wiki, worktree, engineering-principles, and sandbox workers. The `/coderails:init` command makes or migrates it. Share values through the usual project configuration procedure. |
| `.claude/test_command` | Project working directory | Yes (project-local) | Plain-text file containing the test command. Made by `/coderails:test-gate-setup`. Activates `test_gate.py`. |
| Codex `coderails/test_command` | Worktree Git metadata, resolved by `git rev-parse --git-path coderails/test_command` | No | Trusted native Codex test-gate command. A workspace file cannot configure it. |
| Test-gate runs and reader records | `~/.coderails/test-output/` or `CODERAILS_TEST_OUTPUT_DIR` | No | Completed logs automatically rotate and compress. Active logs stay untouched. Run metadata, retrieval records, and tool transport observations have their own files. |
| Specs from brainstorming | Session-local scratch path (`docs/coderails/specs/` is gitignored) | No. Git ignores the files. | The `superpowers:brainstorming` skill writes the spec after agreement on the design. The owner decided on 2026-07-11 to use `coderails:handoff` or a wiki page for a durable record. |
| Plans from writing-plans | Session-local scratch path (`docs/coderails/plans/` is gitignored) | No. Git ignores the files. | The `superpowers:writing-plans` skill writes the plan. The same owner decision of 2026-07-11 applies. |
| Agentic loop `progress.json` | `~/.coderails/agentic-loop/<repo-or-cwd-slug>/<session_id>/progress.json` | No. Temporary data external to the repo. | Records the loop position. The `agentic_loop_path.py` helper uses the session and repo, shared across worktrees. It uses the cwd if there is no Git repo. If the canonical slug has no file, it checks `<base>/*/<session_id>/progress.json` for the same session. This finds data with a different slug from a previous helper or a cwd change. |
| Agentic loop `spec.md` | Same directory as `progress.json` | No. Temporary loop data. | The agentic-loop orchestrator writes the spec for loops with three or more units. It does not publish it in a PR. |
| Agentic loop `plan.md` | Same directory as `progress.json` | No. Temporary loop data. | The agentic-loop invokes `superpowers:writing-plans` to write the plan. The orchestrator reads it again after compaction to get the scope. |
| `evals.json` (pr scope) | The calling workflow sets the path, for example in the working tree or worker prompt. | No. The durable artifact is the SHA-bound `coderails-eval-summary` PR comment. | The workflow makes and freezes this file for the PR. The `/coderails:post-evals` command validates and posts it through `scripts/post_evals.py` and `scripts/lib/eval_artifact.py`. |
| `evals.json` (loop scope) | Same directory as `progress.json` | No. Temporary loop data. | The `loop_state_guard.py` hook reads the file when `progress.json` has `work_units` ≥ 1. It blocks `Stop` if it cannot find the file. |
| Discipline log | `~/.claude/discipline.log` (or `$CLAUDE_DISCIPLINE_LOG`) | No | Hooks append to the structured `key=value` log each time they run. Do not commit the log. |
| LLM Wiki vault | `config.wiki_path` (set in `workflow.config.yaml`) | Its own repo or vault | The `wiki-ingest`, `wiki-lint`, and `wiki-query` skills work with the vault. Browse it in Obsidian. |

### The ephemeral vs committed boundary

The loop's `spec.md`, `plan.md`, and `progress.json` live in `~/.coderails/agentic-loop/`. That directory is external to the repo and Claude configuration tree.
The files hold temporary data for one orchestrator run. Use `coderails:handoff` to give the work to a human.
Put durable records in the wiki or in a repository document that the owner explicitly approves.

### Record-decision entry point

Each provider's graph CLI uses its native lock to run `decision_record.record`:

```text
graph.py record-decision <progress.json> --session <id> --loop-id <loop-id> --revision <revision> --phase <phase> --decision <text> [--flip-condition <text>] [--unit <id>] [--cite-quote <verbatim user quote>]
graph.py flush-decisions <progress.json> --session <id> [--cite-quote <verbatim user quote>]
```

Read the current `loop_id` and `revision` from `progress.json` before you use these commands for decisions.
Do not append rows to `progress.json` by hand.
With the graph lock, `record-decision` checks the caller's loop ID and revision. It checks the current hash chain before it appends.
The `flush-decisions` command checks the chain before it retries pending or degraded rows.

1. With the lock, append the local row (`seq`, `prev_sha256`, `row_sha256`, `muninn: {state: syncing}`).
2. Release the lock. Send a task call or examine its saved receipt.
3. With the lock again, patch the row's `muninn` field.

The result has `{recorded, seq, muninn: {state, id, reason_code}, exit_code}`. The exit codes are:

- 0: Written or disabled.
- 3: Pending, degraded, or unknown. The command shows a cause code, logs `decision.sync/degraded/<code>`, and keeps the local row.
- 2: Refused. No write occurs if the session, loop, or revision is incorrect, or if the phase or decision is empty.

Teardown uses `flush-decisions` to retry pending and safely degraded rows. The recovery step examines a saved R-id again.
An unknown result without that binding and a sync in flight remain `decision_sync_unknown`. The command does not resubmit automatically.
The mutable save observation is external to the authored row hash.
The `memory_counters.memory_counts` function counts `decision.record` and `decision.sync`.

### Integrated dispatch inputs and counter summaries

For a new nonempty unit manifest, give `add-unit --worktree` the absolute path to a clean Git checkout.
The two providers record the source manifest binding. The dispatch contract includes that binding, the checkout HEAD, and current typed lessons.
The `assign-worktree` command binds the same source fields for pending units.

Before the loop lock, `graph_lessons.py` runs the provider's `lessons.py query --format contract` for the loop's repo-key directory.
The `graph_dispatch_inputs.py` check makes sure the owner, loop, and revision did not change during the read.
Native and local driver authorization check the source and lesson snapshot again before consuming a try.
Unavailable or stale lessons cause a refusal with a code.

The dispatch, spec, stop, and worker counter CLIs accept `--trace-json` on stdin from `measure_graph_alignment.py --json`.
Each reads `trace.by_reason` and keeps local recovery entries. The worker counter also keeps the mapping of recorded decision entries for each source.
The counters refuse null or malformed summaries. They also refuse `--since` with aggregate input. The measurement script stays unchanged.
