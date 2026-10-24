---
name: workflow-audit
description: Use when the user asks to look at recent sessions and find repeated tasks worth turning into skills — "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".
model: sonnet
---

# Workflow Audit

Find repeated tool-use patterns in Claude Code session transcripts. A separate judge selects candidates for new skills. Create each proposed skill through `superpowers:writing-skills` TDD and the full PR gate.

## Overview

The audit has four stages. Scan transcripts into tool-use sequences. Cluster repeated n-grams across sessions. Ask a fresh judge subagent to propose or reject each cluster. Send each proposal to one destination: in-session creation by default, or a dashboard queue in queue-mode (section 5). Never create a rejected candidate.

## 1. Scope mapping

Map the user's phrasing onto scan arguments before running anything:

| User says | Args |
|---|---|
| "last N sessions" | `--last-sessions N` |
| no scope given | `--all-projects --days 14` (default) |
| "just this project" / a named project | `--project <slug>` |

Corpus root is `WORKFLOW_AUDIT_ROOT` (default `~/.claude/projects`) — override only if the user names a different root.

## 2. Size sanity

`scan_transcripts.py` prints a `scanning file_count=<N> total_mb=<M>` line to stderr before it scans anything. Surface this line to the user so they know the scale of what's being read before results come back.

## 3. Mechanical pipeline

```bash
python3 skills/workflow-audit/scripts/scan_transcripts.py <scan args> \
  | python3 skills/workflow-audit/scripts/cluster_ngrams.py --min-sessions 3
```

`scan_transcripts.py` emits one JSON line per session. Each line has tool names and a privacy-whitelisted `head`: two Bash command tokens, the Skill name, or the Agent subagent_type. It emits nothing else from the transcript. See `--help` for its full contract.

`cluster_ngrams.py` consumes that stream. It emits one JSON object with n-grams of length 2–5 that recur across distinct sessions. The default `--min-sessions` is 3. The default `--top` cap is 50 clusters. See `--help` for its full contract.

**Report diagnostics.** A `jq_parse_error:<file>` or `jq_parse_error:<line-no>` line on stderr is a parse failure. Do not suppress it. An empty `clusters` array means no repeated pattern met the threshold. Report that result and stop. Do not lower the threshold or invent candidates.

## 4. Judge stage

Read `references/judge-contract.md` in full, then spawn exactly one fresh sonnet subagent to apply it. Construct the judge's prompt from that file's template verbatim, filling in:

1. The cluster JSON — the full stdout object from `cluster_ngrams.py`.
2. The existing-skill list — the `name` and `description` frontmatter lines from every `skills/*/SKILL.md` in the repo.

**The judge receives nothing else.** Do not send transcript content, conversation history, or orchestrator commentary. Its input is limited to tool names, whitelisted heads, counts, session ids, and n-gram lengths. The scanner and clusterer enforce the same boundary. The judge returns one propose/reject verdict per cluster under the contract schema.

## 5. Queue-mode output (optional) — mutually exclusive with in-session creation

A run uses one creation path. By default, each `propose` verdict goes to
section 8 for in-session creation. Queue-mode writes each proposal to the
dashboard instead. Do not create the same proposal in-session in queue-mode.
Use queue-mode when the owner wants to start builds from the dashboard later.

To run in queue-mode, pipe each `verdict: "propose"` judge output through
the writer script, once per candidate, instead of proceeding to section 8:

```bash
echo "$JUDGE_VERDICT_JSON" | python3 skills/workflow-audit/scripts/write_queue_entry.py \
  --queue-dir ~/.claude/coderails-dashboard/approvals \
  --count "$CLUSTER_COUNT" \
  --sessions "$CLUSTER_SESSIONS_JSON"
```

**The dashboard build trigger is owner-initiated.** An "Approve" click changes
an entry from `pending` to `approved` and starts a detached headless build.
The build checks the entry's content hash, then runs the section-8 create
step. See "Approve-click build runner" in `docs/REFERENCE.md` for the full
contract. The click is the only creation path for a queue-mode candidate.
It does not pause this audit session.

