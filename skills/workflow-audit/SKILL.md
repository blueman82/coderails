---
name: workflow-audit
description: Use when the user asks to look at recent sessions and find repeated tasks worth turning into skills — "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".
model: sonnet
---

# Workflow Audit

Find tool-use patterns that occur in multiple Claude Code sessions.
Use the judge contract to select candidates for new skills.
For in-session work, use `superpowers:writing-skills` and the full PR gate for each skill.

## Overview

Read tool calls from transcripts and group recurring n-grams across sessions.
Send the groups to one new judge agent for `propose` or `reject` verdicts.
For each `propose` verdict, make the skill in this session by default or write a dashboard queue entry in queue-mode.
Use only one of these paths.
Do not make skills from `reject` verdicts.

## 1. Scope mapping

Select the scan arguments from the user’s scope before you run the scanner.

| User says | Args |
|---|---|
| "last N sessions" | `--last-sessions N` |
| no scope given | `--all-projects --days 14` (default) |
| "just this project" / a named project | `--project <slug>` |

Corpus root is `WORKFLOW_AUDIT_ROOT` (default `~/.claude/projects`) — override only if the user names a different root.

## 2. Size sanity

`scan_transcripts.py` prints a `scanning file_count=<N> total_mb=<M>` line to stderr before it examines anything. Show this line to the user before you give the results.

## 3. Mechanical pipeline

```bash
python3 skills/workflow-audit/scripts/scan_transcripts.py <scan args> \
  | python3 skills/workflow-audit/scripts/cluster_ngrams.py --min-sessions 3
```

`scan_transcripts.py` gives one JSON line for each session.
It includes tool names and a privacy-whitelisted `head`.
A head contains the first two Bash command tokens, the Skill name, or the Agent `subagent_type`.
It has no other data.

`cluster_ngrams.py` reads the stream and gives one JSON object.
It includes n-grams with n=2..5 that recur across `--min-sessions` different sessions (default 3).
It limits the number of clusters to `--top` (default 50).
See `--help` for each script’s full contract.

**Report diagnostics.**
A `jq_parse_error:<file>` or `jq_parse_error:<line-no>` line on stderr reports a parse error.
Do not suppress it.
An empty `clusters` array means no recurring pattern met the threshold.
Report that result and stop.
Do not lower the threshold or invent candidates.

## 4. Judge stage

Read `references/judge-contract.md` in full, then start one new sonnet subagent to apply it.
Copy the prompt template verbatim and supply these two inputs:

1. The cluster JSON from the full stdout object of `cluster_ngrams.py`.
2. The list of skill names and descriptions. Get the `name` and `description` frontmatter lines from each `skills/*/SKILL.md` in the repo.

**Give the judge only these inputs.**
Do not give it transcripts, conversation history, or orchestrator commentary.
The judge can use only tool names, whitelisted heads, counts, session IDs, and n-gram lengths.
This is the same privacy boundary as the output of `scan_transcripts.py` and `cluster_ngrams.py`.
The judge gives one `propose` or `reject` verdict for each cluster in the contract’s schema.

## 5. Queue-mode output (optional) — mutually exclusive with in-session creation

Use only one path for each run.
For the default in-session path, send each `propose` verdict to section 8 and write no queue entries.
For queue-mode, write one queue entry for each `propose` verdict and do not make skills in this session.
Use queue-mode if the owner wants to start builds from the dashboard at a time they select.

In queue-mode, run the writer for each `verdict: "propose"`:

```bash
echo "$JUDGE_VERDICT_JSON" | python3 skills/workflow-audit/scripts/write_queue_entry.py \
  --queue-dir ~/.claude/coderails-dashboard/approvals \
  --count "$CLUSTER_COUNT" \
  --sessions "$CLUSTER_SESSIONS_JSON"
```

