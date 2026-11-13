# Workflow-audit judge contract

Give this prompt template to a new Sonnet judge during the proposal step of the workflow-audit skill.
The judge uses `cluster_ngrams.py` output to propose or reject candidate skills.

## What the judge receives

Give the judge only these two inputs:

1. **The cluster JSON** — the full stdout object from `cluster_ngrams.py`
   (`{"scanned_sessions","clusters":[{"ngram","n","count","sessions"}],"diagnostics"}`).
2. **A list of existing skill names and descriptions.** Read the `name` and `description` frontmatter fields in the repository.
   For example, use the frontmatter block in each `skills/*/SKILL.md`.

The judge must not get, infer, or reconstruct content that these inputs do not contain.
Its fixed vocabulary comes from the cluster JSON: tool names, `head` strings, counts, session IDs, and n-gram lengths.
`scan_transcripts.py` applies the privacy allowlist to the head strings.

The judge has no access to transcript content, prose, file contents, or other information.
If a verdict depends on the meaning of a command's arguments other than its allowlisted head, the judge cannot give that verdict.
Reject the cluster or give the limit. Do not guess.

## Per-cluster output

For each cluster in the input, the judge gives one object:

```json
{
  "cluster_ngram": ["CommandExecution:git log", "CommandExecution:git push", "CollabAgentToolCall:spawn_agent"],
  "verdict": "propose",
  "reject_reason": "",
  "task_summary": "Sessions repeatedly run `git log`, then `git push`, then spawn a helper agent (seen in 3 sessions).",
  "proposed_name": "git-log-push-prime",
  "proposed_description": "Use when a session needs to review recent commits, push, and delegate a follow-up in sequence — a pattern seen across 3 sessions."
}
```

- `verdict` must be `"propose"` or `"reject"`.
- If `verdict` is `"reject"`, give a non-empty `reject_reason`. If it is `"propose"`, give an empty string.
- Use only the cluster's tool names, heads, and counts for `task_summary` and `proposed_description`.
  Do not invent information or infer intent that the strings do not give.
  You can write "Sessions repeatedly do X then Y".
  Do not write "the user was debugging a flaky CI job" unless an allowlisted head explicitly says that.
- If `verdict` is `"propose"`, give `proposed_name` in kebab-case. It is optional for `"reject"`.

## Mandatory rejection criteria

The judge must reject a cluster if one or more of these conditions apply.
Check them in sequence. Use the first applicable condition as `reject_reason`.

1. **Convention that applies to one project.** The cluster describes a convention for one repository or project.
   For example, it can refer to a recurring command for one project's build script.
   Make skills only for tasks users can do again across different projects.

2. **An existing skill includes the task.** The task overlaps a skill name or description in the supplied list.
   Skip it. Do not propose a duplicate or near-duplicate.

3. **Loop tool artifact.** The cluster describes the loop's own operations.
   Examples are its own `git`/`gh` commands to open PRs and its own scripts to examine, merge, or push changes.
   These n-grams occur because the orchestrator or a worker always does those operations.
   They do not identify a task the user wants to do again.

If none of the three conditions apply, check the cluster JSON for sufficient information to write a coherent `task_summary`.
If it has sufficient information on its own, give `verdict: "propose"`.

## Testability

`workflow-audit`'s `SKILL.md` reads this file to make the literal prompt for the judge subagent.
Readers who examine judge output also read this file.
If you change the schema or the three conditions above, update the two consumers.
