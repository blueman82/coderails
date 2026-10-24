# AGENTS.md — Coderails

Single source read at conversation start. Covers the repo working guide (below) and the coderails wiki schema (`## Wiki schema` near the end). `CLAUDE.md` is a thin pointer here — edit here, not there.

Wiki vault: `../coderails-wiki` relative to the plugin, or wherever `/wiki-init` placed it.

Use the `wiki-query` skill for Coderails questions and context. Use `wiki-lint` to check wiki health or stale pages. The wiki combines earlier findings with source facts. Check it before you search the source or vault directly.

## Writing rule

Use controlled English for new and revised Coderails Markdown and pull-request
text. Follow the `explainer-artifacts` writing guide. Write short sentences in
active voice. Use familiar words. Give each sentence one main idea. Define
technical terms when readers need them. Keep commands, identifiers, evidence,
and historical quotations exact. Apply this rule to roadmap work and later
work. A separate check is necessary before you claim strict ASD-STE100
compliance.

## Current integrity-gate replacement

The semantic judge is replaced by a mechanical `integrity-review` attestor in a trusted GitHub Actions workflow. It checks SHA-bound review/eval evidence, command/eval structure, policy paths, provenance fields, and bounded diff input. It never runs PR code or comment commands and never asks an LLM for a verdict. Authoritative: `docs/INTEGRITY-GATE.md`, `.github/workflows/integrity-review.yml`, `scripts/integrity-gate/integrity_actions.py`, and `integrity_review.enabled` config. GitHub ruleset `25788196` is active on `main` and requires the GitHub Actions app status. Source code alone does not activate the rule.

## What this repo is

Two independent plugins, not an application:
- Working Claude Code plugin at repo root.
- Native Codex plugin at `packages/codex/`.

`install.py` defaults to Claude; `--provider codex` for Codex. Claude plugin bundles:
1. Workflow commands — `prep → push → merge → wiki` chain (`commands/*.md`)
2. Skills — agentic-loop, planning-sequence, premortem, handoff (`skills/*/SKILL.md`)
3. Discipline loop — advisory lints on confidence labels and unverified claims; blocking hooks on destructive bash, failing tests (`hooks/`)

The plugin instructions and Python runtime need no compilation. The dashboard TypeScript packages have their own build and test commands. Source = Markdown instructions, maintained Python hooks/workflow scripts, and dashboard TypeScript. Version-controlled in your own fork/repo. Former shell runtime and test entrypoints are maintained Python; generic shell-policy examples and external tools remain supported.

**Agentic-loop graph runtime**: the `agentic-loop` skill creates durable graph state in `progress.json` (nodes, edges, joins, status, outcomes, retries) with readiness checks and plan/record helpers for dispatching and recording waves. Manually operated — the model reads the graph, dispatches ready work, records results; not an automatic scheduler. Each provider has its own graph adapter, locks and native evidence reader. The sole maintained pure semantics live in `packages/graph-semantics/graph_semantics.py`, materialized byte-for-byte into both independent installs. Current graph schema is 3 only; no legacy reader or alternate writer.

## How the pieces wire together

```
.claude-plugin/plugin.json      → plugin manifest (name, version, metadata)
.claude-plugin/marketplace.json → local-directory marketplace entry (source: ./)
hooks/hooks.json                → maps lifecycle events → hook scripts
  └─ hooks/scripts/*.py         → the actual gate/nudge logic
commands/*.md                   → slash commands (frontmatter + prose instructions)
  └─ scripts/*.py               → Python commands (push.py, merge.py)
       └─ scripts/lib/git_common.py → shared git/gh/PR helpers, imported by both
       └─ scripts/lib/config.py     → workflow.config.yaml resolver (single source of truth; see "Config resolution")
  └─ scripts/sandbox/*.py       → srt sandbox wrapper for spawned workers (see "Sandboxed workers")
  └─ scripts/integrity-gate/*        → trusted GitHub Actions evidence check and `integrity-review` status
skills/*/SKILL.md               → skills with triggering descriptions
agents/*.md                     → subagent definitions the skills spawn (deploy-safety-reviewer,
                                  design-scout, disposition-scout, docs-auditor,
                                  loop-worker, preflight-scout, proof-author,
                                  source-auditor, spec-reviewer, wiki-writer)
packages/codex/                 → independent native Codex plugin root
  ├─ .codex-plugin/plugin.json  → Codex plugin manifest
  ├─ skills/*/SKILL.md          → native Codex skills, including former commands
  ├─ hooks/hooks.json           → Codex hook registration
  ├─ hooks/scripts/*.py         → Codex-only hook scripts using PLUGIN_ROOT
  └─ agents/*.toml              → agents installed by install.py --provider codex
instructions/                   → the discipline rules appended to ~/.claude/CLAUDE.md
starter-memory/                 → feedback memories seeded into the user's memory dir
docs/                            → long-form reference split out of this file
examples/, launchd/             → sample configs and macOS scheduling plists
```

