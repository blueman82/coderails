# Workflow-audit judge contract

This is the prompt template for a new sonnet judge in the workflow-audit
proposal step. The judge turns `cluster_ngrams.py` output into a propose or
reject verdict for each candidate skill.

## What the judge receives

Use only these two inputs.

1. **The cluster JSON** — the full stdout object from `cluster_ngrams.py`
   (`{"scanned_sessions","clusters":[{"ngram","n","count","sessions"}],"diagnostics"}`).
2. **A list of existing skill names and descriptions** — the `name` and
   `description` frontmatter fields of each skill in the repo (e.g.
   read from each `skills/*/SKILL.md` frontmatter block).

The judge must not query other sources for content. It must not infer or reconstruct that content. Its fixed vocabulary comes only from the cluster JSON. That JSON includes tool names, `head` strings that `scan_transcripts.py` permits, counts, session IDs, and n-gram lengths.

The judge has no access to transcript content, prose, file contents, or other information. If the permitted head cannot show the meaning of a command’s arguments, the judge must reject the cluster or report that limit. Do not guess.

## Per-cluster output

For each cluster in the input, the judge gives one object.

```json
{
  "cluster_ngram": ["Bash:git log", "Bash:git push", "Skill:prime"],
  "verdict": "propose",
  "reject_reason": "",
  "task_summary": "Sessions repeatedly run `git log`, then `git push`, then invoke the `prime` skill (seen in 3 sessions).",
  "proposed_name": "git-log-push-prime",
  "proposed_description": "Use when a session needs to review recent commits, push, and load project context in sequence — a pattern seen across 3 sessions."
}
```

- `verdict` must be `"propose"` or `"reject"`.
- For a `verdict` of `"reject"`, give a non-empty `reject_reason`. For `"propose"`, use an empty string.
- Write `task_summary` and `proposed_description` only from the tool names, heads, and counts in the cluster. Do not invent facts or infer intent. "Sessions repeatedly do X then Y" is correct. Use "the user was debugging a flaky CI job" only if a permitted head says this.
- For a `verdict` of `"propose"`, give a `proposed_name` in kebab-case.

## Mandatory rejection criteria

Check these conditions in sequence. If one applies, reject the cluster. Give the first applicable condition in `reject_reason`.

1. **Convention for one repo or project.** For example, a command for one project's build script does not apply across projects. Follow the `superpowers:writing-skills` rule. Do not make skills for project-specific conventions.
2. **Overlap with a skill in the list.** Compare the task to the names and descriptions in the supplied list. Do not propose a duplicate or near-duplicate.
3. **Artifact of the loop tools.** For example, the loop uses `git` or `gh` to open PRs. It uses its own scripts to check, merge, or push them. The orchestrator or a worker does these steps as part of the loop. They do not show a repeatable user task.

A cluster that fails none of these three, and where the judge has sufficient
information from the cluster JSON alone to write a coherent `task_summary`,
gets `verdict: "propose"`.

## Testability

The `workflow-audit` skill uses `SKILL.md` to assemble the judge prompt from this file. A human can also read this file to check the judge output. If the per-cluster schema or the three refusal criteria change, update the prompt and the documentation.
