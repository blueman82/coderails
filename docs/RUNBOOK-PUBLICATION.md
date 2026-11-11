# Publication gate recovery

[Runbook](RUNBOOK.md).

## Diff-manifest check warned or refused

A graph unit that runs `push.py --unit N --progress PATH` must have a nonempty manifest.
Before the first push of a stacked branch, set `--base-branch <parent>` with `graph.py add-unit`.
After a PR opens, its live base must agree with the recorded branch.
The check compares the Git index paths and the full PR diff with the manifest before transport. It checks the two paths for a rename.

Give an absolute worktree path with `add-unit --worktree`.
After checkout setup, an unassigned unit can use `assign-worktree --session S --loop-id L --unit N --worktree ABS_PATH`.
The command holds the graph lock and can fill an unassigned pending unit while a wave is active.
It keeps the revision and refuses a different assignment. At push time, the recorded path must equal the Git checkout root.
Git reports index paths with NUL delimiters so non-ASCII names keep their literal values.

- Symptom: `push.py`, `merge.py`, or direct `gh pr merge` refuses with `diff_manifest:<code>`.
  Stderr gives `! diff_manifest <code>: <path>`. Merge through `gh` uses Claude `enforce_pr_workflow` or Codex `pr_publication_gate`.
  The default is `diff_manifest: enforce` with `policy/diff-policy.default.json`, with or without a config file.
  Set `off` to disable or `advisory` for warnings.

  The diagnostic reader `scripts/diff_manifest.py [--policy FILE]` reports unreadable input with exit 0.
  Publication callers refuse unreadable input in `enforce` mode.

