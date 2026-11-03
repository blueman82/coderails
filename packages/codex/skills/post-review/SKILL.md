---
name: post-review
description: Post a fail-closed, SHA-bound GitHub PR artifact from a completed review by spawned Codex custom agents.
---

# Post review

Create the durable review comment consumed by the Coderails merge gate.

## Input gate

Require an explicitly supplied PR number. Inspect it before using it in any command: it must be non-empty and contain digits only. The script validates it again in code (`pr_number_invalid`) before any network call; never paste a non-numeric value into a command.

## Native Codex review evidence

Resolve the PR's current `headRefOid`. Run guarded reviewers through `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role <role> --prompt-file <file> --cwd <exact-head-worktree>` per [guarded role sessions](../using-coderails/references/guarded-role-sessions.md); use `spawn_agent` for other installed Codex custom reviewers. Wait for every reviewer. Use only their observed findings; never invent or silently omit a finding.

Stop without posting when:

- no Codex reviewer completed successfully;
- any reviewer result is missing or ambiguous;
- the PR head changes before posting; or
- findings were fixed after the review, making the review stale. Review the new head first.

The merge gate computes which reviews the diff needs from `policy/review_policy.json`: a diff touching `hooks/`, `scripts/`, `install.py`, `uninstall.py`, `.claude-plugin/` or the Codex hook/script trees needs a `security-review` pass (spawn `security-reviewer`); `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/` or `skills/dashboard/runner/` needs a `deploy-safety` pass (spawn `deploy-safety-reviewer`). A pass verdict is derived from the validated summary text (a bullet under `## Critical` fails it), never asserted.

Record the reviewer-reported counts. Write one summary file per pass. If a reviewer reports no findings, its file must contain only:

```markdown
## No findings
```

Otherwise, use these headings in order, with at least one bullet or `None` under each:

```markdown
## Critical
None

## Important
- Observed finding.

## Suggestions
None
```

Keep the reviewer names and exact critical, important, and suggestion counts in the posting report. Do not add them to a no-findings body because the validator's no-findings form is intentionally exact.

## Package helper

Resolve [post_review.py](../../scripts/post_review.py) relative to this `SKILL.md`, never relative to the repository working directory. It must exist and load. Stop if it is missing or fails; do not substitute another helper or build the marker by hand.

## Post

Write the summary files with the file-writing tool (not a shell heredoc), then run the one command, replacing `<PR>` with the validated number:

```bash
python3 <resolved post_review.py> post <PR> --summary <review-summary-file> --compat-count <COUNT> --disposition <CHOICE> --pass security-review=<security-summary-file>
```

Omit `--pass NAME=FILE` for passes the diff does not need. Set `COUNT` to the reviewer's count of retained compatibility code findings; use `0` only when no such finding exists. Set `CHOICE` to the registered work-unit choice (`clean-break` or `preserve-compat`). The script validates the files, binds all lines to the current head, and posts two comments: a review-passes record that also carries the compatibility choice, then a server compatible summary. It checks the head before and after each post. A failed second post can leave the first comment; a retry completes the pair. For `stale`, review the new head before posting again. The merge gate refuses a missing compatibility line or `clean-break` with a positive count.

The GitHub PR comment is authoritative. Do not read or write local review caches.

Report the PR number, reviewed SHA, spawned reviewer names and counts, and the posted comment URL.

## Standalone wiki security applicability

The shipped path policy stays in force. Only `security-review` can use the typed
`not_applicable` result for `standalone_wiki_prose_v1`. `review-pr` must pass.
Other required specialists must pass. A plain NOT APPLICABLE message is not a pass.

Use the same resolved helper as the posting command:

```bash
python3 <resolved post_review.py> na-scope <PR>
python3 <resolved post_review.py> validate <security-summary-file> --pass-name security-review
```

`na-scope` prints the current binding and complete inventory. It supplies no inspection or authority.
Give this data and approved source context to `security-reviewer`. The role's structured
`## Not applicable` JSON form records repository purpose, complete consumer references,
base/head blobs, base-change assessments, a complete assessment and no unresolved items.
Do not convert this result into `## No findings`. Post it with the ordinary general summary:
`post <PR> --summary <general-file> --pass security-review=<security-summary-file>`.

The writer and publication gate independently read the actual remote base branch tip,
unique merge base and head. Every affected entry must match between merge base and live base.
Both rename names, deletion sources, added-path absence, blobs, types and modes count.
Only nonempty A/M/D/R ordinary `100644` Markdown inventories qualify. Control files,
plugin command manifests and security matches outside root hooks/commands collisions refuse.
Known unchanged code and settings need consumer assessment too. Consumer base changes need
an explicit assessment. Missing objects, unresolved context and moved bindings refuse.
A stale scope needs a new complete inspection. The writer checks before/after each post and reuse.
The same shared publication gate checks merge helpers and direct publication hooks.

Old readers reject this result. Keep installation on HOLD until the merged release passes
[Check a release candidate](../../../../docs/RELEASE-CANDIDATE.md) and
[Installing coderails](../../../../INSTALLATION.md), using paths relative to the release checkout.
Select explicit new provider versions and matching manifest/marketplace metadata.
Stop new graph work and drain affected sessions with their owners. Preserve old runtime,
state/config/eval/proof/retro/Muninn backups with hashes. Unknown quiescence keeps the HOLD.
Use `release_manifest.py snapshot`, both maintained installer dry runs, then those installers.
Start new sessions; complete Codex `/hooks` trust. Verify explicit installed paths with
`release_manifest.py verify` and `installed_parity.py --require-both`; check allowed/refused routes.
Do not copy helper files into an active version. A new inspection must use both the new writer
and reader. Preserve old runtime/state together for rollback; these checks do not prove all
installed behavior or bytecode authenticity. No current wiki pass or install follows from this change.
