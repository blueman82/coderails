# coderails

coderails is a Claude Code workflow plugin: the prep → push → merge → wiki
command chain plus planning/orchestration skills and a self-checking
discipline loop. Two halves:

- **Workflow** — the `prep → push → merge → wiki` command chain plus the
  agentic-loop, planning-sequence, premortem, and handoff skills.
- **Guardrails** — a self-checking discipline loop: Claude labels claims
  (verified)/(inferred), gets nudged for a `## Did Not Verify` section, and is
  gated on destructive bash and failing project tests.

It started as two separate plugins (`workflow-tools` and `claude-guardrails`).
This is the merge: one install, one marketplace key, no launchd, no calibration
ritual.

## Install

See [INSTALLATION.md](./INSTALLATION.md). Short version:

```bash
git clone https://github.com/blueman82/coderails.git ~/Documents/Github/coderails
cd ~/Documents/Github/coderails
bash install.sh --dry-run
bash install.sh
# restart Claude Code, then:
#   /plugin marketplace add ~/Documents/Github/coderails
#   /plugin install coderails@coderails
#   /reload-plugins
```

Per project, run once: `/coderails:init` scaffolds `.claude/workflow.config.yaml`
from [`examples/workflow.config.yaml`](./examples/workflow.config.yaml) — the
preferred way to set up a new repo.

## Commands

| Command | What it does |
|---|---|
| `/workflow` | Orchestrate the full feature workflow: prep → code → push → review → merge → wiki |
| `/coderails:init` | Scaffold `.claude/workflow.config.yaml` for the current repo |
| `/prep` | Safety branch + feature branch + Jira ticket |
| `/push` | Stage, commit, push, open PR with reviewers; auto-resolve linked Jira |
| `/post-review` | Post SHA-bound review artifact on PR; required by `/merge` gate |
| `/coderails:task-evals` | Generate and freeze a tiered set of success evals for a task |
| `/coderails:post-evals` | Post SHA-bound eval artifact on PR; required by `/merge` gate |
| `/merge` | Merge approved PR, switch to main, pull |
| `/assumptions` | List every assumption, marked verified or inferred |
| `/verify` | Re-derive a specific claim from sources only — no recall |
| `/notchecked` | List claims made but not verified |
| `/disconfirm` | Argue against your own most recent recommendation |
| `/test-gate-setup` | Detect the test runner and create `.claude/test_command` |

## Skills

coderails is self-contained — it ships the dev-workflow skills it needs. `pr-review-toolkit@claude-plugins-official` is still required for the review stage of `/workflow`.

28 skills are bundled across four groups. Full catalog: [`docs/REFERENCE.md`](./docs/REFERENCE.md).

**Dev-workflow skills**

| Skill | Purpose |
|---|---|
| `agentic-loop` | Multi-agent orchestration: spawned teams, no-human-gates, multi-PR loops |
| `brainstorming` | Explore intent and requirements before implementation |
| `dispatching-parallel-agents` | Fan-out independent tasks across agents |
| `executing-plans` | Drive a written plan to completion |
| `finishing-a-development-branch` | Final checks before merging |
| `receiving-code-review` | Apply review feedback systematically |
| `requesting-code-review` | Prepare a PR for review |
| `subagent-driven-development` | Delegate implementation tasks to subagents |
| `systematic-debugging` | Structured root-cause analysis |
| `test-driven-development` | Red-green-refactor discipline |
| `using-git-worktrees` | Parallel work via git worktrees |
| `verification-before-completion` | Final verification pass before declaring done |
| `writing-plans` | Convert specs into step-by-step plans |
| `writing-skills` | Scaffold new skills from scratch |

**coderails-original**

| Skill | Purpose |
|---|---|
| `handoff` | Structured memory + continuation prompt for a fresh session |
| `improve-prompt` | Surfaces ambiguities and rewrites underspecified prompts |
| `planning-sequence` | Pre-Parade → Premortem → Red Team on a plan |
| `premortem` | Assume failure, reason backwards to causes |
| `task-evals` | Game-resistant success-eval generation: frozen `evals.json` with negative controls |
| `using-coderails` | Self-bootstrap: injected at SessionStart, explains coderails to Claude |

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

## Hooks

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.sh` | silent — injects `using-coderails` skill into every new session |
| `UserPromptSubmit` | `inject_context.sh` | silent — prepends `[ctx]` (cwd, branch, date); on the first prompt of a session also appends the discipline reminder |
| `UserPromptSubmit` | `discipline_catchup.sh` | warn |
| `Stop` + `SubagentStop` | `check_confidence_labels.sh` | **block** — response ≥200 chars with no `(verified)`/`(inferred)`/`(guess)` label; on `SubagentStop` reads `last_assistant_message` directly |
| `Stop` + `SubagentStop` | `check_verify_loop.sh` | **block** — any untagged `## Did Not Verify` bullet (only an explicit `(unverifiable: <reason>)` tag passes); on `SubagentStop` reads `last_assistant_message` directly |
| `Stop` | `loop_state_guard.sh` | **block** — agentic loop active but no session-owned progress.json |
| `Stop` | `loop_stall_guard.sh` | **block** — loop incomplete with no valid LOOP-STOP declaration |
| `Stop` | `unregistered_loop_guard.sh` | **nudge** — dispatch-heavy session (≥3 Agent-dispatch turns) with no progress.json and no agentic-loop Skill invocation; never blocks |
| `PreToolUse` (Bash) | `destructive_bash_gate.sh` | **block** — permanent blocklist: `rm -rf`, `git push --force`, `git reset --hard`, SQL DROP/TRUNCATE, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete`, `truncate -s/--size`, `shred`; also blocks in-Bash source-file edits (redirects, `sed -i`, `tee`, `cp`/`mv` to source extensions) when on main/master; also blocks backtick/`$()` command-substitution characters inside a `push.sh`/`merge.sh`/`post_review.sh`/`post_evals.sh` free-text argument |
| `PreToolUse` (Bash) | `enforce_pr_workflow.sh` | **block** — `gh pr create` without `/coderails:push`; `gh pr merge <N>` without `/pr-review-toolkit:review-pr <N>` (per-PR, consume-on-use); `git merge` or `git push` to main/master without `review-pr`; scans subagent transcripts |
| `PreToolUse` (Bash) | `test_gate.sh` | **block** on `git commit` if tests fail — opt-in per repo |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.sh` | **block** — on main/master, blocks edits to any file EXCEPT an explicit allowlist (`.md`/`.txt`/`.rst`, `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg`, `.gitignore`, `LICENSE`); plugin-source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked. Also blocks `.claude/settings.json` / `.claude/settings.local.json` edits on **any** branch (the permission files that can bypass every gate) |

## Requirements

- Claude Code 2.1.x
- `gh`, `jq`, `git`
- For `/push` / `/merge`: a **GitHub**-hosted repo with an authenticated `gh` CLI (`gh auth login`) — the workflow uses `gh`, so non-GitHub remotes (GitLab/Bitbucket/Gitea) are not supported.
- `pr-review-toolkit@claude-plugins-official` for the review stage of `/workflow`

## Uninstall

```bash
bash ~/Documents/Github/coderails/uninstall.sh
# then: /plugin uninstall coderails
```

MIT. Gary Harrison.
