# Runbook: hook and trace observability

Trace rows are NON-AUTHORITATIVE: fail-open, append-only, one `event_id` per event, written by
`hooks/scripts/lib/trace_row.py` to `<agentic-loop dir>/<session_id>/trace.jsonl` (the same per-session directory
`crack_on_gate.py` uses, with or without a loop). Rows hold `schema_version`, `event_id`, `session_id`, `loop_id`
(null outside a loop), `ts`, `command`, `outcome`, `reason_code` and sha256-hashed `inputs`. No gate decision
reads them. Counters dedupe by `event_id`, skip torn lines, and key tallies as `command/outcome/reason_code`.

Query every entry below with:

```
python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['trace'])"
```

## No trace rows appear

- Symptom: `trace.rows` is 0 although gates fired (`gate_blocks` counts are nonzero).
- Query: the command above; then `ls ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
- Remediation: the writer fails open, so an unwritable directory or an unsafe session id (contains `/` or `..`,
  or is empty) silently drops rows. Fix the directory permissions; do not make the gate depend on the write.

## Gate seems off (config key or wiki schema)

- Symptom: a configured gate (wiki taxonomy, wiki-debt, integrity, eval signing) does nothing, or a config key seems ignored.
- Query: `python3 scripts/lib/config.py resolve-config --json | jq .unknown_keys` (also `.findings`); counts via
  `python3 scripts/lib/config_counters.py` for `config_unknown_key`, `config_bad_type`, `config_unreadable`,
  `wiki_schema_missing`, `wiki_schema_invalid`, `wiki_schema_legacy` (scope with `--since 2026-10-05T00:00:00`; the same rows
  also appear in `measure_graph_alignment.py --json` under `trace.by_reason`; trace rows: `config/warned/<code>`, `wiki_taxonomy_gate/failed_open/<code>`).
- Remediation: fix the key (the finding carries a did-you-mean hint) or the value type; for `wiki_schema_*` restore or
  repair `wiki.schema.json` (`page_types` non-empty list of directory names). Both are fail-open by design: findings never
  change a gate's decision, and a stale AGENTS.md Page types table fails the build (`config_docs_drift_test.py`), not the hook. `wiki_schema_legacy` means a vault still has only
  `AGENTS-wiki-schema.md`: policing continues from its Page types table; add `wiki.schema.json` to retire the fallback.

## Discipline lint advisories climbing

- Symptom: `confidence_labels` or `verify_loop` advisories climb. These two hooks no longer block (demoted by user
  override, `docs/decisions/2026-10-04-not-in-gate-demotion.md`); the pre-demotion `blocked` series is history.
- Query: `trace.by_reason` for `check_confidence_labels/demoted/confidence_label_missing` and
  `check_verify_loop/demoted/verify_loop_missing` (keys are `command/outcome/reason_code`; `blocked` and `warned`
  rows are the older series and are separate); `gate_blocks.claude.gates.<gate>` for `demoted`/`would_block`.
  `blocked / decisions` now falls to about 0 by construction; compare `demoted / decisions` instead.
- Remediation: a rising `demoted` count means the model is skipping labels or DNV tags, not that a gate is stuck.
  Fix the prompt or instruction text; there is nothing to unblock.

## Reviewer/scout Bash command denied

- Symptom: a read-only reviewer or scout reports a denied Bash call.
- Query: `trace.by_reason` for `reviewer_bash_allowlist/denied/bash_allowlist_deny_<cause>`, cause one of `meta`
  (chaining/redirection), `flag` (dangerous or unknown rg flag), `parse` (bad quoting), `argv` (command not on the list).
  The discipline log line carries `agent_type`, `argv0` and a 12-char sha of the command.
- Remediation: rerun the inspection with a single allowlisted read-only command (no chaining, redirection or
  interpreters). If a legitimate command is missing, add its exact argv prefix to the allowlist with a test.

## Capability tool refused or denied

- Symptom: a reviewer/scout (usually `source-auditor` running `tests.run`) is refused a `scripts/capability.py` call.
- Query: `trace.by_reason` for `reviewer_bash_allowlist/denied/capability_denied_<tool>`,
  `capability_unknown_tool` or `capability_bad_argv` (hook side, one row per decision;
  `reviewer_bash_allowlist/allowed/capability_allowed_<tool>` counts grants), and `capability/refused/capability_*`
  (script side: `args_invalid`, `path_denied`, `bad_ref`, `no_repo`, `tests_unknown_name`, `sandbox_unavailable`, `io_error`). Narrow with
  `python3 scripts/measure_graph_alignment.py --root . --json | jq '.trace.by_reason | with_entries(select(.key|test("capability")))'`.
  Hook rows need a session id (payload `session_id`); script rows use env `CLAUDE_SESSION_ID` or `CODEX_THREAD_ID`
  (unverified that the harness sets it) and otherwise land under the `unattributed` session directory. `"traced": false`
  now means only that the trace library or disk failed; the hook also logs `denied=1 reason_code=...` to its log, so an empty query is not proof
  of no refusals.
- Remediation: `capability_denied_*` means the agent's profile lacks the tool; change `capabilities/profiles.json`
  deliberately (the validator test keeps frontmatter and Codex sandboxes in step), never widen Bash. `bad_argv` means
  the call was not exactly `<abs path>/scripts/capability.py <tool> --json-args '<json>'`; the path must be absolute.
  `tests_unknown_name` means the name is not in `profiles.json` `tests`.

## Authority object refused or changed

- Symptom: `authority.py` refuses a command, or an object disappeared.
- Query: `trace.by_reason` for `authority/created|narrowed|revoked` and `authority/refused/authority_refused_<cause>`, cause one of `exists`,
  `widen_scope`, `widen_max_prs`, `narrow_empty`, `not_revocable`, `missing`, `expired`, `malformed`, `invalid`,
  `create_invalid`, `write_failed`, `foreign` (an unsafe session id cannot be traced; stderr only).
- Remediation: inspect with `python3 scripts/authority.py inspect --session <exact id>`. A foreign-session refusal
  means the id did not match exactly; ids are never sanitised.

## Manifest says no loop, or the wrong loop

- Symptom: the SessionStart manifest shows `loop: none` or `loop: unknown` although a loop is running, or the
  session injected the static fallback.
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['context'])"`,
  or `jq 'select(.command|startswith("context_"))|.reason_code' ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
  Reason codes: `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`, `manifest_state_unreadable`,
  `manifest_payload_malformed`, `manifest_error`, `route_match`, `route_payload_malformed`, `route_none`
  (an unrouted prompt: no row is written). Events with a missing or unsafe session id are filed under
  `<loop dir>/_unattributed/trace.jsonl`.
- Remediation: `loop: none` for a foreign or unsafe session id is correct (ids match exactly, never sanitised). For
  `manifest_state_unreadable` repair progress.json; for `manifest_graph_invalid` run `graph.py inspect <state>`.
  Check `CLAUDE_AGENTIC_LOOP_DIR` (wins) versus `CODERAILS_AGENTIC_LOOP_DIR`. Routes are advisory text only.

## Crack-on denial wrong (stuck on, or off too early)

- Symptom: `AskUserQuestion` / `request_user_input` is denied when the user no longer wants autonomy, or is allowed
  right after "crack on".
- Query: `trace.by_reason` for `crack_on/granted/authority_granted`, `crack_on/blocked/authority_deny`,
  `crack_on/allowed/authority_expired_allow`, `crack_on/blocked/crack_on_legacy_flag`,
  `crack_on/ignored/authority_corrupt_ignored` (authority.json unparseable: treated as none; legacy flag still honoured),
  `crack_on/failed_open/authority_write_failed` (user said "crack on" but no authority was written, so nothing is
  suppressed; if the trace dir is also unwritable only the `stamped=0 err=write_failed` discipline.log line remains),
  `authority/refused/authority_refused_foreign`. Inspect with
  `python3 scripts/authority.py inspect --session <exact id>`.
- Remediation: revoke with `python3 scripts/authority.py revoke --session <id>` (also deletes any legacy flag). An old flag
  (`crack_on_legacy_flag`) is cleared with `rm <loop dir>/<id>/crack_on_active` (Codex:
  `$PLUGIN_DATA/sessions/<id>/crack_on_active`). Allowed right after "crack on": the phrase was quoted, backticked,
  negated or asked as a question (by design), or `authority_expired_allow` shows the 24h object lapsed; say "crack on" again to re-grant.
- Baseline note: the old 103 fires / 5 blocks figure (`docs/graph-alignment-measurement.md`) came from discipline-log
  telemetry; after-numbers come from trace rows, so they are not comparable. Reproduce:
  `python3 scripts/measure_graph_alignment.py --root . --json`.

## Memory silently using Markdown

- Symptom: retro lessons or handoffs never appear as typed records; `memory_adapter.py probe` exits 3.
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`
  (`by_reason_code`, deduped by `event_id`), or `grep '"command": "memory\.' <agentic-loop dir>/<session_id>/trace.jsonl`.
  Codes: `muninn_absent`, `muninn_old_ledger`, `muninn_timeout`, `muninn_error`, `uncited_write`, `restricted_refused`,
  `bad_record`, `handwritten_protected`. An unsafe session id writes no row; an unset or empty session id
  (CLI without `CLAUDE_SESSION_ID` or `--session`) writes rows under the fixed id `memory-adapter-nosession`.
