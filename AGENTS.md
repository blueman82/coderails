# AGENTS.md — Coderails

Single source read at conversation start. Covers the repo working guide (below) and the coderails wiki schema (`## Wiki schema` near the end). `CLAUDE.md` is a thin pointer here — edit here, not there.

Wiki vault: `../coderails-wiki` relative to the plugin, or wherever `/wiki-init` placed it.

## Current integrity-gate replacement

The semantic judge is replaced by a root-owned mechanical `integrity-review` attestor. Checks SHA-bound review/eval evidence, command/eval structure, policy paths, provenance fields, bounded diff input — never classifies work or asks an LLM for a verdict. Authoritative: `docs/INTEGRITY-GATE.md`, `scripts/integrity-gate/integrity-gate-runner.sh`, `integrity_review.machine_user` config.

## What this repo is

Two independent plugins, not an application:
- Working Claude Code plugin at repo root.
- Native Codex plugin at `packages/codex/`.

`install.sh` defaults to Claude; `--provider codex` for Codex. Claude plugin bundles:
1. Workflow commands — `prep → push → merge → wiki` chain (`commands/*.md`)
2. Skills — agentic-loop, planning-sequence, premortem, handoff (`skills/*/SKILL.md`)
3. Discipline loop — hooks nudging/blocking on confidence labels, unverified claims, destructive bash, failing tests (`hooks/`)

No build step, no compiled artifact. Source = markdown (commands, skills) + bash (hook scripts, workflow scripts). Version-controlled in your own fork/repo.

**Agentic-loop graph runtime**: the `agentic-loop` skill creates durable graph state in `progress.json` (nodes, edges, joins, status, outcomes, retries) with readiness checks and plan/record helpers for dispatching and recording waves. Manually operated — the model reads the graph, dispatches ready work, records results; not an automatic scheduler. Belongs only to the root Claude plugin.

## How the pieces wire together

```
.claude-plugin/plugin.json      → plugin manifest (name, version, metadata)
.claude-plugin/marketplace.json → local-directory marketplace entry (source: ./)
hooks/hooks.json                → maps lifecycle events → hook scripts
  └─ hooks/scripts/*.sh         → the actual gate/nudge logic
commands/*.md                   → slash commands (frontmatter + prose instructions)
  └─ scripts/*.sh               → bash the commands shell out to (push.sh, merge.sh)
       └─ scripts/lib/git-common.sh → shared git/gh/PR helpers, sourced by both
       └─ scripts/lib/config.sh     → workflow.config.yaml resolver (single source of truth; see "Config resolution")
  └─ scripts/sandbox/*.sh       → srt sandbox wrapper for spawned workers (see "Sandboxed workers")
  └─ scripts/integrity-gate/*        → root-owned launchd daemon that posts the `integrity-review` commit status
skills/*/SKILL.md               → skills with triggering descriptions
agents/*.md                     → subagent definitions the skills spawn (deploy-safety-reviewer,
                                  design-scout, disposition-scout, docs-auditor,
                                  loop-worker, preflight-scout, proof-author,
                                  source-auditor, spec-reviewer, wiki-writer)
packages/codex/                 → independent native Codex plugin root
  ├─ .codex-plugin/plugin.json  → Codex plugin manifest
  ├─ skills/*/SKILL.md          → native Codex skills, including former commands
  ├─ hooks/hooks.json           → Codex hook registration
  ├─ hooks/scripts/*.sh         → Codex-only hook scripts using PLUGIN_ROOT
  └─ agents/*.toml              → agents installed by install.sh --provider codex
instructions/                   → the discipline rules appended to ~/.claude/CLAUDE.md
starter-memory/                 → feedback memories seeded into the user's memory dir
docs/                            → long-form reference split out of this file
examples/, launchd/             → sample configs and macOS scheduling plists
```

`${CLAUDE_PLUGIN_ROOT}` in `hooks.json` resolves to this repo's root at runtime — how hook commands locate `hooks/scripts/*.sh`.

## Two enforcement mechanisms — don't confuse them

- **Hooks = mechanical enforcement.** Run automatically on lifecycle events, can *block* (exit 2 / `permissionDecision: deny`). Use when behaviour must be enforced regardless of Claude's cooperation.
- **Slash commands = advisory.** Claude must *choose* to invoke them. Encode a workflow, don't rely on them to enforce one.

"Make X mandatory" → a `PreToolUse` hook, not a command.

**Enforcement ceiling.** A local hook checks evidence of *invocation*, not of *completion* — e.g. `enforce_pr_workflow` is satisfied by a hollow `/coderails:push` or `/pr-review-toolkit:review-pr` step that ran but did nothing. A hook runs inside the agent's own trust domain (no privilege boundary), so it's a **redirect-and-audit layer** (steers a cooperating agent, leaves a `discipline.log` trail), not a tamper-proof barrier. The real "no unreviewed change reaches `main`" guarantee is **server-side: GitHub branch protection** (required PR + reviews + no direct pushes) — no local agent can fake that; local hooks complement it, don't replace it. Same ceiling applies to Stop-hook gates: they force a declared step to *appear*, not to *be real*.