`${CLAUDE_PLUGIN_ROOT}` in `hooks.json` resolves to this repo's root at runtime — how hook commands locate `hooks/scripts/*.py`.

## Two enforcement mechanisms — don't confuse them

- **Hooks = mechanical enforcement.** Run automatically on lifecycle events, can *block* (exit 2 / `permissionDecision: deny`). Use when behaviour must be enforced regardless of Claude's cooperation.
- **Slash commands = advisory.** Claude must *choose* to invoke them. Encode a workflow, don't rely on them to enforce one.

"Make X mandatory" → a `PreToolUse` hook, not a command.

**Enforcement ceiling.** A local hook checks evidence of *invocation*, not of *completion* — e.g. `enforce_pr_workflow` is satisfied by a hollow `/coderails:push` or `/pr-review-toolkit:review-pr` step that ran but did nothing. A hook runs inside the agent's own trust domain (no privilege boundary), so it's a **redirect-and-audit layer** (steers a cooperating agent, leaves a `discipline.log` trail), not a tamper-proof barrier. The real "no unreviewed change reaches `main`" guarantee is **server-side: GitHub branch protection** (required PR + reviews + no direct pushes) — no local agent can fake that; local hooks complement it, don't replace it. Same ceiling applies to Stop-hook gates: they force a declared step to *appear*, not to *be real*.

**This repo** does not enable general review-approval branch protection (2026-07-15, standing decision). The active integrity rule below is the server-side PR and status gate. It checks evidence structure, not whether an independent reviewer actually ran.

**One server-side exception: integrity-review.** The active GitHub ruleset on `main` requires a PR and a successful `integrity-review` status from the GitHub Actions app. The workflow validates the head SHA's review/eval evidence and policy as data. Local hooks cannot substitute for the rule.

**Sandboxed workers narrow the ceiling for worker processes only, never the orchestrator.** With `config.sandbox_workers: true` (`skills/agentic-loop/SKILL.md` Phase 3/3a; status `read_by_prose_only`: the orchestrator reads it from the resolve-config text and no script does), an implementation-unit worker runs as a separate OS process via `@anthropic-ai/sandbox-runtime` (srt, pinned), Seatbelt/bubblewrap-enforced — outside the agent's trust domain, the first non-hook layer. The orchestrator itself is never sandboxed.

Containment rests on the rendered settings' **allow-only write policy**, not srt's mandatory `.git/hooks`/`.git/config` denies — those are cwd-anchored (`path.resolve(cwd,...)` + relative glob) and never reach the *primary* repo's `.git` (which allowWrite must grant for commits to work). This repo's rendered settings add explicit `denyWrite` on the primary `.git/hooks` and `.git/config` to close that gap. Corollary: srt's other mandatory denies (shell rc files, `.mcp.json`, etc.) are also cwd-anchored — protected at `$HOME` only because `$HOME` sits outside allowWrite; widening a worker's allowWrite toward `$HOME` would silently re-expose them.

Named residuals:
- **Primary `.git`-write residual.** Must stay writable for worker commits, so a worker can still vandalise refs on other branches; only `hooks`/`config` under it are denied (above) — srt deliberately doesn't block `.git` wholesale. Contained by the PR gate chain + `git fsck`/reflog recoverability, not the sandbox.
- **`~/.claude`-write residual — deliberate, bounded.** Claude Code needs
  `~/.claude` and `~/.claude.json` writable for its worker process. Worker
  containment therefore excludes Claude home. Executable files there can run
  **unsandboxed** in a later session. `settings.json` names hook scripts, but
  the script bodies can also be writable. Plugin manifests can declare hooks.
  Denying only the file that names an executable leaves its body exposed.

  A sandboxed worker demonstrated this by writing to `~/.claude/hooks/`,
  including `destructive_bash_gate` (the motivating `rm -rf` incident).
  `denyWrite` now protects `settings.json`, `settings.local.json`,
  `~/.claude/hooks`, and `~/.claude/plugins`, at the same level as
  `.git/hooks`. This mirrors srt's block on `.claude/commands` and
  `.claude/agents`. A writable directory with executable files remains an
  escape even if the file that names them is denied.

  **Irreducible: `~/.claude.json`.** It mixes required session state with a
  live `mcpServers` block. A worker that can edit it can point an MCP server at
  an arbitrary command, which can start unsandboxed with full network access
  in the next session. Denying writes to this file breaks the worker. Only a
  change to what Claude Code needs writable can close this gap. **Real, open
  hole:** the sandbox contains worker filesystem writes, but it does not
  prevent a worker from editing `~/.claude.json`.
