# coderails

coderails ships two independent workflow plugins: the root Claude Code plugin
and the native Codex plugin under `packages/codex/`. Each has its own skills,
agents, and hooks; neither dispatches to the other. They provide:

- **Workflow** — the `prep → push → merge → wiki` command chain plus the
  agentic-loop, planning-sequence, premortem, and handoff skills.
- **Guardrails** — a self-checking discipline loop: Claude labels claims
  (verified)/(inferred), is nudged at stop by advisory lints (never a block) to
  add the `## Did Not Verify` section and resolve it, and is gated on destructive bash and
  failing project tests.
- **Integrity gate** — A three-layer evidence check (local gate, root-owned attestor,
  GitHub ruleset) that blocks stale, missing, or malformed review/eval evidence.
  See [`docs/INTEGRITY-GATE.md`](./docs/INTEGRITY-GATE.md) for details.

## Install

See [INSTALLATION.md](./INSTALLATION.md). Short version:

```bash
git clone https://github.com/blueman82/coderails.git ~/Documents/Github/coderails
cd ~/Documents/Github/coderails
python3 install.py --provider claude --dry-run
python3 install.py --provider claude
# restart Claude Code, then:
#   /plugin marketplace add ~/Documents/Github/coderails
#   /plugin install coderails@coderails
#   /reload-plugins
```

For Codex, use `python3 install.py --provider codex` instead. It registers the
plugin and installs its bundled agent definitions under `${CODEX_HOME:-~/.codex}/agents`.
Codex skips plugin hooks until you review and trust them. After installation,
start a fresh Codex session, run `/hooks`, and review and trust the Coderails hooks.

Owned shell entrypoints have been replaced by Python commands. Both providers
accept graph schema 3 only and share one pure semantic source, materialized
into independent installations. Dispatch, transcript evidence, and state locks
remain provider-local. See [INSTALLATION.md](./INSTALLATION.md) before upgrading
an installation with older commands or loop state.

Per project, run once: Claude Code users run `/coderails:init`; Codex users run
`$coderails-codex:init`. Both scaffold `.coderails/workflow.config.yaml` from
[`examples/workflow.config.yaml`](./examples/workflow.config.yaml) — the preferred
way to set up a new repo.

## Commands

| Command | What it does |
|---|---|
| `/workflow` | Orchestrate the full feature workflow: prep → code → push → review → merge → wiki |
| `/coderails:init` | Scaffold `.coderails/workflow.config.yaml` for the current repo |
| `/prep` | Safety branch + feature branch + Jira ticket |
| `/push` | Stage, commit, push, open PR with reviewers; auto-resolve linked Jira |
| `/post-review` | Post SHA-bound review artifact on PR; required by `/merge` gate |
| `/coderails:task-evals` (skill, not a `commands/` file) | Freeze ungraded success evals before implementation, then grade actual results |
| `/coderails:post-evals` | Post SHA-bound eval artifact on PR; required by `/merge` gate |
| `/merge` | Merge approved PR, switch to main, pull |
| `/coderails:authorize` | User-typed only: grant this session an expiring, revocable authority (the phrase "crack on" only prints this command) |
| `/assumptions` | List every assumption, marked verified or inferred |
| `/coderails:cite-check` (skill, not a `commands/` file) | Re-derive a specific claim from sources only — no recall. Forks into `coderails:source-auditor`, so it audits with no access to the context that produced the claim. Named `cite-check`, not `verify`, because `/verify` is a Claude Code bundled skill |
| `/notchecked` | List claims made but not verified |
| `/disconfirm` | Argue against your own most recent recommendation |
| `/test-gate-setup` | Detect the test runner and create `.claude/test_command` |

## Skills

coderails ships its own coderails-specific skills. General dev-workflow
discipline — planning, TDD, systematic debugging, code review, git worktrees —
comes from the required `superpowers@claude-plugins-official` plugin
dependency; install it alongside coderails. `pr-review-toolkit@claude-plugins-official`
is still required for the review stage of `/workflow`.

25 skills are bundled across three groups. Full
catalog: [`docs/REFERENCE.md`](./docs/REFERENCE.md).

**Required plugin dependency: `superpowers@claude-plugins-official`**