- Remediation: `muninn_absent`/`muninn_old_ledger`: install a muninn release with the typed-ledger flags (Part A, muninn
  PR #9); the Markdown path keeps working meanwhile. `uncited_write`: pass `--cite` and a verbatim `--quote`.
  `handwritten_protected`: the target is hand-written; render to a new path. `muninn_timeout`: muninn hung past 10s;
  run `muninn know list` by hand and check ledger locks. `muninn_error`: muninn exited nonzero or returned unparseable
  JSON on add/list; run the same `muninn know ...` command by hand and read its stderr. `bad_record`: the typed record
  failed validation (type, scope, tag, date or missing loop id). A help probe that exits nonzero is reported as
  `muninn_old_ledger`, not `muninn_error`.

## Stop declared in text instead of recorded, or a stop released unexpectedly

- Symptom: the Stop hook releases or blocks a loop and the model says it recorded nothing; or `progress.json`
  `loop_stop_counts` disagrees with the declared turn category. Stops are model-written intent rows
  (`progress.stops[]`, written by `graph.py stop`); `loop_stop_counts` stays the hook-owned count of consumed stops.
- Query: `python3 scripts/graph_alignment_stops.py --json` gives `stops_recorded`, `stops_consumed`,
  `legacy_text_parse` (the hook fell back to the final-line text, trace `loop_stall_guard/fallback/legacy_text_parse`)
  and `legacy_log_parse` (absent-state grace fell back to the discipline.log regex because `hook_state.json` was
  missing or torn). Inspect one loop with `python3 -c "import json;print(json.load(open('<progress.json>')).get('stops'))"`.
- Remediation: a high `legacy_text_parse` against `stops_consumed` means agents are not running `graph.py stop`: fix
  the prompt, and if it persists tighten the text parse rather than retiring it. An unconsumed row at the current
  revision releases the next Stop once, and only when `graph.py stop` ran after the last user prompt (an older row is
  ignored with trace `stale_stop_row`, so recording a stop early cannot excuse later undeclared turns); a row at an older revision is ignored by design. A refused `graph.py stop`
  prints the refusal on stderr (foreign session, unknown category or reason code, `complete` while the graph is
  unresolved); fix the argument, never edit `stops` by hand. Codex records the same row but only a `hard-stop` row on a
  typed hard-stopped graph releases its guard (`consume-stop`); other categories are recorded and ignored there.

## Diff-manifest check warned or refused

- Symptom: `push.py`, `merge.py`, a direct `gh pr merge` (Claude `enforce_pr_workflow`, Codex `pr_publication_gate`)
  refuses with `diff_manifest:<code>` and prints `! diff_manifest <code>: <path>` on stderr. The check is ON by default
  (`diff_manifest: enforce`, no config file needed, shipped policy `policy/diff-policy.default.json`); `off` and
  `advisory` (warn only) are the explicit switches. `scripts/diff_manifest.py [--policy FILE]` is a diagnostic verdict
  reader: it reports unreadable inputs with exit 0; the publication callers refuse them under enforce.
- Query: `trace.by_reason` for `diff-manifest/ok/diff_manifest_ok`, `diff-manifest/warned|refused/<code>` (rows are keyed by
  `<repo>@<branch>` or `<repo>@pr-<N>`), `publication/refused/diff_manifest:<code>` (one row per refusal from the single
  publication gate, every path), plus `diff-manifest/failed_open/manifest_unreadable` (advisory only),
  `diff-manifest/legacy/manifest_legacy_absent` (policy file without a manifest key; also written by the gate) and `diff-manifest/refused/foreign_session`. Tally them with
  `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`
  (`manifest_counters.py` still tallies only `diff-manifest`). See `docs/workflow-gates-measurement.md`.
- Codes: `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`, `special_file_type` (type change, symlink or gitlink), `mode_change`, `status_not_allowed` (policy `statuses`), `too_many_paths` (policy `max_paths`), `manifest_unreadable`, `manifest_internal_error`, `diff_manifest_mode_invalid` (unknown mode, treated as enforce).
- Remediation: a real violation means the diff left its declared scope; fix the diff, or widen `unit.manifest`
  (re-register with `add-unit --manifest`) or the policy file on purpose. `push.py`/`merge.py --unit N --progress PATH`
  bound the diff to that unit's manifest. `manifest_unreadable` means the policy file, progress.json or diff (or an
  unresolved PR head) could not be read: it refuses under enforce (fails open only under advisory); fix the path.
  `manifest_internal_error` refuses under enforce; advisory records `failed_open` and continues, including when repository
  metadata lookup fails. Set `diff_manifest: off` to disable. Invalid modes, including an empty mode, enforce and report
  `diff_manifest_mode_invalid`. A null policy value selects the shipped default; the typed config grammar also coerces
  an empty nullable scalar to null.