- **Shared-`$TMPDIR` residual (parallel workers only).** `$TMPDIR` is granted whole; each worker's scratch is a sibling dir under it, so concurrent workers aren't isolated from each other (worker A can corrupt B's `worker.log` or overwrite B's `srt-settings.json` mid-render). Not exploited today (serial dispatch). Narrowing means granting only each worker's own scratch subdir — but node/npx/git also write to `$TMPDIR`, so that needs its own probe.

Sandboxing is write-containment, not a correctness/review substitute: a sandboxed worker's PR clears the same review/eval/hook-seam gates as any other. It contains filesystem writes only — not credential scope (the worker holds the operator's full `gh` token), not peer isolation (see `$TMPDIR` residual), not `~/.claude.json`.

### Skills↔hooks seam convention

When a skill instructs an action a hook gates — `git merge`/`gh pr create`/`gh pr merge` → `enforce_pr_workflow`; code-file/plugin-source edits on main → `no_edit_on_main`; `git commit` → `test_gate` — the skill must name the gating hook and the resolution path. Adding a hook that gates a common action → update the skills that instruct it. `enforce_pr_workflow`'s merge gate recognises PR-review evidence as the `/pr-review-toolkit:review-pr <PR#>` Skill invocation (PR number in args), NOT a manually-spawned agent fanout — the agentic loop must invoke the Skill to clear the merge gate.

`/coderails:post-review <PR#>` runs after `review-pr` (and after findings are applied + pushed) to post the SHA-bound review artifact. `/merge` (`scripts/merge.py`) gates on a live-fetched PR comment carrying that artifact for the current head SHA — fail-closed: a `gh` fetch failure or no matching artifact both block.

Second, additive merge gate — task evals: `/coderails:task-evals` freezes an ungraded `evals.json` before implementation and grades actual results afterward (see `skills/task-evals/SKILL.md`); `/coderails:post-evals <PR#>` validates and posts it as a SHA-bound PR comment (`coderails-eval-summary`, via `scripts/lib/eval_artifact.py`). `scripts/merge.py` reads it right after the review-artifact gate — same fail-closed rc semantics: `gh` fetch failure or `NO-GO`/missing artifact both block. Loop scope: `loop_state_guard` also requires a loop-scope `evals.json` when `progress.json`'s `work_units` ≥1, blocking stop if none — fail-open when `work_units` is absent. A loop-scope `result` must be computed by `scripts/post_evals.py grade-loop` (never hand-written) and carry a valid `grading` stamp, or `loop_state_guard` demotes an otherwise-valid `GO`/`VERIFICATION_LEVEL0` to `UNSTAMPED` and blocks.

Third, additive merge gate — GitHub Actions attestation: when `config.integrity_review.enabled` is true, `scripts/merge.py` and `enforce_pr_workflow` require the newest `integrity-review` status on the exact head SHA to be successful, posted by `github-actions[bot]`, carrying `integrity=pass sha=<head>`. Wrong creator, missing status, stale SHA, non-success state, malformed description, or fetch failure all block. The GitHub ruleset is the server boundary.

Fourth seam instance: `agentic-loop` Phase 13 teardown writes `retro.json` (`schema_version` 2) beside `progress.json` before a `complete` declaration; `loop_stall_guard` gates that declaration on it, accepting `schema_version >= 1`. Resolution: do what Phase 13 says, then re-declare `complete`. At `schema_version` 2, Phase 13 step 1 also runs `python3 hooks/scripts/lib/loop_cost.py <session_id>`, writes the result as `retro.cost` (dated, once-frozen per-model token/USD breakdown), and lifts `models_used` to top-level `retro.models_used` — fail-open (miner failure → both empty, never blocks; caller error → self-describing error object). See `skills/agentic-loop/SKILL.md` Phase 13 / `teardown.md`.

