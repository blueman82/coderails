---
name: workflow-audit
description: Use when the user asks to look at recent sessions and find repeated tasks worth turning into skills — "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".
---

# Workflow Audit

Mines Codex session transcripts for tool-use patterns that repeat across sessions, judges which ones are genuine candidates for a new skill, and creates each proposed skill through `$skill-creator`, a fresh-subagent pressure test, and the native Codex PR workflow.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`; run all
bundled scripts through that path.

## Overview

Four stages: scan transcripts into tool-use event sequences, cluster repeated n-grams across sessions, hand the clusters to a fresh judge subagent for propose/reject verdicts, then carry every `propose` verdict forward — straight to creation in-session by default, or to a dashboard queue entry if the run is in queue-mode (section 5), never both. Nothing is created that the judge rejected.

## 1. Scope mapping

Map the user's phrasing onto scan arguments before running anything:

| User says | Args |
|---|---|
| "last N sessions" | `--last-sessions N` |
| no scope given | `--all-projects --days 14` (default) |
| "just this project" / a named project | `--project <slug>` |

Corpus root is `WORKFLOW_AUDIT_ROOT` (default `~/.codex/sessions`) — override only if the user names a different root. Native Codex stores JSONL below dated directories; `--project` matches the basename of `session_meta.payload.cwd`, and child-agent threads are excluded so they cannot inflate cross-session support.

## 2. Size sanity

`scan_transcripts.sh` prints a `scanning file_count=<N> total_mb=<M>` line to stderr before it scans anything. Surface this line to the user so they know the scale of what's being read before results come back.

## 3. Mechanical pipeline

```bash
bash "$SKILL_DIR/scripts/scan_transcripts.sh" <scan args> \
  | bash "$SKILL_DIR/scripts/cluster_ngrams.sh" --min-sessions 3
