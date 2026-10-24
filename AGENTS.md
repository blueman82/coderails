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

The trusted GitHub Actions workflow runs a mechanical `integrity-review`
attestor. It replaces the semantic judge. It checks review and eval evidence
bound to the head SHA. It also checks command and eval structure, policy
paths, provenance fields, and bounded diff input. It does not run PR code or
commands from comments. It does not ask an LLM for a verdict.

The authoritative sources are `docs/INTEGRITY-GATE.md`,
`.github/workflows/integrity-review.yml`,
`scripts/integrity-gate/integrity_actions.py`, and the
`integrity_review.enabled` setting. GitHub ruleset `25788196` is active on
`main`. It requires the status from the GitHub Actions app. Source code alone
cannot activate this rule.

## What this repo is

Two independent plugins, not an application:
- Working Claude Code plugin at repo root.
- Native Codex plugin at `packages/codex/`.

`install.py` defaults to Claude; `--provider codex` for Codex. Claude plugin bundles:
1. Workflow commands — `prep → push → merge → wiki` chain (`commands/*.md`)
2. Skills — agentic-loop, planning-sequence, premortem, handoff (`skills/*/SKILL.md`)
3. Discipline loop — advisory lints on confidence labels and unverified claims; blocking hooks on destructive bash, failing tests (`hooks/`)

The plugin instructions and Python runtime need no compilation. The dashboard
TypeScript packages have separate build and test commands. Source includes
Markdown instructions, maintained Python hooks and workflow scripts, and
dashboard TypeScript. Keep it under version control in your fork or repo.
Python replaces the former shell runtime and test entrypoints. Generic shell
policy examples and external tools remain supported.

**Agentic-loop graph runtime:** The `agentic-loop` skill stores nodes, edges,
joins, status, outcomes, and retries in `progress.json`. Readiness checks and
plan and record helpers support each dispatch wave. The model reads the graph,
dispatches ready work, and records results. The graph is not an automatic
scheduler. Each provider has its own graph adapter, locks, and native evidence
reader. The maintained graph semantics live in
`packages/graph-semantics/graph_semantics.py`. Both installs contain identical
copies. Graph schema 3 is the only supported schema. There is no legacy
reader or alternate writer.

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

**Enforcement ceiling.** A local hook can check invocation: it can tell that
an agent called a step.
It cannot prove that the step did the work. For example, a hollow
`/coderails:push` or `/pr-review-toolkit:review-pr` can satisfy
`enforce_pr_workflow`. A hook runs with the agent's own access. It has no
separate privilege boundary. It can redirect a cooperating agent and leave a
`discipline.log` record. This is a **redirect-and-audit layer**. It cannot
prevent tampering. Server-side branch protection can block an unreviewed
change from reaching `main`. It can require a PR, reviews, and no direct
push. A local agent cannot fake that server rule. Stop-hook gates have
the same limit: they can require a declared step, but cannot prove its result.

**This repo** does not enable general review approval branch protection. This is a standing decision from 2026-07-15. The active integrity rule below requires a
PR and a status check. It checks evidence structure. It cannot prove that an independent reviewer ran.

**Server rule: `integrity-review`.** The active GitHub ruleset on `main` requires a PR. It also requires a successful `integrity-review` status from the GitHub
Actions app. The workflow checks review evidence, eval evidence, and policy data for the head SHA. Local hooks cannot replace this rule.

**Sandboxed workers.** With `config.sandbox_workers: true`, an implementation
worker runs as a separate OS process. The pinned
`@anthropic-ai/sandbox-runtime` (`srt`) uses Seatbelt or bubblewrap to limit
writes. This is the first boundary outside the agent's own process. It applies
only to workers. The orchestrator is not sandboxed. In Phase 3 and 3a of
`skills/agentic-loop/SKILL.md`, the orchestrator reads this setting from
`resolve-config` text. No script reads it directly (`read_by_prose_only`).

The rendered settings use an **allow-only write policy**. This policy is the
main containment boundary. The mandatory srt denies for `.git/hooks` and
`.git/config` use the worker's current directory. They do not reach the main
repo's `.git`, which must remain writable for commits. The rendered settings
therefore add an explicit `denyWrite` for those two paths in the main repo.
Other mandatory srt denies, such as shell startup files and `.mcp.json`,
also use the worker's current directory. `$HOME` stays protected because it
is outside `allowWrite`. If a worker can write to `$HOME`, those files become
exposed.

Named residuals:
- **Primary `.git` write access.** Workers need write access to `.git` to commit. A worker can therefore change refs on other branches. The rendered settings
  deny writes to `.git/hooks` and `.git/config` only. The sandbox does not protect the rest of `.git`. The PR gates limit what reaches the server. `git fsck`
  and the reflog can help recover damaged refs.
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
- **Shared `$TMPDIR` for parallel workers.** The policy grants access to all of `$TMPDIR`. Worker scratch directories are siblings there. One worker can change
  another worker's `worker.log` or replace its `srt-settings.json` during rendering. Current dispatch is serial, so this case is not exercised. Granting only
  each worker's scratch directory could reduce this risk. Node, npx, and git also write to `$TMPDIR`; test their needs before narrowing access.