**This repo** deliberately does not enable general branch protection (2026-07-15, standing decision) — so for ordinary PRs the server-side layer is absent and the redirect-and-audit layer is the whole story, by design.

**One server-side exception: integrity-review.** A GitHub ruleset on `main` requires a PR + successful `integrity-review` status, posted only after the root-owned daemon (`scripts/integrity-gate/`) validates the head SHA's review/eval evidence and policy. Owner-provisioned; local hooks stay fail-closed but can't substitute for it.

**Sandboxed workers narrow the ceiling for worker processes only, never the orchestrator.** With `config.sandbox_workers: true` (`skills/agentic-loop/SKILL.md` Phase 3/3a), an implementation-unit worker runs as a separate OS process via `@anthropic-ai/sandbox-runtime` (srt, pinned), Seatbelt/bubblewrap-enforced — outside the agent's trust domain, the first non-hook layer. The orchestrator itself is never sandboxed.

Containment rests on the rendered settings' **allow-only write policy**, not srt's mandatory `.git/hooks`/`.git/config` denies — those are cwd-anchored (`path.resolve(cwd,...)` + relative glob) and never reach the *primary* repo's `.git` (which allowWrite must grant for commits to work). This repo's rendered settings add explicit `denyWrite` on the primary `.git/hooks` and `.git/config` to close that gap. Corollary: srt's other mandatory denies (shell rc files, `.mcp.json`, etc.) are also cwd-anchored — protected at `$HOME` only because `$HOME` sits outside allowWrite; widening a worker's allowWrite toward `$HOME` would silently re-expose them.

Named residuals:
- **Primary `.git`-write residual.** Must stay writable for worker commits, so a worker can still vandalise refs on other branches; only `hooks`/`config` under it are denied (above) — srt deliberately doesn't block `.git` wholesale. Contained by the PR gate chain + `git fsck`/reflog recoverability, not the sandbox.
- **`~/.claude`-write residual — deliberate, bounded.** Claude Code needs `~/.claude`/`~/.claude.json` writable for the worker's own process, so worker containment excludes claude-home. That grants exec surfaces that run **unsandboxed** next session: `settings.json` only *names* hook scripts, so denying it alone leaves hook **bodies** writable; plugin manifests declare their own hooks too. Demonstrated live: a sandboxed worker wrote into `~/.claude/hooks/`, including `destructive_bash_gate` (the motivating `rm -rf` incident). Now `denyWrite`-protected at the same level as `.git/hooks`: `settings.json`, `settings.local.json`, `~/.claude/hooks`, `~/.claude/plugins` — mirroring srt's own block on `.claude/commands`/`.claude/agents`. General rule: a writable directory containing exec-capable files is an escape; denying only the file that *names* an executable is worthless while the executable's body stays writable. **Irreducible: `~/.claude.json`.** Mixes required session state with a live `mcpServers` block — writable intrinsically permits MCP command injection (a worker points an MCP server at an arbitrary command, which spawns unsandboxed with full network next session). No `denyWrite` fixes this without breaking the worker; only narrowing what Claude Code needs writable would. **Real, open hole**: a sandboxed worker is contained against filesystem escape, not against an agent editing `~/.claude.json`.
- **Shared-`$TMPDIR` residual (parallel workers only).** `$TMPDIR` is granted whole; each worker's scratch is a sibling dir under it, so concurrent workers aren't isolated from each other (worker A can corrupt B's `worker.log` or overwrite B's `srt-settings.json` mid-render). Not exploited today (serial dispatch). Narrowing means granting only each worker's own scratch subdir — but node/npx/git also write to `$TMPDIR`, so that needs its own probe.

Sandboxing is write-containment, not a correctness/review substitute: a sandboxed worker's PR clears the same review/eval/hook-seam gates as any other. It contains filesystem writes only — not credential scope (the worker holds the operator's full `gh` token), not peer isolation (see `$TMPDIR` residual), not `~/.claude.json`.

### Skills↔hooks seam convention

When a skill instructs an action a hook gates — `git merge`/`gh pr create`/`gh pr merge` → `enforce_pr_workflow`; code-file/plugin-source edits on main → `no_edit_on_main`; `git commit` → `test_gate` — the skill must name the gating hook and the resolution path. Adding a hook that gates a common action → update the skills that instruct it. `enforce_pr_workflow`'s merge gate recognises PR-review evidence as the `/pr-review-toolkit:review-pr <PR#>` Skill invocation (PR number in args), NOT a manually-spawned agent fanout — the agentic loop must invoke the Skill to clear the merge gate.

`/coderails:post-review <PR#>` runs after `review-pr` (and after findings are applied + pushed) to post the SHA-bound review artifact. `/merge` (`scripts/merge.sh`) gates on a live-fetched PR comment carrying that artifact for the current head SHA — fail-closed: a `gh` fetch failure or no matching artifact both block.