- Limits: a cooperating-agent safeguard. A same-user agent can edit the config to `off`; the Codex hook only sees merges
  `guarded_segments` can match; Codex hooks need `/hooks` trust before they run; Claude's direct arm needs a
  `workflow.config.yaml` in the repo.
- Hardening notes: `mode_change` refuses a chmod (100644 to 100755). The default denylist is best-effort secret shapes
  (`.env*`, `*.pem`, `*.key`, `*.p12`, `credentials*.json`, `.npmrc`, `.netrc`, `.git-credentials`, `id_rsa|dsa|ecdsa|ed25519*`)
  and the gate's own files (`.coderails/workflow.config.yaml`, `policy/diff-policy*.json`, the Codex copy), so a PR that
  edits them is refused; deleting a denied path is not. It cannot catch a secret under another name. The gate reads config
  and policy from the local checkout: a same-user boundary, not a defence against someone who controls that checkout.
  `--unit` without `--progress` (or the reverse) refuses `manifest_unreadable`. Both separated and `--unit=N`/`--progress=PATH`
  forms are supported; empty or repeated flag values refuse. A requested unit must exist and carry a string-list `manifest`
  and a nonblank absolute `worktree` whose real path equals the current Git repository root. The progress object must carry
  nonblank string `session_id` and `loop_id` fields. Missing, malformed or mismatched metadata refuses `manifest_unreadable`;
  `manifest: []` allows no changed paths. With no paired flags, standalone publication uses the policy alone. Unit and policy
  manifests both apply, so a unit cannot widen policy scope. Custom policies retain the default denylist. An unreadable config
  refuses `manifest_internal_error` and emits its refusal trace. Direct-merge hooks parse
  the target with `scripts/lib/merge_target.py` (flag values skipped, URL and branch resolved through gh); `-R/--repo`, another
  repo's URL, multiple targets or an unknown branch deny `pr_number_invalid`. `merge.py` accepts one number, URL or branch
  and pins all gates and the merge to the same head
  with `--match-head-commit`; a hook
  cannot pin the agent's own `gh pr merge`, so a push between the hook check and that merge is a known gap. Unit metadata
  is a shape and worktree check, not publisher authentication: a same-user actor can forge owner fields for the same
  worktree. It does not compare a worker's session with its parent's. Claude's direct arm also requires a readable transcript;
  `NO_CONFIG`, raw Git operations and unseen aliases remain outside this manifest arm.