```

`scan_transcripts.sh` (full contract: `--help`) emits one JSON line per root session from native `event_msg.payload.item` records. It allows only completed `CommandExecution`, `FileChange`, `Extension`, and `CollabAgentToolCall` items. The optional `head` is limited to the first two command tokens or an explicit allowlist of native extension and collaboration tool names; unknown names lose their head. Message, prompt, result, reasoning, remaining command arguments, and file-change content is never copied. `cluster_ngrams.sh` (full contract: `--help`) consumes that stream and emits one JSON object: n-grams (n=2..5) that recur across `--min-sessions` (default 3) distinct sessions, capped at `--top` (default 50) clusters.

**Diagnostics are not noise.** `jq_parse_error:<file>` or `jq_parse_error:<line-no>` lines on stderr are real parse failures — surface them, don't swallow them. An empty `clusters` array is a legitimate result ("no repeated patterns found at this threshold") — report it plainly and stop; don't lower the threshold or invent candidates to fill the gap.

## 4. Judge stage

Read `$SKILL_DIR/references/judge-contract.md` in full, then call `spawn_agent` exactly once for a fresh Codex judge. Construct the judge's prompt from that file's template verbatim, filling in:

1. The cluster JSON — the full stdout object from `cluster_ngrams.sh`.
2. The existing-skill list — the `name` and `description` frontmatter lines from every `skills/*/SKILL.md` in the repo.

**The judge receives nothing else.** No transcript content, no conversation history, no orchestrator commentary. This is a deliberate privacy boundary: the judge's entire vocabulary is tool names, whitelisted heads, counts, session ids, and n-gram lengths — the same boundary `scan_transcripts.sh` and `cluster_ngrams.sh` already enforce on their own output. The judge returns one propose/reject verdict per cluster per the contract's schema.

## 5. Queue-mode output (optional) — mutually exclusive with in-session creation

A run either creates in-session (the default: every `propose` verdict goes
straight to section 8, no queue entries written) **or** defers to the
dashboard (queue-mode: every `propose` verdict is written as a queue entry
and the run does NOT also create in-session). Never both for the same run
— a candidate is created by exactly one path, never twice. Choose
queue-mode when the session wants proposals surfaced on the dashboard for
the owner to trigger builds from at a time of their choosing, instead of
building them immediately in-session.

To run in queue-mode, pipe each `verdict: "propose"` judge output through
the writer script, once per candidate, instead of proceeding to section 8:

```bash
echo "$JUDGE_VERDICT_JSON" | bash "$SKILL_DIR/scripts/write_queue_entry.sh" \
  --queue-dir ~/.codex/coderails-dashboard/approvals \
  --count "$CLUSTER_COUNT" \
  --sessions "$CLUSTER_SESSIONS_JSON"
```

**The dashboard build trigger is owner-initiated, not an audit surface.**
A dashboard "Approve" click on one of these entries flips its on-disk
`status` from `pending` to `approved` and triggers a build — the
dashboard's approve-path spawns a detached headless build that
re-validates the entry's content hash and drives the section-8 create
step (see `docs/REFERENCE.md`'s "Approve-click build runner" entry for the
full runner contract). This is the owner clicking a button on their own
initiative, not the session pausing to ask — it never blocks or stalls a
session, and it is the sole creation path for a queue-mode candidate.
**A stale or context-free status flip is not equivalent to a live owner
exchange** — an `approved` queue entry carries real consequence, so treat
the moment of clicking Approve with the same weight as any other consent
that triggers action, not less because it happened outside a live
conversation. The runner never merges the resulting skill PR; the owner
reviews and merges it by hand.

**Zero clicks is a complete, successful run here too** — an audit run
that writes queue entries nobody has approved yet ends cleanly; there is
no retry, no nag, no follow-up ask.

The queue file itself carries only the D2-whitelisted fields already
vetted by the judge contract (`cluster_ngram`, `count`, `sessions`,
`task_summary`, `proposed_name`, `proposed_description`) — never verbatim
transcript content — and is never committed to any repo
(`~/.codex/coderails-dashboard/approvals/` lives outside every repo).

## 6. Proposal chart

Present one row per candidate cluster to the owner:

| Field | Source |
|---|---|
| Task summary | judge's `task_summary` |
| Evidence count | cluster's `count` |
| Sessions touched | cluster's `sessions` (count and/or ids) |
| Proposed name / description | judge's `proposed_name` / `proposed_description` |
| Verdict | judge's `verdict` (+ `reject_reason` if rejected) |

Only rows with `verdict: "propose"` go forward (to creation or a queue entry, per section 7); rejected clusters are reported (with their reason) but nothing further is done with them.

**Privacy invariant.** The chart and every downstream artifact (proposal file, wrap-up report) contain only tool names, whitelisted heads, counts, and session ids — never verbatim transcript prose, file contents, or reconstructed intent beyond what those fields literally say. Any proposal artifact written to disk stays local (scratch or loop-state dir) and is never committed to the repo.

## 7. Proceed to creation

Unless the run is in queue-mode (section 5), every candidate the judge marked `propose` goes straight to the section-8 create step without asking the owner again. In queue-mode, a `propose` verdict is written as a queue entry instead (section 5) and is NOT also created here — the dashboard Approve-click is its sole creation path. Either way, the judge's propose/reject verdict is the only filter that decides what gets built — nothing is created that the judge rejected, and zero `propose` verdicts is a complete, successful run, not a failure to escalate past.

## 8. Create step — one skill at a time

For each proposed candidate, in sequence, never batched:

1. Author the skill via `$skill-creator`, fully specified from the candidate's own judge-contract fields. Run a fresh-subagent baseline scenario without the new skill, write the smallest `SKILL.md` that addresses the observed failure, then repeat the scenario.
2. Land the new skill in the coderails repo as a plugin skill, via its own branch and PR. Run the test gate, spawn the installed `spec-reviewer` custom agent against the current PR head, add `deploy-safety-reviewer` only for a production surface, then invoke `$coderails-codex:post-review`, PR-scope `$coderails-codex:task-evals`, `$coderails-codex:post-evals`, and `$coderails-codex:merge`. Never commit straight to `main`, and never write into a user's personal `~/.codex/skills` directory — this is a repo skill, not a local one.
3. **Stop after this skill is merged before starting the next proposed candidate.** Test and ship each candidate separately.

## 9. Wrap-up

Report, unscored:
- Skills created (name, PR, merge SHA).
- Candidates rejected by the judge, with `reject_reason`.
- Clusters below the `--min-sessions` threshold (`diagnostics.below_threshold`), so the owner knows what's sitting just under the bar.

## 10. On-demand invocation

Native Codex does not bundle a scheduler. Invoke this skill on demand, either directly in Codex or from the dashboard's manually triggered `workflow-audit-weekly` routine (see the dashboard's `docs/routines.md` for the full operator guide). Despite its historical name, the routine does not run weekly or automatically. It scans transcripts from the last 7 days (`--days 7`), clusters repeated patterns, judges them, and writes any `propose` verdicts as queue entries on the dashboard. **Queue-mode is mandatory for this dashboard routine** — in-session skill creation is forbidden, and the owner's Approve click on a queue entry is the sole build trigger for each proposal. A direct interactive run can create skills in-session or defer to queue-mode at the user's discretion. The routine completes cleanly only if `proposals_written == proposals_attempted` (no queue write failures); a run with zero proposals is successful, not a failure.