## Hook event map (`hooks/hooks.json`)

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.py` | silent — injects `using-coderails` skill into every new session |
| `SessionStart` | `remember_inject_cap_guard.py` | warns when another plugin has no memory-injection byte cap. It does not block session start. See the rules below. |
| `UserPromptSubmit` | `inject_context.py` | adds cwd, branch, and date. It adds the discipline reminder on the first prompt. |
| `UserPromptSubmit` | `crack_on_gate.py` | grants or checks the session authority described below. |
| `Stop` + `SubagentStop` | `check_confidence_labels.py` | warns about missing confidence labels. It never blocks. |
| `Stop` + `SubagentStop` | `check_verify_loop.py` | warns about missing verification notes. It never blocks. |
| `Stop` | `voice_announce.py` | speaks loop events on macOS. It never blocks. |
| `Stop` | `loop_state_guard.py` | blocks invalid loop state or unstamped loop evals. See the rules below. |
| `Stop` | `loop_stall_guard.py` | blocks an incomplete loop without a valid stop, and blocks an invalid completion claim. See the rules below. |
| `Stop` | `unregistered_loop_guard.py` | warns when agents run without a registered loop. |
| `Stop` + `SubagentStop` | `offload_push_guard.py` | warns once if a response tells the user to push to main. |
| `PreToolUse` (Bash) | `destructive_bash_gate.py` | blocks listed destructive commands and source edits on main. See the rules below. |
| `PreToolUse` (Bash) | `enforce_pr_workflow.py` | blocks PR actions without required workflow evidence. See the rules below. |
| `PreToolUse` (Bash) | `test_gate.py` | blocks a commit when opted-in tests fail; keeps the full output. |
| `PreToolUse` (Bash) | `verification_volume_ceiling.py` | blocks a third full-suite or structure-validation run per branch. |
| `PreToolUse` (Bash) | `action_authority_gate.py` | checks optional action receipts for PR merges and main pushes. |
| `PreToolUse` (Bash) | `reviewer_bash_allowlist.py` | limits named reviewer agents to read-only commands and granted capabilities. |
| `PreToolUse` (AskUserQuestion) | `crack_on_gate.py` | grants or checks the session authority described below. |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.py` | blocks source edits on main and settings edits on all branches. |
| `PreToolUse` (Write/Edit/MultiEdit) | `comment_citation_gate.py` | blocks comments that cite ephemeral session labels. |
| `PreToolUse` (Write/Edit/MultiEdit) | `wiki_taxonomy_gate.py` | blocks wiki writes outside the live schema when it can identify the vault. |
| `PreToolUse` (`Bash\|Edit\|Write\|MultiEdit\|Read\|Grep\|Glob\|WebFetch\|NotebookEdit`) | `agent_only_gate.py` | steers top-level work to agents; enforcement is opt-in. |
| `PreToolUse` (`Agent`) | `agent_model_routing_nudge.py` | suggests a model for mechanical or complex agent tasks. |
| `PreToolUse` (`Agent`) | `loop_dispatch_guard.py` | blocks graph-bound agent requests without a valid ownership envelope. |

### Session and command hook details

- `remember_inject_cap_guard.py` checks another plugin's memory-injection
  cap. The default cap is `REMEMBER_INJECT_MAX_BYTES=8000`. By default, the
  hook writes nothing and warns once per plugin version. If
  `REMEMBER_INJECT_CAP_AUTOWRITE=1`, it replaces only the expected memory loop
  with the patch from `hooks/patches/`. It saves a rolling backup. A shape
  mismatch leaves the file unchanged and asks for a manual update.
- `crack_on_gate.py` reads only the raw prompt. It accepts an unquoted,
  unnegated, whole-word `crack on`, without regard to case. It writes
  `<base>/<session_id>/authority.json` for 24 hours. The base comes from
  `$CLAUDE_AGENTIC_LOOP_DIR` or `~/.coderails/agentic-loop`. It binds the exact
  session ID and, when set, `$CLAUDE_LOOP_ID`. The object grants
  `autonomous_decisions`, sets `max_prs` to 0, and still requires merge
  approval. The hook returns a revoke command and records
  `authority_granted`. It does not read injected context or a transcript.
- For `AskUserQuestion`, `crack_on_gate.py` denies only when that session has
  valid, unexpired authority. It traces expiry and foreign-session cases.
  A legacy `crack_on_active` flag still denies for one release. The hook
  does not gate prose questions. Use `LOOP-STOP` for a loop hard stop.
- `check_confidence_labels.py` warns on a response of at least 200 characters
  without `(verified)`, `(inferred)`, or `(guess)`. It reads
  `last_assistant_message`, emits an advisory, and records a demotion. It
  always exits 0. A `Stop` event with `CODERAILS_HEADLESS_RUN=1` is exempt;
  `SubagentStop` is not.
- `check_verify_loop.py` warns when a `## Did Not Verify` bullet lacks
  `(unverifiable: <reason>)`. It also warns when a turn edits at least three
  files and omits that section. It records a demotion and always exits 0.
  The same headless `Stop` exemption applies.
- `voice_announce.py` uses macOS `say` for loop completion, waiting,
  stopping, or stalling. It debounces each kind and is silent outside a loop.
- `loop_state_guard.py` gives one missing-`progress.json` grace per session
  and invocation count. It does not give grace for a foreign session or a
  stale complete state. When `work_units` is at least 1, it requires a
  sibling `evals.json` with a stamped `GO` or `VERIFICATION_LEVEL0` result
  and a nonblank verification justification. It blocks `ABSENT`, `NO-GO`,
  `UNJUSTIFIED`, and `UNSTAMPED`. It fails open when `work_units` is absent.
