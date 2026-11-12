# Hook behavior

The paths in code refer to the repo root. For the installed registrations, see [the hook table in AGENTS.md](../AGENTS.md#generated-hook-registration).

## Hook behavior by script

### Session start and prompt hooks

- **`inject_bootstrap.py` at `SessionStart`.** Adds the `using-coderails` skill to each new session. It runs silently.

- **`remember_inject_cap_guard.py` at `SessionStart`.** Gives warnings only by default. It gives a warning if the other plugin's `session-start-hook.sh` has no `REMEMBER_INJECT_MAX_BYTES` cap. The default cap is 8000. It records one warning for each plugin version in `~/.claude/coderails/remember_inject_cap_warned`.

  Set `REMEMBER_INJECT_CAP_AUTOWRITE=1` to let the hook patch the `for MFILE...done` loop in that file. The patch replaces a full literal block from `hooks/patches/`. If the block differs, the hook refuses and tells the user to apply it by hand. It keeps one rolling `.coderails-bak-*` copy. The patch does not change the enclosing `if`. The hook does not block session start.

- **`inject_context.py` at `UserPromptSubmit`.** Puts `[ctx]` (cwd, branch, date) before the prompt. It adds the discipline reminder to the first prompt in a session. It runs silently.

- **`autonomous_gate.py` at `UserPromptSubmit`.** Adds context only. It checks for "autonomous" as a word in the raw prompt. Uppercase and lowercase letters give the same result. It does not interpret negation, quotes, or questions.

  If the session has no live authority, the hook adds `additionalContext` with "no authority granted; type /coderails:authorise". It logs `autonomous/ignored/authority_phrase_ignored`. The phrase "crack on" does not give the hint.

  Only the typed `authority.py grant` grants authority. `/coderails:authorise` runs it before the skill and sets `disable-model-invocation: true`. This protects against accidental grants or text copied into a prompt. An agent with the same user permissions can run the grant command itself. See [the authority object decision](decisions/e3-authority-object.md).

### Stop hooks

- **`check_confidence_labels.py` at `Stop` and `SubagentStop`.** Advisory in and out of loops. For a reply of 200 characters or more, the hook checks for `(verified)`, `(inferred)`, or `(guess)`. If there is no label, it gives an `[discipline-advisory]` in `additionalContext`. The hook logs `demoted=1 reason_code=confidence_label_missing` and adds an `outcome=demoted` telemetry row. It exits with code 0.

  It reads `last_assistant_message` directly to prevent a race with the parent transcript write. At `Stop`, it exits with code 0 without the check if `CODERAILS_HEADLESS_RUN=1`. The user directed the demotion when the e1 criteria were not met. See `docs/decisions/2026-10-04-not-in-gate-demotion.md`.

- **`check_verify_loop.py` at `Stop` and `SubagentStop`.** Advisory only. A bullet in `## Did Not Verify` without `(unverifiable: <reason>)` gives an advisory. The hook also checks for a missing section after a turn with three or more files. It puts `[discipline-advisory]` in `additionalContext` and logs `demoted=1 reason_code=verify_loop_missing`. It adds an `outcome=demoted` telemetry row and exits with code 0.

  `loop_state_guard` and `loop_stall_guard` can block at `Stop` only. At `Stop`, `check_verify_loop.py` skips the check if `CODERAILS_HEADLESS_RUN=1`.

- **`voice_announce.py` at `Stop`.** Uses macOS `say` to speak a notice for `complete`, `waiting-on-human`, `stopped`, or `stall`. It stays silent when there is no loop or no text. It sets a minimum interval between notices of the same type. It runs first in the Stop array and always exits with code 0.

- **`loop_state_guard.py` at `Stop`.** Blocks an active loop without session-owned `progress.json`. It gives this block one time for the same session and invocation count. It gives no such grace for a session mismatch or stale `complete` record.

  If `work_units` is one or more, the hook checks the sibling `evals.json`. It checks for `GO` or `VERIFICATION_LEVEL0`, text in `verification_justification`, and a correct grading stamp. It blocks on `ABSENT`, `NO-GO`, `UNJUSTIFIED`, or `UNSTAMPED`. If there is no `work_units` field, the eval check lets the stop continue.

- **`loop_stall_guard.py` at `Stop`.** Blocks an active unfinished loop if there is no current-turn `stops[]` row. It reports `stop_row_missing`. It shares the missing-`progress.json` grace from `loop_state_guard` and uses its log line.

  For `complete`, the hook checks for a well-formed `retro.json` with `schema_version` 3 or higher. It applies `retro_check` to find stale source hashes, a damaged decisions chain, or a missing teardown step. It also checks each frozen proof in a sibling `proof.json` against the controller's records. It blocks if a proof did not run or its last run did not succeed.

  For schema 3, no `proof.json` also blocks unless `progress.json.proof_disposition` is `none` or `none: <reason>`. A sibling `withdrawn_proofs` array has more checks. The last proof run must have verdict `failed` or `timeout`, and the proof must have `withdrawn_reason`. Its `id` must not be in `.proofs`. The combined limit is 100 entries.

  For an unresolved native graph, the block gives one notice for the loop, revision, session, active wave, and hard stop. It can show the notice again after 900 seconds while the stall continues. The notice gives `graph.py summarize` status. For a silent wave, it makes one `recover-wave` try. That try can start a duplicate if the first worker is alive but silent. The `retry.max` limit applies.

  The hook writes the marker after it prints the notice. It removes markers for earlier revisions of the same loop. Codex `graph_completion_guard.py` uses the same helper and key. Codex writes `decision: block` JSON with `reason` and `systemMessage` to stdout and exits with code 0. Claude writes to stderr and exits with code 2.

- **`unregistered_loop_guard.py` at `Stop`.** Gives a nudge if the session has three or more Agent-dispatch turns, no `progress.json`, and no `agentic-loop` invocation. It does not block.

- **`offload_push_guard.py` at `Stop` and `SubagentStop`.** Checks the last reply for a `git push` to `main` or `master`. Gives a nudge if the reply also tells the user to do the push. Example cues are `! `, "your own shell", and "run this yourself". It gives at most one nudge in a session and does not block. It runs last in the two arrays.

### Bash and publication hooks

- **`destructive_bash_gate.py` at `PreToolUse` for Bash.** Blocks `rm -rf`, bare `git push --force` or `-f`, `git reset --hard`, and the SQL commands `DROP TABLE/DATABASE/SCHEMA` and `TRUNCATE TABLE`. It also blocks `dd if=`, `mkfs.*`, `chmod -R 777`, and `git commit --no-verify`. Other blocked commands are `git clean -f` or `--force`, `find -delete` or `--delete`, `truncate -s` or `--size`, and `shred`.

  The hook blocks reads or writes to a literal `.env` path. It lets `.envrc`, `.env.example`, `.sample`, `.template`, and `.dist` through. It conditionally lets `--force-with-lease` through.

  On `main` and `master` it also blocks Bash edits to source and plugin Markdown. These include `sed -i`, `perl -i`, redirects, `tee`, `cp`, `mv`, and `dd of=`. It rejects backticks, `$(...)`, `<(...)`, and `>(...)` in arguments to `push.py`, `merge.py`, `post_review.py`, and `post_evals.py`.

- **`enforce_pr_workflow.py` at `PreToolUse` for Bash.** Blocks `gh pr create` without `/coderails:push`. It blocks `gh pr merge <N>` and `scripts/merge.py <N>` without `review-pr <N>`. One invocation for that PR satisfies subsequent merges for the same PR.

  It blocks `git merge` on `main` or `master` without `review-pr` since the last merge, and consumes the invocation on use. It also blocks `git push` to those branches without `review-pr`. It reads subagent transcripts. It skips `merge-base`, `merge-file`, `merge-tree`, and the options `--abort`, `--continue`, `--quit`, and `--skip`. With no `workflow.config.yaml`, it does nothing.

  After the `review-pr` check, it also checks for a SHA-bound `GO` eval artifact for the head. `gate_smoke_verify` runs the `cmd` and `negative_control` again for each eval with `verification_level` 1 or higher. It uses a detached worktree at the trusted SHA. If this check does not succeed, it blocks the merge regardless of the other checks.

- **`test_gate.py` at `PreToolUse` for Bash.** Blocks `git commit` if the tests fail. Turn it on for each repo that uses it. Keep full stdout and stderr for each run. Report measurements and the reader path.

- **`verification_volume_ceiling.py` at `PreToolUse` for Bash.** Blocks the third and subsequent calls to `hooks/scripts/tests/run_all.py` or `post_evals.py validate-structure` for a work unit (branch). The limit has no override.

- **`action_authority_gate.py` at `PreToolUse` for Bash.** The default `action_authority: enforce` checks a single-use signature. The signature covers the command, repo, ref, SHA, session, and loop. This default applies with no config. Invalid config denies operations that the hook checks.

  Set `advisory` to log and give a warning, or `off` to disable the receipt gate. The owner approves each operation at a terminal. Passphrases are optional. An autonomy grant cannot replace the receipt.

  The same user that runs the agent can write the user-tier signers file. This is a cooperating-agent safeguard. It cannot show that a different user gave approval. If an unexpected error occurs, the hook denies the guarded command in `enforce` mode or with a loaded live authority. In `advisory` mode without live authority, the error lets the command continue. See [the receipt decision](decisions/p3-human-only-minting.md) and [the runbook](RUNBOOK.md).

- **`pr_publication_gate.py` at `PreToolUse` for Codex Bash.** On by default in `packages/codex/hooks/hooks.json`. It applies the Codex version of the `enforce_pr_workflow` merge check. It uses the same publication gate.

  The hook denies `gh pr merge`, `gh api .../merge`, or `merge.py` if `scripts/lib/publication_gate.evaluate` gives a violation. It gives the code first, for example `diff_manifest:denied_path`. It also denies a PR it cannot resolve or a command that gives an internal error.

  Set `diff_manifest: off` to turn off the manifest check. Set `review_passes: off` or `eval_level: off` to turn off those checks. Trust the hook in `/hooks`. See the publication gate limits in [AGENTS.md](../AGENTS.md).

- **`reviewer_bash_allowlist.py` at `PreToolUse` for Bash.** Applies to `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, `security-reviewer`, and `source-auditor`. The list comes from `capabilities/profiles.json`. The hook takes no step without a guarded `agent_type`.

  It lets the role use one read-only command. These are `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, and `sha256sum`. It also lets the role use `git status`, `git log`, `git diff`, `git show`, `git blame`, `gh pr view --json`, and `gh pr list --json`. It denies chaining, redirection, substitution, interpreters, and the flags `--output`, `--pre`, and `--ext-diff`.

  It checks the absolute path of `scripts/capability.py`, with `--json-args '<json>'` and a tool from `capabilities/profiles.json`. Tool names are `repo.inspect`, `diff.read`, `tests.run`, and `pr.comment`. It denies a tool that the caller's entry does not grant with `capability_denied_<tool>`. The check uses typed arguments and the argv path. The harness does not supply a typed tool for this Bash path.

  The five guarded agent files list only their own MCP tools. The hook adds protection for installs where an agent file has `Bash`. Codex has no Bash hook for an individual agent. It uses `sandbox_mode` and instructions. See [the tool access guide](CAPABILITIES.md) and [the Bash allowlist decision](decisions/e2-reviewer-bash-allowlist.md).

- **`subagent_identity_gate.py` at `PreToolUse` for Bash.** The hook checks `progress.json` for `graph` and the current session ID. In that session it checks a Bash call with a nonblank `agent_id`. It blocks if `agent_type` has no text, is not a string, or is unavailable. It reports `bash_agent_type_absent` in the discipline log and telemetry.

  It does not block other calls. The safeguard works only if Claude Code fills in `agent_id`. Codex does not supply `agent_type` or `agent_id` at `PreToolUse`. Codex uses `shell_tool = false` role files and contained role sessions. See [the tool access guide](CAPABILITIES.md).

### Other tool hooks

- **`autonomous_gate.py` at `PreToolUse` for `AskUserQuestion`.** Blocks this tool with `authority_deny` if a live authority for the session has `autonomous_decisions` in `scope`. It does not use expired, revoked, or torn authority. It also skips authority for a different session or with an empty scope. Earlier `crack_on_active` flags have no effect. The loop hard-stops use `LOOP-STOP` declarations.

- **`no_edit_on_main.py` at `PreToolUse` for `Write`, `Edit`, and `MultiEdit`.** On `main` or `master`, the allowlist has `.md`, `.txt`, and `.rst`. It also has `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, `.cfg`, `.gitignore`, and `LICENSE`. It blocks other files.

  If the file's repo has `.claude-plugin/plugin.json`, the hook also blocks plugin-source Markdown (`skills/*/SKILL.md` and `commands/*.md`). It blocks edits to `.claude/settings.json` and `.claude/settings.local.json` on all branches in all repos.

- **`comment_citation_gate.py` at `PreToolUse` for `Write`, `Edit`, and `MultiEdit`.** Denies new or changed comments that use session-artifact labels. Examples are `E#:`, `F# fix/design`, `CHANGE B#/C#`, `Task A#`, and `TA-I#`. Others are "reviewer finding", `eval E#`, `WU#:`, `C2`, "per the plan/design/session", and "per F#". It checks only fields with comments and skips `.md` files. It lets `PR #NN` through because the PR is a durable artifact.

- **`wiki_taxonomy_gate.py` at `PreToolUse` for `Write`, `Edit`, and `MultiEdit`.** The hook uses `.coderails/workflow.config.yaml`. The write's Git root must be the directory at `wiki_path`. Resolve a relative `wiki_path` from `CLAUDE_PLUGIN_ROOT`. Two or more of the parsed directories must be on disk as a second check.

  The hook reads `page_types` and `structural_dirs` from `wiki.schema.json`. It blocks writes to top-level directories that the schema does not list. If there is no schema or it has an error, it logs `wiki_schema_missing` or `wiki_schema_invalid` and lets the write continue. The drift test checks the `## Page types` tables in `AGENTS.md` against the schema.

  It lets the write continue if the repo has no config or is not a Git repo. It also lets the write continue if `wiki_path` is null or cannot resolve, or if the schema has no page types. Writes to a different vault or with fewer than two parsed directories also continue. It lets `raw/`, files at the vault root, and dotfile directories such as `.git/`, `.obsidian/`, and `.claude/` through.

- **`agent_only_gate.py` at `PreToolUse`.** Nudges the orchestrator to use `Agent` for inline work. Set `AGENT_ONLY_GATE_ENFORCE=1` to block. It checks `Bash`, `Edit`, `Write`, and `MultiEdit`. It also checks `Read`, `Grep`, `Glob`, `WebFetch`, and `NotebookEdit`.

  If the payload has `agent_id`, the hook lets the call continue. A live check showed that field on a dispatched subagent call. Without the field, the hook also lets Bash run one allowed full workflow command. These commands use `gh`, `git`, `scripts/push.py`, `scripts/merge.py`, `scripts/post_review.py`, or `scripts/post_evals.py`. An interpreter prefix is optional. The command must have no chaining or substitution.

  For other calls it gives `additionalContext` by default and `deny` if the flag is on. It does not gate `Agent`, `TodoWrite`, `TaskCreate`, `AskUserQuestion`, or `ExitPlanMode`.

- **`agent_model_routing_nudge.py` at `PreToolUse` for `Agent`.** Advisory only. If there is no `tool_input.model`, it checks the dispatch description or prompt. For a mechanical word, it suggests `haiku`. Examples are `rename`, `format`, `boilerplate`, `scaffold`, `reformat`, `relabel`, and `find-replace`. A complex word such as `design`, `architecture`, `redesign`, or `re-architect` gives `opus` advice. It stays silent if the call sets `model`, if no word matches, or if the two lists match.

- **`loop_dispatch_guard.py` at `PreToolUse` for `Agent`.** Checks each graph-bound native call for the v2 `CODERAILS_GRAPH_DISPATCH` envelope and the rendered contract sections from `begin-wave`. It finds the record in `graph.dispatches` and checks each ownership field. It recalculates the sections digest from the stored contract. The dispatch can be used one time.

  The hook checks the role in the contract. Scout roles in `guarded_agents` use `coderails:<role>`. Other roles can use that or `general-purpose`. A different role gives `role_mismatch`.

  The hook logs `dispatch_missing_envelope`, `dispatch_unknown_id`, `dispatch_foreign`, `dispatch_stale_revision`, `dispatch_replayed`, `dispatch_contract_altered`, `dispatch_sections_missing`, or `role_mismatch` in `recovery-trace.jsonl`. If the roster has work units, implementation needs owned frozen loop evals. The frozen suites bind the session and loop, without binding the changing graph revision.

  The hook blocks if ownership is unavailable or belongs to a different session. The Python sandbox launcher calls the same guard before it sets up scratch space. To complete the loop, use neutral grading, native records, proofs, and the retrospective.

## Hook limits

### Command checks

- **Bash blocklists.** The lists check named command patterns. They do not check obfuscated commands or filenames from shell parameters. They also skip quoted paths with spaces, here-docs, shell substitutions, and writes with `python -c open(...)`.

- **Eval checks.** `/coderails:merge` checks evals with or without config. The `enforce_pr_workflow` check on `gh pr merge <N>` needs config. It is off with `NO_CONFIG`. A raw `git merge` or `git push` to `main` or `master` has no PR number for the eval check.

  The commands that check evals run `scripts.post_evals.smoke_verify`. The check blocks if `gh` cannot fetch, if there is no artifact or it grades `NO-GO`, or if re-execution does not succeed.

- **`no_edit_on_main` allowlist.** The hook blocks `.sh` files on `main` but lets edits to `.json` and `.yaml` config through. Use the settings JSON `Write` or `Edit` permission for a permitted override.

- **Command parser.** The two plugins use the same literal command parser. It finds Git, GitHub, and script commands that it knows in shell text. It records literal directory changes. It checks a literal `eval` body without evaluating shell parameters or building commands at run time.

  It cannot resolve aliases or shell functions. A quote with no closing mark or some wrapper options can make a command unclear. Do not issue a receipt for an unclear operation. The policy file protects plugin source paths. Telemetry uses the `argv/` prefix. See the command parser entry in `docs/RUNBOOK.md`.

### Hook limits during a session

- **Wiki steps after a merge.** `/wiki-ingest` and `/wiki-lint` are advisory slash commands. Hooks do not make them mandatory.

- **Stop loops.** `check_verify_loop`, `check_confidence_labels`, `loop_state_guard`, and `loop_stall_guard` stop their checks if `stop_hook_active=true`. The two loop guards block at most one time in a turn. The two discipline lints are advisory and exit with code 0. `voice_announce` reads the flag with the shared loop helper. It always exits with code 0.

- **Test sequence.** `test_gate` checks if tests succeed at commit time. It does not check if the author wrote the tests first.

- **Test output.** The two providers keep full logs for each command in `~/.coderails/test-output/`. Set `CODERAILS_TEST_OUTPUT_DIR` for a different directory. Each provider's `hooks/scripts/test_output.py` measures reads of the full log, a line range, or a literal lookup. The default read gives metadata and guidance.

  The agent can read more of the log without predicting line ranges across runs. The bytes the reader gives do not show what the model gets. The metric has no data for file reads that do not use the reader.

  Completed logs compress automatically. The default compressed budget is 1 GiB. Set `CODERAILS_TEST_LOG_BUDGET_BYTES` to change it. The cleanup expires the oldest completed logs first. It keeps active logs and the most recent completed run.

  The protected logs can use more than the budget. Compact metrics and expiry records stay available. See [retained test-gate output](REFERENCE.md#retained-test-gate-output) for use and measurement limits.

- **Authority objects (E3).** `scripts/authority.py grant --session <id> --max-prs N [...]` writes an object with `granted_by: command`. The Claude `/coderails:authorise` command and the Codex `authorise` skill use it. The word "autonomous" only gives a hint. There is no `create` alias.

  The grant writes `<loop dir>/<session_id>/authority.json`. Use `inspect`, `narrow`, or `revoke` to manage it. The two providers use the same validator. It refuses an object without `granted_by: command`. Earlier `crack_on_active` flags have no effect. Expiry and revocation end the denial.

  The two gates read the loop root from `CLAUDE_AGENTIC_LOOP_DIR`. Codex uses `CODERAILS_AGENTIC_LOOP_DIR` if necessary. One `authority.py revoke` covers the two providers. If a grant does not succeed, it reports `authority_refused_write_failed` and grants nothing.

  An agent with file access can write the unsigned `granted_by` label. This is a safeguard for agents that follow the rules. See [the authority object decision](decisions/e3-authority-object.md) and [the runbook](RUNBOOK.md).

- **Internal decisions.** Hooks cannot see how Claude decides to invoke a skill, handle ambiguity, or check memory. They cannot make those decisions mandatory.

- **Subagent startup.** There is no `SubagentStart` trigger. Subagents get `using-coderails` only from the orchestrator's system prompt.

- **PR reviewer records.** `/coderails:post-review` checks the summary structure. It shows that a SHA-bound artifact with a checked summary was posted. The check applies to the general artifact and each entry in `passes[]`. It cannot show who wrote the summary or how they examined the change.

  The `review-pr` arm of `enforce_pr_workflow` can change from block to nudge only after a live check of the artifact gate. Do not make that change before the live check. That would leave a period with no active gate.

- **Role and `effort`.** Phase 2.8 of `agentic-loop` sets the role and `effort` for each task. Roles are `fast-mechanical`, `default`, and `frontier`. See the Phase 2.8 table and `model-routing.md` for defaults and Fable escalation.

  The assignment is checked when agents start in Phases 2, 2.5, 3, 3a, 9, and 10. `agent_model_routing_nudge.py` is the only hook for this. It gives advice only. It cannot show that the role is correct. A worker with the `frontier` role must clear all PR gates.

  Phase 2.8 permits a judgment between `default` and `frontier`. A strict gate could distinguish that judgment from a disallowed start only by trusting the agent's report of why it used that role.

- **`agent_only_gate` scope.** A live Claude Code 2.1.220 probe showed no `agent_id` on top-level Bash and Agent calls. A subagent Bash call had `agent_id` and `agent_type`. The three calls had the same `session_id`, so it cannot distinguish them.

  The hook can identify the level of a call. It cannot show that an orchestrator follows the rules. It cannot see top-level work until the session calls a tool for that work. A hard top-level block by default would block the repo's publication path. Its workflow commands use `gh`, `git`, or `scripts/*.py` inline.

  Set `AGENT_ONLY_GATE_ENFORCE=1` for a hard block with the same allowed workflow commands. The live probe used a plain headless session. It did not check `claude --agent <name>`, which can reportedly set `agent_type` on top-level calls.

- **Headless Stop checks.** `check_confidence_labels.py` and `check_verify_loop.py` skip the `Stop` check when `CODERAILS_HEADLESS_RUN=1` is in their environment. A headless `claude -p` run cannot do an interactive correction turn. The two lints give their advisory for `SubagentStop` regardless of the flag.

  Set the flag only in the `spawn(...)` call in `skills/dashboard/app/src/app/api/run/route.ts`. A second assignment breaks the trust boundary. This includes a session that sets the flag for itself. `scripts/sandbox/spawn_sandboxed_worker.py` unsets the flag before it starts a sandboxed worker. Keep these two paths synchronized.

- **Headless runs.** `docs-sync` and `loop-retro-promotion` use `claude -p`, where `PreToolUse` does not run. `scripts/routine_run.py` handles the step sequence, manifest check, refusals, and cleanup. The specs are in `routines/*.json`. Codex has a copy in `packages/codex/`.

  The manifest check uses `diff_manifest.py` with the U1 policy file. A nonzero gate exit gives `run_refused`. Cleanup uses Git and gh only. `scripts/routine_log.py` writes JSONL rows with a closed outcome enum and codes for each scheduled run type. An unknown outcome gives exit code 2.

  The legacy `run=ok`, `abort=`, and `refused=` lines come from these rows. `begin` writes a provisional `run_incomplete` row. If a child exits with no terminal row, the runner adds `run_abort runner_exit_no_terminal`. If an agent does not run the script, only the standing row and runner check can show that omission.

  The counter prefix is `routine/`. See `docs/routines.md` and the RUNBOOK entry "A routine run ended incomplete, aborted or refused".

## Publication and loop checks

### Required reviewer passes

The publication gate uses `policy/review_policy.json` to map changed paths to the passes that the gate checks. The check is on by default. The merge helper and the two direct-merge paths use the same gate.

- `review-pr` applies to all PRs.
- `security-review` applies to the hook and script trees, install and uninstall scripts, plugin manifests, and the policy's control paths.
- The control paths include `policy/`, `capabilities/`, `agents/`, `commands/`, `AGENTS.md`, `workflow.config.yaml`, and `.coderails/`.
- The policy also includes the Codex copies, hook and script trees, and the Codex post-review and merge skills.
- `deploy-safety` applies to `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/`, and `skills/dashboard/runner/`.

Read the policy for the path rules. Its own control paths need `security-review` to prevent a weaker policy from using only `review-pr`.

Use `scripts/post_review.py post <PR> --summary FILE [--pass NAME=FILE ...]`. It posts the v1 marker and the `coderails-review-passes v1` line. It calculates verdicts from the checked summaries. The gate recalculates the hash and verdict from the posted sections. If the values are different, it reports `review_passes_malformed`. A `Critical` line can have only the token `None` for a clean result.

The gate blocks with `required_review_missing:<name>`, `required_review_failed:<name>`, `review_passes_malformed`, `review_artifact_missing`, or `review_policy_unreadable`. A v1 artifact with no passes line gives only its checked `review-pr` summary. For a `hooks/` PR, post again with the other mandatory pass.

Set `review_passes: off` to skip this check. All other values apply the check. It operates without regard to `diff_manifest`.

A pass shows that a summary with that name, hash, and verdict was posted. It cannot show who wrote the summary or what checks they did. `post_review.py` accepts a file for each named pass. The PR author can thus post `## No findings` for `security-review` or `deploy-safety` as the same user. There is no binding to a reviewer agent. See the RUNBOOK entry "Required review passes refused a merge".

### Eval level from the PR diff

The gate calculates a minimum `verification_level` from the diff. It is on by default. See `policy/surface_policy.json` for the path classes.

- `irreversible` includes `install.py`, `uninstall.py`, `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, and `.github/workflows/`.
- The two `hooks.json` files, the policy, and the policy reader are also `irreversible`.
- `outward` includes `commands/`, `skills/`, `hooks/`, `scripts/`, `agents/`, `packages/codex/`, `policy/`, and `capabilities/`.
- The class is none only for the anchored docs and test directories. An unlisted path such as `AGENTS.md` is `outward`.

The reader in `scripts/lib/eval_level.py` also uses the number of work units. Level 0 requires one unit and no outward surface. Level 1 applies to an outward surface or two units. Level 2 applies to an irreversible surface or three units.

Use `scripts/post_evals.py post <PR> <evals.json> [--progress PATH]` to post evals. It checks the PR number (`pr_number_invalid`). It checks structure (with `verify_suite` and `not_frozen`), discriminating checks, and the embed. It writes the v1 marker on line 1 and `coderails-eval-facts v1` on line 2.

Line 2 has `derived_min_level`, `late_freeze`, and `suite`. The body then has the summary and an embed with `gate_facts` that the code stamps. The previous `$ARGUMENTS` shell recipe is no longer available.

The merge helper, Claude `enforce_pr_workflow`, and Codex `pr_publication_gate` calculate the level again from the live diff. They do not use the stamped level. They block on `level_below_derived`, `suite_hash_mismatch`, `chain_broken`, or `integrity_stripped`. Other refusals are `not_frozen`, `late_freeze_unstamped`, `suite_hash_marker_mismatch`, and `eval_facts_missing`. An outward diff with a v1 artifact that has no facts line needs a new post.

A diff does not show the number of work units that produced it. If there is no `--progress` or declared lower bound, the check counts one. The suite hash and chain use no key. An agent that runs as the same user can calculate them again and post with `gh api`. The `late_freeze` value is an attestation. The check can find simple edits.

Set `eval_level: off` to skip this check. See the RUNBOOK entry "Eval level or suite integrity refused a merge" and [workflow gate measurements](workflow-gates-measurement.md). The counter prefix is `eval-level/`.

### Security applicability for standalone wiki prose

Only `security-review` can use `not_applicable`. Its boundary is `standalone_wiki_prose_v3`. The `review-pr` check must succeed. `post_review.py na-scope <PR>` prepares immutable inventory data. The command does not examine the prose or its consumers.

The `## Not applicable` JSON summary binds the repo, PR, base branch, live base head, unique merge base, head, and inventory digest. Each page entry must agree at the merge base and live base. This applies to the two rename names and to a missing entry. Controls, command plugin manifests, modes other than ordinary files, and changes other than pages cause refusal.

The context digest binds all tracked entries other than trees in merge base, live base, and head. It has no authored page endpoints and includes unchanged Markdown. The explicit groups must include the full path set one time. Missing, duplicate, unrelated, or glob-selected paths cause refusal. All entries in a group must have the same base-change status. Only changed base entries can have nonempty base-change text.

The full `consumer_scope` and each group need explicit `effect_state=effect_free`. The possible values are `effect_free`, `active`, and `unknown`. Start with `unknown`. Known execution, access, or instruction effects cause refusal. Unknown or missing effect data also causes refusal, with or without complete coverage or `unresolved=[]`.

The full effect status includes the merge-base, base, and head facts. It also includes authored merge-base-to-head operations with live-base context and group interactions. A group includes its members in that combination. Do not infer `effect_free` from filenames, modes, or unchanged files. The reader refuses versions 1 and 2 and unknown context. It reads tree and blob data in batches.

The scope tool has a 131072-byte limit. The complete comment has a 65536-character limit. The two writers and the publication reader check the facts. Invalid scope gives `required_review_not_applicable_invalid:security-review`. A malformed summary gives `review_passes_malformed`.

A report by the same user cannot show reviewer independence or prove that the content cannot execute. The GitHub workflow reads the general reviewer companion and does not check the N/A scope. See the RUNBOOK for limits and release steps. Earlier readers reject the new result.

For installation, follow `INSTALLATION.md`. Select a version that passed its checks. Drain affected sessions and keep copies of the earlier runtime and data. Run the maintained installer dry runs, install, start new sessions, and trust the Codex hooks.

Check that the installed files agree. If you cannot confirm quiescence or if qualification has not finished, keep installation on HOLD. Do not patch an active installed reader or bypass an earlier gate.

### Loop evals, GitHub status, and retrospective

`/coderails:task-evals` freezes ungraded `evals.json` before implementation and grades the results after it. See `skills/task-evals/SKILL.md`. `/coderails:post-evals <PR#>` validates it and posts a SHA-bound comment with `coderails-eval-summary` through `scripts/lib/eval_artifact.py`. The merge helper reads this after the reviewer artifact. A fetch error, `NO-GO`, or no artifact blocks the merge.

If `progress.json.work_units` is one or more, `loop_state_guard` checks for a loop-scope `evals.json`. It blocks the stop if there is no file. If there is no `work_units` field, the check lets the stop continue. Use `scripts/post_evals.py grade-loop` to calculate `result` and give it a `grading` stamp. Do not write the result by hand. If `GO` or `VERIFICATION_LEVEL0` has no correct stamp, the guard gives `UNSTAMPED` and blocks.

If `config.integrity_review.enabled` is `true`, `scripts/merge.py` and `enforce_pr_workflow` check the newest `integrity-review` status for the current head SHA. It must be `success` from `github-actions[bot]` with `integrity=pass sha=<head>`. A different author, no status, an earlier SHA, a status other than `success`, a malformed description, or a fetch error blocks. The GitHub ruleset is the server boundary.

In Phase 13, `agentic-loop` records `complete` after all updates to `progress.json`. It prepares data for `orders.py` and runs `python3 scripts/lib/retro.py assemble <state-dir> --session <id>`. This writes `retro.json` with `schema_version` 3 next to `progress.json`. Claude `loop_stall_guard` and Codex `graph.py complete` or `verify-completion` use `scripts/lib/retro_check.py`.

A hand-written or earlier retro gives `retro_not_assembled`. The reader calculates the source hashes and decisions chain again. It checks for `proof_run`, `decisions_flushed`, `orders_prepared`, and `retro_assembled` in sequence. If the record omits a step or shows it out of sequence, the reader gives `retro_steps_missing`. The prepared data must agree with D4's artifact and receipt for the owner and source.

After the loop save, the Claude Stop hook consumes the recorded row. The source check normalizes the consumed bit only on that last row. After the save, `orders.py tick` gives `orders_ticked`. That observation is not part of the hash for the frozen prepared data.

The retro reports degraded Muninn operation without blocking. This is a safeguard for agents that follow the rules. It cannot prevent tampering.

The assembler writes the dated cost and top-level `models_used` from the cost miner. If the cost miner cannot give a result, it lets assembly continue. See Phase 13 in `skills/agentic-loop/SKILL.md` and `teardown.md`.