An `approved` queue entry starts work, so treat the click as consequential
consent. A stale status change does not replace a live owner exchange. The
runner never merges the resulting skill PR; the owner reviews and merges it.

**Zero clicks is a complete run.** The audit ends after it writes queue
entries. It does not retry, nag, or ask again if nobody approves them.

The queue file carries only judge-approved D2-whitelisted fields:
`cluster_ngram`, `count`, `sessions`, `task_summary`, `proposed_name`, and
`proposed_description`. It never contains verbatim transcript content.
The queue lives outside every repo at `~/.claude/coderails-dashboard/approvals/`.
Do not commit it.

## 6. Proposal chart

Present one row per candidate cluster to the owner:

| Field | Source |
|---|---|
| Task summary | judge's `task_summary` |
| Evidence count | cluster's `count` |
| Sessions touched | cluster's `sessions` (count and/or ids) |
| Proposed name / description | judge's `proposed_name` / `proposed_description` |
| Verdict | judge's `verdict` (+ `reject_reason` if rejected) |

Only rows with `verdict: "propose"` go to creation or the queue. Report rejected clusters and their reasons. Take no further action on them.

**Privacy invariant.** The chart and downstream artifacts contain only tool names, whitelisted heads, counts, and session ids. Do not include transcript prose, file contents, or inferred intent. Keep proposal files in local scratch or loop state. Never commit them.

## 7. Proceed to creation

If the run is not in queue-mode (section 5), send every `propose` candidate to the create step in section 8. Do not call `AskUserQuestion` or wait for the owner.

In queue-mode, write each `propose` verdict as a queue entry (section 5). Do not also create the skill here. The dashboard Approve click is the only way to create it.

The judge's `propose` or `reject` verdict is the only filter. Create nothing that the judge rejected. A run with zero `propose` verdicts succeeds; it does not need escalation.

## 8. Create step — one skill at a time

For each proposed candidate, in sequence, never batched:

1. Author the skill via `/skill-creator:skill-creator`, as the owner directed on 2026-07-07. Use the candidate's judge-contract fields. In a headless run, skip the human-facing eval viewer.
   Skill-creator has no autonomous "done" signal. Use `superpowers:writing-skills` RED/GREEN/REFACTOR as the stop rule. In RED, test a fresh subagent without the new skill and record its behavior. In GREEN, write the smallest `SKILL.md` that fixes the observed failures. In REFACTOR, repeat the same pressure test and close any loopholes.
2. Add the skill to the Coderails repo on its own branch and PR. Run the full gate sequence: `test_gate` → `pr-review-toolkit:review-pr` → security review → `post-review` → PR-scope evals → merge. Do not commit to `main` or write to `~/.claude/skills`. This is a repo skill.
3. **Wait for this skill to merge before starting the next candidate.** Test and ship each skill separately. Do not batch their creation.

## 9. Wrap-up

Report, unscored:
- Skills created (name, PR, merge SHA).
- Candidates rejected by the judge, with `reject_reason`.
- Clusters below the `--min-sessions` threshold (`diagnostics.below_threshold`), so the owner knows what's sitting just under the bar.

## 10. Scheduled invocation

The `workflow-audit-weekly` routine invokes this skill each week. See `docs/routines.md` for the operator guide. The routine scans the last 7 days of transcripts (`--days 7`). It clusters and judges repeated patterns, then writes `propose` verdicts as dashboard queue entries.

**Scheduled runs must use queue-mode.** They must not create skills in-session. Only the owner's Approve click on a queue entry can start each build. An interactive run can create skills in-session or use queue-mode, at the user's discretion.

The routine completes cleanly only when `proposals_written == proposals_attempted`, with no queue write failures. A week with zero proposals is successful.
