---
name: workflow-audit
description: Use when the user asks to look at recent sessions and find repeated tasks worth turning into skills — "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".
---

# Workflow Audit

Mines Claude Code session transcripts for tool-use patterns that repeat across sessions, judges which ones are genuine candidates for a new skill, and creates each proposed skill through the normal `writing-skills` TDD process and a full PR gate.

## Overview

Four stages: scan transcripts into tool-use event sequences, cluster repeated n-grams across sessions, hand the clusters to a fresh judge subagent for propose/reject verdicts, then carry every `propose` verdict straight into creation. Nothing is created that the judge rejected; nothing else stands in the way of what it proposed.

## 1. Scope mapping

Map the user's phrasing onto scan arguments before running anything:

| User says | Args |
|---|---|
| "last N sessions" | `--last-sessions N` |
| no scope given | `--all-projects --days 14` (default) |
| "just this project" / a named project | `--project <slug>` |

Corpus root is `WORKFLOW_AUDIT_ROOT` (default `~/.claude/projects`) — override only if the user names a different root.

## 2. Size sanity

`scan_transcripts.sh` prints a `scanning file_count=<N> total_mb=<M>` line to stderr before it scans anything. Surface this line to the user so they know the scale of what's being read before results come back.

## 3. Mechanical pipeline

```bash
bash skills/workflow-audit/scripts/scan_transcripts.sh <scan args> \
  | bash skills/workflow-audit/scripts/cluster_ngrams.sh --min-sessions 3
```

`scan_transcripts.sh` (full contract: `--help`) emits one JSON line per session: tool names plus a privacy-whitelisted `head` (first two Bash command tokens, the Skill name, or the Agent subagent_type — nothing else). `cluster_ngrams.sh` (full contract: `--help`) consumes that stream and emits one JSON object: n-grams (n=2..5) that recur across `--min-sessions` (default 3) distinct sessions, capped at `--top` (default 50) clusters.

**Diagnostics are not noise.** `jq_parse_error:<file>` or `jq_parse_error:<line-no>` lines on stderr are real parse failures — surface them, don't swallow them. An empty `clusters` array is a legitimate result ("no repeated patterns found at this threshold") — report it plainly and stop; don't lower the threshold or invent candidates to fill the gap.

## 4. Judge stage

Read `references/judge-contract.md` in full, then spawn exactly one fresh sonnet subagent to apply it. Construct the judge's prompt from that file's template verbatim, filling in:

1. The cluster JSON — the full stdout object from `cluster_ngrams.sh`.
2. The existing-skill list — the `name` and `description` frontmatter lines from every `skills/*/SKILL.md` in the repo.

**The judge receives nothing else.** No transcript content, no conversation history, no orchestrator commentary. This is a deliberate privacy boundary: the judge's entire vocabulary is tool names, whitelisted heads, counts, session ids, and n-gram lengths — the same boundary `scan_transcripts.sh` and `cluster_ngrams.sh` already enforce on their own output. The judge returns one propose/reject verdict per cluster per the contract's schema.

## 5. Queue-mode output (optional)

When running inside a session that also wants proposals surfaced on the
dashboard (not just the interactive chart below), pipe each `verdict:
"propose"` judge output through the writer script, once per candidate:

```bash
echo "$JUDGE_VERDICT_JSON" | bash skills/workflow-audit/scripts/write_queue_entry.sh \
  --queue-dir ~/.claude/coderails-dashboard/approvals \
  --count "$CLUSTER_COUNT" \
  --sessions "$CLUSTER_SESSIONS_JSON"
```

This is additive to, never a replacement for, the interactive approval
gate in section 7 below — the session's own `AskUserQuestion` flow runs
exactly as it always has, unchanged. Queue-mode gives the same proposals a
second, asynchronous surface on the dashboard.