## Required review passes refused a merge

- Symptom: `merge.py`, a direct `gh pr merge` (Claude `enforce_pr_workflow`, Codex `pr_publication_gate`) refuses with
  `required_review_missing:<name>`, `required_review_failed:<name>`, `review_passes_malformed`,
  `review_artifact_missing` or `review_policy_unreadable`. The check is the second entry of the single publication gate
  (`scripts/lib/publication_gate.py`), ON by default with no config. The required names come only from
  `policy/review_policy.json` (`review-pr` always; `security-review` for `hooks/`, `scripts/`, `install.py`,
  `uninstall.py`, `.claude-plugin/`, `packages/codex/hooks/`, `packages/codex/scripts/`, and the control files
  `policy/`, `capabilities/`, `agents/`, `commands/`, `AGENTS.md`, `workflow.config.yaml`, `.coderails/`, their Codex
  copies and the Codex post-review/merge skills; `deploy-safety` for `launchd/`,
  `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/`, `skills/dashboard/runner/`), matched against
  the PR diff (renames count both sides). Config `review_passes: off` skips the check (absent or any other value
  enforces; `diff_manifest: off` does not touch it). The policy file is the control, and deleting or corrupting it
  refuses (`review_policy_unreadable`), it does not allow.
- Artifact: line 1 is the unchanged v1 marker; line 2 is `<!-- coderails-review-passes v1 {"head_sha":...,"passes":[...]} -->`
  with `{name, verdict, blocking, summary_sha256}` per pass. `post_review.py post <PR> --summary FILE [--pass NAME=FILE ...]`
  validates each summary, derives each verdict from the text (a bullet under `## Critical` is `fail`) and posts it. A v1
  artifact with no passes line counts as no passes: `review-pr` is satisfied by the marker, but a `hooks/` PR is refused
  until it is re-posted. A passes line naming another `head_sha` is ignored.
