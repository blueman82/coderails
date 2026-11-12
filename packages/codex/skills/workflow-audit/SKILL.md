---
name: workflow-audit
description: Use when the user asks to look at recent sessions and find repeated tasks worth turning into skills — "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".
---

# Workflow Audit

Read Codex session transcripts for tool-use patterns that occur across multiple sessions.
A judge selects candidates for new skills. Use `$skill-creator`, a test with a new subagent, and the native Codex PR workflow for each build.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. Use that path for the bundled scripts.

## Overview

1. Read transcripts into sequences of tool use.
2. Cluster n-grams that occur across sessions.
3. Give the clusters to a new judge subagent for propose or reject verdicts.
4. Use each `propose` verdict to make the skill in-session by default.
   In queue-mode, write a dashboard queue entry (section 5).

Select one mode for the run. Do not make a skill that the judge rejects.

## 1. Scope mapping

Map the user's words to the script arguments before you run the scripts:

| User says | Args |
|---|---|
| "last N sessions" | `--last-sessions N` |
| no scope given | `--all-projects --days 14` (default) |
| "just this project" / a named project | `--project <slug>` |

The transcript root is `WORKFLOW_AUDIT_ROOT` (default `~/.codex/sessions`). Change it only if the user names a different root.
Native Codex keeps JSONL in dated directories. The `--project` value matches the basename of `session_meta.payload.cwd`.
The script excludes child-agent threads so they cannot inflate the number of matching sessions.

## 2. Size sanity

Before it reads files, `scan_transcripts.py` prints `scanning file_count=<N> total_mb=<M>` to stderr.
Show this line to the user before the results so they know the scale of the read.

## 3. Mechanical pipeline

```bash
python3 "$SKILL_DIR/scripts/scan_transcripts.py" <scan args> \
  | python3 "$SKILL_DIR/scripts/cluster_ngrams.py" --min-sessions 3
```

`scan_transcripts.py` (`--help` gives the full contract) gives one JSON line for each root session from native `event_msg.payload.item` records.
It accepts only completed `CommandExecution`, `FileChange`, `Extension`, and `CollabAgentToolCall` items.
The optional `head` has the first two command tokens or a name from the native extension and collaboration tool allowlist.
The script drops the head for unknown names.

It does not copy messages, prompts, results, analysis text, remaining command arguments, or file-change contents.
`cluster_ngrams.py` (`--help` gives the full contract) reads that stream and gives one JSON object.
It includes n-grams (n=2..5) that occur in `--min-sessions` (default 3) different sessions.
The result has a maximum of `--top` (default 50) clusters.

Report `jq_parse_error:<file>` or `jq_parse_error:<line-no>` lines on stderr as parse errors. Do not hide them.
If `clusters` is empty ("no repeated patterns found at this threshold"), report that result and stop.
Do not decrease the threshold or invent candidates.

## 4. Judge stage

Read all of `$SKILL_DIR/references/judge-contract.md`. Use `spawn_agent` one time for a new Codex judge.
Copy the prompt template verbatim and fill in:

1. The cluster JSON, which is the full stdout object from `cluster_ngrams.py`.
2. The existing skill list with the `name` and `description` frontmatter lines from each `skills/*/SKILL.md` in the repository.

**Give the judge only those inputs.** Do not give it transcripts, conversation history, or orchestrator commentary.
Its allowed vocabulary is tool names, allowlisted heads, counts, session IDs, and n-gram lengths.
The two scripts apply that same privacy rule to their own output.
The judge gives one propose or reject verdict for each cluster using the contract's schema.

## 5. Queue-mode output (optional) — mutually exclusive with in-session creation

By default, each `propose` verdict goes to the section 8 build in the same session. Do not write a queue entry.
In queue-mode, write a dashboard queue entry for each `propose` verdict. Do not build the skill in the same session.

Use only one of these modes in a run. Each candidate has only one build path.
Use queue-mode if the session will let the owner start dashboard builds when they want to.

In queue-mode, pipe each `verdict: "propose"` output to the writer script one time for each candidate. Do not continue to section 8:

```bash
echo "$JUDGE_VERDICT_JSON" | python3 "$SKILL_DIR/scripts/write_queue_entry.py" \
  --queue-dir ~/.codex/coderails-dashboard/approvals \
  --count "$CLUSTER_COUNT" \
  --sessions "$CLUSTER_SESSIONS_JSON"
```