- Query: In `trace.by_reason`, read `diff-manifest/ok/diff_manifest_ok` and `diff-manifest/warned|refused/<code>`.
  These entries use `<repo>@<branch>` or `<repo>@pr-<N>`. The single publication gate logs `publication/refused/diff_manifest:<code>` for each refused path.
  The advisory mode alone can give `diff-manifest/failed_open/manifest_unreadable`.

  The gate also writes `diff-manifest/legacy/manifest_legacy_absent` for a policy file without a manifest key.
  Check `diff-manifest/refused/foreign_session` for a different session.
  Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`.
  The `manifest_counters.py` tool counts only `diff-manifest`. See `docs/workflow-gates-measurement.md`.

- Codes: `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`, and `special_file_type`.
  The `special_file_type` code covers a type change, symlink, or gitlink.
  Other codes are `mode_change`, `status_not_allowed` (policy `statuses`), `too_many_paths` (policy `max_paths`), `manifest_unreadable`, and `manifest_internal_error`.
  An unknown mode gives `diff_manifest_mode_invalid` and uses `enforce`.

- Remediation: If the diff exceeds its declared scope, keep the refused unit and history.
  Remove changes external to the manifest from the publication through the usual worktree workflow.
  The `add-unit` command adds a new ID only. It cannot change a manifest for a unit that exists.
  The `assign-worktree` command can attach a pending unit only to its first checkout or the same recorded path.
  It uses the current manifest. It cannot widen that manifest or repair an active assignment.

  If only the assigned checkout is unavailable, put it back at the recorded path without changing the binding.
  If the necessary binding or scope cannot be put back, keep publication on HOLD. Keep loop data, proofs, and dispatch history.
  A different manifest must use its own checked plan and source registration for a new graph.
  This procedure does not migrate the refused unit or move its authority and proof results.

  Do not add hashes by hand, set status again, or use `convert` to repair source binding.
  The `push.py` and `merge.py --unit N --progress PATH` commands bind publication to the recorded manifest.
  The `manifest_unreadable` code means the reader could not read policy, `progress.json`, the diff, or the PR head. Correct the path or head lookup.
  The `enforce` mode refuses this condition. The `advisory` mode alone can continue on error.

  The `manifest_internal_error` code refuses in `enforce`. The `advisory` mode logs `failed_open` and continues. This includes a repo metadata lookup error.
  Set `diff_manifest: off` to disable. An incorrect or empty mode uses `enforce` and reports `diff_manifest_mode_invalid`.

  A null policy value selects the default from the plugin. The config parser also changes an empty nullable scalar to null.

- Limits: This is a cooperating-agent safeguard. An agent with the same user ID can set the config to `off`.
  Publication hooks see only merges that `guarded_segments` can recognize. Codex hooks use `/hooks` trust.
  Claude checks the manifest without a config or transcript. Its inspection and eval sequence uses the two.

### Protected paths and publication bindings

The `mode_change` code refuses a chmod from 100644 to 100755.
The default denylist uses these secret name patterns: `.env*`, `*.pem`, `*.key`, `*.p12`, and `credentials*.json`. It also uses `.npmrc`, `.netrc`, `.git-credentials`, and `id_rsa|dsa|ecdsa|ed25519*`.
The list also includes the gate's `.coderails/workflow.config.yaml`, `policy/diff-policy*.json`, and the Codex copy.

The gate refuses edits or deletions of its own files. It lets a PR remove a secret-shaped path. It cannot find a secret with a different name.
The gate reads config and policy from the local checkout. The checks do not stop someone who controls that checkout.

A call with only `--unit` or only `--progress` gives `manifest_unreadable`.
Use a flag with a space or use `--unit=N` and `--progress=PATH`. Empty or duplicate values cause a refusal.
The named unit must have a record and a string-list `manifest`. The absolute `worktree` path must resolve to the Git repository root.
The `progress.json` object must have nonempty strings in `session_id` and `loop_id`.

Missing, malformed, or incorrect metadata gives `manifest_unreadable`.
Before transport, `push.py` gives `publication:graph_owner_missing` if an owner field is empty or missing.
That refusal logs `publication/refused/graph_owner_missing` to the publication session.

A missing, relative, or different checkout gives `publication:worktree_invalid` and a corresponding log entry.
A PR base that differs from the recorded base gives `publication:base_mismatch`.
Index or branch paths external to the manifest give `diff_manifest:out_of_manifest`.
These refusals log `publication/refused/<code>` before the policy gate runs. The `trace.by_reason` field counts them.

A `manifest: []` value refuses publication. A session that owns a graph unit in this worktree must give the two flags.
Without a corresponding graph unit, standalone publication uses only the policy.
The unit and policy manifests apply together, so a unit cannot widen the policy. Custom policies keep the default denylist.
An unreadable config gives `manifest_internal_error` and logs a refusal.

Publication hooks use `scripts/lib/merge_target.py` to parse the target. The parser skips flag values and resolves URLs and branches through gh.
The `-R/--repo` flag, a URL for a different repo, multiple targets, or an unknown branch give `pr_number_invalid`.
The `GH_REPO` override gives `pr_repo_override`.

A merge in the same call as `gh pr edit` or `gh api .../pulls/N` gives `pr_base_mutation`.
Make the edit in its own call so the next check reads the new base.

The diff uses the PR's live `baseRefOid` and checked head. The local default branch does not select the base.
The `merge.py` command accepts one number, URL, or branch. It pins all checks and merge to the same head with `--match-head-commit`.
A hook cannot pin the agent's direct `gh pr merge`. A push or base change can occur after the hook check and before merge.

Unit metadata checks structure and worktree. It does not authenticate the publisher.
An agent with the same user ID can forge owner fields for that worktree. The gate does not compare a worker's session with its parent's.
The manifest check does not see raw Git operations or aliases it cannot resolve.

## Required review passes refused a merge

- Symptom: `merge.py` or direct `gh pr merge` refuses with `required_review_missing:<name>` or `required_review_failed:<name>`.
  Other codes are `review_passes_malformed`, `review_artifact_missing`, and `review_policy_unreadable`.
  Merge through `gh` uses Claude `enforce_pr_workflow` or Codex `pr_publication_gate`.

The check is second in `scripts/lib/publication_gate.py`. It defaults to ON without a config.
The names come only from `policy/review_policy.json`. The diff uses live `baseRefOid` and the checked head. It checks the two names of a rename.

- `review-pr` is always mandatory.
- `security-review` applies to `hooks/`, `scripts/`, `install.py`, `uninstall.py`, `.claude-plugin/`, `packages/codex/hooks/`, and `packages/codex/scripts/`.
  It also applies to control files: `policy/`, `capabilities/`, `agents/`, `commands/`, `AGENTS.md`, `workflow.config.yaml`, and `.coderails/`.
  The Codex copies and Codex post-review and merge skills are in scope.
- `deploy-safety` applies to `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/`, and `skills/dashboard/runner/`.

The `review_passes: off` setting skips this check. No value or a different value applies it. The `diff_manifest: off` setting does not change it.
Removal or damage to the policy file gives `review_policy_unreadable`.

### Comment pair

The `post_review.py post <PR> --summary FILE [--pass NAME=FILE ...]` command posts two comments for one head.
The first has the v1 marker, a pass list, an optional compat-findings line, and inspection text.
The pass list has the name, verdict, blocking value, and summary hash for each pass.
The second has the same v1 marker, optional compat-findings line, and general inspection text.

The current server integrity check reads the second comment. The local gate accepts the pair only if the comments are adjacent and the general inspection text agrees.
The script derives each verdict from the text. An issue in `## Critical` makes the pass fail.
A pass list must include `review-pr` with a verdict bound to its summary.