- `unregistered_loop_guard.py` warns after at least three agent dispatches
  if no `progress.json` or `agentic-loop` call exists. It never blocks.
- `offload_push_guard.py` warns once per session when a final response both
  names a push to main/master and tells the user to run it. It detects a
  `! ` command or text such as "your own shell" or "run this yourself".
  It runs last.
- `destructive_bash_gate.py` blocks `rm -rf`, a naked force push, hard reset,
  SQL `DROP` or `TRUNCATE`, `dd if=`, `mkfs.*`, `chmod -R 777`,
  `git commit --no-verify`, forced `git clean`, `find -delete`, `truncate`,
  and `shred`. It blocks literal `.env` path access, but permits example,
  sample, template, dist, and `.envrc` paths. It blocks inline source edits
  on main/master through `sed -i`, `perl -i`, redirects, `tee`, `cp`, `mv`,
  or `dd of=`. It also blocks shell substitution inside arguments to
  `push.py`, `merge.py`, `post_review.py`, and `post_evals.py`.
  `--force-with-lease` remains conditional.
- `enforce_pr_workflow.py` blocks `gh pr create` without `/coderails:push`.
  It blocks `gh pr merge <N>` and `scripts/merge.py <N>` without a recorded
  `review-pr <N>`. It requires a fresh review after each local merge or
  push to main/master. It reads subagent transcripts. It excludes Git
  merge inspection and in-progress controls. It stands down without
  `workflow.config.yaml`. For a PR merge, it also needs a SHA-bound `GO`
  eval artifact. `gate_smoke_verify` reruns each level-1-or-higher eval
  command and negative control at the trusted SHA in a detached worktree.

### Other hook details

- `test_gate.py` runs only when enabled. It checks the configured tests
  before `git commit`. It keeps full stdout and stderr for each command and
  reports measurements and the reader path.
- `verification_volume_ceiling.py` blocks the third and later invocation of
  `hooks/scripts/tests/run_all.py` or `post_evals.py validate-structure`
  on one work-unit branch. It has no override.
- `action_authority_gate.py` is off unless config selects `advisory` or
  `enforce`. It guards only `gh pr merge` and pushes to main/master. Advisory
  mode logs a warning. Enforce mode needs one unused receipt for each guarded
  command segment. The receipt binds the command text, effective directory,
  branch, session, loop, and relevant SHA. It is consumed atomically. Hook
  errors fail open and leave a trace. A same-user agent can mint a receipt,
  so a receipt does not prove human approval. The command hash omits the
  environment, aliases, shell wrappers, and implicit upstream pushes.
  A subagent may have a different session ID; that case remains unverified.
  Codex vendors the checker but does not ship the receipt CLI. See
  [the authority decision](docs/decisions/e3-authority-object.md).
- `reviewer_bash_allowlist.py` applies only to the named deploy, design,
  disposition, preflight, and source-auditor roles. It permits one read-only
  command from its allowlist: `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`,
  `sha256sum`, `git status/log/diff/show/blame`, or `gh pr view/list --json`.
  It rejects command chains, redirects,
  substitutions, interpreters, and output or external-diff flags. It also
  permits a typed `scripts/capability.py` call for `repo.inspect`,
  `diff.read`, `tests.run`, or `pr.comment` when
  `capabilities/profiles.json` grants that tool. A different or absent
  `agent_type` makes the hook a no-op. Codex has no per-agent Bash hook.
  See [capability limits](docs/CAPABILITIES.md) and
  [the reviewer decision](docs/decisions/e2-reviewer-bash-allowlist.md).
- `no_edit_on_main.py` permits only listed text, config, license, and
  ignore-file edits on main/master. This includes `.md`, `.txt`, `.rst`,
  `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, `.cfg`, `.gitignore`, and
  `LICENSE`. It blocks plugin source Markdown there when the repo has
  `.claude-plugin/plugin.json`.
  It blocks `.claude/settings.json` and `.claude/settings.local.json` on
  every branch.
- `comment_citation_gate.py` rejects changed code comments that cite
  ephemeral labels such as `E#:`, `Task A#`, or `per the plan`. It does not
  apply to Markdown. Durable PR numbers remain allowed.
- `wiki_taxonomy_gate.py` reads top-level directories from
  `wiki.schema.json`. It needs an unambiguous vault from workflow config, a
  matching Git root, and at least two known directories on disk. A missing
  `.coderails/workflow.config.yaml` makes the hook inert. It allows
  `raw/`, root files, and dotfile directories. Ambiguous config, schema, or
  location makes it fail open with a trace.
- `agent_only_gate.py` allows calls with `agent_id`. It also allows one
  top-level `gh`, `git`, or workflow-script command without chaining. Other
  top-level work gets a nudge. `AGENT_ONLY_GATE_ENFORCE=1` turns the nudge
  into a block. Agent and task-control tools are outside this gate.
