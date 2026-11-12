# AGENTS.md — Coderails

Read this file at the start of the conversation. It contains the repo working guide and the Coderails wiki schema. See `## Wiki schema` near the end. `CLAUDE.md` points to this file. Make changes to the guide here.

The wiki vault is at `../coderails-wiki` from the plugin directory, or at the path that `/wiki-init` set.

Use `wiki-query` for Coderails questions, lookups, and context. Use `wiki-lint` for wiki health or stale content. Use these skills before you examine the source or vault by hand. The wiki records decisions and relationships that you cannot always get from the code alone.

## Current integrity-gate replacement

The trusted GitHub workflow runs the `integrity-review` attestor. This attestor replaces the semantic judge. It checks SHA-bound PR reviewer and eval records. It also checks command and eval structure, policy paths, provenance fields, and the diff input limit. It does not run PR code or commands from comments. It does not use an LLM to get a verdict.

See `docs/INTEGRITY-GATE.md`, `.github/workflows/integrity-review.yml`, `scripts/integrity-gate/integrity_actions.py`, and the `integrity_review.enabled` config. The source code does not turn on the GitHub rule. Turn on the rule in GitHub.

## What this repo is

The repo has two plugins. Each plugin runs on its own.

- The Claude Code plugin is at the repo root.
- The native Codex plugin is at `packages/codex/`.

`install.py` installs the Claude plugin by default. Use `--provider codex` to install the Codex plugin.

The Claude plugin includes these components.

1. Workflow commands for `prep → push → merge → wiki` in `commands/*.md`.
2. The agentic-loop, planning-sequence, premortem, and handoff skills in `skills/*/SKILL.md`.
3. Advisory lints for confidence labels and unverified claims. Hooks in `hooks/` block destructive Bash commands and commits when tests do not succeed.

The plugin instructions and Python runtime use no compilation step. The dashboard TypeScript packages have their own build and test commands. The source includes Markdown instructions, Python hooks and workflow scripts, and dashboard TypeScript. Keep your version in your fork or repo. Python replaces the former shell runtime and test entry points. The plugins can use generic shell policy examples and external tools.

**Agentic-loop graph runtime.** The `agentic-loop` skill stores the graph in `progress.json`. The graph records nodes, edges, joins, status, outcomes, and retries. Readiness checks and helpers for planning and recording are available for wave dispatch. The model reads the graph, sends work when its readiness checks succeed, and records the results. There is no automatic scheduler.

Each provider has its own graph adapter, locks, and reader for native records. The pure semantics source is `packages/graph-semantics/graph_semantics.py`. The two installations get copies with the same bytes. `graph_vocab.py` defines the only stop enum. `decision_chain.py` calculates pure decision hashes and checks the chain.

`graph_convert.py` provides `graph.py convert` and versioned `state_minor`. `graph_spec.py`, `graph-spec.yaml`, and `policy.yaml` define node types and thresholds. Each load refuses a missing spec edge. `graph.py instantiate` builds from the spec. `scripts/gen_graph_docs.py` writes the docs. The graph uses schema 3, with no legacy reader or a second writer.

## How the pieces wire together