Second, additive merge gate — task evals: `/coderails:task-evals` generates and freezes a graded `evals.json` (see `skills/task-evals/SKILL.md`); `/coderails:post-evals <PR#>` validates and posts it as a SHA-bound PR comment (`coderails-eval-summary`, via `scripts/lib/eval-artifact.sh`). `scripts/merge.sh` reads it right after the review-artifact gate — same fail-closed rc semantics: `gh` fetch failure or `NO-GO`/missing artifact both block. Loop scope: `loop_state_guard` also requires a loop-scope `evals.json` when `progress.json`'s `work_units` ≥3, blocking stop if none — fail-open when `work_units` is absent. A loop-scope `result` must be computed by `scripts/post_evals.sh grade-loop` (never hand-written) and carry a valid `grading` stamp, or `loop_state_guard` demotes an otherwise-valid `GO`/`VERIFICATION_LEVEL0` to `UNSTAMPED` and blocks.

Third, additive merge gate — machine attestation: when `config.integrity_review.machine_user` is set, `scripts/merge.sh` and `enforce_pr_workflow` require the newest `integrity-review` status on the exact head SHA to be successful, posted by that login, carrying `integrity=pass sha=<head>`. Wrong creator, missing status, stale SHA, non-success state, malformed description, or fetch failure — all block. Redundant defence-in-depth; the GitHub ruleset is the real boundary.

Fourth seam instance: `agentic-loop` Phase 13 teardown writes `retro.json` (`schema_version` 2) beside `progress.json` before a `complete` declaration; `loop_stall_guard` gates that declaration on it, accepting `schema_version >= 1`. Resolution: do what Phase 13 says, then re-declare `complete`. At `schema_version` 2, Phase 13 step 1 also sources `hooks/scripts/lib/loop_cost.sh`, runs `dc_mine_token_usage`, writes the result as `retro.cost` (dated, once-frozen per-model token/USD breakdown), and lifts `models_used` to top-level `retro.models_used` — fail-open (miner failure → both empty, never blocks; caller error → self-describing error object). See `skills/agentic-loop/SKILL.md` Phase 13 / `teardown.md`.

