# workflow-audit → Dashboard Queue Consumption Seam — Contract

**Date:** 2026-07-07
**Status:** Contract normative; producer (WU1) and renderer (WU2) shipped and merged
**Sub-project:** workflow-audit × dashboard queue-mode integration (builds on
sub-project 4's queue contract)

## Context

This document builds on the generic `QueueFileEntry` envelope frozen in
[`2026-07-06-assistant-link-panel-design.md`](2026-07-06-assistant-link-panel-design.md).
That contract is reused **verbatim** here — no schema change, no new field,
no new file format. This document adds exactly one new `toolName` value to
the existing generic queue: `"workflow-audit:propose-skill"`.

Two pieces already shipped and are described here, not proposed:

- **WU1** (merged, PR #43): `skills/workflow-audit/scripts/write_queue_entry.sh`,
  invoked from `workflow-audit`'s SKILL.md section 5 ("Queue-mode output
  (optional)"), writes one `QueueFileEntry` file per judge `verdict:"propose"`
  candidate.
- **WU2** (merged, PR #44): `AssistantLinkPanel.tsx` renders those entries
  readably (proposed name/description/task summary/session count), instead of
  as an opaque `JSON.stringify` blob — via the existing Approve/Deny buttons
  and `POST /api/queue` path, unchanged.

This document (WU3) is the third and final piece: the **consumption seam**
for the not-yet-built routines runner that will eventually act on an approved
entry.

## The `workflow-audit:propose-skill` toolInput contract

A `QueueFileEntry` with `toolName: "workflow-audit:propose-skill"` carries a
`toolInput` built from exactly six fields, all drawn from the judge-contract's
own output vocabulary (`skills/workflow-audit/references/judge-contract.md`) —
the same D2 privacy whitelist `scan_transcripts.sh` and `cluster_ngrams.sh`
already enforce:

| Field | Type | Provenance |
|---|---|---|
| `cluster_ngram` | `string[]` | the recurring tool-use n-gram, e.g. `["Bash:git log", "Bash:git push", "Skill:prime"]` |
| `count` | `number` | the originating cluster's session-recurrence count |
| `sessions` | `string[]` | session-id strings from the originating cluster |
| `task_summary` | `string` | judge's one-line description of the observed pattern |
| `proposed_name` | `string` | judge's proposed skill name |
| `proposed_description` | `string` | judge's proposed skill description |

No other field is ever present. `write_queue_entry.sh` builds `toolInput` by
explicit `jq -n` field construction — a structural whitelist, not a filter —
so any stray field on the piped judge-verdict object (e.g. a hypothetical
`raw_transcript_line`) is dropped, never copied through.

Worked example (the `git-log-push-prime` fixture):

```json
{
  "hash": "<sha256 hex of canonicalised toolInput>",
  "toolName": "workflow-audit:propose-skill",
  "toolInput": {
    "cluster_ngram": ["Bash:git log", "Bash:git push", "Skill:prime"],
    "count": 3,
    "sessions": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"],
    "task_summary": "Sessions repeatedly run `git log`, then `git push`, then invoke the `prime` skill (seen in 3 sessions).",
    "proposed_name": "git-log-push-prime",
    "proposed_description": "Use when a session needs to review recent commits, push, and load project context in sequence — a pattern seen across 3 sessions."
  },
  "createdAt": 1720389600000,
  "status": "pending"
}
```

`hash` is `sha256(JSON.stringify(sortKeysDeep(toolInput)))` hex — identical
recipe to `assistant-agent`'s `gate/sendGate.ts`. `write_queue_entry.sh`
computes it as `jq -S -c .` (sorted-key compact JSON) piped through
`shasum -a 256`, which is canonically equivalent to the TypeScript recipe for
this flat `toolInput` shape.

## Consumption seam contract (the routines runner — not built by this document)

The routines runner is a separate, unbuilt sub-project. This section is its
contract, not its implementation.

**Filter.** The runner selects queue entries matching:

```
status === "approved" && toolName === "workflow-audit:propose-skill"
```

**Re-validate before acting.** Before treating a matched entry as a valid
approval, the runner MUST recompute `sha256(jq -S -c <toolInput>)` (or the
equivalent `sortKeysDeep` + `JSON.stringify` + sha256 recipe) over the
entry's own `toolInput` and compare it against the entry's stored `hash`
field. This guards against a stale approval bound to a since-mutated
`toolInput` — the approval is bound to the content it covered at write time,
not to the file's current contents. A hash mismatch is a distinct, logged
rejection (e.g. `hash_mismatch:<hash>`), never treated as a soft warning and
never treated as license to proceed with a "close enough" match.

**Unparseable entries are also a distinct rejection.** A file that fails
`parseQueueEntry` (`skills/dashboard/app/src/lib/collect/queue.ts`) — missing
field, wrong type, unrecognised `status` — is a separate logged rejection
(e.g. `unparseable_entry:<filename>`) from a hash mismatch. Both are
rejections, not creates; neither is swallowed silently.

**On successful re-validation.** Only then does the runner drive
`coderails:writing-skills`'s full process for the proposed skill: RED/GREEN/
REFACTOR against a fresh baseline-pressure-test subagent, landed via its own
branch and PR through the full gate sequence (`test_gate` →
`pr-review-toolkit:review-pr` → security review → `post-review` → pr-scope
evals → merge) — `workflow-audit` SKILL.md section 8, "Create step — one
skill at a time". The runner never writes straight to `main`, and never
writes into a user's personal `~/.claude/skills` directory — a created skill
is always a repo skill, landed through the same gates any other coderails
skill change goes through.

## Honesty requirement — superseded, read this before assuming the old claim still holds

**This section originally stated that clicking "Approve" on a
`workflow-audit:propose-skill` queue entry changed only that entry's
`status` field, in place, and triggered nothing else. That claim is no
longer true.** A later loop (loop 2) built the consumption seam this
document specified above as a contract, and clicking Approve now **does**
trigger the routines runner described above: the dashboard's
`POST /api/queue` route claims the approved entry and spawns a detached
headless build that authors the proposed skill via skill-creator and opens
a PR through the full gate sequence. See
[`2026-07-07-approve-build-runner.md`](2026-07-07-approve-build-runner.md)
for the runner's full contract — trigger condition, sidecar schema, hash
re-validation, concurrency handling, and the threat-model honesty note that
document carries in its place.

The filter → re-validate → create sequence this section specified above is
exactly what the runner now implements: `status === "approved" && toolName
=== "workflow-audit:propose-skill"`, a hash re-validation before any action
is taken, and — on success — the same `writing-skills` RED/GREEN/REFACTOR
process landed via branch + PR + full gates that `workflow-audit`'s SKILL.md
section 8 always specified. The one deliberate change from what was
originally proposed here: the runner never reaches `/coderails:merge`. It
stops at an open PR with gates green; the owner merges by hand (rationale in
the new spec doc's §5).

Zero approvals, or approved entries whose build fails and is never retried,
remain valid, complete states — there is no nag, no implicit timeout that
force-converts a stalled or failed build into a merge.

## Non-goals

- No change to the dashboard collector, `/api/queue` route, or Approve/Deny
  button wiring — all already shipped (sub-project 4) and untouched by WU1,
  WU2, or this document.
- No scheduling or cron — that is the routines sub-project's own scope, not
  this seam's.
- No poller or consumer process is built here. The secretary gate's
  in-process ~500ms poll model does not transfer to this seam: no live
  process is waiting at the moment a dashboard Approve click happens, so
  there is nothing for a poller to poll until the routines runner exists.
- No TTL or dismissal machinery — matches the base queue contract's own
  explicit non-decision (no `expired`/`timeout` status in the file; see
  `2026-07-06-assistant-link-panel-design.md`).
- The routines runner's own implementation is out of scope for this
  document — this is its consumption contract, to be picked up when that
  sub-project is built.
