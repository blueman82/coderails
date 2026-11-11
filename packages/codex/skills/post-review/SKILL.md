---
name: post-review
description: Post a fail-closed, SHA-bound GitHub PR artifact from a completed review by spawned Codex custom agents.
---

# Post review

Post the durable PR comment that the Coderails merge gate reads.

## Input gate

The user must explicitly supply a PR number. Before you use it in a command, check that it has one or more digits and no other characters.
The script checks the value again before network access. An invalid value gives `pr_number_invalid`.
Do not put a non-numeric value into a command.

## Native Codex review evidence

Get the PR's current `headRefOid`. Follow [guarded role sessions](../using-coderails/references/guarded-role-sessions.md).
For guarded reviewers, use `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role <role> --prompt-file <file> --cwd <exact-head-worktree>`.
Use `spawn_agent` for other installed Codex custom reviewers.

Wait for each reviewer. Use only the results they gave. Do not invent results or silently leave one out.

Stop without posting if one of these conditions holds:

- No Codex reviewer completed with success.
- A reviewer's result is unavailable or ambiguous.
- The PR head changes before you post.
- You corrected results after the reviewers examined the head. Examine the new head before you post.

The merge gate uses `policy/review_policy.json` to select the checks from the diff:

- Start `security-reviewer` for the mandatory `security-review` pass.
  This applies to `hooks/`, `scripts/`, `install.py`, `uninstall.py`, `.claude-plugin/`, and the Codex hook and script trees.
- `deploy-safety` is mandatory for `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/`, or `skills/dashboard/runner/`. Start `deploy-safety-reviewer`.

The gate derives the verdict from the validated summary. A bullet in `## Critical` gives a negative verdict. Do not assert the verdict by hand.

Record the counts that the reviewer gives. Write one summary file for each pass.
If a reviewer gives no results, its file must contain only:

```markdown
## No findings
```

If it gives results, use the headings below in this sequence. Give a minimum of one bullet or `None` for each heading:

```markdown
## Critical
None

## Important
- Result from the reviewer.

## Suggestions
None
```

Give the reviewer names and counts for `Critical`, `Important`, and `Suggestions` in the posting report.
Do not add names or counts to the no-results body. The validator checks its literal text.

## Package helper

Find [post_review.py](../../scripts/post_review.py) relative to this `SKILL.md`.
Do not resolve it from the repository working directory.
Stop if the file is unavailable, cannot load, or does not work. Do not use a different helper or write the marker by hand.

## Post

Use the file-writing tool for the summary files. Do not use a shell heredoc.
Run the command below. Replace `<PR>` with the validated number:

```bash
python3 <resolved post_review.py> post <PR> --summary <review-summary-file> --compat-count <COUNT> --disposition <CHOICE> --pass security-review=<security-summary-file>
```

Use `--pass NAME=FILE` only for passes the diff needs.
Set `COUNT` to the reviewer's count of retained compatibility code results. Use `0` only if there are no such results.
Set `CHOICE` to the registered work-unit selection (`clean-break` or `preserve-compat`).

The script validates the files and binds all lines to the current head.
It posts a record of the passes with the compatibility selection, then a server-compatible summary.
It checks the head before and after each post.
If the second post does not succeed, the first comment can stay on the PR. A retry completes the pair.

For `stale`, examine the new head before posting again.
The merge gate refuses a missing compatibility line or `clean-break` with a positive count.

The GitHub PR comment is authoritative. Do not read or write local reviewer caches.

Report the PR number, the SHA the reviewers examined, their names and counts, and the posted comment URL.

## Standalone wiki security applicability

The shipped path policy stays in effect. Only `security-review` can use the typed `not_applicable` result for `standalone_wiki_prose_v3`.
The `review-pr` pass and other mandatory specialists must succeed.
A plain NOT APPLICABLE message does not satisfy the gate.

Use the same resolved helper as the posting command:

```bash
python3 <resolved post_review.py> na-scope <PR>
python3 <resolved post_review.py> validate <security-summary-file> --pass-name security-review
```

`na-scope` prints the compact current binding, authored inventory, and full context metadata.
It gives no inspection or authority.
Context includes all tracked non-tree paths at merge base, live base, and head, other than the authored page endpoints.
Include unchanged Markdown and assets. A filename cannot show that the file has no effect.
The same path and entry facts can share explicit tree-membership tags.