- `.claude-plugin/plugin.json` has the Claude plugin name, version, and metadata. `.claude-plugin/marketplace.json` sets the local-directory source to `./`.
- `hooks/hooks.json` tells the provider when to run the hooks. The checks and nudges are in `hooks/scripts/*.py`.
- `commands/*.md` has the slash command frontmatter and instructions. The commands use Python in `scripts/*.py`, for example `push.py` and `merge.py`.
- The two commands use the Git, gh, and PR helpers in `scripts/lib/git_common.py`. For `workflow.config.yaml`, see `scripts/lib/config.py` and "Config resolution".
- `scripts/sandbox/*.py` uses srt to start sandboxed workers. `scripts/integrity-gate/*` checks records and gives the `integrity-review` status in the trusted GitHub workflow.
- `skills/*/SKILL.md` holds skills and their descriptions. `agents/*.md` holds the subagent definitions that the skills use.
- Claude roles include `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `docs-auditor`, `loop-worker`, and `preflight-scout`. Other roles are `proof-author`, `security-reviewer`, `source-auditor`, `spec-reviewer`, and `wiki-writer`.
- `packages/codex/` is the native Codex plugin root. Its manifest is `.codex-plugin/plugin.json`. Its `skills/*/SKILL.md` files include former commands.
- The Codex plugin uses `hooks/hooks.json` and `hooks/scripts/*.py` with `PLUGIN_ROOT`. The command `install.py --provider codex` installs `agents/*.toml`.
- The installer adds rules from `instructions/` to `~/.claude/CLAUDE.md` and feedback memories from `starter-memory/` to the user's memory directory.
- `docs/` has documentation. `examples/` and `launchd/` have sample configs and macOS scheduling plists.

`${CLAUDE_PLUGIN_ROOT}` in `hooks.json` resolves to the repo root at run time. Hook commands use it to find `hooks/scripts/*.py`.

## Two enforcement mechanisms — don't confuse them

- **Hooks apply rules mechanically.** They run automatically at set points in the session. They can block with exit code 2 or `permissionDecision: deny`.
- **Slash commands give guidance.** Claude must invoke them. Use them to give workflow instructions. They cannot make the workflow mandatory.

Use a `PreToolUse` hook to make a rule mandatory without depending on Claude to follow it.

**Limits of local hooks.** A local hook checks that a step ran. It cannot show that the step did its work. For example, `enforce_pr_workflow` accepts an invocation of `/coderails:push` or `/pr-review-toolkit:review-pr` if that invocation did nothing.

The hook runs in the agent's trust domain. There is no privilege boundary. It gives an agent instructions and writes a `discipline.log` record. It cannot prevent tampering. Stop hooks can make a declared step show in the records, but cannot prove the step did its work.

GitHub branch protection can make PRs and reviewer approvals mandatory for `main` and block direct pushes. A local agent cannot forge those server checks. Local hooks supplement GitHub branch protection.

The standing decision of 2026-07-15 is to use no general branch protection in this repo. Ordinary PRs use the local hooks without the general server checks.

The planned GitHub ruleset for `main` makes a PR and a `success` status for `integrity-review` from the `github-actions` app mandatory. The workflow checks the PR reviewer and eval records for the head SHA. It reads these records and the policy as data.

After the workflow reaches `main`, turn on the GitHub rule and check it. The local hooks cannot replace the rule.

**Worker sandbox.** If `config.sandbox_workers` is `true` or has no value, the control is on. The control is `enforced_by_code`. The reader is `scripts/sandbox/containment.py`.

`resolve()` gives `sandboxed` only when all four components are available.

- The OS sandbox is `sandbox-exec` with `rg` on macOS, or `bwrap` on Linux.
- `npx` is available.
- The npx cache has srt 0.0.65.
- The owner has set up the worker credential.

If a component is unavailable, `resolve()` gives `fallback` with `sandbox_unavailable` or `worker_credential_missing`. The graph stops sending implementation work. If the setting is `false`, the result is `off`.

The credential is one line in `~/.coderails/worker_credential` with mode 0600. It is `ANTHROPIC_API_KEY=...` or `CLAUDE_CODE_OAUTH_TOKEN=...` from `claude setup-token`. The mode stays `fallback` until the owner sets up the file.

A loopback probe on 2026-10-05 showed that headless Claude sends each credential type with an isolated `HOME` and `CLAUDE_CONFIG_DIR`. It uses `x-api-key` for an API key or `Authorization: Bearer` for an OAuth token. The probe did not check if a live account accepts it.

In `sandboxed` mode, `@anthropic-ai/sandbox-runtime` runs the implementation worker in its own OS sandbox. This isolates the worker from the agent's trust domain. The orchestrator has no sandbox.

**How a sandboxed worker runs.** The launcher in `scripts/sandbox/spawn_sandboxed_worker.py` runs `git clone --no-hardlinks` into a scratch directory for that worker. The worker runs there and cannot write to the primary `.git` refs, hooks, or config. The srt rules for `.git/hooks` and `.git/config` apply in the worker's own checkout.

The worker can write only to its scratch directory and its own `/tmp/claude-<uid>/<slug>` data directory. It cannot write to `~/.claude`, `~/.claude.json`, or the shared `$TMPDIR`. The launcher sets `HOME`, `CLAUDE_CONFIG_DIR`, `XDG_*`, and `TMPDIR` to paths in scratch. It builds the child environment from `PATH`, `LANG`, `TERM`, and the worker credential. It does not copy `GH_TOKEN` or `ANTHROPIC_API_KEY` from the parent. It keeps `CODERAILS_HEADLESS_RUN` unset.

The sandbox blocks GitHub network traffic. The worker does not push. If the worker exits with code 0, the launcher checks the U3 manifest and checks new Git objects for known secrets. It imports only the worker's branch, through a private ref and a fast-forward-only merge. It then pushes with the operator's Git authorization without the worker sandbox.

The launcher gives `branch_import_refused` if the worker moves a different branch, such as `main` or `master`. It gives the same code for a history rewrite or a file in the commit that the manifest does not list. It does not import or push. If the worker exits with a nonzero code, the launcher does not import and leaves the clone in scratch.

The local Claude graph driver prepares execution checkout C before prompt authorization. It reserves clean checkout D for root publication. The driver captures the fixed, untrusted proposed source in private Git objects. It checks scope and known secrets. It copies the proposal to D without changing D's HEAD or index. The root then checks and publishes it.

If work continues after a stop, the driver keeps edits that the root made after the copy. If the copy does not finish or the destination differs, the driver quarantines D. The ignore rules from trusted H classify new generated files. The driver does not use the worker's ignore rules, config, index, or filters as authority.

These checks do not prove that the terminal tree is coherent or that descendant workers stopped. See `docs/WORKER-CONTAINMENT.md`.

**In-process fallback.** `hooks/scripts/worker_containment_gate.py` is a different hook from `loop_dispatch_guard.py`. If `resolve()` gives `fallback`, it denies each in-process graph U3 dispatch with `containment_unavailable`.

If `resolve()` gives `sandboxed`, it checks all native roles. It blocks in-process graph U3 dispatch if `manifest` or `write_scope` can touch `HIGH_RISK_PREFIXES`, or if the unit does not declare a scope. The code is `containment_ack_required`. The hook lets the dispatch continue if the owner issues a `worker_fallback` receipt. It lets low-risk units continue and logs `containment_fallback_low_risk`. See `scripts/lib/containment_counters.py` for counts.

The high-risk paths include `hooks/`, `scripts/`, `capabilities/`, `agents/`, `skills/`, `commands/`, `.claude-plugin/`, `.coderails/`, and `.github/`. They also include all of `packages/codex/` and `packages/graph-semantics/`. Other entries are `workflow.config*`, the config schemas, `install.sh`, `install.py`, `pyproject.toml`, `AGENTS.md`, and `CLAUDE.md`. The hook normalizes entries. It counts `..`, absolute paths, backslashes, non-ASCII, and brace globs as high risk.

The owner uses `action_receipt_cli.py approve-action --kind worker_fallback --command 'worker_fallback <unit>'`. The signed receipt can be used one time. The signature covers the repo, branch, base SHA, and unit.

The worker cannot write to the shared `$TMPDIR`, `~/.claude`, `~/.claude.json`, or the primary Git refs, hooks, or config. It does not inherit the full `gh` token. This is a cooperating-agent safeguard with these limits.

- **Network.** The sandbox allows traffic only to `api.anthropic.com`. The worker can send data to the Anthropic API with its dedicated credential. The sandbox blocks GitHub domains.
- **Reads.** `denyRead` is empty because a read restriction breaks toolchains. The worker can read what the user can read in the user's `HOME`. This includes `~/.claude.json` and credentials on disk. The launcher filters only the environment.

- **Launcher.** The launcher uses the operator's Git authorization without the sandbox. It clones, imports, and pushes. The sandbox cannot contain a launcher bug or a malicious clone config. Git calls on the clone ignore its `fsmonitor` and hooks.

- **Orchestrator.** The orchestrator has no sandbox. An agent with the same user permissions can edit `sandbox_workers`, the unit manifest, and the receipt trust root.

- **Codex worker records.** If `sandbox_workers` is on, `loop_dispatch_guard.py` refuses native U3 spawns.
  Use the OAuth graph driver with its issued dispatch, immutable prompt, terminal receipt, publication checks, and sealed worker records.
  The standalone OAuth helper in `packages/codex/scripts/codex_worker.py` runs with `workspace-write`. Its output and telemetry cannot complete a graph node.

  The driver and helper select ChatGPT login and the OpenAI provider. They use an allowlist for the inherited environment.
  Native `spawn_agent` inherits the parent's `sandbox_mode`. It cannot prove containment for an individual worker.

  The driver uses the user's OAuth location. It shares `HOME` and `CODEX_HOME`. The worker can read files and can access tokens as the same user.

- **Conditions for sandbox mode.** The owner must supply `~/.coderails/worker_credential`. The sandbox runtime must be available.
  Until then, `resolve()` gives `fallback` with `worker_credential_missing` or `sandbox_unavailable`.
  The graph stops implementation work with `containment_unavailable`.
  The loopback probe did not check if a live account accepts the credential with a custom `CLAUDE_CONFIG_DIR`.

- **Role scope.** The gate checks graph U3 envelopes without regard to the optional native role label.
  It logs low-risk units and lets them run without the launcher.

- **Secrets in a push.** The worker holds the live API credential and can read secrets in the user's `HOME`.
  Examples are `~/.config/gh`, `~/.ssh`, and `~/.git-credentials`. It can also use a keychain-backed Git credential helper through the user's passwd `HOME`.
  Before import or push, the launcher checks new commit objects for the worker credential and known secret patterns.

  It checks binary blobs and commits from the base to the branch head. If it finds a secret, it gives `branch_import_refused`.
  It cannot find a secret in a format that the check does not recognize, such as an encoded value.

The sandbox limits file writes and credential scope. A sandboxed worker's PR must clear the same reviewer, eval, and hook checks as other PRs.

### Skills↔hooks seam convention

If a skill tells the agent to run a gated step, name the hook and tell the agent how to satisfy it. For `git merge`, `gh pr create`, or `gh pr merge`, name `enforce_pr_workflow`. For source or plugin edits on `main`, name `no_edit_on_main`. For `git commit`, name `test_gate`. If a new hook gates a step in a usual workflow, update the skills that tell the agent to do that step.

For the Claude merge gate, invoke the Skill `/pr-review-toolkit:review-pr <PR#>`. Give the PR number as an argument. A set of reviewer agents alone does not satisfy the Skill invocation check. After `review-pr`, apply the corrections and push them. Then use `/coderails:post-review <PR#>` for the current head. The merge helper fetches the SHA-bound comment live and blocks if the fetch or artifact check does not succeed.

Keep the required reviewer passes and eval level for the changed paths. The merge and Stop checks also use the GitHub status, loop evals, proof results, and retrospective where configured. See [publication and loop checks](docs/HOOK-BEHAVIOR.md#publication-and-loop-checks) for the pass policy, wiki applicability, and Phase 13 requirements.

## Hook event map (`hooks/hooks.json`)

For hook behavior and limits, see [the hook instructions](docs/HOOK-BEHAVIOR.md). The generated table below lists the installed registrations.

### Generated hook registration

The table lists the current provider registration and the step for each control. Run `python3 scripts/gen_hooks.py --check` after a hook change.

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

### Enforcement ceilings — deliberate, not bugs

See [hook limits](docs/HOOK-BEHAVIOR.md#hook-limits).

**Hook script conventions.** Follow these rules when you add or edit a script.

- Use the provider-local Python payload reader with a total deadline of five seconds. The same deadline applies if only part of the input arrives. Let empty or invalid input continue where the hook is fail-open. Do not extend the hook timeout to conceal an unbounded read.
- Run cheap skip checks before costly transcript parsing. Hooks use maintained Python functions. Do not embed Bash implementations or compatibility wrappers.
- Claude Stop blocks write to stderr and exit with code 2. PreToolUse writes `hookSpecificOutput.permissionDecision: "deny"` and exits with code 0.
- Append escaped structured audit records to `$CLAUDE_DISCIPLINE_LOG` (default `~/.claude/discipline.log`).
- The harness can be late to write the last reply. Use the provider's helper that waits for the transcript with a time limit.
- Native worker labels belong to the provider. Include the agent's instructions. Correlate graph nodes through ownership envelopes and native call identities. Do not rely on a custom label alone.

## Workflow command architecture

`/coderails:workflow` coordinates the steps. Each phase uses a subcommand that can also run on its own.

```
/workflow  →  /prep → (code) → /push → /pr-review-toolkit:review-pr → /coderails:post-review → (ship-it) → /merge → /wiki-ingest + /wiki-lint
```

The workflow pauses for the user to code and test. It pauses again for ship-it authorization. The other steps run automatically. After `review-pr` and before ship-it, `/coderails:post-review <PR#>` writes a durable SHA-bound reviewer artifact.

Agentic-loop Phase 4b and non-loop `/workflow` Phase 3 post the same artifact. The `/merge` command fetches live PR comments and checks for an artifact for the current head SHA. It blocks if the fetch or check does not succeed. The gate is in the `OPEN` branch of `scripts/merge.py` before `gh pr merge`.

**Config resolution.** Workflow command frontmatter runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`. The maintained `config_path(start_dir)` checks the current directory and its parents up to the Git root. It uses the nearest `.coderails/workflow.config.yaml` and does not merge configs. `resolve-config` gives its contents or `NO_CONFIG`.

Commands and gates use the same provider-local resolver. If you add a config field, update the workflow, prep, push, and init instructions. Init keeps and checks the config before it moves migrated files to Trash. The runtime does not use legacy config paths. `NO_CONFIG` means the project has no initialized config.

**`scripts/` and `commands/`.** `push.py` and `merge.py` run commit, push, `gh pr create`, and merge operations deterministically. The `.md` commands give instructions and decisions. They use the shell to run these scripts. Add shared Git and gh helpers to `scripts/lib/git_common.py`.

**Script procedures.** `scripts/wiki_lint.py stale` checks typed `wiki_stale_days` (default 30). The `verify-merged-pr` skill and agentic-loop Phase 9 use `scripts/verify_merged.py <PR> [--grep S --path P]`. It checks content, or ancestry for a merge commit with two parents. `scripts/merge.py --describe` reads `VERIFY_STAGES` and `publication_gate.CHECKS` and prints the gate list without contacting the remote.

`scripts/memory_dir.py` serves memory-consolidation. `scripts/detect_test_command.py` serves test-gate-setup. The wiki lint, merge verification, memory directory, and test detection helpers have provider copies with the same bytes. The two `merge.py` copies use different provider command names. Only Codex has strict config validation in that helper.

The two `quality_feedback.py` hooks use `scripts/quality/check.py --json`. The skill must invoke its script. See the RUNBOOK procedure entry for limits and codes.

## Project-specific assumptions (change when generalising)

- **Auth host**: `push.py` requires a `github.com` remote (`scripts.lib.git_common.require_repo`).
- **Jira fields.** `prep.md` reads `config.jira.epic_field` and `points_field`. Jira workflow status changes have names for each project. See INSTALLATION.md "Notes".
- **Jira tools.** Commands use `config.jira.mcp_namespace`. The default `jira` gives `mcp__jira__*`. For a different namespace, add `"mcp__<namespace>__*"` to `.claude/settings.json`. If Jira MCP is unavailable, the commands skip Jira steps.

## Working in this repo

- After a command, skill, or hook edit, use `/reload-plugins`. There is no compilation step.
- To test a hook, trigger it and check `~/.claude/discipline.log`. Use `python3 install.py --dry-run` to preview changes.
- Keep `install.py` idempotent. A second run must not duplicate CLAUDE.md edits or overwrite seeded memories.
- `uninstall.py` must remove the block in CLAUDE.md and settings keys that `install.py` adds. Keep user data such as `discipline.log` and memories. Update the installer and uninstaller together.
- Edit `instructions/self-checking-discipline.md`. This is the source that `install.py` adds to `~/.claude/CLAUDE.md`.

## Requirements

- Use Python 3.9 or newer. The runtime uses the standard library and has no `jq` dependency.
- Use Claude Code 2.1.x for the root plugin, or Codex CLI for the native Codex plugin.
- Put `gh` and `git` on PATH. Use an authenticated GitHub host for `/push` and `/merge`.
- Install `pr-review-toolkit@claude-plugins-official` for the Claude `/workflow` PR checks.
- See `docs/CODE-QUALITY.md` for development and test tools.

---

# Wiki schema

Based on the LLM Wiki pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

This is the only source for Coderails wiki conventions. Do not make a `schema.md` in the vault.

**Location.** `/wiki-init` sets the vault path, usually `../coderails-wiki`. The flat keys in `.coderails/workflow.config.yaml` set the vault path, Git flow, and supervision mode.

The keys are `wiki_path`, `wiki_git_worktree`, `wiki_git_bypass_flag`, `wiki_git_pull_path`, and `wiki_supervision`. See Step 0 of `wiki-ingest`, `wiki-lint`, and `wiki-query`.

```
coderails-wiki/
  index.md          ← content catalog; read first on every query
  log.md            ← append-only chronological record
  commands/         ← one page per slash command
  hooks/            ← one page per hook script
  skills/           ← one page per skill
  design/           ← architectural decisions and invariants
  investigations/   ← point-in-time filed analyses (<topic>_<YYYY-MM-DD>.md)
  sources/          ← ingested PR records (pr_<N>_<slug>.md)
  templates/        ← page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md)
  assets/           ← charts and images
```

**Three layers.**

1. The plugin repo supplies immutable source files. Examples are commands, hooks, scripts, skills, `install.py`, and `CLAUDE.md`. Read them for wiki work. Do not change them.
2. Claude owns the wiki's LLM-generated Markdown in the vault.
3. This file tells Claude how to structure the wiki. The maintainer edits it. Claude reads it.

## Page types

> **`wiki.schema.json` in the repo root is the source of truth.** The two `wiki_taxonomy_gate.py` copies read `page_types` and `structural_dirs` at run time. If there is no usable schema, the hook lets the write continue. It logs `wiki_schema_missing` or `wiki_schema_invalid`.

> The tables below document the schema. The build fails if the tables differ from the schema or if this heading changes or is removed. See `hooks/scripts/tests/config_docs_drift_test.py`.

| Type | Directory | Naming | Purpose |
|---|---|---|---|
| command | `commands/` | `<command-name>.md` | Documents one slash command: what it does, config fields, scripts invoked |
| hook | `hooks/` | `<script-name>.md` | Documents when one hook runs, its mode, its logic, and when it blocks |
| skill | `skills/` | `<skill-name>.md` | Documents one skill's purpose, trigger phrases, phases, and problems it prevents |
| `design` | `design/` | `<topic>.md` | Lasting architectural decisions and invariants |
| investigation | `investigations/` | `<topic>_<YYYY-MM-DD>.md` | Analysis for a point in a workflow session. A subsequent analysis can supersede it. |
| source | `sources/` | `pr_<N>_<slug>.md` | Immutable record of a merged PR from `/wiki-ingest` |

**Structural directories.** Their files have no wiki frontmatter. Do not use `[[wiki-link]]` for them.

| Directory | Naming | Purpose |
|---|---|---|
| `templates/` | `<page-type>.md` | Page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md) with the YAML frontmatter shape |
| `assets/` | freeform | Charts and images generated for wiki pages (e.g. matplotlib output) |
| `dashboard-runs/` | `<routine>.md` | Scheduled-routine run notes, `type: routine-run`, written by `skills/dashboard/runner` |

`dashboard-runs/` holds run output. Do not apply wiki page rules or wiki links to it. The `/wiki-ingest` and `/wiki-lint` commands skip it.

The Obsidian plugin's direct-exec path writes one note for each run in the same directory. It sets `status` to `running`, `done`, or `failed` and has no `type` field. Use the two types of notes as run output regardless of their frontmatter. See `docs/routines.md`.

## Page format

Use this frontmatter for each page.

```yaml
---
title: "<Page title>"
type: <command|hook|skill|design|investigation|source>
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
sources: []        # list of PR source page paths that informed this page
tags: []           # freeform list
---
```

Use `[[wiki-links]]` for cross-references. Write `[[page_name]]` without a directory prefix. Write each page so that a reader can read it in less than two minutes. Record relationships, decisions, and patterns that build on other knowledge. Skip facts that a reader can get from source alone.

Mark substantive claims `(verified)`, `(inferred)`, or `(guess)`. Use `> ⚠️ CONTRADICTION: <description>` to mark a contradiction inline. The `/wiki-lint` command checks for this marker.

**Enforcement model.** See `## Two enforcement mechanisms` above. On a hook or command page, name the mechanism and its guarantees and limits. Add `[[enforcement-model]]` and cite the limits verbatim.

## Workflows

**After each PR merge, use `/wiki-ingest`.** Do not write PR pages directly.

1. Make `sources/pr_<N>_<slug>.md` from `templates/source.md`.
2. Update the related pages with new knowledge.
3. Append `## [YYYY-MM-DD] ingest | PR #N merged: <description>` to `log.md`.
4. If there are new pages, update `index.md`.
5. Run `/wiki-lint`.

**Query.** `/wiki-query` reads `index.md` first, fetches related pages, and answers with citations. If a query gives new knowledge that was not obvious, record it in an `investigations/` page.

**Lint.** Run `/wiki-lint` after `/wiki-ingest`. It checks orphaned pages, stale `last_updated`, missing cross-references, and contradictions. Correct problems from the current PR. Defer unrelated problems.

## Conventions

- Frontmatter tags: lowercase, hyphenated.
- Use one concept for each page. Use more pages if a page has multiple concepts.
- Source pages give the PR number and important changed files.

**When to examine code.** Use a subagent or examine code if a wiki operation cannot answer a question. Examples are no page for a query, unfamiliar code for `/wiki-ingest`, or a result from `/wiki-lint` that gives a basis to check a page. Use the wiki by default. Correct it when the source shows an error.

**Changes to conventions.** The maintainer updates this file before related vault pages. This applies to new page types, frontmatter fields, and naming rules. Claude reads the current rules.
