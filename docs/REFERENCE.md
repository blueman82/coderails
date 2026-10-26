# coderails Component Reference

Catalogue of coderails skills, hooks, commands, and scripts: what it does, when it's active, when it's NOT, and dependencies. General dev-workflow skills (planning, TDD, debugging, code review, worktrees) are provided by the required `superpowers@claude-plugins-official` plugin dependency, not bundled here. Ground truth: all entries verified from source files. See README for a lighter overview.

---

## Table of Contents

1. [Skills](REFERENCE-SKILLS.md#skills)
2. [Agents](REFERENCE-AGENTS.md#agents)
3. [Hook Activation Matrix](#hook-activation-matrix)
4. [Commands](#commands)
5. [Scripts and Libraries](#scripts-and-libraries)
6. [Artifact and State Locations](#artifact-and-state-locations)

---

## Skills

See [the skills catalogue](REFERENCE-SKILLS.md).

## Agents

See [the agents catalogue](REFERENCE-AGENTS.md).

## Hook Activation Matrix

The authoritative event map is [AGENTS.md](../AGENTS.md#hook-event-map-hookshooksjson),
with exact registrations in [hooks.json](../hooks/hooks.json). Claude hooks and
Codex hooks are independently installed Python entrypoints. Stop denials exit 2;
PreToolUse denials return native permission JSON with exit 0. Payload reads have
a five-second deadline, including partially written input. Test-gate output is
retained in full; failure notices provide measurements and a reader command
instead of a fixed excerpt (see below).

Local hooks redirect and audit a cooperating agent. Their files and transcripts
remain inside the local trust domain. The trusted GitHub Actions workflow and
GitHub required status provide the server-side boundary described in
[INTEGRITY-GATE.md](INTEGRITY-GATE.md).

### Retained test-gate output

Each configured test-command execution is one **run**, which may contain many
individual tests. Both providers execute their configured first line through
`/bin/bash -c`, preserving their existing command trust rules. Claude reads
`.claude/test_command`; Codex reads the worktree's trusted Git-internal
`coderails/test_command`. Passing commands still allow the commit. Failing
commands deny it and return the run identity, byte/line measurements, full log
path and a quoted reader command. An unknown platform output budget does not
justify an automatically selected tail or byte cap.

Every run, including passing and empty-output runs, captures combined stdout and
stderr bytes unchanged in a unique directory:
`~/.coderails/test-output/<provider>/<project-command-hash>/<run-id>/output.log`.
Completed logs rotate to `output.log.gz` automatically; active logs stay untouched.
Compression preserves all captured bytes, and the reader transparently handles it.
The sibling `run.json` records the run identity, provider, project, command,
exit status and measurements. `CODERAILS_TEST_OUTPUT_DIR` overrides the storage
root. A 1 GiB compressed-log budget applies across that storage root by default; set
`CODERAILS_TEST_LOG_BUDGET_BYTES` to choose another byte budget. Oldest completed
logs expire first. Active runs, logs being completed or read, and the cleanup
caller's current run are protected. File locks release automatically if a process
exits; later cleanup can expire previously protected completed logs. Therefore
retained content can exceed the budget; `run.json` records
`retention.remaining_compressed_bytes` and `retention.over_budget`.
Compact run metadata, retrieval metrics and delivery observations persist
separately, together with `retention.json` expiry records when log content is
removed. The budget governs compressed logs, not these records or active raw
output. A metadata-only notification does not itself mean the log is empty or
expired.
An expired log read fails explicitly; its retained metadata remains available
in `run.json`, request records and `retention.json`.

One canonical helper is copied byte-for-byte into each independent provider
installation. Use the helper from the same installation as the hook. In this source
checkout it is `hooks/scripts/test_output.py` for Claude and
`packages/codex/hooks/scripts/test_output.py` for Codex. Replace the quoted run
directory below with the directory reported by the denial. The examples use
the Claude helper; substitute the Codex path when appropriate.

```sh
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --all
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --start 2 --end 12
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --search "AssertionError" --before 3 --after 5
python3 hooks/scripts/test_output.py read "/path/to/run-directory"
```

Line ranges are one-based and inclusive. Search is literal, with caller-chosen
context; it does not guess a framework's failure syntax. Full, range and search
reads return JSON with the text, selected source ranges, source/text byte
measurements, omitted line count and `policy_truncated: false`. Intentional
selection can omit content without policy truncation. Decoding for JSON text
can change its byte count, especially for invalid UTF-8; the captured bytes in
the retained log remain authoritative until retention expires its content.

Without selection flags, the reader always returns metadata and request
guidance only, including after earlier explicit reads. Adaptation is the
agent's demand-driven expansion of requests: inspect a literal match, request
more context, or read everything as needed. There is no automatic prediction
from prior runs' line positions, which can change between runs. Compact
measurements make retrieval auditable; neither fewer requests nor absence of
follow-ups proves diagnostic sufficiency or an optimal policy.

Each reader request writes a unique compact record of its selection,
requested and returned measurements, and emitted response bytes, without
duplicating the selected log text in the record. Emission is not proof
that a model received those bytes: delivery starts as unknown. To attach an
actual downstream observation to the exact request record, use:

```sh
python3 hooks/scripts/test_output.py observe "/path/to/request-file" --delivered-bytes 420 --truncated yes --source "reported tool transport observation"
```

Replace the example measurements with observed values; do not infer them from
file size or reader success. Observations are stored separately from request
measurements. Reading `output.log` with `cat` or a file-read tool bypasses this
telemetry and is **unobserved**, not zero delivery. Failed retrievals do not
remove the retained log. Disposable local fixtures can exercise these hooks
and readers without installed provider accounts.

### Hook library files

| Module | Responsibility |
|---|---|
| `hooks/scripts/hook_common.py` | Bounded payload reads and native hook responses. `read_payload` fails open on host exhaustion (logged); `read_payload_strict` raises `HostResourceError` and is used only by the gates that deny on it (`action_authority_gate`, `destructive_bash_gate`, `enforce_pr_workflow`, `no_edit_on_main`). |
| `hooks/scripts/lib/agentic_loop_path.py` | Resolve the repository/session-owned loop state path. |
| `hooks/scripts/lib/hook_telemetry.py` | Content-free, fail-open JSONL hook telemetry (`hook_telemetry.jsonl`): exit cause, duration, open fds, native-signal children, `deny` vs `ok` cause (set by `deny()`). Byte-identical copy in `packages/codex/hooks/scripts/lib/`. |
| `hooks/scripts/lib/discipline_common.py` | Read native Claude transcript tools, final text and edited-file count. |
| `hooks/scripts/lib/loop_state_common.py` | Loop detection, ownership, atomic state update behind the `dir_lock` mkdir lock; live completion marker. |
| `hooks/scripts/lib/dir_lock.py` | Stdlib-only mkdir lock with owner pid and start time; steals a dead owner's lock atomically (see `docs/graph-alignment-measurement.md`, stale-lock policy). |
| `hooks/scripts/lib/loop_evals.py` | Frozen dispatch authority and checksum-bound neutral completion verdicts. |
| `hooks/scripts/lib/loop_completion.py`, `loop_proofs.py`, `loop_cost.py` | Independent work-unit, retrospective, observed proof execution and dated cost checks. |
| `hooks/scripts/lib/graph_executor.py` | Provider-local lock around the installed pure schema-3 semantic operations. |
| `hooks/scripts/lib/graph_dispatch.py` | Current native ownership envelopes, instruction-source plan, wave collection and completion artifact gates. |
| `hooks/scripts/lib/graph_evidence.py` | Actual parent requests/results, confined native transcript paths, child attribution and genuine harness notifications. |
| `hooks/scripts/lib/graph_evidence_bind.py`, `graph_evidence_revalidate.py` | Derive and revalidate all native child identities and attempts; reject caller provenance, reused children and echoed completion. |

The sole maintained pure semantics are `packages/graph-semantics/graph_semantics.py`.
The installer materializes exact copies into each provider. Each adapter retains
its own dispatch, transcript, lock and artifact behavior. There are no schema-2
readers or shell fallback writers. See
[execution-graph.md](../skills/agentic-loop/execution-graph.md) for native CLI
commands, whole-wave collection and retry/respawn rules. Graph IDs identify work;
provider-native labels identify workers. Explicit worker instructions travel in
the prompt. `work_units` remains independent of `graph.nodes`.

## Commands

Commands are slash commands invoked by Claude (or the user via `/coderails:<name>`). They encode workflow logic but are **advisory** — Claude must choose to invoke them. Unlike hooks, commands cannot self-enforce.

| Command | Description | Key dependencies |
|---|---|---|
| `/coderails:workflow` | Orchestrate the full feature workflow: `prep → code → push → review → merge → wiki-ingest → wiki-lint`. Two interactive pauses: the code/iterate loop, and final ship-it authorisation. | Delegates to all other commands; reads `workflow.config.yaml`; requires `pr-review-toolkit` plugin for the review stage |
| `/coderails:prep` | Create a safety branch, a feature/bug branch, and optionally a Jira ticket. | `git worktree`, Jira MCP (optional — skips if `config.jira` is null or no Jira MCP); reads `workflow.config.yaml` |
| `/coderails:push` | Stage, commit, push changes, and create a PR. Runs an engineering-principles pre-flight if `config.engineering_principles_paths` is set. | Shells out to `scripts/push.py`; requires a GitHub remote; reads `workflow.config.yaml` |
| `/coderails:post-review` | Post the SHA-bound review artifact as a GitHub PR comment. Validates the review summary structure, then posts a machine-marked comment. The `/merge` gate requires this artifact for the current head SHA — fail-closed. | Shells out to `scripts/post_review.py`; runs the Python review marker CLI; uses `gh api` (not `gh pr comment`) to capture the returned comment URL; best-effort cache write to `progress.json` if it exists |
| `/coderails:post-evals` | Validate and post the SHA-bound eval-artifact summary as a GitHub PR comment. Consumes the `evals.json` produced by `/coderails:task-evals` for this PR, computes `GO`/`NO-GO` (never hand-written), and posts a machine-marked comment. The `/merge` gate requires this artifact for the current head SHA — fail-closed, additive to the review-artifact gate. | Shells out to `scripts/post_evals.py`; runs the Python eval marker CLI |
| `/coderails:authorize` | User-typed only (`disable-model-invocation: true`): pre-executes `scripts/authority.py grant --session ${CLAUDE_SESSION_ID} ...`, writing an expiring, revocable authority object with `granted_by: command`. The phrase "crack on" no longer grants anything; it only prints this command. Cooperating-agent safeguard: an agent with shell access can also run `authority.py grant`. | Shells out to `scripts/authority.py`; merge approval stays mandatory |
| `/coderails:merge` | Merge an approved PR, switch to main, and pull latest. Requires a coderails review artifact AND a coderails eval artifact on the PR for the current head SHA before merging, and — where the repo config activates it (`wiki_debt_epoch_pr` + `wiki_path`) — a wiki-ingest debt check (`has_wiki_ingest_for_merged_prs`) that greps the wiki vault's `origin/main` for coverage of every PR merged after the epoch. | Shells out to `scripts/merge.py`; requires GitHub remote; checks PR approval if branch protection is on; fetches live PR comments for both the review-artifact gate and the eval-artifact gate |
| `/coderails:init` | Scaffold or migrate a `workflow.config.yaml` for the current project. Writes to `$(pwd)/.coderails/` (resolved by walk-up — see Config resolution). | `git rev-parse`, Write tool; confirms before overwriting |
| `/coderails:test-gate-setup` | Configure the test gate for the current project. Detects the test runner (npm, cargo, pytest, go test, etc.) and writes `.claude/test_command`. | Write tool; opt-in gate for `test_gate.py` hook |
| `/coderails:assumptions` | List every assumption currently being made (task, codebase, environment, state), marked `(verified)` or `(inferred)`. Pure inventory — does no other work. | None |
| `/coderails:disconfirm` | Argue against the most recent recommendation — find the strongest case it is wrong. Steelmans the opposition. | None |
| `/coderails:cite-check` (skill at `skills/cite-check/`, not a `commands/` file) | Re-derive a specific claim from durable sources only (file contents, git output, fresh command output). No recall, no inference. Runs `context: fork` into `coderails:source-auditor` with `background: false`, so the audit has no access to the conversation that produced the claim — verifying inside that context would be self-verification. Named `cite-check` rather than `verify` because `/verify` is a Claude Code bundled skill and a same-named project skill would override it. | `coderails:source-auditor` agent |
| `/coderails:notchecked` | Review recent responses and list every non-trivial claim that was NOT verified. Surface gaps ruthlessly. | None |

### Config resolution (`workflow`, `prep`, and `push`) and init scope

Command frontmatter runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`.
The same `config_path(start_dir)` implementation is imported by workflow gates:
walk toward the Git root, choose the nearest `.coderails/workflow.config.yaml`,
and emit `NO_CONFIG` when absent. No legacy runtime fallback or config merging
occurs. Init validates preserved configuration before moving legacy files to
Trash; it never silently overwrites user values.

### Workflow config keys

`config.schema.json` (repo root, mirrored at `packages/codex/config.schema.json`) is the source of truth for
`.coderails/workflow.config.yaml`. `load_config(path)` in `scripts/lib/config.py` applies the defaults, coerces
types and returns reason-coded findings (`config_unknown_key` with a did-you-mean hint, `config_bad_type`,
`config_unreadable`). Guarded actions reject an invalid config; other readers report findings. The parser supports
the documented one-level mapping, nested fields, and scalar forms. It is a bounded grammar, not full YAML 1.2.
Quote a number or Boolean word when a string value is required. `python3 scripts/lib/config.py resolve-config --json` prints
`{path, values, defaults_applied, unknown_keys, findings}`; plain `resolve-config` is unchanged. Status says who
reads a key: `enforced_by_code`, `read_by_prose_only` (skills and commands read it from the resolve-config text,
no script does) or `unused`. Regenerate the table with `python3 scripts/lib/config_schema_docs.py --write`.

<!-- config-schema:start -->
| Key | Type | Default | Control ON value | Status | Description |
|---|---|---|---|---|---|
| `project` | string/null | `null` | - | read_by_prose_only | Project name written by /coderails:init; read by command prose only. |
| `wiki_path` | string/null | `null` | - | enforced_by_code | LLM wiki vault directory (relative to the project dir, or absolute). null disables the wiki gate and the wiki-debt merge gate. |
| `wiki_stale_days` | integer | `30` | - | enforced_by_code | Age in days after which a wiki page becomes a staleness candidate; scripts/wiki_lint.py stale reads it. Without comparable repo sources, an old candidate is stale on a date-only basis. |
| `wiki_supervision` | string/null | `"discuss"` | - | read_by_prose_only | wiki-ingest mode: discuss (pause before writing) or autonomous. |
| `wiki_git_worktree` | boolean/null | `true` | - | read_by_prose_only | true = PR flow for wiki commits; false = commit directly to the vault. |
| `wiki_git_bypass_flag` | string/null | `null` | - | read_by_prose_only | Env var set when creating or merging the wiki's own PRs, for example BYPASS_REVIEW=1. |
| `wiki_git_pull_path` | string/null | `null` | - | read_by_prose_only | Source repo pulled after a wiki PR merges. |
| `wiki_debt_epoch_pr` | integer | `null` | - | enforced_by_code | First PR number the wiki-ingest debt merge gate covers. An absent key disables the gate; an empty or null value is invalid. |
| `worktree_base` | string/null | `null` | - | read_by_prose_only | Parent directory for sibling worktrees. |
| `worktree_script` | string/null | `null` | - | read_by_prose_only | Project script that creates a worktree. |
| `jira` | object/null | `null` | - | read_by_prose_only | Jira settings (project, epic, component_name, component_id, epic_field, points_field, fix_version, mcp_namespace, transitions). Nested keys are not type-checked. |
| `engineering_principles_paths` | array/null | `null` | - | read_by_prose_only | Glob patterns that trigger the engineering-principles pre-flight in /coderails:push. |
| `engineering_principles_skill` | string/null | `"/engineering-principles-python"` | - | read_by_prose_only | Slash command run by the pre-flight; null skips it. |
| `sandbox_workers` | boolean/null | `true` | `true` | enforced_by_code | Default ON. Claude graph_dispatch.plan() reports sandboxed or in-process-fallback:<reason> for U3 nodes, and the Claude worker launcher consumes that mode. Codex native workers inherit the parent session sandbox; this setting does not configure or prove per-worker Codex containment. |
| `subagent_identity_gate` | string | `"on"` | `"on"` | enforced_by_code | on (default) denies an untyped Bash subagent in a graph-bound Claude session; off disables that hook. |
| `action_authority` | string/null | `"off"` | `"advisory"` | enforced_by_code | Absent = off; the shipped workflow uses advisory. Explicit enforce requires a signed receipt for guarded merges and pushes. Invalid values are rejected by strict config consumers. |
| `diff_manifest` | string/null | `"enforce"` | `"enforce"` | enforced_by_code | Diff-manifest publication gate for push.py, merge.py and direct-merge hooks. Default enforce uses the shipped policy; invalid values are rejected by strict config consumers. |
| `review_passes` | string | `"enforce"` | - | enforced_by_code | Required-reviewer check in the publication gate (policy/review_policy.json): off skips it; enforce (default) and any other value apply it. |
| `eval_level` | string | `"enforce"` | - | enforced_by_code | Derived-eval-level and suite-integrity check in the publication gate (policy/surface_policy.json): off skips it; enforce (default) and any other value apply it. |
| `diff_manifest_policy` | string/null | `null` | - | enforced_by_code | Path to the diff-manifest policy JSON; null or absent uses policy/diff-policy.default.json. |
| `integrity_review` | object/null | `null` | - | enforced_by_code | Integrity attestation settings. |
| `integrity_review.enabled` | boolean/null | `false` | - | enforced_by_code | true = local merge checks require the exact-head GitHub Actions integrity-review status after the server rule is live. |
| `integrity_review.machine_user` | string/null | `null` | - | enforced_by_code | Deprecated. A non-empty legacy login remains the required local status author until enabled is true. |
| `evals` | object/null | `{"require_signatures": true}` | - | enforced_by_code | Eval settings. |
| `evals.require_signatures` | boolean/null | `true` | `true` | enforced_by_code | true (default) = eval artifacts must be signed; the local key is created on first use, and signing refuses when ssh-keygen is unavailable. false opts out. |
| `memory` | object/null | `null` | - | enforced_by_code | Typed-memory settings. |
| `memory.backend` | string/null | `"muninn"` | - | enforced_by_code | muninn (default) = Muninn is the authoritative typed-memory store and a missing or refusing Muninn fails with a reason code; off = no typed memory at all (reason memory_backend_off, traced, Markdown is never read or written). Any other value fails with memory_backend_invalid. |
<!-- config-schema:end -->

## Scripts and Libraries

| Entrypoint/module | Responsibility |
|---|---|
| `scripts/push.py`, `merge.py` | Explicit staging/commit/PR workflow and current-head review, eval, integrity and wiki-debt merge gates. |
| `scripts/post_review.py`, `post_evals.py` | Review grammar/cache, structural eval validation, neutral grading and observed smoke execution. |
| `scripts/lib/git_common.py` | GitHub repository/PR operations and newest trusted exact-head artifact selection. Requires a `github.com` remote. |
| `scripts/lib/{config,review_artifact,eval_artifact,artifact_io}.py` | Shared root-provider config and structured artifact operations. |
| `scripts/lib/memory_adapter.py` (+ byte-identical `packages/codex/scripts/lib/` mirrors of it, `memory_cite.py`, `memory_reasons.py`, `memory_schema.py`), `memory_counters.py` | Authoritative typed-memory adapter over the `muninn` CLI (subprocess only; never imported, muninn needs py3.12). `add\|list\|render\|probe`. Config `memory.backend: muninn\|off` (default `muninn`): `off` is the only no-Muninn mode (`memory_backend_off`, traced); an invalid value is `memory_backend_invalid`. `probe()` checks the backend, muninn on PATH, the Part A help flags, the store schema (`memory_schema.check`, never `--version`) and one read smoke. `add()` returns `Written(id='K<n>')` or a reason-coded `Degraded` (exit 3); a muninn refusal (rc 2) is `refused_<code>`. Cites must anchor in a user prompt (`memory_cite`: `quote_only` 12-300 chars, or `approved_reply` via `--approval REF`), else `cite_not_user`. `list` with `--query` uses `muninn search --all-projects` filtered to `loop:<id>`. Reason codes and fixes: `memory_reasons.REASONS`, mirrored in `docs/RUNBOOK.md`. There is no Markdown fallback; `render --write PATH` only replaces an absent or marker-stamped file. `memory_counters.memory_counts` counts `memory./decision./order./lesson./proof./retro./teardown./handoff.` trace rows (`rows`, `by_reason_code`, `by_command`). Limits (orchestrator-only writes, user-anchored cites, cooperating-agent boundary): `docs/decisions/2026-10-05-memory-authoritative.md`. The Codex copy cannot trace (no `trace_row.py` ships there); it fails open. |
| `scripts/lib/decision_record.py` (+ byte-identical `packages/codex/scripts/lib/` mirror) | Typed, hash-chained loop decisions; the only writer of `decisions_absorbed`. `add_decision` (pure), `verify_chain`, `sync_row` (Muninn `kind=decision`, `scope=loop`, tag `run-<loop_id[:28]>`, `confidence=inferred`, cite = a quote of `authorising_prompt_raw` or a caller `cite_quote`), `mark_synced`, `record` and `flush_pending`. Entry point section below. Limits: cooperating-agent safeguard, last-row deletion undetectable, a short prompt like "yes" degrades visibly. Reasons: `decision_*` in `memory_reasons.REASONS`. |
| `scripts/lib/{eval_validation,eval_execution}.py` | Eval criteria and command/control verification. Gate smoke runs in a detached worktree at the trusted SHA. |
| `scripts/sandbox/spawn_sandboxed_worker.py` | Guard dispatch before scratch allocation; run a separate Claude process through pinned srt and retain its exit status. |
| `scripts/sandbox/{render_settings,sandbox_probe}.py` | Render explicit write containment and discriminate allowed versus forbidden filesystem writes. |
| `.github/workflows/integrity-review.yml`, `scripts/integrity-gate/integrity_actions.py` | Trusted GitHub Actions review/eval/diff check. It uses the built-in token and runs no PR code. |
| `scripts/integrity-gate/setup.py` | Preview and activate the GitHub Actions source-bound ruleset after a live candidate status. |
| `install.py`, `uninstall.py` | Independent provider installation/removal with preserved user data, preflight checks and read-only dry-run. |
| `launchd/*_routines.py`, `*_dashboard_agent.py` | Literal-path launch agent installation and verified unload/removal. |
| `scripts/quality/check.py` | Strict source, format, typing, size and generated-materialization checks. |
| `hooks/scripts/tests/run_all.py` | Native Python suite discovery with explicit skips and all-skipped failure. |

## Artifact and State Locations

| Artifact | Location | Committed? | Notes |
|---|---|---|---|
| `workflow.config.yaml` | first `.coderails/workflow.config.yaml` found walking from cwd up to git root (`$(pwd)/.coderails/` for `/init`) | No — local project setup, ignored by Git | Project-specific config for jira, wiki, worktree, engineering-principles, and sandbox workers. Created or migrated by `/coderails:init`; share its values through your normal project configuration process. |
| `.claude/test_command` | Project working directory | Yes (project-local) | Plain-text file containing the test command. Created by `/coderails:test-gate-setup`. Activates `test_gate.py`. |
| Codex `coderails/test_command` | Worktree Git metadata, resolved by `git rev-parse --git-path coderails/test_command` | No | Trusted native Codex test-gate command; a workspace file cannot configure it. |
| Test-gate runs and reader records | `~/.coderails/test-output/` or `CODERAILS_TEST_OUTPUT_DIR` | No | Completed logs automatically rotate and compress; active logs stay untouched. Run metadata, retrieval records and reported delivery observations persist separately. |
| Specs from brainstorming | Session-local scratch path (`docs/coderails/specs/` is gitignored) | No — ephemeral, never tracked | Written by `superpowers:brainstorming` after design resolution. Owner decision 2026-07-11: use `coderails:handoff` or a wiki page for a durable record instead. |
| Plans from writing-plans | Session-local scratch path (`docs/coderails/plans/` is gitignored) | No — ephemeral, never tracked | Written by `superpowers:writing-plans`. Same owner decision, 2026-07-11. |
| Agentic loop `progress.json` | `~/.coderails/agentic-loop/<repo-or-cwd-slug>/<session_id>/progress.json` | No — ephemeral loop state, outside the repo | Dynamic position tracker for the loop. Path computed by `agentic_loop_path.py` — keyed to the repo (shared across its worktrees) when cwd is inside a git repo, falling back to cwd otherwise. Session-keyed. When the canonical slug has no file, the helper probes `<base>/*/<session_id>/progress.json` so state written under a different slug (older helper version, mid-loop cwd drift) is still found by session_id. |
| Agentic loop `spec.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by the agentic-loop orchestrator for ≥3-unit loops. Not a PR deliverable. |
| Agentic loop `plan.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by `superpowers:writing-plans` as invoked by the agentic-loop. Consumed, not write-only: the orchestrator re-reads it after compaction to recover scope. |
| `evals.json` (pr scope) | Working material only — no fixed path; wherever the invoking workflow placed it (e.g. current working tree or a path named in the worker prompt) | No — the durable artifact is the SHA-bound `coderails-eval-summary` PR comment, not this file | Generated and frozen per PR; validated and posted by `/coderails:post-evals` via `scripts/post_evals.py` + `scripts/lib/eval_artifact.py`. |
| `evals.json` (loop scope) | Same dir as `progress.json` | No — ephemeral loop state | Read by the `loop_state_guard.py` hook when `progress.json`'s `work_units` ≥ 1; blocks `Stop` if absent. |
| Discipline log | `~/.claude/discipline.log` (or `$CLAUDE_DISCIPLINE_LOG`) | No | Structured `key=value` log appended by hooks on every fire. Never committed. |
| LLM Wiki vault | `config.wiki_path` (set in `workflow.config.yaml`) | Separate repo/vault | Maintained by `wiki-ingest`, `wiki-lint`, `wiki-query`. Browsed in Obsidian. |

### The ephemeral vs committed boundary

The loop's `spec.md`, `plan.md`, and `progress.json` live in `~/.coderails/agentic-loop/` — **outside** the code repo and Claude's configuration tree. They are loop state keyed to this orchestrator run, not shareable design records. If work needs handing to a human, `coderails:handoff` is the right tool. Durable records belong in the wiki or an explicitly authorized repository document, not these session-local scratch files.

### Record-decision entry point

Both provider graph CLIs call `decision_record.record` through their native state locks:

```text
graph.py record-decision <progress.json> --session <id> --loop-id <loop-id> --revision <revision> --phase <phase> --decision <text> [--flip-condition <text>] [--unit <id>] [--cite-quote <verbatim user quote>]
graph.py flush-decisions <progress.json> --session <id> [--cite-quote <verbatim user quote>]
```

Read the current `loop_id` and `revision` from `progress.json` before each call. Use these commands for decisions;
never append rows to `progress.json` by hand. `record-decision` checks the caller's loop ID and revision under the
graph lock. It verifies the existing hash chain before appending. `flush-decisions` verifies it before retrying
pending or degraded rows.

Order: (1) under the lock the local row is appended (`seq`, `prev_sha256`, `row_sha256`, `muninn: {state: syncing}`);
(2) outside the lock Muninn is written; (3) under the lock again the row's `muninn` field is patched. Return
`{recorded, seq, muninn: {state, id, reason_code}, exit_code}`; exit 0 written or disabled, 3 degraded or unknown (loud reason
code, trace `decision.sync/degraded/<code>`, local row kept), 2 refused (wrong session, loop, or revision, or blank phase or decision: nothing
written). Teardown runs `flush-decisions` to retry pending and safely degraded rows. An in-flight or uncertain sync
returns `decision_sync_unknown` and must be reconciled against Muninn before any manual retry. Trace commands: `decision.record`,
`decision.sync` (counted by `memory_counters.memory_counts`).