**The owner starts the dashboard build.** The owner clicks "Approve" on an entry.
The dashboard changes the on-disk `status` from `pending` to `approved` and starts a detached headless build.
The build checks the entry's content hash again and runs the section 8 build.
See "Approve-click build runner" in `docs/REFERENCE.md` for the full runner contract.

The session does not prompt the owner to click or wait for a click. This is the only build path for a queue-mode candidate.
A stale status change or one with no context does not equal an approval from the owner.
The Approve click gives consent for the build with the same authority as direct consent in conversation.
The runner does not merge the skill PR. The owner examines and merges it by hand.

The run is complete if it writes queue entries, with or without owner approval. Do not try again, remind the owner, or prompt for approval.

The queue file has only the fields D2 allows and the judge contract checks.
They are `cluster_ngram`, `count`, `sessions`, `task_summary`, `proposed_name`, and `proposed_description`.
It has no verbatim transcript content. Do not commit it.
The queue directory is `~/.codex/coderails-dashboard/approvals/`, apart from the repositories.

## 6. Proposal chart

Give the owner one row for each candidate cluster:

| Field | Source |
|---|---|
| Task summary | judge's `task_summary` |
| `Evidence count` | cluster's `count` |
| Sessions touched | cluster's `sessions` (count, IDs, or the two) |
| Proposed name / description | judge's `proposed_name` / `proposed_description` |
| Verdict | judge's `verdict`. If it rejects, include `reject_reason`. |

Only rows with `verdict: "propose"` continue to a build or queue entry (section 7).
Report rejected clusters with `reject_reason`. Do nothing else with them.

**Privacy rule.** The chart, proposal file, and wrap-up report contain only tool names, allowlisted heads, counts, and session IDs.
Do not include verbatim transcript prose, file contents, or inferred intent those fields do not show.
Keep proposal artifacts on disk in a local scratch or loop directory. Do not commit them.

## 7. Proceed to creation

Unless you selected queue-mode, send each `propose` candidate to section 8 without asking the owner again.
For queue-mode, write a queue entry as in section 5. Only the dashboard Approve click starts its build.
The judge's verdict is the only filter for what gets built. Do not make a skill from a rejected candidate.
If the judge proposes no candidates, the run is complete.

## 8. Create step — one skill at a time

For each proposed candidate, use this sequence. Do not batch candidates:

1. Write the skill through `$skill-creator` using only the candidate's judge-contract fields.
   Use a new subagent to run a baseline scenario without the new skill.
   Write the smallest `SKILL.md` that corrects the observed problem. Then run the same scenario again.

2. Publish the skill in the Coderails repository as a plugin skill on its own branch and PR.
   Run the test gate. Start the installed `spec-reviewer` custom agent against the current PR head.
   For a production surface, follow [guarded role sessions](../using-coderails/references/guarded-role-sessions.md) for `deploy-safety-reviewer`.
   Run `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role deploy-safety-reviewer --prompt-file <file> --cwd <exact-head-worktree>`.

   Then invoke `$coderails-codex:post-review`, PR-scope `$coderails-codex:task-evals`, `$coderails-codex:post-evals`, and `$coderails-codex:merge`.
   Do not commit directly to `main` or write into the user's personal `~/.codex/skills` directory. This is a repository skill.

3. **Finish the merge for this skill before you start the next candidate.** Test and publish each candidate independently.

## 9. Wrap-up

Report without scoring:

- Skills you made (name, PR, and merge SHA).
- Candidates the judge rejected, with `reject_reason`.
- Clusters below the `--min-sessions` threshold (`diagnostics.below_threshold`).

## 10. On-demand invocation

Native Codex has no scheduler. Invoke this skill on demand in Codex or with the dashboard's `workflow-audit-weekly` button.
See the dashboard's `docs/routines.md` for the operator guide.
Despite its historical name, the button does not run the skill weekly or automatically.
The button reads the last 7 days of transcripts (`--days 7`), clusters patterns, and asks the judge for verdicts.
It writes `propose` verdicts as dashboard queue entries.

**The dashboard run uses queue-mode only.** Do not build in-session. Only the owner's Approve click starts a build.
In a direct interactive run, the user can select in-session builds or queue-mode.
The run is complete only if `proposals_written == proposals_attempted`. If there are no proposals, the run is complete.