## Hook event map (`hooks/hooks.json`)

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.sh` | silent — injects `using-coderails` skill into every new session |
| `SessionStart` | `remember_inject_cap_guard.sh` | warn-only by default (writes nothing unless `REMEMBER_INJECT_CAP_AUTOWRITE=1`): reports that the memory-injection byte cap (`REMEMBER_INJECT_MAX_BYTES`, default 8000) is absent from another plugin's `session-start-hook.sh`; stamped once per plugin version in `~/.claude/coderails/remember_inject_cap_warned`. Opted in, it patches that file (whole-block literal replace from `hooks/patches/`, refuses + asks for hand re-application on shape mismatch), leaves a rolling `.coderails-bak-*` backup. Scoped to the `for MFILE...done` loop only, not the enclosing `if`. Never blocks session start |
| `UserPromptSubmit` | `inject_context.sh` | silent — prepends `[ctx]` (cwd, branch, date); first prompt of a session also appends the discipline reminder |
| `UserPromptSubmit` | `crack_on_gate.sh` | silent — "crack on" (case-insensitive, word-boundary) in the raw prompt stamps a session-only `crack_on_active` flag (`<base>/<session_id>/crack_on_active`, base = `$CLAUDE_AGENTIC_LOOP_DIR` or `~/.coderails/agentic-loop`), not the progress.json resolver path (existence-probe drift would fail unsafe here). Never reads transcript/injected context (the phrase is in skill text + memory almost every session; a transcript scan would false-positive and permanently suppress human interaction) |
| `Stop` + `SubagentStop` | `check_confidence_labels.sh` | block outside an active loop when a ≥200-char response has no `(verified)`/`(inferred)`/`(guess)` label; inside an active, incomplete loop, `Stop` violations demote to an `additionalContext` warn — `SubagentStop` still blocks (reads `last_assistant_message` directly, avoiding the parent-transcript flush race). `Stop` only: exempt (exit 0) when `CODERAILS_HEADLESS_RUN=1` |
| `Stop` + `SubagentStop` | `check_verify_loop.sh` | block outside an active loop on any untagged `## Did Not Verify` bullet (only `(unverifiable: <reason>)` passes), or a missing section after a 3+-file turn; inside an active, incomplete loop, `Stop` violations demote to a warn — `SubagentStop` still blocks. `loop_state_guard`/`loop_stall_guard` stay Stop-only. `Stop` only: exempt when `CODERAILS_HEADLESS_RUN=1` |
| `Stop` | `voice_announce.sh` | observe-only, always exits 0 — speaks a loop lifecycle event (complete/waiting-on-human/stopped/stall) via macOS `say`. Silent outside a loop or on empty text extraction. Debounced per kind. Runs first in the Stop array |
| `Stop` | `loop_state_guard.sh` | block when a loop is active but no session-owned `progress.json` exists (nag-once grace: stands down after one absent-block per session+invocation count; session-mismatch/stale-complete carry no grace). Also gates loop-scope evals when `work_units` ≥3: blocks unless a sibling `evals.json` grades `GO`/`VERIFICATION_LEVEL0` with a non-blank `verification_justification` and a valid stamp — `ABSENT`, `NO-GO`, `UNJUSTIFIED`, `UNSTAMPED` each block; fails open when `work_units` is absent |
| `Stop` | `loop_stall_guard.sh` | block when a loop is active and incomplete with no valid `LOOP-STOP` declaration; shares `loop_state_guard`'s absent-`progress.json` grace (keyed off its log line). On `complete`, also blocks if `retro.json` is absent/malformed/below `schema_version` 1, and if a sibling `proof.json` exists but any frozen proof is unexecuted-in-transcript or last-failed (mined from this session's own Bash tool_use/result pairs). Absent `proof.json` fails open only for `schema_version < 2`; at ≥2 it blocks unless `progress.json.proof_disposition` is `"none"`/`"none: <reason>"`. A sibling `withdrawn_proofs` array is mined the same pass, stricter — blocks unless the proof ran, last failed, carries `withdrawn_reason`, and its `id` isn't also in `.proofs`; combined 100-entry cap |
| `Stop` | `unregistered_loop_guard.sh` | nudge, never blocks — flags a dispatch-heavy session (≥3 Agent-dispatch turns) with no `progress.json` and no `agentic-loop` invocation |
| `Stop` | `crack_on_prose_gate.sh` | block — while `crack_on_active` is stamped, blocks a final message that hands a question back in prose (closing the evasion of asking outside the denied `AskUserQuestion` tool). Heuristic: terminal `?` on the last body line, first-person-modal question in the last 3 lines, or ~15 high-precision phrases. Fail-closed on discipline, fail-open on infra failure. Per-turn block cap 3 (`CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS`). `Stop`-only |
| `Stop` + `SubagentStop` | `offload_push_guard.sh` | nudge, never blocks — final text names a `git push` to `main`/`master` AND an offload-to-user cue (`! ` prefix, "your own shell", "run this yourself"). At most once per session. Runs last in both arrays |
| `PreToolUse` (Bash) | `destructive_bash_gate.sh` | block — permanent blocklist: `rm -rf`, naked `git push --force`/`-f`, `git reset --hard`, SQL `DROP TABLE/DATABASE/SCHEMA` and `TRUNCATE TABLE`, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete/--delete`, `truncate -s/--size`, `shred`, a `.env` literal path token read or write (`.envrc`/`.env.example`/`.sample`/`.template`/`.dist` allowed). Also blocks in-Bash source edits (`sed -i`, `perl -i`, redirects, `tee`, `cp`/`mv`/`dd of=` onto source/plugin-markdown) on main/master. Denies backtick/`$(...)`/process-substitution inside `push.sh`/`merge.sh`/`post_review.sh`/`post_evals.sh` args. `--force-with-lease` conditionally allowed |
| `PreToolUse` (Bash) | `enforce_pr_workflow.sh` | block — `gh pr create` without `/coderails:push`; `gh pr merge <N>` without `review-pr <N>` (per-PR, not consumed — one review satisfies later merges); `git merge` on main/master without review-pr since the last merge (consume-on-use); `git push` to main/master without review-pr. `scripts/merge.sh <N>` gated identically. Scans subagent transcripts. `merge-base/-file/-tree`, `--abort/--continue/--quit/--skip` excluded. No-op without `workflow.config.yaml`. Post review-pr check, also blocked without a SHA-bound `GO` eval artifact for the head; `gate_smoke_verify` then re-executes every verification_level≥1 eval's `cmd`/`negative_control` in a detached worktree at the trusted SHA and denies independently on failure |
| `PreToolUse` (Bash) | `test_gate.sh` | block on `git commit` if tests fail — opt-in only |
| `PreToolUse` (Bash) | `verification_volume_ceiling.sh` | block — hard-blocks the 3rd+ invocation per work-unit (branch) of `hooks/scripts/tests/run_all.sh` or a `post_evals.sh validate-structure` ceremony; no override |
| `PreToolUse` (AskUserQuestion) | `crack_on_gate.sh` | block — denies `AskUserQuestion` while `crack_on_active` is stamped. Scoped to that tool only — the loop hard-stops are `LOOP-STOP` declarations, not `AskUserQuestion` calls |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.sh` | block — on main/master, blocks edits to any file except `.md`/`.txt`/`.rst`, `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg`, `.gitignore`, `LICENSE`. Plugin source markdown (`skills/*/SKILL.md`, `commands/*.md`) also blocked when that repo carries `.claude-plugin/plugin.json` (keyed off the file's own repo). Separately blocks `.claude/settings.json`/`.claude/settings.local.json` edits on any branch, any repo |
| `PreToolUse` (Write/Edit/MultiEdit) | `comment_citation_gate.sh` | block — denies new/changed comments citing a session-artifact label (`E#:`, `F# fix/design`, `CHANGE B#/C#`, `Task A#`, `TA-I#`, "reviewer finding", `eval E#`, `WU#:`, `C2`, "per the plan/design/session", "per F#"). Scoped to comment-bearing fields; `.md` out of scope. `PR #NN` survives (durable checkable artifact) |
| `PreToolUse` (Write/Edit/MultiEdit) | `wiki_taxonomy_gate.sh` | block — writes into an unsanctioned top-level directory of an LLM wiki vault. Inert until `.coderails/workflow.config.yaml` exists. Sanctioned dirs parsed live from this file's own `## Page types` section, never hardcoded. Vault identified positively: `wiki_path` from `.coderails/workflow.config.yaml` (relative to `CLAUDE_PLUGIN_ROOT` unless absolute) must equal the write's repo root exactly; ≥2 parsed dirs existing on disk is a secondary sanity check only. Fails open on any ambiguity (schema/config absent, not a git repo, `wiki_path` null/unresolvable, no section, zero parsed dirs, write outside vault, <2 dirs present). `raw/`, vault-root files (no directory component), and dotfile dirs (`.git/`, `.obsidian/`, `.claude/`) always allowed |
| `PreToolUse` (`Bash\|Edit\|Write\|MultiEdit\|Read\|Grep\|Glob\|WebFetch\|NotebookEdit`) | `agent_only_gate.sh` | nudge by default, block opt-in (`AGENT_ONLY_GATE_ENFORCE=1`) — steers the orchestrator from inline do-work calls toward `Agent`. `agent_id` present in the payload iff the call originates inside a dispatched subagent (empirically confirmed) → always allow. `agent_id` absent + the Bash command is entirely one whole-command carve-out (`gh`, `git`, `scripts/push\|merge\|post_review\|post_evals.sh`, optional interpreter prefix, no chaining/substitution) → always allow. Otherwise: `additionalContext` nudge by default, hard `deny` under the env flag. `Agent`/`TodoWrite`/`TaskCreate`/`AskUserQuestion`/`ExitPlanMode` are never gated |
| `PreToolUse` (`Agent`) | `agent_model_routing_nudge.sh` | advisory nudge only, never denies — when `tool_input.model` is absent and the description/prompt carries a mechanical word (rename/format/boilerplate/scaffold/reformat/relabel/find-replace) or a complex one (design/architecture/redesign/re-architect), nudges `haiku`/`opus` respectively. Silent if `model` set, neither/both match |
| `PreToolUse` (`Agent`) | `loop_dispatch_guard.sh` | block — gates every `Agent` dispatch with `subagent_type: coderails:loop-worker` in a loop whose `progress.json.work_units` roster has ≥3 entries (including the first dispatch), denying unless a sibling `evals.json` reads `GO`/`VERIFICATION_LEVEL0`/`FROZEN`. `FROZEN` accepted HERE ONLY (freeze-time-satisfiable subset: non-blank `frozen_sha`, ungraded, ≥1 P0, valid `id`/`mode`) — completion-time callers still require `GO`/`VERIFICATION_LEVEL0`. Scoped to `coderails:loop-worker` only. Requires `progress.json.session_id` to match this session. Never fires for `config.sandbox_workers: true` (separate OS process, not an `Agent` tool_use). A stale `evals.json` from a prior loop is demoted to `STALE` when its `session_id`/`loop_id` differs; a legacy loop with no `loop_id`, or a suite with no `session_id`, can't be fully disambiguated and is accepted. Binding is `session_id`+`loop_id` only, never `revision` (a revision check would invalidate a frozen suite on the first wave) |

### Enforcement ceilings — deliberate, not bugs

- **Bash blocklists are enumerated families, not exhaustive.** Obfuscated forms, variable filenames, quoted paths with spaces, here-docs, process substitution, `python -c open(...)` writes remain uncaught.
- **Eval-gate coverage boundary.** Enforced only at `/coderails:merge` (config-independent) and `gh pr merge <N>` via `enforce_pr_workflow` (config-dependent, inactive under `NO_CONFIG`). NOT enforced on raw `git merge`/`git push` to main/master (no PR number to resolve an artifact against) or in any `NO_CONFIG` repo. Both enforced points then run `gate_smoke_verify`/`post_evals::smoke_verify` — three failure modes: `gh` fetch failure, `NO-GO`/missing artifact, failed re-execution.
- **`no_edit_on_main` allowlist breadth is intentional (fail-safe).** `.sh` blocked on main, `.json`/`.yaml` config stays editable. Settings.json `Write`/`Edit` permission covers any legitimate override.
- **Wiki/workflow sequence past merge is advisory.** `/wiki-ingest` + `/wiki-lint` after merge are slash commands; nothing enforces them.
- **`check_verify_loop`, `check_confidence_labels`, both loop guards** all short-circuit on `stop_hook_active=true` (block at most once per turn) — intentional infinite-loop safety valve. `voice_announce` reads it too (via `als_gate_stop_loop`), no observable effect (always exits 0). `crack_on_prose_gate` reads it only to reset a per-turn counter, not to short-circuit.
- **TDD is not enforced test-first.** `test_gate` only checks tests pass at commit time.
- **Skill invocation, ask-on-ambiguity, verify-memory are structurally unenforceable by hooks** — they depend on Claude's internal reasoning, which a hook can't observe.
- **No `SubagentStart` event exists.** `inject_bootstrap.sh` can't inject `using-coderails` into subagents; they get it only via the orchestrator's system prompt.
- **`/coderails:post-review` validates summary structure, not provenance.** Proves an auditable SHA-bound artifact exists, not that the review was substantive. The `review-pr` arm of `enforce_pr_workflow` is expected to demote block→nudge once the artifact gate is verified live — never before, or a window opens with neither gate active.
- **Model-role routing is advisory, hook-enforced only as a nudge.** `agentic-loop` Phase 2.8 assigns a role (`fast-mechanical`/`default`/`frontier`) + effort per task (table in Phase 2.8, defaults + fable-escalation in `model-routing.md`), asserted at spawn sites (Phases 2, 2.5, 3, 3a, 9, 10). `agent_model_routing_nudge.sh` is the only hook touching this — advisory only. No hook enforces *correct* role selection; a `frontier`-role worker still produces a fully-gated PR. Phase 2.8 also sanctions a legitimate `default`-vs-`frontier` judgement call a blunt gate can't distinguish from a disallowed spawn without a self-reported carve-out (reintroducing the same trust problem).
- **`agent_only_gate`'s detection is real but narrow.** `agent_id` presence/absence was confirmed empirically on Claude Code 2.1.220 via a live probe (top-level Bash/Agent calls carried no `agent_id`; a subagent's Bash call carried both `agent_id`/`agent_type`; `session_id` was identical across all three, so it alone can't distinguish them). This answers "did this call originate at top level," not "is the orchestrator cooperating" — a top-level session doing real work in-context and never calling `Agent` is invisible until it attempts a do-work call. Hard top-level block isn't default because it would deadlock this repo's own shipping path (`enforce_pr_workflow`, `merge.sh`, every workflow command assume the orchestrator runs `gh`/`git`/`scripts/*.sh` inline). `AGENT_ONLY_GATE_ENFORCE=1` opts into hard-blocking with the same workflow-chain carve-out. Unverified: behaviour under `claude --agent <name>` mode (reportedly sets `agent_type` even on top-level calls, per docs) — the live probe used a plain headless session, not `--agent` mode.
- **Headless-run exemption is env-triggered, `Stop`-only, inside the agent trust domain.** `check_confidence_labels.sh`, `check_verify_loop.sh`, `crack_on_prose_gate.sh` skip enforcement when `CODERAILS_HEADLESS_RUN=1` is in their process env — a headless `claude -p` run has no interactive turn left to satisfy a repair-turn block. Does NOT extend to `SubagentStop`: worker output always blocks regardless of the flag. Set in exactly one place: `skills/dashboard/app/src/app/api/run/route.ts`'s `spawn(...)` call — a second set-site (including a session setting it on itself) is a security finding. `scripts/sandbox/spawn-sandboxed-worker.sh` force-unsets it before launching a sandboxed worker so no inherited value leaks the exemption in; keep the two in lockstep.

**Hook script conventions** (follow when editing/adding a script):
- Read stdin via `IFS= read -r -d '' -t 5 input || true`, parse with `jq`. The 5s timeout backstops a hook orphaned past its parent's death (can no longer be killed by hooks.json's own timeout); it's deliberately ≤ the smallest hooks.json timeout — don't reconcile by raising that instead. On timeout, empty input → jq empty → the gate stands aside (exit 0); deliberate fail-open, don't add `set -e` or flip it to deny.
- **Exit early and often.** `enforce_pr_workflow.sh`, `loop_state_guard.sh`/`loop_stall_guard.sh` (shared `als_gate_*` from `lib/loop_state_common.sh`), and `voice_announce.sh` use named gate functions; every other gate script uses inline `if`-blocks (both fine). Cheap skip-gates first, expensive transcript-parsing last. No `set -euo pipefail` in guard scripts; gate functions `exit` directly.
- Block via `exit 2` + stderr message for Stop hooks; `hookSpecificOutput.permissionDecision: "deny"` JSON to stdout then `exit 0` for PreToolUse — never `exit 2` in PreToolUse.
- Append a structured `key=value` line to `$CLAUDE_DISCIPLINE_LOG` (default `~/.claude/discipline.log`).
- Guard the transcript-flush race: `loop_stall_guard.sh` retries `extract_last_text` with backoff until length stabilises.

