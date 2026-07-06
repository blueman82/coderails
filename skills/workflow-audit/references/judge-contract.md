# Workflow-audit judge contract

The prompt template handed to a fresh sonnet judge at the propose stage of the
workflow-audit skill. The judge turns `cluster_ngrams.sh` output into
propose/reject verdicts for candidate skills.

## What the judge receives

Exactly two inputs, nothing else:

1. **The cluster JSON** — the full stdout object from `cluster_ngrams.sh`
   (`{"scanned_sessions","clusters":[{"ngram","n","count","sessions"}],"diagnostics"}`).
2. **A list of existing skill names and descriptions** — the `name` and
   `description` frontmatter fields of every skill already in the repo (e.g.
   read from each `skills/*/SKILL.md` frontmatter block).

The judge must not request, infer, or reconstruct any content beyond these
two inputs. Its fixed vocabulary is limited to what appears in the cluster
JSON: tool names, `head` strings (already privacy-whitelisted by
`scan_transcripts.sh`), counts, session ids, and n-gram lengths. It has no
access to transcript content, prose, file contents, or any other detail —
if a judgement would require knowing what a command's arguments *meant*
beyond its whitelisted head, the judge cannot make that judgement and must
reject or note the limitation, not guess.

## Per-cluster output

For every cluster in the input, the judge returns one object:

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

- `verdict` is exactly `"propose"` or `"reject"`.
- `reject_reason` is required (non-empty) when `verdict` is `"reject"`; empty
  string when `"propose"`.
- `task_summary` and `proposed_description` must be constructed only from the
  tool names, heads, and counts present in the cluster — no invented
  specifics, no assumed intent beyond what those strings say. "Sessions
  repeatedly do X then Y" is fine; "the user was debugging a flaky CI job" is
  not, unless a whitelisted head literally says so.
- `proposed_name` is required only when `verdict` is `"propose"`; kebab-case.

## Mandatory rejection criteria

The judge must reject a cluster (not propose a skill for it) when any of the
following holds. These are checked in order; the first that fires is the
`reject_reason`.

1. **Project-specific convention, not a generalisable task.** The cluster
   reflects a convention specific to one repo or project (e.g. a recurring
   command tied to one project's build script) rather than a task a user
   would want repeated across different projects. This is the
   `writing-skills` rule: don't create skills for project-specific
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

A cluster that fails none of these three, and where the judge has enough
information from the cluster JSON alone to write a coherent `task_summary`,
gets `verdict: "propose"`.

## Testability

This file is read by both `workflow-audit`'s `SKILL.md` (to construct the
literal prompt handed to the judge subagent) and by humans reviewing judge
output. Any change to the per-cluster schema or the three rejection criteria
above must be reflected in both consumers.