- Query: `trace.by_reason` for `review-passes/ok/review_passes_ok` and `review-passes/refused/<code>`, plus
  `publication/refused/<code>`. Tally with `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`.
- Remediation: spawn the missing reviewer (`security-reviewer`, `deploy-safety-reviewer`; both providers ship them),
  write its findings to a file in the post-review grammar, re-run `post_review.py post` with `--pass NAME=FILE`. A
  `failed` pass needs the Critical finding fixed and the artifact re-posted for the new head. `review_artifact_missing`
  also covers a failed trusted-comment fetch (identity, permission, comments): retry or check `gh auth`.
- Limits: the gate re-derives each pass from the posted sections (hash and verdict; a mismatch is
  `review_passes_malformed`), so a hand-posted passes line without its text is refused. A pass still proves only that a
  summary was posted for that name, not that a reviewer wrote it or that the review was substantive: `post_review.py`
  takes any file for any pass, so the PR author can self-issue a `## No findings` security-review or deploy-safety
  pass. The same user can write any summary, so this is a cooperating-agent safeguard. `blocking` is derived and never waives a
  required pass. The Codex hook only sees merges `guarded_segments` can match and needs `/hooks` trust. Row-9 wording in
  the closure matrix (`.json` policy file) is not recorded in this repo: the matrix lives outside it.