## Workflow command architecture

`/coderails:workflow` is the umbrella orchestrator; every phase delegates to a standalone sub-command that also works alone:

```
/workflow  →  /prep → (code) → /push → /pr-review-toolkit:review-pr → /coderails:post-review → (ship-it) → /merge → /wiki-ingest + /wiki-lint
```

Two interactive pauses: the code/iterate loop, and final ship-it authorization. Everything else auto-chains. `/coderails:post-review <PR#>` sits between `review-pr` and ship-it, converting ephemeral review output into the durable SHA-bound review artifact; `/merge` fetches live PR comments and requires a matching artifact for the current head SHA — fail-closed. Both the agentic loop (Phase 4b) and non-loop `/workflow` (Phase 3) post the same artifact; `/merge` checks both the same way. `scripts/merge.sh` holds the gate in its `OPEN` branch before `gh pr merge`.

**Config resolution** — every workflow command reads `workflow.config.yaml` via a `!` bash substitution in its frontmatter: `source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.sh" && coderails::resolve_config`. `scripts/lib/config.sh` is the single source of truth for locating it. `coderails::config_path [dir]` walks up from `dir` (default `$PWD`) to the git root, echoing the first `.coderails/workflow.config.yaml` found (empty if none); `coderails::resolve_config [dir]` echoes its contents or `NO_CONFIG`. Layout-agnostic (standalone repos, `projects/<name>/` monorepos, `apps/web`-style layouts) — nearest wins, replacement not merge. `${CLAUDE_PLUGIN_ROOT}` is string-substituted in frontmatter (fixed bug: previously wasn't for `allowed-tools`) — always the real plugin dir. Same resolver sourced by `scripts/merge.sh` and `hooks/scripts/enforce_pr_workflow.sh` (must match, or the merge gate would silently go inactive in a non-`projects/` layout). Adding a config field → update `workflow.md`, `prep.md`, `push.md`, `init.md`. `workflow.md`/`prep.md`/`push.md` each read the file independently via the shared resolver. `init.md` writes `$(pwd)/.coderails/workflow.config.yaml`: scaffolds fresh, or preserves legacy contents/schema/values when migrating, validating before moving legacy files to the macOS Trash. No runtime fallback to legacy paths. `NO_CONFIG` = "not initialised."

**`scripts/` vs `commands/`** — `push.sh`/`merge.sh` hold deterministic git plumbing (commit, push, `gh pr create`, merge); `.md` commands hold prose/decision logic and shell out to those scripts. Shared git/gh helpers live in `scripts/lib/git-common.sh` — add reusable primitives there, not inline.

## Project-specific assumptions (change when generalising)

- **Auth host**: `push.sh` requires a `github.com` remote (`require::repo`).
- **Jira fields**: `prep.md` reads `config.jira.epic_field`/`points_field`; transition names are project-specific (see INSTALLATION.md "Notes").
- **Jira route**: commands build Jira MCP tool names from `config.jira.mcp_namespace` (default `jira` → `mcp__jira__*`). Add `"mcp__<namespace>__*"` to `.claude/settings.json` for non-default namespaces; without a Jira MCP, Jira steps no-op.

## Working in this repo

- Editing a command/skill: effective after `/reload-plugins` — nothing to compile.
- Editing a hook: same; test by triggering the event, checking `~/.claude/discipline.log`. `bash install.sh --dry-run` previews changes.
- `install.sh` is idempotent — re-running won't duplicate CLAUDE.md edits or overwrite seeded memories. Preserve that.
- `uninstall.sh` must reverse exactly what `install.sh` adds (CLAUDE.md block, settings keys) while preserving user data (`discipline.log`, memories). Keep the two in lockstep.
- `instructions/self-checking-discipline.md` is the authoritative copy `install.sh` appends to `~/.claude/CLAUDE.md` — edit there, not the installed copy.

## Requirements

Claude Code 2.1.x · `gh`, `jq`, `git` on PATH · authenticated git host for `/push`/`/merge` · `pr-review-toolkit@claude-plugins-official` for `/workflow`'s review stage.

---

# Wiki schema

Based on the LLM Wiki pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

Single source of truth for coderails wiki conventions. Do NOT create a separate `schema.md` inside the vault.

**Location**: `../coderails-wiki` (set during `/wiki-init`). Vault path/git flow (`wiki_path`, `wiki_git_worktree`, `wiki_git_bypass_flag`, `wiki_git_pull_path`) and supervision mode (`wiki_supervision`) are flat keys in `.coderails/workflow.config.yaml` — see the `wiki-ingest`, `wiki-lint`, `wiki-query` skills' Step 0.

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

**Three layers**: (1) raw sources (immutable) — the plugin repo (commands, hooks, scripts, skills, install.sh, CLAUDE.md); read from, never modify. (2) The wiki — LLM-generated markdown in the vault; Claude owns this layer entirely. (3) This file — tells Claude how the wiki is structured; the maintainer edits it, Claude reads it.

## Page types

> **This section is live enforcement config, not just documentation.** At
> runtime, `hooks/scripts/wiki_taxonomy_gate.sh` parses everything from this
> heading up to the next `## ` heading as its write allow-list: any
> backticked directory-slash token found anywhere in that span sanctions
> that directory for writes. Adding, removing, or reformatting such a token
> — in a table cell or in surrounding prose — changes what the gate
> permits, not just what this doc says.

| Type | Directory | Naming | Purpose |
|---|---|---|---|
| command | `commands/` | `<command-name>.md` | Documents one slash command: what it does, config fields, scripts invoked |
| hook | `hooks/` | `<script-name>.md` | Documents one hook script: event, mode, logic, block condition |
| skill | `skills/` | `<skill-name>.md` | Documents one skill: purpose, trigger phrases, phases, failure modes encoded |
| design | `design/` | `<topic>.md` | Architectural decisions and invariants; evergreen |
| investigation | `investigations/` | `<topic>_<YYYY-MM-DD>.md` | Point-in-time analysis filed during a workflow session; may be superseded |
| source | `sources/` | `pr_<N>_<slug>.md` | Immutable record of a merged PR, created by `/wiki-ingest` |

**Not page types — structural directories.** Skeletons/charts, no frontmatter, never `[[wiki-link]]`ed:

| Directory | Naming | Purpose |
|---|---|---|
| `templates/` | `<page-type>.md` | Page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md) with the YAML frontmatter shape |
| `assets/` | freeform | Charts and images generated for wiki pages (e.g. matplotlib output) |
| `dashboard-runs/` | `<routine>.md` | Scheduled-routine run notes, `type: routine-run`, written by `skills/dashboard/runner` |

