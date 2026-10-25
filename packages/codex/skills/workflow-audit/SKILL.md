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

`scan_transcripts.py` prints `scanning file_count=<N> total_mb=<M>` to
stderr after it parses and filters candidate files, before it emits the
event sequences. Surface this line so the user knows the size of the
selected corpus before the cluster result arrives.

## 3. Mechanical pipeline

```bash
python3 "$SKILL_DIR/scripts/scan_transcripts.py" <scan args> \
  | python3 "$SKILL_DIR/scripts/cluster_ngrams.py" --min-sessions 3
```

`scan_transcripts.py` (full contract: `--help`) emits one JSON line per root
session from completed native tool events. It keeps `CommandExecution`,
`FileChange`, `Extension`, and `CollabAgentToolCall` items. For a command,
`head` is the first two tokens of its command text. These tokens are not
allowlisted and can contain a literal argument. Extension and collaboration
heads use a small allowlist. The scanner omits the rest of each command,
message, prompt, result, reasoning, and file-change content.
`cluster_ngrams.py` emits recurring n-grams (n=2..5), capped at `--top`
(default 50) across `--min-sessions` (default 3) distinct sessions.

**Diagnostics are not noise.** `jq_parse_error:<file>` or `jq_parse_error:<line-no>` lines on stderr are real parse failures — surface them, don't swallow them. An empty `clusters` array is a legitimate result ("no repeated patterns found at this threshold") — report it plainly and stop; don't lower the threshold or invent candidates to fill the gap.

## 4. Judge stage

Read `$SKILL_DIR/references/judge-contract.md` in full. Call `spawn_agent`
exactly once for a fresh Codex judge, with `fork_turns: "none"`. This prevents
the judge from inheriting the current conversation. Construct its prompt from
that file's template verbatim, filling in:

1. The cluster JSON — the full stdout object from `cluster_ngrams.py`.
2. The existing-skill list — the `name` and `description` frontmatter from
   both `skills/*/SKILL.md` and `packages/codex/skills/*/SKILL.md` in the
   repo. Deduplicate equal names; use the native Codex description when
   both roots define the same name.

Give the judge only those two inputs, with no conversation history or
orchestrator commentary. Before dispatch, inspect command heads for literal
secrets or private text. If one appears, stop this run; do not send the JSON
to the judge or write a queue entry. The two-token limit reduces content but
does not guarantee privacy. The judge returns one propose/reject verdict per
cluster per the contract's schema.

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
echo "$JUDGE_VERDICT_JSON" | python3 "$SKILL_DIR/scripts/write_queue_entry.py" \
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

The queue file carries `cluster_ngram`, `count`, `sessions`,
`task_summary`, `proposed_name`, and `proposed_description`. Command heads
inside these fields can contain literal command text. Apply the head check
in section 4 before writing a queue entry. The queue file is never committed
to any repo
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

**Privacy limit.** The chart and downstream artifacts contain tool names,
command heads, counts, and session IDs. A command head can itself contain
private text. Stop before creating these artifacts if the section-4 check
finds such text. Keep any local proposal file in scratch or loop state;
never commit it to the repo.

## 7. Proceed to creation

Unless the run is in queue-mode (section 5), every candidate the judge marked `propose` goes straight to the section-8 create step without asking the owner again. In queue-mode, a `propose` verdict is written as a queue entry instead (section 5) and is NOT also created here — the dashboard Approve-click is its sole creation path. Either way, the judge's propose/reject verdict is the only filter that decides what gets built — nothing is created that the judge rejected, and zero `propose` verdicts is a complete, successful run, not a failure to escalate past.

## 8. Create step — one skill at a time

For each proposed candidate, in sequence, never batched:

1. Prepare a branch and worktree for this candidate. Freeze PR-scope
   `$coderails-codex:task-evals` before writing the skill.
2. Author the skill via `$skill-creator` from the candidate's judge-contract
   fields. Run a fresh-subagent baseline scenario without the skill, write
   the smallest `SKILL.md` that addresses the observed failure, then repeat
   the scenario.
3. Land the skill in the coderails repo through its own PR. Run the test
   gate. Review the current PR head with
   `source-auditor` through `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role source-auditor --prompt-file <file> --cwd <exact-head-worktree>`.
   For a production surface, also run `deploy-safety-reviewer` through that
   helper. See [guarded role sessions](../using-coderails/references/guarded-role-sessions.md).
   Run and grade the frozen checks. Then invoke `$coderails-codex:post-review`,
   `$coderails-codex:post-evals`, and `$coderails-codex:merge`. Never commit
   straight to `main` or write into `~/.codex/skills`.
4. **Stop after this skill is merged before starting the next proposed
   candidate.** Test and ship each candidate separately.

## 9. Wrap-up

Report, unscored:
- Skills created (name, PR, merge SHA).
- Candidates rejected by the judge, with `reject_reason`.
- Clusters below the `--min-sessions` threshold (`diagnostics.below_threshold`), so the owner knows what's sitting just under the bar.

## 10. On-demand invocation

Native Codex does not bundle a scheduler. Invoke this skill on demand, either directly in Codex or from the dashboard's manually triggered `workflow-audit-weekly` routine (see the dashboard's `docs/routines.md` for the full operator guide). Despite its historical name, the routine does not run weekly or automatically. It scans transcripts from the last 7 days (`--days 7`), clusters repeated patterns, judges them, and writes any `propose` verdicts as queue entries on the dashboard. **Queue-mode is mandatory for this dashboard routine** — in-session skill creation is forbidden, and the owner's Approve click on a queue entry is the sole build trigger for each proposal. A direct interactive run can create skills in-session or defer to queue-mode at the user's discretion. The routine completes cleanly only if `proposals_written == proposals_attempted` (no queue write failures); a run with zero proposals is successful, not a failure.