| Skill | Purpose |
|---|---|
| `superpowers:brainstorming` | Explore intent and requirements before implementation |
| `superpowers:dispatching-parallel-agents` | Fan-out independent tasks across agents |
| `superpowers:executing-plans` | Drive a written plan to completion |
| `superpowers:finishing-a-development-branch` | Final checks before merging |
| `superpowers:receiving-code-review` | Apply review feedback systematically |
| `superpowers:requesting-code-review` | Prepare a PR for review |
| `superpowers:subagent-driven-development` | Delegate implementation tasks to subagents |
| `superpowers:systematic-debugging` | Structured root-cause analysis |
| `superpowers:test-driven-development` | Red-green-refactor discipline |
| `superpowers:using-git-worktrees` | Parallel work via git worktrees |
| `superpowers:verification-before-completion` | Final verification pass before declaring done |
| `superpowers:writing-plans` | Convert specs into step-by-step plans |
| `superpowers:writing-skills` | Scaffold new skills from scratch |

**coderails-original**

| Skill | Purpose |
|---|---|
| `agentic-loop` | Multi-agent orchestration: spawned teams, no-human-gates, multi-PR loops |
| `cite-check` | Re-derive a specific claim from sources only — no recall, no inference. Forks into `coderails:source-auditor`, so it audits with no access to the context that produced the claim |
| `dashboard` | Live local web HUD: sessions, loops, PR gate states, runs, memory activity |
| `execution-discipline` | High-autonomy, self-verifying work for non-trivial tasks |
| `handoff` | Structured memory + continuation prompt for a fresh session |
| `improve-prompt` | Surfaces ambiguities and rewrites underspecified prompts |
| `docs-sync` | Scheduled nightly pipeline that audits git-tracked docs for drift and, only if drift is found, edits/pushes/reviews/self-merges the fix through the full gate chain (scheduled, not for interactive use) |
| `loop-retro-promotion` | Predicate-dormant pipeline that promotes proven loop lessons into learned-failure-modes.md via the full gate chain (scheduled, not for interactive use) |
| `memory-consolidation` | Health-checks and consolidates a project's persistent memory directory; runs on demand or as a weekly scheduled routine |
| `planning-sequence` | Pre-Parade → Premortem → Red Team on a plan |
| `premortem` | Assume failure, reason backwards to causes |
| `sync-docs` | Audit in-tree docs for drift against the codebase; generate sync reports |
| `task-evals` | Game-resistant success-eval generation: frozen `evals.json` with negative controls |
| `using-coderails` | Self-bootstrap: injected at SessionStart, explains coderails to Claude |
| `verify-merged-pr` | Verify a "PR is merged" claim against origin before relying on it |
| `workflow-audit` | Mine transcripts for repeated tasks worth turning into skills |

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
| `engineering-principles` | Enforce YAGNI/KISS/DRY/Fail-Fast/SSOT/Law of Demeter; dispatches to a language skill |
| `engineering-principles-python` | Python idioms and standards |
| `engineering-principles-go` | Go idioms and standards |
| `engineering-principles-ts` | TypeScript idioms and standards |
| `engineering-principles-bash` | Bash/shell idioms and standards |

## Agents

These bundled Claude agent definitions remain available as optional native
roles. Graph dispatch uses the provider's available role and task-name fields:
Claude receives a native `subagent_type`; Codex receives the helper's printed
`task_name` and a native role only when its tool supports one. The orchestrator
includes the relevant agent instruction body explicitly. A custom Coderails
label is not required and does not prove that instructions were loaded.

How far that goes varies by agent, and the honest split is worth stating:
`spec-reviewer` declares `tools: Read, Grep, Glob` and therefore *cannot* write.
`source-auditor` needs `Bash` to re-derive numbers, so it withholds
`Write`/`Edit` via `disallowedTools` but its read-only property still rests
partly on instruction. `pr-review-toolkit:code-reviewer` declares no `tools:`
key at all and so has full tool access — its read-only discipline is prose, not
enforcement.

