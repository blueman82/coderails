# coderails

Gary's Claude Code kit, in one plugin. Two halves:

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
unzip coderails.zip -d ~/Documents/Github/
bash ~/Documents/Github/coderails/install.sh
# restart Claude Code, then:
#   /plugin marketplace add ~/Documents/Github/coderails
#   /plugin install coderails@coderails
#   /reload-plugins
```

## Commands

| Command | What it does |
|---|---|
| `/workflow` | Orchestrate the full feature workflow: prep → code → push → review → merge → wiki |
| `/coderails:init` | Scaffold `.claude/workflow.config.yaml` for the current repo |
| `/prep` | Safety branch + feature branch + Jira ticket |
| `/push` | Stage, commit, push, open PR with reviewers; auto-resolve linked Jira |
| `/merge` | Merge approved PR, switch to main, pull |
| `/assumptions` | List every assumption, marked verified or inferred |
| `/verify` | Re-derive a specific claim from sources only — no recall |
| `/notchecked` | List claims made but not verified |
| `/disconfirm` | Argue against your own most recent recommendation |
| `/test-gate-setup` | Detect the test runner and create `.claude/test_command` |

## Skills

coderails is self-contained — it ships the dev-workflow skills it needs. `pr-review-toolkit@claude-plugins-official` is still required for the review stage of `/workflow`.

23 skills are bundled across three groups. Full catalog: [`docs/REFERENCE.md`](./docs/REFERENCE.md).

**Dev-workflow skills**

| Skill | Purpose |
|---|---|
| `agentic-loop` | Multi-agent orchestration: TeamCreate, no-human-gates, multi-PR loops |
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
| `using-coderails` | Self-bootstrap: injected at SessionStart, explains coderails to Claude |

**Wiki**

| Skill | Purpose |
|---|---|
| `wiki-ingest` | Write or update wiki pages from a PR/decision |
| `wiki-init` | Scaffold the wiki vault and index |
| `wiki-lint` | Validate wiki structure and links |
| `wiki-query` | Answer questions from the wiki |

## Hooks

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.sh` | silent — injects `using-coderails` skill into every new session |
| `UserPromptSubmit` | `inject_context.sh` | silent — prepends `[ctx]` (cwd, branch, date) |
| `UserPromptSubmit` | `discipline_catchup.sh` | warn |
| `Stop` | `check_confidence_labels.sh` | **block** — response ≥200 chars with no confidence label |
| `Stop` | `check_verify_loop.sh` | **block** — `## Did Not Verify` bullet naming a resolvable file |
| `Stop` | `loop_state_guard.sh` | **block** — agentic loop active but no session-owned progress.json |
| `Stop` | `loop_stall_guard.sh` | **block** — loop incomplete with no valid LOOP-STOP declaration |
| `PreToolUse` (Bash) | `destructive_bash_gate.sh` | **block** |
| `PreToolUse` (Bash) | `enforce_pr_workflow.sh` | **block** — `gh pr create/merge` without the required workflow steps |
| `PreToolUse` (Bash) | `test_gate.sh` | **block** on `git commit` if tests fail — opt-in per repo |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.sh` | **block** — code-file edits directly on main/master |

## Requirements

- Claude Code 2.1.x
- `gh`, `jq`, `git`
- For `/push` / `/merge`: an authenticated git host (`gh auth login`)
- `pr-review-toolkit@claude-plugins-official` for the review stage of `/workflow`

## Uninstall

```bash
bash ~/Documents/Github/coderails/uninstall.sh
# then: /plugin uninstall coderails
```

MIT. Gary Harrison.