A legacy single comment without a pass list can satisfy `review-pr` for a docs-only diff if its `## Critical` section is clean.
After a pass list comment exists for the head, a missing, malformed, or stale second comment gives `review_passes_malformed`.

- Query: Read `trace.by_reason` for `review-passes/ok/review_passes_ok`, `review-passes/refused/<code>`, and `publication/refused/<code>`.
  Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`.

- Remediation: Run the missing reviewer. The two providers ship `security-reviewer` and `deploy-safety-reviewer`.
  Write its results to a file in the post-review grammar. Run `post_review.py post` again with `--pass NAME=FILE`.
  For a `failed` pass, correct the issue in `## Critical` and post again for the new head.
  The `review_artifact_missing` code also includes a trusted comment fetch error. Check identity, permissions, comments, or `gh auth`, then retry.

- Limits: The gate derives the hash and verdict again from the posted sections.
  A different hash or verdict gives `review_passes_malformed`. A hand-posted pass list without the text is refused.

  A pass shows that a summary was posted for the name. It does not prove authorship or inspection quality.
  The `post_review.py` command accepts a file for each pass, so the PR author can self-issue `## No findings` for `security-review` or `deploy-safety`.
  The same user can write the summary. This is a cooperating-agent safeguard.

  The gate derives `blocking` and does not use it to waive a mandatory pass.
  The Codex hook sees only merges that `guarded_segments` can recognize. It uses `/hooks` trust.
  Row 9 of the closure matrix uses a `.json` policy file. The matrix is external to this repo.

### Standalone wiki security applicability

The path policy from the plugin stays in force. Only `security-review` can use `not_applicable` for `standalone_wiki_prose_v3`.
The `review-pr` pass and other mandatory specialist passes must succeed. A plain NOT APPLICABLE message does not count.

Use the same resolved helper as the posting command:

```bash
python3 <resolved post_review.py> na-scope <PR>
python3 <resolved post_review.py> validate <security-summary-file> --pass-name security-review
```

The `na-scope` command gives compact current binding, authored inventory, and full context metadata. It supplies no inspection or authority.
Context includes all tracked non-tree paths at merge base, live base, and head other than authored page endpoints.
Include unchanged Markdown and assets. File names cannot prove that a file has no effect. Equal path and entry facts can share explicit tree membership tags.

Give this data and approved source context to `security-reviewer`.
Its structured `## Not applicable` JSON document records repository purpose, the full context digest, and explicit path groups for the inspection.
Each context path must occur in one group. Do not skip or duplicate paths. Do not add paths from elsewhere or use glob selectors.

A group must contain only unchanged base entries or only changed base entries. Changed base entries must have inspection text.
The digest uses the immutable mode, type, and blob facts from the three trees. Keep `complete=true` and `unresolved=[]`.

Version 3 uses `effect_state` in `consumer_scope` and each group. Its values are `effect_free`, `active`, and `unknown`.
The initial value is `unknown`. The full scope and each group must explicitly declare `effect_free` for N/A.

Use `active` for known execution, access-control, or instruction-loading effects.
Those effects must have an ordinary inspection, with or without full coverage and `unresolved=[]`.
Unknown, missing, malformed, and other values cause a refusal.

The full declaration includes repository purpose, all authored operations, and all facts at merge base, live base, and head.
It also includes the effects of authored operations from merge base to head in combination with live-base context and group interactions.
Each group covers its members at the three trees and their role in that combination.
Do not infer `effect_free` from suffixes, modes, unchanged files, or an empty unresolved list.