| Agent | Purpose | Tools |
|---|---|---|
| `coderails:source-auditor` | Re-derives a claim from durable sources only; returns PASS/FAIL/UNSUPPORTED. Backs `/coderails:cite-check` | read + Bash; `Write`/`Edit` disallowed |
| `coderails:spec-reviewer` | Reviews a spec for completeness, consistency, clarity, scope, YAGNI before planning | read-only |
| `coderails:wiki-writer` | Authors and maintains LLM Wiki pages against the schema; commits and opens PRs | read + write |
| `coderails:loop-worker` | Implements one scoped task: code, tests, commit, self-review, evidence-backed report | read + write |
| `coderails:deploy-safety-reviewer` | Reviews a PR/change for deploy-safety risk — rollback risk, blast radius, migration/schema safety, feature-flag applicability, deploy-time observability coverage | read + Bash; `Write`/`Edit` disallowed |
| `coderails:design-scout` | Resolves one unresolved architectural fork by reading actual code paths and originating ONE recommendation with a named flip-condition; never reviews an existing document | read + Bash; `Write`/`Edit` disallowed |
| `coderails:disposition-scout` | Resolves the clean-break vs preserve-compat fork per retirement unit in a Phase 1 plan, from the actual consumers and constraints | read + Bash; `Write`/`Edit` disallowed |
| `coderails:docs-auditor` | Runs `/sync-docs` to audit in-tree docs for drift against just-merged code; fixes only loop-caused drift, surfaces pre-existing drift to the human | read + Bash + `Edit`; `Write` disallowed |
| `coderails:preflight-scout` | Runs the pre-planning skill sequence (planning-sequence, premortem, assumptions, notchecked, wiki-query) plus a retro-intake pass; additive-only, never relaxes a gate | read + Bash; `Write`/`Edit` disallowed |
| `coderails:proof-author` | Writes a frozen `proof.json` from `authorising_prompt_raw` + `session_id` + `loop_id` (explicit dispatch inputs) and directly-referenced docs — never the plan or dispatching conversation; every proof stays `pending` | read + Bash + `Write` |

Review agents are **not** duplicated here — `pr-review-toolkit@claude-plugins-official`
already ships `code-reviewer`, `code-simplifier`, `comment-analyzer`,
`pr-test-analyzer`, `silent-failure-hunter` and `type-design-analyzer`, and it is
already a required dependency. coderails only fills the gaps; `deploy-safety-reviewer`
above is one such gap — it covers deploy-safety concerns none of the six address,
and explicitly defers code-level error-handling correctness to `silent-failure-hunter`.

## Hooks