## Eval level or suite integrity refused a merge

- Symptom: `post_evals.py post`, `merge.py`, a direct `gh pr merge` (Claude `enforce_pr_workflow`, Codex
  `pr_publication_gate`) refuses with `level_below_derived`, `late_freeze_unstamped`, `suite_hash_mismatch`,
  `suite_hash_marker_mismatch`, `chain_broken`, `chain_truncated`, `integrity_stripped`, `not_frozen`,
  `eval_facts_missing`, `eval_artifact_missing`, `eval_artifact_unreadable`, `eval_embed_malformed`,
  `eval_head_mismatch`, `eval_result_mismatch` or `eval_level_diff_unavailable`.
  The check is the third entry of the single publication gate, ON by default (config
  `eval_level: off` is the optional switch). The minimum level comes from `policy/surface_policy.json` applied to the PR diff
  (`scripts/lib/eval_level.py`): level 2 for an irreversible path (`install.py`, `launchd/`, `.github/workflows/`,
  `hooks/hooks.json`, ...) or three work units, level 1 for any outward path (`hooks/`, `scripts/`, `skills/`, ...) or two
  units, else 0; only the anchored docs and test directories are neutral, every unlisted path (`AGENTS.md`, `.claude-plugin/`, ...) is outward.
- Artifact: line 1 is the unchanged v1 marker, line 2 is `<!-- coderails-eval-facts v1 derived_min_level=N
  late_freeze=0|1 suite=<16 hex> -->`, then the summary and the fenced embed whose `gate_facts` block is stamped by
  `post_evals.py post <PR> <evals.json> [--progress PROGRESS]`. The merge side ignores the stamped level and recomputes it
  from the live diff, the embed's declared `facts` and posted `gate_facts` (lower bounds), and the optional
  `--unit N --progress PATH` flags of `merge.py`. Omitting progress on a direct hook call cannot erase a posted count.
  The facts-line displayed minimum is informational at merge; the enforced floor is recomputed. The late-freeze
  flag and suite hash are checked against the embedded suite, and the marker and embedded levels must agree.
  The selected suite must name the current PR head and every P0 must pass under the same neutral GO rule used
  by posting; a valid frozen hash or signature does not establish those volatile head/status fields.
- Query: `trace.by_reason` for `eval-level/ok/eval_level_ok` and `eval-level/refused/<code>`, plus
  `publication/refused/<code>`. Tally with `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`.
- Remediation: `level_below_derived` means the suite was frozen at a lower level than the diff needs; write a suite at the
  derived level (the level is part of the suite hash, so editing it after the freeze is `suite_hash_mismatch`), smoke-run
  it and re-post. `suite_hash_mismatch` after an intentional oracle edit: `post_evals.py amend <evals.json> <eval_id>
  <reason> <actor>`, then re-post. `late_freeze_unstamped`/`eval_facts_missing`: re-post with the current
  `post_evals.py post` (an artifact posted by the old recipe has no facts line and is refused for outward diffs).
  `eval_artifact_unreadable` is a failed trusted-comment fetch (identity, permission, comments): retry or check `gh auth`.
  `not_frozen` also rejects a missing, abbreviated or symbolic `frozen_sha` at level 1 or 2 on every merge route;
  stamping it late does not satisfy the full 40-hex commit requirement.
  `eval_head_mismatch` means the selected suite's head is absent or stale; `eval_result_mismatch` means its P0
  statuses contradict GO. Correct the head/evidence, rerun and regrade the evals, then re-post with
  `post_evals.py post <PR> <evals.json>`; the existing eval-level and publication trace rows/counters expose both codes.