The gate refuses version 1 and 2 records. Do not add affirmative declarations automatically.
Do not change this result to `## No findings`. Post it with the ordinary general summary:
`post <PR> --summary <general-file> --pass security-review=<security-summary-file>`.

The writer and publication gate each read the head of the remote base branch, the unique merge base, and the head.
Each affected entry must be the same at merge base and live base.
The check includes the two names of a rename, deletion sources, confirmation that the base has none of the added paths, blobs, types, and modes.

Only nonempty A/M/D/R inventories of ordinary `100644` Markdown files qualify.
Control files, plugin command manifests, and matches to `security-review` rules other than `hooks/**` and `commands/**` cause refusal.
Examine known unchanged code, pages, data, and settings. Unknown context causes refusal.

Full path coverage binds the statement to Git objects. It cannot prove the statements are correct or identify the reviewer.
The helper batches tree and blob reads without a child call for each context path.

The complete comment must fit 65536 characters. Compact data for inspection must fit 131072 bytes.
Each limit includes all serialized data. Refuse oversized output. Do not truncate it or raise the cap.

Missing objects, unresolved context, or moved bindings cause refusal. Stale scope must have a new complete inspection.
The writer checks before and after each post and before use again. Merge helpers and direct publication hooks use the same publication gate.

Previous readers reject this result. Keep installation on HOLD until the merged release passes [the installation checks](../INSTALLATION.md).
Use paths relative to the release checkout. Select the new provider versions and matching manifest and marketplace metadata explicitly.

Stop new graph work and drain affected sessions with their owners. Keep previous runtime, data, config, eval, proof, retro, and Muninn copies with hashes.
If you cannot prove that affected sessions have stopped, keep the HOLD.

Use `release_manifest.py snapshot` and the two installer dry runs. Then use those installers.
Start new sessions and complete Codex `/hooks` trust.
Check explicit installed paths with `release_manifest.py verify` and `installed_parity.py --require-both`. Check paths that accept and refuse operations.

Do not copy helper files into an active version. A new inspection must use the new writer and reader.
Keep the previous runtime and its data together for rollback. These checks cannot prove all installed behavior or bytecode authenticity.
This change does not give a current wiki pass or installation.

The finite path list cannot prove that prose external to the list has no effect.
Scope checks compare the record with selected objects. They cannot prove substantive inspection or reviewer independence.
A same-user author can write an inspection. The GitHub status reads the ordinary companion only and does not validate scope.

For `required_review_not_applicable_invalid:security-review`, get a new applicable inspection or complete eligible scope.
Do not make an inspection pass without the inspection.

## Eval level or suite integrity refused a merge

The third check in the publication gate defaults to ON. Set `eval_level: off` to disable it.
The `post_evals.py post`, `merge.py`, or direct `gh pr merge` command can refuse. Merge through `gh` uses Claude `enforce_pr_workflow` or Codex `pr_publication_gate`.

Codes include `level_below_derived`, `late_freeze_unstamped`, `suite_hash_mismatch`, `suite_hash_marker_mismatch`, `chain_broken`, `chain_truncated`, and `integrity_stripped`.
Other codes are `not_frozen`, `eval_facts_missing`, `eval_artifact_missing`, `eval_artifact_unreadable`, `eval_embed_malformed`, `eval_head_mismatch`, `eval_result_mismatch`, and `eval_level_diff_unavailable`.

The `scripts/lib/eval_level.py` code applies `policy/surface_policy.json` to the diff from live `baseRefOid` to the checked head.
An unavailable PR base gives a refusal and cannot show that freeze happened on time.

- Level 2 applies to an irreversible path or to three work units. Examples are `install.py`, `launchd/`, `.github/workflows/`, and `hooks/hooks.json`.
- Level 1 applies to an outward path such as `hooks/`, `scripts/`, or `skills/`, or to two units.
- Level 0 applies when the other conditions do not apply. Only anchored docs and test directories are neutral.
  Unlisted paths such as `AGENTS.md` and `.claude-plugin/` are outward.

### Eval artifact