Give this data and approved source context to `security-reviewer`.
The role's structured `## Not applicable` JSON records repository purpose and the full context digest.
It also records explicit path groups in `references` with an `assessment` for each group.
Each context path must occur in one group.
Include all inventory paths one time each. Do not add other paths or use glob selectors.

A group can contain only unchanged base entries or only changed base entries.
A group with changed entries needs a non-empty `base_change_assessment`.
The digest includes immutable mode, type, and blob facts at all three trees.
Keep `complete=true` and `unresolved=[]`.

Version 3 needs `effect_state` at `consumer_scope` and in each group of paths.
The allowed values are `effect_free`, `active`, and `unknown`. The initial value is `unknown`.
N/A needs explicit `effect_free` at the two levels.

If there are known execution, access-control, or instruction-loading effects, use `active` and do the applicable inspection.
Do this if coverage is complete and `unresolved=[]` too.
The gate refuses `unknown`, missing, malformed, or other values.

The full declaration covers repository purpose, all authored operations, and all facts at merge base, live base, and head.
It also includes the authored merge-base-to-head operations together with live-base context and group interactions.
Each group covers its members at all three trees and their role in that combination.

Do not infer `effect_free` from suffixes, modes, unchanged files, or an empty unresolved list.
The gate refuses version 1 and 2 records. Do not automatically add affirmative declarations to them.
Do not change this result to `## No findings`.
Post it with the ordinary general summary:
`post <PR> --summary <general-file> --pass security-review=<security-summary-file>`.

The writer and publication gate independently read the actual remote base branch head, unique merge base, and PR head.
Each authored entry must have the same facts at merge base and live base.
Check the two rename names, deletion sources, blobs, types, and modes.
There must be no entry for an added path at merge base or live base.

The inventory must be non-empty and contain only A/M/D/R operations on ordinary Markdown files with mode `100644`.
The gate refuses control files and plugin command manifests.
Root `hooks/` and `commands/` collisions are the only permitted `security-review` path matches.
Examine known unchanged code, pages, data, and settings too. The gate refuses unknown context.

Full path coverage binds the statement to objects. It cannot prove semantic truth or reviewer identity.
The helper reads trees and blobs in batches. It does not run a command for each context path.

The complete last comment must fit in 65536 characters.
The compact `na-scope` output must fit in 131072 bytes. These limits count all serialized data.
Refuse oversized output. Do not truncate it or increase the limit.
The gate refuses missing objects, unresolved context, and moved bindings.

If the scope becomes stale, do a new full inspection.
The writer checks the binding before and after each post and each reuse.
The shared publication gate checks merge helpers and direct publication hooks.

Earlier readers reject this result. Keep installation on HOLD until release qualification is complete.
Use [Installing coderails](../../../../INSTALLATION.md) for the maintained installer options.
Resolve paths from the selected release checkout. That document alone does not qualify this change.
Select explicit new provider versions and matching manifest and marketplace metadata.

Stop new graph work. Drain affected sessions with their owners.
Keep copies of the earlier runtime, graph data, config, evals, proofs, retros, and Muninn. Record their hashes.
If you cannot confirm quiescence, keep the HOLD.
Run the two maintained previews from that checkout:

```bash
python3 install.py --dry-run
python3 install.py --provider codex --dry-run
```

The previews do not install or clear the HOLD.
Complete the expected-file and link inventories. Keep hashed copies of the runtime and graph data and check the coordinated restore procedure.
The maintained tools supply no release manifest or approved rollback procedure.
Keep installation on HOLD until release qualification supplies and checks these parts.

After the HOLD clears, use the maintained installers for the selected versions.
Start new sessions and complete Codex `/hooks` trust. Compare explicit installed roots:

```bash
python3 scripts/installed_parity.py --source-root /path/to/release-checkout --claude-installed /path/to/selected-claude-version --codex-installed /path/to/selected-codex-version
```

Replace all three paths with the selected directories. The helper compares existing installed regular files to source.
It skips symlinks and does not find missing expected source files.
It does not give a full installation inventory. Check the inputs the writer and reader accept and refuse.

Account-free checks are mandatory for the two providers.
For a Codex-only live release, record Claude live checks as not complete. A Claude account is optional for that scope.
Do not copy helper files into an active version. A new inspection must use the new writer and reader together.

Keep earlier runtime and graph data together for rollback. These checks cannot prove all installed behavior or bytecode authenticity.
This change does not authorize a current wiki pass or an install.