- `agent_model_routing_nudge.py` suggests `haiku` for mechanical tasks and
  `opus` for complex design tasks. It stays silent when a model is set or
  both kinds of cue appear. It never blocks.
- `loop_dispatch_guard.py` checks the session, loop, revision, wave, and
  node for graph-bound agent calls. It requires frozen, owned loop evals
  before a nonempty work-unit roster can dispatch. Frozen suites bind to
  session and loop, not graph revision. Missing or foreign ownership blocks.
  The Python sandbox launcher uses the same guard. Completion still needs
  neutral grading, native evidence, proofs, and a retrospective.

### `loop_stall_guard.py` completion and stall rules

- An incomplete loop needs a valid `LOOP-STOP` declaration. The guard shares
  `loop_state_guard`'s one-time grace when `progress.json` is absent.
- A `complete` declaration needs a valid `retro.json` with `schema_version`
  at least 1. Frozen proofs must have run in this session's Bash transcript
  and must not have failed last. Under graph schema 3, a missing `proof.json`
  needs `progress.json.proof_disposition` set to `"none"` or `"none: <reason>"`.
- A withdrawn proof must have run, failed last, carry `withdrawn_reason`,
  and have an ID absent from `.proofs`. The combined proof limit is 100.
- For an unresolved graph, the blocking Stop shows one notice per graph
  state: loop, revision, session, active wave, and hard stop. It repeats once
  per 900-second lease while the stall continues. The notice includes
  `graph.py summarize` status. For a silent wave, it can try one bounded
  `recover-wave`; this can duplicate a live but quiet worker, within
  `retry.max`. The guard writes the dedupe marker only after it prints the
  notice and prunes markers from older revisions.
- Codex `graph_completion_guard.py` uses the same helper and key. It returns
  `decision: block` JSON on stdout (reason and systemMessage, exit 0).
  The Claude guard uses stderr and exit 2.

### Enforcement ceilings — deliberate, not bugs