- Limits: a cooperating-agent safeguard. The work-unit count of a diff cannot be derived from the diff, so the floor
  without `--progress` (and without a declared lower bound) assumes one unit; the PR author can omit the progress file.
  `verify_suite` is tamper-evident, not tamper-proof: the suite hash and amendment chain are unkeyed and a signature is
  optional, so a same-user agent can recompute `frozen_hash`/`suite_hash` after editing a cmd and post it with `gh api`;
  nothing ties the embed to the hash recorded at smoke-run time (see `skills/task-evals/SKILL.md`). Only a naive edit is
  caught. `late_freeze` is attestation, not evidence: an empty, abbreviated or rev-expression `frozen_sha` counts as late
  (a level-0 suite may omit it) and level >= 1 needs a full 40-hex sha, but an honest-looking real sha cannot be proven to
  be the freeze commit, and the
  disclosure requirement is a substring match for "freeze"/"frozen" in the justification or an amendment `why`. The surface
  classes are globs: irreversible wins, then the anchored docs and test directories (`none`), and every other path is
  outward (level 1), so a new control directory needs no entry to be covered, only an irreversible one does. The policy and
  `eval_level.py`/`publication_gate.py` are themselves irreversible (editing them forces level 2), but they are read from the
  running checkout, so run `merge.py` from main, not from the PR branch. The gate trusts the posted comment's author (the
  authenticated, write-permission login), not the content. Config `eval_level: off` skips the check (absent or any other
  value enforces) and records `eval-level/skipped/eval_level_off`.

## Commit, push or ceiling gate behaves differently than the text suggests (argv classifier)

- Symptom: `test_gate` did not run (or ran) for a `git commit`; `destructive_bash_gate` denied or allowed a
  `--no-verify`/`-n` commit; `enforce_pr_workflow` / the Codex action hook missed a `git -C d push origin main`; the
  verification-volume ceiling denied the 3rd `run_all.py`, `test_codex_hooks.py` or `post_evals.py post|validate-structure`
  after a branch rename, or did not deny in a second repo; an edit on main was denied with `protected_paths_unreadable`.
- Mechanism: `hooks/scripts/lib/argv_match.py` (byte-identical Codex copy) splits the command on `; && || | & ( )` and
  newlines outside quotes, unwraps `env/sudo/command/exec/time/nohup/nice`, absolute paths and `bash -c '...'`, and
  recognises git by subcommand (global options `-C dir`, `-c k=v`, `--git-dir`, `--no-pager`, `-p` skipped; `-nm` decoded) and
  scripts by basename plus operation. Quoted text is one token, so `echo "git commit"` matches nothing. If shlex cannot
  parse (unbalanced quote) the classifier falls back to a whitespace split, which over-matches by design.
- Ceiling key: `sha1(realpath(git common dir) + realpath(toplevel))` plus the target, in
  `<loop dir>/verification-ceiling/` (Codex `$PLUGIN_DATA/verification-ceiling/`). A renamed branch keeps its count; a
  linked worktree or a second clone starts at zero. To reset, delete the one count file (the digest is printed in no
  message; compute it, or list the directory by mtime). The count is mirrored into `progress.json`
  `work_units[u].verification{run_all,post_evals}` when a unit's `worktree` equals the toplevel (no unit carries
  `worktree` until `add-unit --worktree` exists, so today only the file counter applies).