**Every pinned invariant from section 7 still applies to a queue entry, with
one update:** a dashboard "Approve" click on one of these entries flips its
on-disk `status` from `pending` to `approved` **and now also triggers a
build** — the dashboard's approve-path spawns a detached headless build
that re-validates the entry's content hash and drives the section-8 create
step (see `docs/REFERENCE.md`'s "Approve-click build runner" entry for the
full runner contract). **A stale or context-free status flip is still not
equivalent to a live owner exchange** — an `approved` queue entry now
carries real consequence, so treat the moment of clicking Approve with the
same weight as any other consent that triggers action, not less because
it happened outside a live conversation. The runner never merges the
resulting skill PR; the owner reviews and merges it by hand.

**Zero approvals is a complete, successful run here too** — an audit run
that writes queue entries nobody has approved yet ends cleanly; there is
no retry, no nag, no follow-up ask.

The queue file itself carries only the D2-whitelisted fields already
vetted by the judge contract (`cluster_ngram`, `count`, `sessions`,
`task_summary`, `proposed_name`, `proposed_description`) — never verbatim
transcript content — and is never committed to any repo
(`~/.claude/coderails-dashboard/approvals/` lives outside every repo).

## 6. Proposal chart

Present one row per candidate cluster to the owner:

| Field | Source |
|---|---|
| Task summary | judge's `task_summary` |
| Evidence count | cluster's `count` |
| Sessions touched | cluster's `sessions` (count and/or ids) |
| Proposed name / description | judge's `proposed_name` / `proposed_description` |
| Verdict | judge's `verdict` (+ `reject_reason` if rejected) |

Only rows with `verdict: "propose"` go forward to the approval gate; rejected clusters are reported (with their reason) but not offered for approval.

**Privacy invariant.** The chart and every downstream artifact (proposal file, approval-gate summary, wrap-up report) contain only tool names, whitelisted heads, counts, and session ids — never verbatim transcript prose, file contents, or reconstructed intent beyond what those fields literally say. Any proposal artifact written to disk stays local (scratch or loop-state dir) and is never committed to the repo.

## 7. Approval gate — hard stop, no exceptions

Ask via `AskUserQuestion`, multi-select, one option per proposed candidate (plus an implicit "approve none" if the user selects nothing). Wait for the response.

**This gate overrides any standing autonomy the session has.** Even inside an agentic-loop session authorised for "crack on", "no human gates", "self-merge", or any other full-autonomy envelope, this specific gate does not fall inside that envelope. Skill creation from a workflow-audit run NEVER proceeds without the owner's explicit approval given in *this* interaction — not an earlier blanket authorisation, not an inferred "they'd probably want this." If the owner approves zero candidates, the skill ends here having created nothing, and that is a complete, successful run — not a failure to escalate past.

## 8. Create step — one skill at a time

For each approved candidate, in sequence, never batched:

1. Author the skill via `/skill-creator:skill-creator` (per the owner's 2026-07-07 directive) fully specified from the candidate's own judge-contract fields, skipping its human-facing eval-viewer step in a headless run. Substitute `coderails:writing-skills`'s RED/GREEN/REFACTOR discipline as the stop condition, since skill-creator itself has no autonomous "done" signal: RED — run a fresh-subagent baseline pressure-test scenario *without* the new skill present, and document what it actually does. GREEN — write the minimal `SKILL.md` addressing the observed baseline failures. REFACTOR — re-test under the same pressure and close any loopholes found.
2. Land the new skill in the coderails repo as a plugin skill, via its own branch and PR, through the full gate sequence: `test_gate` → `pr-review-toolkit:review-pr` → security review → `post-review` → pr-scope evals → merge. Never commit straight to `main`, and never write into a user's personal `~/.claude/skills` directory — this is a repo skill, not a local one.
3. **Stop after this skill is merged before starting the next approved candidate.** Batching multiple skill creations without testing and shipping each individually is the exact anti-pattern `writing-skills` prohibits — apply it here too.

## 9. Wrap-up

Report, unscored:
- Skills created (name, PR, merge SHA).
- Candidates rejected by the judge, with `reject_reason`.
- Candidates the judge proposed but the owner declined at the approval gate.
- Clusters below the `--min-sessions` threshold (`diagnostics.below_threshold`), so the owner knows what's sitting just under the bar.