The sandbox limits filesystem writes. A worker PR must still pass the same review, eval, and hook gates as any other PR. The worker still has the operator's
full `gh` token. Parallel workers can still affect each other through `$TMPDIR`. The worker can still edit `~/.claude.json`.

### Skills↔hooks seam convention

When a skill asks for a gated action, name the hook and how to satisfy it.
`enforce_pr_workflow` gates `git merge`, `gh pr create`, and `gh pr merge`.
`no_edit_on_main` gates code and plugin-source edits on main. `test_gate`
gates `git commit`. Update the relevant skills when you add a hook for a
common action. The merge gate recognizes a
`/pr-review-toolkit:review-pr <PR#>` Skill call with the PR number. A manually
spawned review group does not satisfy this local hook. The agentic loop must
invoke the Skill.

Apply review findings and push them before you run `/coderails:post-review <PR#>`. Run it after `review-pr`. It posts a review artifact bound to the head SHA.
`/merge` (`scripts/merge.py`) fetches the PR comments and checks for this artifact. A failed `gh` fetch blocks the merge. An absent artifact for the current
head SHA also blocks the merge.

**Task eval gate.** `/coderails:task-evals` freezes an ungraded `evals.json`
before implementation. It grades actual results afterward. See
`skills/task-evals/SKILL.md`. `/coderails:post-evals <PR#>` validates the
suite and posts a SHA-bound `coderails-eval-summary` PR comment through
`scripts/lib/eval_artifact.py`. `scripts/merge.py` reads this comment after
the review artifact. A failed GitHub fetch, missing artifact, or `NO-GO`
blocks the merge.

For a loop with at least one `work_units` entry, `loop_state_guard` requires
a sibling `evals.json`. Without it, Stop blocks. An absent `work_units`
field makes this check stand down. Run `scripts/post_evals.py grade-loop` to
compute the loop result. Do not write the result by hand. The result needs a
valid `grading` stamp. Without it, the guard changes `GO` or
`VERIFICATION_LEVEL0` to `UNSTAMPED` and blocks.

**GitHub Actions merge gate.** When `config.integrity_review.enabled` is true, `scripts/merge.py` and `enforce_pr_workflow` require the newest
`integrity-review` status for the exact head SHA. The status must be successful. Its creator must be `github-actions[bot]`. Its description must contain
`integrity=pass sha=<head>`. A wrong creator, absent status, stale SHA, unsuccessful state, malformed description, or fetch failure blocks the merge. The GitHub
ruleset provides the server boundary.

**Loop teardown gate.** Phase 13 writes `retro.json` beside `progress.json` before the loop declares `complete`. It uses `schema_version` 2. `loop_stall_guard`
blocks a `complete` declaration without a valid retro. It accepts `schema_version >= 1`. Follow Phase 13 and declare `complete` again to clear this gate.

For schema version 2, Phase 13 step 1 runs `python3 hooks/scripts/lib/loop_cost.py <session_id>`. It writes the dated, once-frozen token and USD totals by model
to `retro.cost`. It copies `models_used` to top-level `retro.models_used`. A cost-miner failure leaves both fields empty and does not block teardown. A caller
error produces a self-describing error object. See Phase 13 in `skills/agentic-loop/SKILL.md` and `teardown.md`.

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
  `review-pr <N>`. A raw `git merge` on main/master consumes the prior review
  evidence, so the next raw merge needs a fresh review. A push to main/master
  also needs a recorded review, but does not consume it. It reads subagent
  transcripts. It excludes Git
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

- **Bash blocklists cover named command forms.** Obfuscation can bypass them. Variable filenames, quoted paths with spaces, here-docs, process substitution, and
  `python -c open(...)` writes also remain outside them.
- **Eval gate scope.** `/coderails:merge` checks evals in every config. `enforce_pr_workflow` checks them for `gh pr merge <N>` when config exists. Neither
  checks raw `git merge` or `git push` to main or master. Those commands supply no PR number for an artifact lookup. `NO_CONFIG` also disables the `gh pr merge`
  check. At each enforced point, `scripts.post_evals.smoke_verify` runs the checks again. A failed `gh` fetch, missing or `NO-GO` artifact, or failed run blocks
  the merge.
- **`no_edit_on_main` allows some config edits.** It blocks `.sh` files on main. It allows `.json` and `.yaml`. The `Write` and `Edit` permission for
  `settings.json` permits a legitimate override.