- `protected_paths_unreadable`: `policy/protected_paths.json` (both plugin copies) is missing, torn or ill-shaped, so
  `no_edit_on_main` and the in-Bash source-write check refuse every non-owner edit on main/master until it is repaired.
  Owner permission files stay denied on every branch. Keys: `source_extensions`, `plugin_source_globs`, `doc_extensions`,
  `doc_names`, `settings_files`. Adding `.rs` to `source_extensions` protects `sed -i x.rs` on main with no code change;
  `no_edit_on_main` treats every suffix not in `doc_extensions`/`doc_names` as protected already.
- Query: `trace.by_reason` for `argv/denied/ceiling_exceeded` and `argv/denied/protected_paths_unreadable`
  (`python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`).
  See `docs/workflow-gates-measurement.md`.
- Limits: still no shell parser. `eval`, `xargs`, aliases, shell functions, `$(...)` built at run time and scripts that
  themselves run `git commit` or `run_all.py` are not seen; `git commit --no-ver` style abbreviations of `--no-verify`
  and `--work-tree`-relative targets are not resolved. A cooperating-agent safeguard, not a barrier.

## Action-authority hook denied a merge or push (or warned in advisory)

- Symptom: `gh pr merge` or `git push` to main/master is denied with "needs an action receipt (<code>)" (enforce), or a
  stderr "action_authority (advisory)" warning appears. Only when config `action_authority` is `enforce` or `advisory`;
  absent or any other value is off.
- Query: `jq -r 'select(.command=="action_authority" or .command=="action_receipt") | [.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl`,
  or `trace.receipts.by_reason_code` from `python3 scripts/measure_graph_alignment.py --root . --json` (deduped by
  event_id). Codes: `denied_<code>` / `advisory_<code>` where `<code>` is one of `no_receipt`, `hash_mismatch`,
  `sha_mismatch`, `expired`, `revoked`, `consumed`, `foreign_session`, `foreign_loop`, `kind_mismatch`, `no_session` (payload had no session_id; traced under session dir `_no_session`), `malformed`;
  `receipt_consumed` (allowed); `action_authority_failed_open` (the hook itself errored and allowed);
  `receipt_approved` / `receipt_revoked` (CLI).
- `action_authority_failed_open`: the row carries `inputs.error_class` (sha256 of the exception class name; compare with
  `printf ZeroDivisionError | shasum -a 256`) and `loop_id` when known; the hook's stderr (hook log) prints
  `action_authority failed open: <Class>: <message>`. A session-less failure is traced under `_no_session`.
- Remediation: mint a receipt for the exact command:
  `python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge|git_push --command '<exact command>' --cwd <directory it runs in>`
  (receipts are single-use, 1h by default; `inspect-receipt` / `revoke-receipt` take `--receipt-id`). `hash_mismatch`
  means args, cwd or branch differ from the minted command. `foreign_session` can also mean a worker whose
  `session_id` differs from the minter's (unverified guess): mint under the session the hook reports. Or set
  `action_authority: off` in `.coderails/workflow.config.yaml`.
- Scope of one receipt: each guarded segment of a chained command (`a && b`) needs its own receipt; a leading
  `cd <dir>` moves the directory the hash binds (mint with `--cwd` set to where the command really runs). A receipt
  minted with `--artifact-sha` verifies only against the real HEAD (push) or PR head via `gh pr view` (merge, 4s
  timeout; unknowable means `sha_mismatch`, fail closed).
- Codex: the hook is vendored and parity-tested, but `scripts/action_receipt_cli.py` is NOT shipped in the Codex
  package; mint receipts from a coderails repo checkout (same session id) or leave `action_authority` off.
- Limits: a receipt binds approval to an exact action but does not prove a human approved it (a same-user agent can run
  `approve-action`). The hash covers only the command text the hook sees, not aliases, functions, eval/xargs or scripts that
  push (env/sudo/subshell/`bash -c`/`gh api .../merge` wrappers are unwrapped). Limits: scope 500 chars, 8 KB per receipt,
  50 receipts per session (`receipt_refused_scope_too_long`, `receipt_refused_too_many`). Protected branches are main and master only.