Line 1 is the unchanged v1 marker. Line 2 is `<!-- coderails-eval-facts v1 derived_min_level=N late_freeze=0|1 suite=<16 hex> -->`.
The summary and fenced embed follow. The `post_evals.py post <PR> <evals.json> [--progress PROGRESS]` command stamps `gate_facts` in the embed.

The merge check does not use the stamped level. It calculates the floor from the live diff, declared `facts`, posted `gate_facts`, and optional `--unit N --progress PATH`.
The declared and posted facts supply minimum values. A hook without `--progress` uses the posted count.
The displayed minimum in the facts line is informational at merge.

The check compares the late-freeze flag and suite hash with the embedded suite. The marker and embedded levels must agree.
The selected suite must name the current head. Each P0 must satisfy the same neutral GO rule that posting uses.
A correct frozen hash or signature cannot establish the current head or status.

Read `trace.by_reason` for `eval-level/ok/eval_level_ok`, `eval-level/refused/<code>`, and `publication/refused/<code>`.
Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py` to tally them.

### Eval refusal procedures

- For `level_below_derived`, write a suite at the derived level, smoke-run it, and post it again.
  The level is part of the suite hash. An edit after freeze gives `suite_hash_mismatch`.
- For `suite_hash_mismatch` after an intentional oracle edit, run `post_evals.py amend <evals.json> <eval_id> <reason> <actor>`. Then post again.
- For `late_freeze_unstamped` or `eval_facts_missing`, post again with the current `post_evals.py post`.
  An artifact from the previous procedure has no facts line, so the gate refuses it for outward diffs.
- The `eval_artifact_unreadable` code means the reader could not fetch the trusted comment. Check identity, permissions, comments, or `gh auth`, then retry.
- The `not_frozen` code also refuses a missing, abbreviated, or symbolic `frozen_sha` at level 1 or 2 on all merge paths.
  A late stamp cannot satisfy the full 40-hex commit condition.

- The `eval_head_mismatch` code means the selected suite has no head or has a stale head.
  The `eval_result_mismatch` code means the P0 statuses contradict GO.
  Correct the head or verification records, run and grade the evals again, and post with `post_evals.py post <PR> <evals.json>`.
  Eval-level and publication counters report the two codes.

A saved version 1 suite has unverifiable freeze timing. This applies if its SHA resolves before the branch base.

Version 2 binds `frozen_sha` and `frozen_at` in its signed hash.
If the freeze SHA is late or missing, use a copy. Set `CODERAILS_KEYS_DIR` to the saved signing directory.
Run `post_evals.py amend <copy> <eval_id> 'frozen_sha <40-hex SHA> frozen_at <ISO8601> timing=late' <actor>`.
For version 1, use `timing=unverifiable`. The explanation must use that token and bind the two fields.

Posting and merge check the signed change. Plain `freeze_disclosure` or justification does not clear the refusal.
Grade and post the copy.

### Eval trust limits

This is a cooperating-agent safeguard. The diff cannot give the work-unit count.
Without `--progress` or a declared lower bound, the check uses one unit. The PR author can publish without `--progress`.

The `verify_suite` check finds an edit if the suite hash or chain does not agree.
The suite hash and chain are unkeyed and signatures are optional. The same user can edit a command, calculate `frozen_hash` and `suite_hash` again, and post with `gh api`.
The embed has no binding to the hash recorded at smoke-run. See `skills/task-evals/SKILL.md`.

The `late_freeze` flag is an attestation. An empty, abbreviated, or rev-expression `frozen_sha` counts as late. A level-0 suite can have no `frozen_sha`.
Level 1 or higher uses a full 40-hex SHA. The check cannot prove that the supplied SHA is the freeze commit.

For version 1 or a late or unresolved version 2 SHA, the timing check accepts only a signed change that it can validate. The SHA, timestamp, and timing token must agree.

Surface classes use globs. Irreversible wins, then docs and tests at paths with root anchors (`none`). All other paths are outward (level 1).

A new control directory is outward by default. An entry is necessary only if it is irreversible.
The policy, `eval_level.py`, and `publication_gate.py` are irreversible. An edit to them gives level 2.

The gate reads those files from the checkout that runs the command. Run `merge.py` from `main`.
The gate trusts the authenticated comment author with write permission. It does not check the content.
The `eval_level: off` setting skips the check and logs `eval-level/skipped/eval_level_off`. No value or a different value applies the check.
