# Workflow-audit judge contract

The workflow-audit skill gives this prompt template to a fresh sonnet judge.
The judge reads `cluster_ngrams.py` output. It proposes or rejects candidate
skills.

## What the judge receives

Exactly two inputs, nothing else:

1. **The cluster JSON** — the full stdout object from `cluster_ngrams.py`
   (`{"scanned_sessions","clusters":[{"ngram","n","count","sessions"}],"diagnostics"}`).
2. **A list of existing skill names and descriptions** — the `name` and
   `description` frontmatter fields of every skill already in the repo (e.g.
   read from each `skills/*/SKILL.md` frontmatter block).

The judge must use only these two inputs. It must not request or reconstruct
other content. It can use tool names, `head` strings, counts, session IDs,
and n-gram lengths from the cluster JSON. `scan_transcripts.py` has already
put the `head` strings on a privacy allowlist. The judge cannot read
transcripts, file contents, or other prose. If a verdict needs the meaning
of command arguments beyond the allowed `head`, the judge must reject the
cluster or state the limit. It must not guess.

## Per-cluster output

For every cluster in the input, the judge returns one object:

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

- `verdict` is exactly `"propose"` or `"reject"`.
- `reject_reason` is non-empty when `verdict` is `"reject"`. It is empty
  when `verdict` is `"propose"`.
- Build `task_summary` and `proposed_description` only from the tool names,
  heads, and counts in the cluster. Do not invent details or user intent.
  "Sessions repeatedly do X then Y" is allowed. "The user was debugging a
  flaky CI job" needs a whitelisted head that says so.
- `proposed_name` is required only when `verdict` is `"propose"`; kebab-case.

## Mandatory rejection criteria

The judge must reject a cluster (not propose a skill for it) when any of the
following holds. These are checked in order; the first that fires is the
`reject_reason`.

1. **Project-specific convention, not a generalisable task.** The cluster
   reflects a convention specific to one repo or project (e.g. a recurring
   command tied to one project's build script) rather than a task a user
   would want repeated across different projects. This is the
   general skill-design rule: don't create skills for project-specific
   conventions.
2. **Already covered by an existing skill.** The cluster's task overlaps
   with the name/description of a skill already in the supplied existing-skill
   list. Skip it — do not propose a duplicate or near-duplicate.
3. **Tooling-mechanics artifact, not a user task.** The cluster is an
   artifact of the loop's own plumbing (e.g. its own `git`/`gh` commands for
   opening PRs, its own review/merge/push scripts) rather than something a
   user asked for. These n-grams show up because the orchestrator or a
   worker always does them, not because they represent a repeatable user
   intent.

Use `verdict: "propose"` only if no rejection rule applies. The cluster
JSON must also support a coherent `task_summary`.

## Testability

The `workflow-audit` skill reads this file to build the judge prompt.
People also read it to review judge output. Update the skill when this
file's output schema or rejection rules change.
