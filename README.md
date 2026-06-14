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

| Skill | When it fires |
|---|---|
| `agentic-loop` | Multi-agent orchestration: TeamCreate, no-human-gates, multi-PR loops |
| `planning-sequence` | Pre-Parade → Premortem → Red Team on a plan |
| `premortem` | Assume failure, reason backwards to causes |
| `handoff` | Structured memory + continuation prompt for a fresh session |
| `improve-prompt` | Surfaces ambiguities and rewrites underspecified prompts before execution |

## Hooks

| Event | Hook | Mode |
|---|---|---|
| Stop | confidence-label check | **block** |
| Stop | verify-loop / Did-Not-Verify check | **block** |
| UserPromptSubmit | inject `[ctx]` line (cwd, branch, date) | silent |
| UserPromptSubmit | discipline catch-up reminder | warn |
| PreToolUse (Bash) | destructive-bash gate | **block** |
| PreToolUse (Bash) | project test gate (opt-in per repo) | **block** |

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