`dashboard-runs/` is operational output, not wiki content — follows none of the page-format rules, never linked, not touched by `/wiki-ingest`/`/wiki-lint`. The Obsidian plugin's direct-exec path writes separate per-run notes into the same folder with `status: running|done|failed` and no `type` field; treat both as non-wiki regardless of frontmatter shape. See `docs/routines.md`.

## Page format

Every page needs:

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

Body rules: `[[wiki-links]]` for cross-references (`[[page_name]]`, no directory prefix). Keep pages under 2 minutes to read. Focus on knowledge that compounds (relationships, decisions, patterns), not facts derivable from reading source. Confidence-label non-trivial assertions: `(verified)`/`(inferred)`/`(guess)`. Flag contradictions inline as `> ⚠️ CONTRADICTION: <description>` — `/wiki-lint` scans for this marker.

**Enforcement model (wiki lens)**: the full hooks-vs-commands treatment lives in `## Two enforcement mechanisms` above. For wiki purposes: when documenting a hook page vs a command page, record which mechanism it is and what it can/can't guarantee; link to `[[enforcement-model]]` and cite the ceiling caveats verbatim.

## Workflows

**Ingest** (after every PR merge) — `/wiki-ingest`, never write pages directly for PR content: (1) create `sources/pr_<N>_<slug>.md` from `templates/source.md`; (2) update affected pages with new knowledge; (3) append to `log.md`: `## [YYYY-MM-DD] ingest | PR #N merged: <description>`; (4) update `index.md` if new pages were created; (5) run `/wiki-lint`.