**The owner starts the dashboard build.**
When the owner clicks "Approve", the entry’s on-disk `status` changes from `pending` to `approved`.
The dashboard starts a detached headless build.
The runner checks the entry’s content hash again, then does the section 8 steps.
See the "Approve-click build runner" entry in `docs/REFERENCE.md` for the runner contract.

The owner can click "Approve" without a prompt from this session.
This is the only path to make a skill from a queue entry.
A stale or context-free status change does not show a live owner decision.
The click gives consent to start the build.
The runner does not merge the skill PR. The owner examines and merges it by hand.

An audit ends successfully if it writes queue entries and the owner has not approved them.
Do not retry, send a reminder, or wait.

The queue entry contains only the D2-whitelisted fields the judge contract checks.
These are `cluster_ngram`, `count`, `sessions`, `task_summary`, `proposed_name`, and `proposed_description`.
Do not copy transcript content into the entry.
Keep the file in `~/.claude/coderails-dashboard/approvals/` and out of Git repositories.

## 6. Proposal chart

Give the owner one row for each candidate cluster.

| Field | Source |
|---|---|
| Task summary | judge's `task_summary` |
| Count | cluster's `count` |
| Sessions touched | cluster's `sessions` (count and/or ids) |
| Proposed name / description | judge's `proposed_name` / `proposed_description` |
| Verdict | judge's `verdict` (+ `reject_reason` if rejected) |

Only rows with `verdict: "propose"` go to setup or the queue. Report rejected clusters and why the judge refused them. Stop work on them.

**Privacy invariant.** The chart, proposal files, and wrap-up report use only tool names, whitelisted heads, counts, and session IDs. Do not include transcript prose or file contents. Do not infer intent the fields do not show. Keep proposal files in a local scratch or loop-state directory. Do not commit them.

## 7. Proceed to creation

For in-session work, send each `propose` verdict to section 8. Do not use `AskUserQuestion` or wait for the owner. For queue-mode, write a queue entry as in section 5. Only the owner’s Approve click starts that build. Select candidates only by the judge verdict. The audit succeeds if there are no `propose` verdicts.

## 8. Create step — one skill at a time

Work on one proposed skill at a time.

1. Use `/skill-creator:skill-creator` as directed by the owner on 2026-07-07. Specify the skill from that candidate’s judge-contract fields. For a headless run, skip the human-facing eval viewer. The skill creator has no autonomous "done" signal. Use the RED/GREEN/REFACTOR steps from `superpowers:writing-skills`. For RED, run a baseline pressure test with a new subagent that has no new skill. Record what it does. For GREEN, write the minimum `SKILL.md` to correct the problems the test showed. For REFACTOR, repeat the same pressure test and correct the problems you find.
2. Use one branch and PR to add the plugin skill to the Coderails repo. Do `test_gate`, `pr-review-toolkit:review-pr`, the check for vulnerabilities, `post-review`, PR-scope evals, and merge in sequence. Do not commit directly to `main`. Do not write into the user’s personal `~/.claude/skills` directory.
3. **Merge this skill before starting the next candidate.** Follow `superpowers:writing-skills`: check and ship each skill individually.

## 9. Wrap-up

Report, unscored:
- Skills created (name, PR, merge SHA).
- Candidates rejected by the judge, with `reject_reason`.
- Clusters below the `--min-sessions` threshold (`diagnostics.below_threshold`), so the owner can see the patterns that stayed below it.

## 10. Scheduled invocation

The `workflow-audit-weekly` schedule invokes this skill each week. See `docs/routines.md` for the operator guide. The scan reads the last 7 days of transcripts (`--days 7`). It groups and judges recurring patterns, then writes `propose` verdicts to the dashboard queue.

**Scheduled runs must use queue-mode.** They must not make skills in-session. Only the owner's Approve click on a queue entry can start each build. An interactive run can make skills in-session or use queue-mode, at the user's discretion.

A scheduled run succeeds only if `proposals_written == proposals_attempted` and there are no queue write errors. A week with no proposals is satisfactory.
