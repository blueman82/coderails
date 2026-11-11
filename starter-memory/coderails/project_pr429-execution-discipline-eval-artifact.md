---
name: pr429-execution-discipline-eval-artifact
description: PR #429 execution-discipline rename and Bash worktree-detection fix, awaiting only the exact-head eval PR artifact.
type: project
---

# PR #429 Execution Discipline Eval Artifact

> Supersession note (2026-09-21): This is a historical PR #429 handoff. Posting or merging requires current authorization. `scripts/quality/check.py` and targeted Python tests supersede its Bash checker paths. Fetch the current PR head and artifact status only when a current task authorizes work on that PR. The pending artifact below is historical.

## Goal

Finish the clean-break rename of the `fable-mode` skill to `execution-discipline` and keep its behavior. Include the Bash quality-script repair that the user approved. Implementation and verification are complete. The last step is to post the frozen eval result as a SHA-bound PR artifact.

## Decisions

- Rename `fable-mode` to `execution-discipline`. Do not keep the previous name as an alias or compatibility path.
- Keep skill behavior. The change applies to the name and wording only.
- Do not add an alias or bump the plugin version.
- Include the Bash quality-script repair in PR #429 after the hook blocked the workflow. The user explicitly approved the repair in this PR. Use this handoff for the repair too.
- Do not bypass repository hooks or weaken the verification gates.
- Keep PR #429 unmerged at the user's direction. Merge requires explicit approval from the user.

## Constraints

- This session runs the earlier installed hook from the plugin cache. Its primary eval-ceremony counter reached its limit. The repository has a pushed commit with the command-worktree guard repair. It cannot update the installed cache during this session.
- Do not work around or bypass the earlier installed hook. Start a new session in the correct feature worktree to post the artifact through the usual path.
- Fetch PR #429 again and check the current head before validation or posting. Associate all records with that head. If its SHA changed, stop and examine the frozen eval input again.
- Use the `post-evals` skill to post the remaining artifact. Do not hand-post or hand-edit it.
- Keep the existing reviewer and eval results as records. Rerun the full set of checks only for a concrete need.

## Schema / Taxonomy

- Frozen eval file: `/tmp/coderails-execution-discipline-evals.json`
- Result from eval tooling: `GO`
- Verification level: `1`
- Frozen eval SHA-256: `413182ed904216782b846664a7d8bacb673038ca7076b4565640b923a2a7d0eb`
- Eval outcomes: E1, E2, E3, E4, and E5 independently pass.
- The PR has the reviewer artifact. It does not have the eval artifact.

## Key files

- `README.md` uses the new skill name in the user guide.
- `docs/REFERENCE.md` uses the new skill name.
- `skills/execution-discipline/SKILL.md`: root Claude plugin skill, renamed from `fable-mode` with behavior preserved.
- `packages/codex/skills/execution-discipline/SKILL.md`: native Codex plugin skill, renamed from `fable-mode` with behavior preserved.
- `scripts/quality/check.sh`: Bash fix for explicit feature-worktree branch detection after the hook block.
- `scripts/quality/tests/quality.test.sh`: regression coverage for the Bash fix.

## Branch and worktree

- Repository: `blueman82/coderails`
- PR: `#429` — https://github.com/blueman82/coderails/pull/429
- Base branch: `main`
- Git branch: `feature/execution-discipline`
- Worktree for the change: `/Users/garyharr/Github/coderails-execution-discipline`
- PR head at handoff: `7f432649df1c5014810471edadf980a184286339`

## Done so far

- PR #429 is open at https://github.com/blueman82/coderails/pull/429.
- At handoff, the head check gave `7f432649df1c5014810471edadf980a184286339`.
- Implementation tests passed.
- The command-worktree guard fix and its regression test are committed and pushed.
- A new reviewer checked the PR head independently. The formal, vulnerability, and deploy-safety checks each reported 0 issues.
- The SHA-bound reviewer artifact is at https://github.com/blueman82/coderails/pull/429#issuecomment-5356278449.
- Frozen eval result is `GO`, verification level 1, with E1-E5 independently passing and SHA-256 `413182ed904216782b846664a7d8bacb673038ca7076b4565640b923a2a7d0eb`.
- Eval validate-smoke and discriminating checks passed.
- The eval artifact is the only missing PR record.
- The user gave no merge instructions. The PR stayed open.

## Next steps

1. Start a new Codex session in `/Users/garyharr/Github/coderails-execution-discipline`. Read this memory, current `AGENTS.md`, and the current `post-evals` skill.
2. Fetch PR #429 metadata again. Check that the head is `7f432649df1c5014810471edadf980a184286339`.
3. Check that `/tmp/coderails-execution-discipline-evals.json` has SHA-256 `413182ed904216782b846664a7d8bacb673038ca7076b4565640b923a2a7d0eb`. Check the recorded GO/level-1/E1-E5-pass result.
4. Use the `post-evals` skill to validate and post the SHA-bound eval artifact for PR #429 from the correct feature worktree.
5. Check the live PR eval artifact URL, its head SHA, and its GO result.
6. Report the posted artifact and stop. Do not merge without explicit user approval.

## Open questions

- None for posting the artifact. After posting and checks, the user decides independently on merge.