- **Wiki steps after merge are advisory.** `/wiki-ingest` and `/wiki-lint` are slash commands. No hook enforces them.
- **Stop hooks have a loop guard.** `check_verify_loop`, `check_confidence_labels`, and both loop guards stop when `stop_hook_active=true`. The loop guards
  block at most once per turn. The discipline lints are advisory and always exit 0. This avoids an infinite Stop loop. `voice_announce` reads the flag too, but
  its exit behavior stays 0.
- **TDD has no test-first gate.** `test_gate` checks tests at commit time.
- **Retained test output.** Both providers keep complete command logs under
  `~/.coderails/test-output/`. `CODERAILS_TEST_OUTPUT_DIR` can change that
  path. The provider-local `hooks/scripts/test_output.py` reader measures
  full, ranged, and literal-search retrievals. Default reads return
  metadata and guidance. The agent asks for more output when needed.
  Emitted bytes do not prove delivery to the model. Direct file reads are
  not observed. Completed logs compress automatically. The default
  `CODERAILS_TEST_LOG_BUDGET_BYTES` limit is 1 GiB of compressed logs.
  Old completed logs expire first; active and just-completed runs remain
  protected. Protected logs can exceed the limit. Compact metrics and
  expiry records remain. See [retained test-gate output](docs/REFERENCE.md#retained-test-gate-output).
- **Authority objects back the crack-on denial.** `crack_on_gate.py`
  writes and reads `<loop dir>/<session_id>/authority.json`. The Codex
  copy keeps a subset of the validator in `hook_common.py` because its
  package does not ship `scripts/lib`. Run
  `scripts/authority.py <inspect|narrow|revoke> --session <id>` to manage it.
  Expiry or revocation ends the denial. Grant or revoke also removes the legacy
  `crack_on_active` flag from the Claude loop directory and Codex
  `$PLUGIN_DATA/sessions/<id>/`. One release still honors an old flag and
  traces `crack_on_legacy_flag`.

  Both providers read `CLAUDE_AGENTIC_LOOP_DIR`. Codex uses
  `CODERAILS_AGENTIC_LOOP_DIR` as a fallback. One `authority.py revoke`
  can therefore cover both. A failed grant stands down and traces
  `crack_on/failed_open/authority_write_failed`. See
  [the authority decision](docs/decisions/e3-authority-object.md) and the
  runbook entry.
- **Hooks cannot observe internal reasoning.** They cannot enforce skill invocation, when to ask about ambiguity, or memory verification.
- **There is no `SubagentStart` event.** `inject_bootstrap.py` cannot send `using-coderails` to subagents. They receive it only from the orchestrator's system
  prompt.
- **`/coderails:post-review` checks structure, not review quality.** Its SHA-bound artifact proves that a review summary was posted. It does not prove the
  review was substantive. Keep the `review-pr` block in `enforce_pr_workflow` until the artifact gate is verified live. Only then can that block become a nudge.
  An earlier change would leave a gap.
- **Model-role routing is advisory.** Phase 2.8 assigns each task a role:
  `fast-mechanical`, `default`, or `frontier`, plus effort. Its table gives
  defaults and the escalation rule in `model-routing.md`. Spawn sites in
  Phases 2, 2.5, 3, 3a, 9, and 10 assert the role. Only
  `agent_model_routing_nudge.py` checks it, and that hook only nudges.
  It cannot judge whether the choice was correct. A `frontier` worker can
  still produce a fully gated PR. Phase 2.8 also allows a real choice
  between `default` and `frontier`. A blunt hook cannot tell that choice
  from a wrong spawn without trusting the agent's own carve-out.
- **`agent_only_gate` detects a top-level call.** A live probe on Claude
  Code 2.1.220 found no `agent_id` on top-level Bash and Agent calls. A
  subagent Bash call carried `agent_id` and `agent_type`. All three shared
  one `session_id`, so that field cannot distinguish the caller.
  The gate can tell where a tool call came from. It cannot tell whether
  the orchestrator is cooperating before that call.

  A hard top-level block is off by default. It would block this repo's
  shipping commands, which expect the orchestrator to run `gh`, `git`,
  and `scripts/*.py` inline. `AGENT_ONLY_GATE_ENFORCE=1` enables the hard
  block with the existing workflow-command carve-out. Behavior under
  `claude --agent <name>` remains unverified. The live probe used a plain
  headless session; docs suggest that mode can put `agent_type` on
  top-level calls.
- **Headless-run exemption.** At `Stop`, `check_confidence_labels.py` and
  `check_verify_loop.py` stand down when their process has
  `CODERAILS_HEADLESS_RUN=1`. A headless `claude -p` run has no interactive
  turn in which to repair a block. This exemption does not apply to
  `SubagentStop`; worker output still gets the advisory.

  Set this variable only in the `spawn(...)` call in
  `skills/dashboard/app/src/app/api/run/route.ts`. A second set site,
  including one set by the session itself, is a security finding.
  `scripts/sandbox/spawn_sandboxed_worker.py` removes an inherited value
  before it launches a worker. Keep these rules in step.

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