**Query** — `/wiki-query` reads `index.md` first, fetches relevant pages, answers with citations. If a query reveals something non-obvious, file it back as an `investigations/` page — that is the birth condition for one.

**Lint** — `/wiki-lint`, always after ingest. Checks orphaned pages, stale `last_updated`, missing cross-references, contradictions. Fix anything related to the current PR; defer unrelated findings.

## Search

`qmd` is an optional accelerator — absent, search falls back to reading `index.md` directly.

- `qmd query "<question>"` — hybrid BM25 + vector search with reranking (inferred). Best for open-ended questions.
- `qmd search "<keywords>"` — BM25 only, fast (verified: `qmd --help` states "Full-text BM25 keywords (no LLM)"). Best for known-term lookups.
- `qmd get <file>` — fetch a specific page by path.

**Reindex**: after wiki changes, run `qmd update && qmd embed` — `embed` alone only refreshes already-known content hashes (inferred); `update` scans for new/changed files and must run first. `qmd collection add` is first-time setup only (errors "Collection already exists" on reruns, verified) — don't run it as routine maintenance.

## Conventions

- Frontmatter tags: lowercase, hyphenated.
- One concept per page — split a page that covers too much.
- Source pages reference the PR number and key files changed.

**Exploration boundary**: subagent/code exploration explores code; the wiki captures understanding. Use it when a wiki operation hits a specific gap (a query found no page, an ingest touches unfamiliar code, a lint finds a page you have specific reason to doubt) — not to routinely validate wiki content. The wiki is trusted by default, corrected by evidence.

**Evolution note**: this file is co-evolved. Convention changes (new page types, frontmatter fields, naming rules) — update this file first, then affected vault pages. The maintainer edits; Claude reads. Living system, not a snapshot.