- **Bash blocklists are enumerated families, not exhaustive.** Obfuscated forms, variable filenames, quoted paths with spaces, here-docs, process substitution, `python -c open(...)` writes remain uncaught.
- **Eval-gate coverage boundary.** Enforced only at `/coderails:merge` (config-independent) and `gh pr merge <N>` via `enforce_pr_workflow` (config-dependent, inactive under `NO_CONFIG`). NOT enforced on raw `git merge`/`git push` to main/master (no PR number to resolve an artifact against) or in any `NO_CONFIG` repo. Both enforced points then run `scripts.post_evals.smoke_verify` — three failure modes: `gh` fetch failure, `NO-GO`/missing artifact, failed re-execution.
- **`no_edit_on_main` allowlist breadth is intentional (fail-safe).** `.sh` blocked on main, `.json`/`.yaml` config stays editable. Settings.json `Write`/`Edit` permission covers any legitimate override.
- **Wiki/workflow sequence past merge is advisory.** `/wiki-ingest` + `/wiki-lint` after merge are slash commands; nothing enforces them.
- **`check_verify_loop`, `check_confidence_labels`, both loop guards** all short-circuit on `stop_hook_active=true` (the two loop guards block at most once per turn; the two discipline lints are advisory and exit 0 either way) — intentional infinite-loop safety valve. `voice_announce` reads it too (via its shared loop helper), no observable effect (always exits 0).
- **TDD is not enforced test-first.** `test_gate` only checks tests pass at commit time.
- **Test-output delivery is not observable from capture alone.** Both providers retain complete per-command logs under `~/.coderails/test-output/` (override: `CODERAILS_TEST_OUTPUT_DIR`). The provider-local `hooks/scripts/test_output.py` reader measures explicit full/ranged/literal-search retrievals. Default reads always return metadata and guidance; the agent expands requests as needed, without predicting line ranges across runs. Emitted bytes are not confirmed delivered bytes; direct file reads are unobserved. Completed logs compress automatically; a 1 GiB compressed-log budget (`CODERAILS_TEST_LOG_BUDGET_BYTES`) expires oldest completed logs first while protecting active and just-completed runs. Protected logs may exceed the budget; compact metrics and expiry records persist. See [retained test-gate output](docs/REFERENCE.md#retained-test-gate-output) for usage and measurement limits.
- **Authority objects (E3) back the crack-on denial.** `crack_on_gate.py` (and the Codex copy, which vendors a subset of the validator in `hook_common.py` because its package ships without `scripts/lib`) writes and reads `<loop dir>/<session_id>/authority.json`; `scripts/authority.py inspect|narrow|revoke --session <id>` manage it. Expiry and revocation end the denial; granting or revoking also deletes any legacy `crack_on_active` flag (Claude loop dir and Codex `$PLUGIN_DATA/sessions/<id>/`). Until then a legacy flag is honoured one more release via `crack_on_legacy_flag`. Both gates read the loop root from `CLAUDE_AGENTIC_LOOP_DIR` (Codex falls back to `CODERAILS_AGENTIC_LOOP_DIR`), so one `authority.py revoke` covers both providers. A failed grant fails open with a `crack_on/failed_open/authority_write_failed` trace row. See [docs/decisions/e3-authority-object.md](docs/decisions/e3-authority-object.md) and the RUNBOOK entry.
- **Skill invocation, ask-on-ambiguity, verify-memory are structurally unenforceable by hooks** — they depend on Claude's internal reasoning, which a hook can't observe.
- **No `SubagentStart` event exists.** `inject_bootstrap.py` can't inject `using-coderails` into subagents; they get it only via the orchestrator's system prompt.
- **`/coderails:post-review` validates summary structure, not provenance.** Proves an auditable SHA-bound artifact exists, not that the review was substantive. The `review-pr` arm of `enforce_pr_workflow` is expected to demote block→nudge once the artifact gate is verified live — never before, or a window opens with neither gate active.
- **Model-role routing is advisory, hook-enforced only as a nudge.** `agentic-loop` Phase 2.8 assigns a role (`fast-mechanical`/`default`/`frontier`) + effort per task (table in Phase 2.8, defaults + fable-escalation in `model-routing.md`), asserted at spawn sites (Phases 2, 2.5, 3, 3a, 9, 10). `agent_model_routing_nudge.py` is the only hook touching this — advisory only. No hook enforces *correct* role selection; a `frontier`-role worker still produces a fully-gated PR. Phase 2.8 also sanctions a legitimate `default`-vs-`frontier` judgement call a blunt gate can't distinguish from a disallowed spawn without a self-reported carve-out (reintroducing the same trust problem).
- **`agent_only_gate`'s detection is real but narrow.** `agent_id` presence/absence was confirmed empirically on Claude Code 2.1.220 via a live probe (top-level Bash/Agent calls carried no `agent_id`; a subagent's Bash call carried both `agent_id`/`agent_type`; `session_id` was identical across all three, so it alone can't distinguish them). This answers "did this call originate at top level," not "is the orchestrator cooperating" — a top-level session doing real work in-context and never calling `Agent` is invisible until it attempts a do-work call. Hard top-level block isn't default because it would deadlock this repo's own shipping path (`enforce_pr_workflow`, `merge.py`, every workflow command assume the orchestrator runs `gh`/`git`/`scripts/*.py` inline). `AGENT_ONLY_GATE_ENFORCE=1` opts into hard-blocking with the same workflow-chain carve-out. Unverified: behaviour under `claude --agent <name>` mode (reportedly sets `agent_type` even on top-level calls, per docs) — the live probe used a plain headless session, not `--agent` mode.
- **Headless-run exemption is env-triggered, `Stop`-only, inside the agent trust domain.** `check_confidence_labels.py`, `check_verify_loop.py` skip enforcement when `CODERAILS_HEADLESS_RUN=1` is in their process env — a headless `claude -p` run has no interactive turn left to satisfy a repair-turn block. Does NOT extend to `SubagentStop`: the two discipline lints still emit their advisory for worker output regardless of the flag. Set in exactly one place: `skills/dashboard/app/src/app/api/run/route.ts`'s `spawn(...)` call — a second set-site (including a session setting it on itself) is a security finding. `scripts/sandbox/spawn_sandboxed_worker.py` force-unsets it before launching a sandboxed worker so no inherited value leaks the exemption in; keep the two in lockstep.

**Hook script conventions** (follow when editing/adding a script):
- Use the provider-local Python payload reader with a five-second total deadline, including partial input on an open pipe. Empty/invalid input stands aside where the hook contract is fail-open; do not extend the hook timeout to conceal an unbounded read.
- Cheap skip gates precede expensive transcript parsing. Hooks use maintained Python functions, not embedded Bash implementations or compatibility wrappers.
- Stop blocks use exit 2 and stderr; PreToolUse emits `hookSpecificOutput.permissionDecision: "deny"` and exits 0.
- Append escaped structured audit records to `$CLAUDE_DISCIPLINE_LOG` (default `~/.claude/discipline.log`).
- Use the provider's bounded transcript stabilization helper when the native harness may still be flushing its final response.
- Native worker labels belong to the provider. Carry agent instruction bodies explicitly and correlate graph nodes through ownership envelopes/native call identities, never a custom label alone.

## Workflow command architecture

`/coderails:workflow` is the umbrella orchestrator; every phase delegates to a standalone sub-command that also works alone:

```
/workflow  →  /prep → (code) → /push → /pr-review-toolkit:review-pr → /coderails:post-review → (ship-it) → /merge → /wiki-ingest + /wiki-lint
```

Two interactive pauses: the code/iterate loop, and final ship-it authorization. Everything else auto-chains. `/coderails:post-review <PR#>` sits between `review-pr` and ship-it, converting ephemeral review output into the durable SHA-bound review artifact; `/merge` fetches live PR comments and requires a matching artifact for the current head SHA — fail-closed. Both the agentic loop (Phase 4b) and non-loop `/workflow` (Phase 3) post the same artifact; `/merge` checks both the same way. `scripts/merge.py` holds the gate in its `OPEN` branch before `gh pr merge`.

**Config resolution** — workflow command frontmatter runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`. The maintained `config_path(start_dir)` walks upward from the current directory to the Git root, selecting the nearest `.coderails/workflow.config.yaml`; nearest wins without merging. `resolve-config` emits its contents or `NO_CONFIG`. Commands and workflow gates import the same provider-local resolver. Adding a config field requires updating workflow/prep/push/init instructions. Init preserves and validates configuration before moving migrated files to Trash. There is no runtime fallback to legacy paths; `NO_CONFIG` means not initialized.

**`scripts/` vs `commands/`** — `push.py`/`merge.py` hold deterministic git plumbing (commit, push, `gh pr create`, merge); `.md` commands hold prose/decision logic and shell out to those scripts. Shared git/gh helpers live in `scripts/lib/git_common.py` — add reusable primitives there, not inline.

## Project-specific assumptions (change when generalising)

- **Auth host**: `push.py` requires a `github.com` remote (`scripts.lib.git_common.require_repo`).
- **Jira fields**: `prep.md` reads `config.jira.epic_field`/`points_field`; transition names are project-specific (see INSTALLATION.md "Notes").
- **Jira route**: commands build Jira MCP tool names from `config.jira.mcp_namespace` (default `jira` → `mcp__jira__*`). Add `"mcp__<namespace>__*"` to `.claude/settings.json` for non-default namespaces; without a Jira MCP, Jira steps no-op.

## Working in this repo

- Editing a command/skill: effective after `/reload-plugins` — nothing to compile.
- Editing a hook: same; test by triggering the event, checking `~/.claude/discipline.log`. `python3 install.py --dry-run` previews changes.
- `install.py` is idempotent — re-running won't duplicate CLAUDE.md edits or overwrite seeded memories. Preserve that.
- `uninstall.py` must reverse exactly what `install.py` adds (CLAUDE.md block, settings keys) while preserving user data (`discipline.log`, memories). Keep the two in lockstep.
- `instructions/self-checking-discipline.md` is the authoritative copy `install.py` appends to `~/.claude/CLAUDE.md` — edit there, not the installed copy.

## Requirements

Python 3.9+ (standard-library runtime) · Claude Code 2.1.x for the root provider or Codex CLI for the native provider · `gh` and `git` on PATH for workflow commands · authenticated GitHub host for `/push`/`/merge` · `pr-review-toolkit@claude-plugins-official` for the Claude `/workflow` review stage. `jq` is not a Python runtime dependency. See `docs/CODE-QUALITY.md` for development and test-only tools.

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

**Three layers**: (1) raw sources (immutable) — the plugin repo (commands, hooks, scripts, skills, install.py, CLAUDE.md); read from, never modify. (2) The wiki — LLM-generated markdown in the vault; Claude owns this layer entirely. (3) This file — tells Claude how the wiki is structured; the maintainer edits it, Claude reads it.

## Page types

> **`wiki.schema.json` (repo root) is the source of truth.** Both
> `wiki_taxonomy_gate.py` copies read its `page_types` and `structural_dirs`
> at runtime and fail open, leaving a `wiki_schema_missing` or
> `wiki_schema_invalid` trace row, if it is absent or unusable. The tables
> below are documentation; `hooks/scripts/tests/config_docs_drift_test.py`
> fails the build when they stop matching the schema, or when this heading
> is renamed or removed.

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

## Conventions

- Frontmatter tags: lowercase, hyphenated.
- One concept per page — split a page that covers too much.
- Source pages reference the PR number and key files changed.

**Exploration boundary**: subagent/code exploration explores code; the wiki captures understanding. Use it when a wiki operation hits a specific gap (a query found no page, an ingest touches unfamiliar code, a lint finds a page you have specific reason to doubt) — not to routinely validate wiki content. The wiki is trusted by default, corrected by evidence.

**Evolution note**: this file is co-evolved. Convention changes (new page types, frontmatter fields, naming rules) — update this file first, then affected vault pages. The maintainer edits; Claude reads. Living system, not a snapshot.