This manual table explains hook behavior. It is not the source for installed registration. The generated table after it gives the exact registration for both providers. Review this text against code when behavior changes.

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.py` | silent — injects `using-coderails` skill into every new session |
| `SessionStart` | `remember_inject_cap_guard.py` | **warn-only by default — writes nothing.** Notices when the **remember** plugin lacks the memory-injection byte cap (`REMEMBER_INJECT_MAX_BYTES`, default 8000) and tells you how to opt in, once per plugin version. Set `REMEMBER_INJECT_CAP_AUTOWRITE=1` in your settings.json `env` block to let it actually apply and re-apply the cap; only then does it **write into another plugin's directory** under `~/.claude/plugins/cache/.../remember/<version>/scripts/`, leaving a timestamped `.coderails-bak-*` backup (one rolling copy). The patch anchors on the plugin's `for MFILE` injection loop only, not the enclosing `if` — see `hooks/patches/README.md` |
| `UserPromptSubmit` | `inject_context.py` | silent — prepends `[ctx]` (cwd, branch, date) and appends the discipline reminder (tag claims (verified)/(inferred)/(guess), add `## Did Not Verify` after file edits) on every prompt |
| `UserPromptSubmit` | `crack_on_gate.py` | context-only — the phrase "crack on" no longer grants anything: when the **raw submitted prompt** contains it, the hook only prints the grant command (`/coderails:authorize`, or `python3 <abs>/scripts/authority.py grant --session <id> --max-prs N`); never scans the transcript or injected context |
| `Stop` + `SubagentStop` | `check_confidence_labels.py` | **advisory (never blocks)** on every path (`Stop` in or out of a loop, `SubagentStop`) — response ≥200 chars with no `(verified)`/`(inferred)`/`(guess)` label emits an `[discipline-advisory]` `additionalContext`, logs `would_block=1 demoted=1 blocked=0 reason_code=confidence_label_missing`, appends an `outcome=demoted` trace row and exits 0 (user override of the unmet criteria, see `docs/decisions/2026-10-04-not-in-gate-demotion.md`); delivery of `additionalContext` to the model at `Stop`/`SubagentStop` is not proven; on `SubagentStop` reads `last_assistant_message` directly. On a `Stop` event, exempt entirely (skipped, logged) when `CODERAILS_HEADLESS_RUN=1`, same rationale as `check_verify_loop.py` below |
| `Stop` + `SubagentStop` | `check_verify_loop.py` | **advisory (never blocks)** on every path — any untagged `## Did Not Verify` bullet (only an explicit `(unverifiable: <reason>)` tag clears it) or a missing section after a 3+-file turn emits an `[discipline-advisory]` `additionalContext`, logs `demoted=1 reason_code=verify_loop_missing`, appends an `outcome=demoted` trace row and exits 0; on `SubagentStop` reads `last_assistant_message` directly. On a `Stop` event, exempt entirely (skipped, logged) when `CODERAILS_HEADLESS_RUN=1` — a dashboard-spawned `claude -p` run has no interactive human to repair a turn for |
| `Stop` | `voice_announce.py` | **observe-only** — speaks a loop lifecycle event (complete / waiting-on-human / stopped / stall) via macOS `say`, backgrounded so it never blocks; silent outside an active loop and when text extraction comes back empty (not a stall); debounced per kind; runs first in the Stop array |
| `Stop` | `loop_state_guard.py` | **block** — agentic loop active but no session-owned progress.json; a nag-once grace stands it down after one delivered absent-progress.json block per session + invocation count. Also blocks a `complete` declaration for a loop with ≥1 work-units when loop-scope `evals.json` is missing, grades `NO-GO`, or grades `GO`/`VERIFICATION_LEVEL0` but is missing a `verification_justification` or a valid grading stamp |
| `Stop` | `loop_stall_guard.py` | **block** — loop incomplete with no recorded stop row (`graph.py stop`; the final LOOP-STOP line is a rendering the hook never reads) (shares loop_state_guard's absent-progress.json grace); an unresolved graph emits one clear human approval request, then stays concise and deduplicated on repeat stops; the native Codex `graph_completion_guard.py` applies the same escalation and fail-closed output-failure fallback; also blocks a recorded `complete` stop when retro.json is missing/malformed (Phase 13 retro gate), when any work_unit is unfinished (deferral gate), or when a sibling proof.json has a proof that's unexecuted-in-transcript or last-failed (proof gate) |
| `Stop` | `unregistered_loop_guard.py` | **nudge** — dispatch-heavy session (≥3 Agent-dispatch turns) with no progress.json and no agentic-loop Skill invocation; never blocks |
| `Stop` + `SubagentStop` | `offload_push_guard.py` | **nudge** — final assistant text names a `git push` to main/master AND carries an offload-to-user cue (e.g. a leading `! ` prefix, "run this yourself"); nudges at most once per session; never blocks |
| `PreToolUse` (Bash) | `destructive_bash_gate.py` | **block** — permanent blocklist: `rm -rf`, `git push --force`/`-f` (naked — `--force-with-lease` has a narrow opt-in carve-out), `git reset --hard`, SQL DROP/TRUNCATE, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete`, `truncate -s/--size`, `shred`, `.env` secret-file access matched as a literal, pre-shell-expansion path token (read or write; `.envrc` and `.env.example`-style templates allowed; a glob whose literal characters commit to the `.env` shape is denied too, but a variable-held path, or a pattern that stays ambiguous until expansion, is uncaught — see docs/REFERENCE.md); also blocks in-Bash source-file edits (redirects, `sed -i`, `tee`, `cp`/`mv` to source extensions) when on main/master; also blocks backtick, `$(...)`, and process-substitution `<(...)`/`>(...)` characters inside a `push.py`/`merge.py`/`post_review.py`/`post_evals.py` free-text argument |
| `PreToolUse` (Bash) | `enforce_pr_workflow.py` | **block** — `gh pr create` without `/coderails:push`; `gh pr merge <N>` (or `scripts/merge.py <N>`, gated identically) without `/pr-review-toolkit:review-pr <N>` (per-PR, consume-on-use) AND without a SHA-bound `GO` coderails eval artifact for the PR's current head (same fail-closed posture as `scripts/merge.py`; a verification_level-0 `GO` satisfies it); `git merge` or `git push` to main/master without `review-pr`; scans subagent transcripts |
| `PreToolUse` (Bash) | `test_gate.py` | **block** on `git commit` if tests fail — opt-in per repo; retain full command logs and report measurements plus a reader command |
| `PreToolUse` (Bash) | `verification_volume_ceiling.py` | **block** — hard-blocks the 3rd+ invocation, per work-unit (branch), of `hooks/scripts/tests/run_all.py` or a `scripts/post_evals.py validate-structure` ceremony; no override |
| `PreToolUse` (Bash) | `reviewer_bash_allowlist.py` | block — only for `agent_type` in `deploy-safety-reviewer`/`design-scout`/`disposition-scout`/`preflight-scout`/`source-auditor`: allows only a single read-only command (`ls`/`cat`/`head`/`tail`/`wc`/`grep`/`rg`/`sha256sum`, `git status\|log\|diff\|show\|blame`, `gh pr view\|list --json`); denies chaining, redirection, substitution, `--output`/`--pre`/`--ext-diff`, interpreters. Absent or other `agent_type` is a no-op. The guarded agent files no longer list `Bash` (their tools are their per-role MCP tools); this hook is defence in depth. Ceilings: [docs/decisions/e2-reviewer-bash-allowlist.md](docs/decisions/e2-reviewer-bash-allowlist.md) |
| `PreToolUse` (Bash) | `subagent_identity_gate.py` | block — a Bash call whose payload carries a non-blank `agent_id` but no usable `agent_type` (absent, blank or not a string) in a graph-bound session (this session's `progress.json` carries `graph` and names this session) is denied, reason `bash_agent_type_absent`, with a discipline-log line and a trace row. A call with no `agent_id` (the orchestrator), any non-blank `agent_type`, no `progress.json`, a foreign session's `progress.json` or a non-Bash tool is untouched. Claude only: Codex PreToolUse payloads carry no `agent_type`/`agent_id`, so Codex has no equivalent hook (its guard is `shell_tool = false` role files plus contained role sessions, see [docs/CAPABILITIES.md](docs/CAPABILITIES.md)). Cooperating-agent safeguard: it relies on the harness filling `agent_id`. |
| `PreToolUse` (Bash) | `action_authority_gate.py` | The shipped workflow sets `action_authority: advisory`: it warns about a missing receipt and checks live session limits. With no setting, the gate is off. Explicit `enforce` requires a signed receipt and an expected head SHA for `merge.py`. Routine PR work needs no key or passphrase. PR review, eval, and integrity checks still apply. See [the authority decision](docs/decisions/e3-authority-object.md). |
| `PreToolUse` (AskUserQuestion) | `crack_on_gate.py` | **block** — denies `AskUserQuestion` while the session's crack-on authority is live (revoke: `python3 scripts/authority.py revoke --session <id>`; it also expires after 24h): proceed autonomously instead of asking. Scoped to `AskUserQuestion` only — prose questions are not blocked, and the agentic-loop hard-stops (turn-ending `LOOP-STOP` declarations) are untouched |
| `PreToolUse` (Bash/Edit/Write/MultiEdit/Read/Grep/Glob/WebFetch/NotebookEdit) | `agent_only_gate.py` | **nudge by default; block opt-in** (`AGENT_ONLY_GATE_ENFORCE=1`) — steers the top-level orchestrator away from inline do-work tool calls; always silent for calls made inside a dispatched subagent or for a whole-command workflow-chain carve-out (`gh`, `git`, `scripts/push\|merge\|post_review\|post_evals.py`) |
| `PreToolUse` (Agent) | `agent_model_routing_nudge.py` | **advisory nudge only** — when no `model` is set and the dispatch description/prompt matches a mechanical or complex/architectural word list, suggests `haiku` or `opus` respectively; never blocks |
| `PreToolUse` (Agent) | `loop_dispatch_guard.py` | **block** — validates graph schema 3, session/loop ownership, current revision, active wave, node and `CODERAILS_GRAPH_DISPATCH` envelope against its `begin-wave` dispatch record (single use; rendered contract sections must appear verbatim). The record's role is asserted against `subagent_type`: guarded scout roles need `coderails:<role>`, other roles also accept `general-purpose`, anything else is `role_mismatch`. With a nonempty work-unit roster, implementation dispatch requires owned frozen or valid graded evals; frozen evals bind session + loop, not the changing graph revision. Preparation nodes remain exempt from that eval check. Missing state blocks marked/custom-worker dispatch; foreign state blocks every Agent request. The Python sandbox launcher invokes the same guard before allocating scratch. |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.py` | **block** — on main/master, blocks edits to any file EXCEPT an explicit allowlist (`.md`/`.txt`/`.rst`, `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg`, `.gitignore`, `LICENSE`); plugin-source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked. Also blocks `.claude/settings.json` / `.claude/settings.local.json` edits on **any** branch (the permission files that can bypass every gate) |
| `PreToolUse` (Write/Edit/MultiEdit) | `comment_citation_gate.py` | **block** — blocks new comment content that cites a session-artifact label (`E#:`, `F# fix`, `CHANGE B#`/`C#`, `Task A#`, `TA-I#`, "reviewer finding", "per the plan", etc.) instead of stating the constraint the code enforces; `.md` files exempt; fails open |
| `PreToolUse` (Write/Edit/MultiEdit) | `wiki_taxonomy_gate.py` | **block** — inert until `.coderails/workflow.config.yaml` exists at the plugin root (absent on a fresh clone until `/coderails:init` scaffolds it); once present, in an LLM wiki vault (identified positively: the write's repo root must equal `wiki_path`, resolved relative to `CLAUDE_PLUGIN_ROOT` unless absolute, corroborated by ≥2 of the parsed "## Page types" directories existing on disk as a secondary sanity check), blocks a write into a top-level directory not sanctioned by that section (read from the plugin's `AGENTS.md`); taxonomy is parsed live, never hardcoded; fails open on any ambiguity (schema absent, no config, the vault not being a git repo, `wiki_path` unresolvable, no section, unparseable, write outside the configured vault, or <2 directories present) |
| `PostToolUse` (Write/Edit/MultiEdit) | `quality_feedback.py` | **warn-only** — injects quality feedback into `PostToolUse` context; always exits successfully and cannot block a write |

### Generated hook registration

This table lists the hooks in each installed provider. Run `python3 scripts/gen_hooks.py --check` to check the generated files.

<!-- hook-registry:start -->
Claude protocol: Claude hook event response: exit 0 JSON or exit 2 block.
Codex protocol: Codex hook event response: exit 0 JSON decision.

| Provider | Event | Matcher | Hook | Options | Mode | Default | Category | Action | Failure | Limit |
|---|---|---|---|---|---|---|---|---|---|---|
| claude | SessionStart | startup\|resume\|clear\|compact | `inject_bootstrap.py` | async=False | silent | registered for its provider event | inject bootstrap | Check the plugin root and hook registration when context is absent. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | SessionStart | startup\|resume\|clear\|compact | `remember_inject_cap_guard.py` | async=False | advisory | warns by default; auto-write requires explicit opt-in | remember inject cap guard | Set the memory injection cap or use the documented opt-in patch. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | UserPromptSubmit | all | `inject_context.py` | timeout=5 | silent | registered for its provider event | inject context | Check the prompt hook registration when context is absent. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | UserPromptSubmit | all | `crack_on_gate.py` | timeout=5 | block | the phrase grants nothing; a live typed authority can block questions | crack on gate | Use the typed authority command, or continue after the authority expires. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `voice_announce.py` | timeout=15, async=True | observe | registered for its provider event | voice announce | Read the loop state when a spoken notice is absent. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `check_confidence_labels.py` | timeout=15 | advisory | registered for its provider event | check confidence labels | Add the correct confidence label to each claim that needs one. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `check_verify_loop.py` | timeout=15 | advisory | registered for its provider event | check verify loop | Complete the verification section and mark each unresolved check. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `loop_state_guard.py` | timeout=15 | block | registered for its provider event | loop state guard | Restore owned graph and graded loop eval evidence. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `loop_stall_guard.py` | timeout=15 | block | registered for its provider event | loop stall guard | Record the required stop and complete unresolved graph work. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `unregistered_loop_guard.py` | timeout=15 | nudge | registered for its provider event | unregistered loop guard | Register the active agentic loop graph before more dispatches. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | Stop | all | `offload_push_guard.py` | timeout=15 | nudge | registered for its provider event | offload push guard | Keep the push in the authorised workflow. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | SubagentStop | all | `check_confidence_labels.py` | timeout=15 | advisory | registered for its provider event | check confidence labels | Add the correct confidence label to each claim that needs one. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | SubagentStop | all | `check_verify_loop.py` | timeout=15 | advisory | registered for its provider event | check verify loop | Complete the verification section and mark each unresolved check. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | SubagentStop | all | `offload_push_guard.py` | timeout=15 | nudge | registered for its provider event | offload push guard | Keep the push in the authorised workflow. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `destructive_bash_gate.py` | timeout=5 | block | registered for its provider event | destructive bash gate | Use a safe command that avoids the blocked operation. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `enforce_pr_workflow.py` | timeout=10 | block | inactive without workflow config | enforce pr workflow | Run the required PR review and post current-head evidence. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `test_gate.py` | timeout=180 | block | off unless test commands are configured | test gate | Fix the failed tests before the commit. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `verification_volume_ceiling.py` | timeout=5 | block | registered for its provider event | verification volume ceiling | Use focused tests after the allowed full-suite runs. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `reviewer_bash_allowlist.py` | timeout=5 | block | registered for its provider event | reviewer bash allowlist | Use an allowed read-only command or a granted capability tool. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `subagent_identity_gate.py` | timeout=5 | block | registered for its provider event | subagent identity gate | Dispatch with a native agent type that the graph can identify. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash | `action_authority_gate.py` | timeout=10 | block | off by default; advisory warns; enforce checks signed receipts | action authority gate | Use the configured authority path for the exact action and session. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | AskUserQuestion | `crack_on_gate.py` | timeout=5 | block | the phrase grants nothing; a live typed authority can block questions | crack on gate | Use the typed authority command, or continue after the authority expires. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Bash\|Edit\|Write\|MultiEdit\|Read\|Grep\|Glob\|WebFetch\|NotebookEdit | `agent_only_gate.py` | timeout=5 | nudge | nudge by default; AGENT_ONLY_GATE_ENFORCE=1 blocks | agent only gate | Dispatch source work to an agent or use the allowed workflow command. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Agent | `agent_model_routing_nudge.py` | timeout=5 | nudge | registered for its provider event | agent model routing nudge | Select a model role that fits the task when the suggestion is useful. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Agent | `loop_dispatch_guard.py` | timeout=10 | block | registered for its provider event | loop dispatch guard | Use the current owned graph dispatch envelope and role. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Agent | `worker_containment_gate.py` | timeout=10 | block | registered for its provider event | worker containment gate | Use the required containment acknowledgement or a low-risk path. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Write\|Edit\|MultiEdit | `no_edit_on_main.py` | timeout=5 | block | registered for its provider event | no edit on main | Move the source edit to a feature branch. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Write\|Edit\|MultiEdit | `comment_citation_gate.py` | timeout=5 | block | registered for its provider event | comment citation gate | State the durable rule in the comment without a session label. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PreToolUse | Write\|Edit\|MultiEdit | `wiki_taxonomy_gate.py` | timeout=5 | block | inactive without workflow config and a resolved wiki | wiki taxonomy gate | Write the page under a directory allowed by the wiki schema. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| claude | PostToolUse | Write\|Edit\|MultiEdit | `quality_feedback.py` | timeout=10 | advisory | registered for its provider event | quality feedback | Read the quality result and correct reported source findings. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | SessionStart | startup\|resume\|clear\|compact | `inject_bootstrap.py` | timeout=10, additionalContextLimit=1200 | silent | registered for its provider event | inject bootstrap | Check the plugin root and hook registration when context is absent. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | UserPromptSubmit | all | `inject_context.py` | timeout=10, additionalContextLimit=500 | silent | registered for its provider event | inject context | Check the prompt hook registration when context is absent. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | UserPromptSubmit | all | `crack_on_gate.py` | timeout=10 | block | the phrase grants nothing; a live typed authority can block questions | crack on gate | Use the typed authority command, or continue after the authority expires. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | Stop | all | `graph_completion_guard.py` | timeout=10 | block | registered for its provider event | graph completion guard | Resolve the graph state and record a valid stop result. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | Stop | all | `check_confidence_labels.py` | timeout=10 | advisory | registered for its provider event | check confidence labels | Add the correct confidence label to each claim that needs one. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | SubagentStop | all | `check_confidence_labels.py` | timeout=10 | advisory | registered for its provider event | check confidence labels | Add the correct confidence label to each claim that needs one. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^Bash$ | `destructive_bash_gate.py` | timeout=10 | block | registered for its provider event | destructive bash gate | Use a safe command that avoids the blocked operation. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^Bash$ | `test_gate.py` | timeout=180 | block | off unless test commands are configured | test gate | Fix the failed tests before the commit. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^Bash$ | `verification_volume_ceiling.py` | timeout=10 | block | registered for its provider event | verification volume ceiling | Use focused tests after the allowed full-suite runs. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^Bash$ | `pr_publication_gate.py` | timeout=60 | block | applies to guarded Codex publication commands | pr publication gate | Complete the required review and eval steps for this PR head. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^Bash$ | `action_authority_gate.py` | timeout=10 | block | off by default; advisory warns; enforce checks signed receipts | action authority gate | Use the configured authority path for the exact action and session. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^request_user_input$ | `crack_on_gate.py` | timeout=10 | block | the phrase grants nothing; a live typed authority can block questions | crack on gate | Use the typed authority command, or continue after the authority expires. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^(?:spawn_agent\|collaborationspawn_agent)$ | `loop_dispatch_guard.py` | timeout=10 | block | registered for its provider event | loop dispatch guard | Use the current owned graph dispatch envelope and role. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^apply_patch$ | `no_edit_on_main.py` | timeout=10 | block | registered for its provider event | no edit on main | Move the source edit to a feature branch. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^apply_patch$ | `comment_citation_gate.py` | timeout=10 | block | registered for its provider event | comment citation gate | State the durable rule in the comment without a session label. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PreToolUse | ^apply_patch$ | `wiki_taxonomy_gate.py` | timeout=10 | block | inactive without workflow config and a resolved wiki | wiki taxonomy gate | Write the page under a directory allowed by the wiki schema. | deny or block with a visible reason | Runs in the caller trust domain; server policy remains the release boundary. |
| codex | PostToolUse | ^apply_patch$ | `quality_feedback.py` | timeout=15, additionalContextLimit=1000 | advisory | registered for its provider event | quality feedback | Read the quality result and correct reported source findings. | continue and record the failure | Runs in the caller trust domain; server policy remains the release boundary. |
<!-- hook-registry:end -->

Test-gate runs retain complete stdout/stderr under `~/.coderails/test-output/`
(override with `CODERAILS_TEST_OUTPUT_DIR`), including successful runs. A failure
notice identifies the log; the provider's `test_output.py` reader supports full,
line-range and literal-search retrieval. Default reads return metadata and
guidance; the agent expands requests as needed. Completed logs compress
automatically under a configurable 1 GiB compressed-log budget
(`CODERAILS_TEST_LOG_BUDGET_BYTES`), expiring oldest completed logs first.
Active and just-completed runs are protected, so the budget may be exceeded.
Compact metrics and expiry records persist separately. Emitted bytes do not establish model delivery. See
[reader examples and measurement limits](docs/REFERENCE.md#retained-test-gate-output).

## Sandboxed workers

With `sandbox_workers: true` (the default), the Claude implementation launcher
uses pinned `@anthropic-ai/sandbox-runtime` in a scratch clone. It needs the
OS sandbox, `npx`, and a dedicated Claude worker credential; missing inputs
stop graph implementation dispatch. The graph driver prepares execution C before
authorization, then checks a fixed uncommitted proposal before materializing it
into reserved root checkout D. Root reviews and publishes; resume preserves later
root edits. The orchestrator remains unsandboxed.

Codex native `spawn_agent` inherits the parent sandbox. The Codex dispatch hook
therefore refuses native implementation work while containment is on. The
existing OAuth graph driver binds issued dispatches to sealed process evidence;
see [driver recovery](docs/RUNBOOK-DRIVER.md). The standalone helper in
`packages/codex/scripts/codex_worker.py` keeps its direct interface and runs with
`workspace-write`, explicit ChatGPT login and the OpenAI provider. Its output
and trace earn no graph completion credit. Neither route uses an API key.
See [worker containment](docs/WORKER-CONTAINMENT.md) for recovery steps, counters, and limits.

## Requirements

- Python 3.9 or newer; the Python runtime uses only the standard library
- Claude Code 2.1.x for the root plugin, or the Codex CLI for `packages/codex/`
- `gh` and `git` for the workflow commands; `jq` is not a runtime dependency
- For `/push` / `/merge`: a **GitHub**-hosted repo with an authenticated `gh` CLI (`gh auth login`) — the workflow uses `gh`, so non-GitHub remotes (GitLab/Bitbucket/Gitea) are not supported.
- `pr-review-toolkit@claude-plugins-official` for the review stage of `/workflow`
- `superpowers@claude-plugins-official` for dev-workflow skills (planning, TDD, debugging, code review, worktrees)
- For Claude sandboxed workers: `node`/`npx`, macOS or Linux/WSL2

## Uninstall Claude

```bash
python3 ~/Documents/Github/coderails/uninstall.py
# then: /plugin uninstall coderails
```

MIT. Gary Harrison.
