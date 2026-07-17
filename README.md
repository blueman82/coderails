# coderails

coderails is a Claude Code workflow plugin: the prep → push → merge → wiki
command chain plus planning/orchestration skills and a self-checking
discipline loop. It combines:

- **Workflow** — the `prep → push → merge → wiki` command chain plus the
  agentic-loop, planning-sequence, premortem, and handoff skills.
- **Guardrails** — a self-checking discipline loop: Claude labels claims
  (verified)/(inferred), is blocked at stop until the `## Did Not Verify`
  section is present and resolved, and is gated on destructive bash and
  failing project tests.

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

36 skills are bundled across four groups. Full
catalog: [`docs/REFERENCE.md`](./docs/REFERENCE.md).

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
| `dashboard` | Live local web HUD: sessions, loops, PR gate states, runs, memory activity |
| `fable-mode` | High-autonomy self-verifying working mode for non-trivial tasks |
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

## Hooks

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.sh` | silent — injects `using-coderails` skill into every new session |
| `UserPromptSubmit` | `inject_context.sh` | silent — prepends `[ctx]` (cwd, branch, date); on the first prompt of a session also appends the discipline reminder |
| `UserPromptSubmit` | `crack_on_gate.sh` | silent — stamps a per-session crack-on flag when the **raw submitted prompt** contains "crack on" (case-insensitive, word-boundary); never scans the transcript or injected context |
| `Stop` + `SubagentStop` | `check_confidence_labels.sh` | **block** outside an active agentic loop — response ≥200 chars with no `(verified)`/`(inferred)`/`(guess)` label; inside an active, incomplete loop, `Stop`-event violations demote to a model-visible warn (`additionalContext`) instead — `SubagentStop`/worker output still blocks; on `SubagentStop` reads `last_assistant_message` directly |
| `Stop` + `SubagentStop` | `check_verify_loop.sh` | **block** outside an active agentic loop — any untagged `## Did Not Verify` bullet (only an explicit `(unverifiable: <reason>)` tag passes); or missing section after a 3+-file turn; inside an active, incomplete loop, `Stop`-event violations demote to a model-visible warn (`additionalContext`) instead — `SubagentStop`/worker output still blocks; on `SubagentStop` reads `last_assistant_message` directly |
| `Stop` | `voice_announce.sh` | **observe-only** — speaks a loop lifecycle event (complete / waiting-on-human / stopped / stall) via macOS `say`, backgrounded so it never blocks; silent outside an active loop and when text extraction comes back empty (not a stall); debounced per kind; runs first in the Stop array |
| `Stop` | `loop_state_guard.sh` | **block** — agentic loop active but no session-owned progress.json |
| `Stop` | `loop_stall_guard.sh` | **block** — loop incomplete with no valid LOOP-STOP declaration; also blocks a `complete` declaration when retro.json is missing/malformed (Phase 13 retro gate), when any work_unit is unfinished (deferral gate), or when a sibling proof.json has a proof that's unexecuted-in-transcript or last-failed (proof gate) |
| `Stop` | `unregistered_loop_guard.sh` | **nudge** — dispatch-heavy session (≥3 Agent-dispatch turns) with no progress.json and no agentic-loop Skill invocation; never blocks |
| `Stop` + `SubagentStop` | `offload_push_guard.sh` | **nudge** — final assistant text names a `git push` to main/master AND carries an offload-to-user cue (e.g. a leading `! ` prefix, "run this yourself"); nudges at most once per session; never blocks |
| `PreToolUse` (Bash) | `destructive_bash_gate.sh` | **block** — permanent blocklist: `rm -rf`, `git push --force`/`-f` (naked — `--force-with-lease` has a narrow opt-in carve-out), `git reset --hard`, SQL DROP/TRUNCATE, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete`, `truncate -s/--size`, `shred`; also blocks in-Bash source-file edits (redirects, `sed -i`, `tee`, `cp`/`mv` to source extensions) when on main/master; also blocks backtick, `$(...)`, and process-substitution `<(...)`/`>(...)` characters inside a `push.sh`/`merge.sh`/`post_review.sh`/`post_evals.sh` free-text argument |
| `PreToolUse` (Bash) | `enforce_pr_workflow.sh` | **block** — `gh pr create` without `/coderails:push`; `gh pr merge <N>` (or `scripts/merge.sh <N>`, gated identically) without `/pr-review-toolkit:review-pr <N>` (per-PR, consume-on-use) AND without a SHA-bound `GO` coderails eval artifact for the PR's current head (same fail-closed posture as `scripts/merge.sh`; a tier-0 `GO` satisfies it); `git merge` or `git push` to main/master without `review-pr`; scans subagent transcripts |
| `PreToolUse` (Bash) | `test_gate.sh` | **block** on `git commit` if tests fail — opt-in per repo |
| `PreToolUse` (AskUserQuestion) | `crack_on_gate.sh` | **block** — denies `AskUserQuestion` while the session's crack-on flag is stamped (the user typed "crack on" in a raw prompt this session): proceed autonomously instead of asking. Scoped to `AskUserQuestion` only — the agentic-loop hard-stops (turn-ending `LOOP-STOP` declarations) are untouched |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.sh` | **block** — on main/master, blocks edits to any file EXCEPT an explicit allowlist (`.md`/`.txt`/`.rst`, `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg`, `.gitignore`, `LICENSE`); plugin-source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked. Also blocks `.claude/settings.json` / `.claude/settings.local.json` edits on **any** branch (the permission files that can bypass every gate) |
| `PreToolUse` (Write/Edit/MultiEdit) | `comment_citation_gate.sh` | **block** — blocks new comment content that cites a session-artifact label (`E#:`, `F# fix`, `CHANGE B#`/`C#`, `Task A#`, `TA-I#`, "reviewer finding", "per the plan", etc.) instead of stating the constraint the code enforces; `.md` files exempt; fails open |

## Sandboxed workers

With `config.sandbox_workers: true` (`.claude/workflow.config.yaml`), the
agentic-loop dispatches implementation-unit workers via
`@anthropic-ai/sandbox-runtime` (`scripts/sandbox/spawn-sandboxed-worker.sh`),
an OS-enforced filesystem containment layer (Seatbelt on macOS, bubblewrap on
Linux) that restricts writes to an explicit per-worker allowlist — the
worktree, per-worker scratch, the primary repo's `.git` (with its `hooks` and
`config` subpaths denied), the per-user `$TMPDIR`, and a narrowed slice of
Claude Code's own `~/.claude` config state (a named residual — worker
containment excludes claude-home) — never the orchestrator, which is
unaffected. Requires `node`/`npx`, macOS or Linux/WSL2.

## Requirements

- Claude Code 2.1.x
- `gh`, `jq`, `git`
- For `/push` / `/merge`: a **GitHub**-hosted repo with an authenticated `gh` CLI (`gh auth login`) — the workflow uses `gh`, so non-GitHub remotes (GitLab/Bitbucket/Gitea) are not supported.
- `pr-review-toolkit@claude-plugins-official` for the review stage of `/workflow`
- For sandboxed workers (opt-in): `node`/`npx`, macOS or Linux/WSL2

## Uninstall

```bash
bash ~/Documents/Github/coderails/uninstall.sh
# then: /plugin uninstall coderails
```

MIT. Gary Harrison.
