<!-- Blind judge prompt for tier-0 eval-artifact verdicts. Consumed by
     tg_judge in tier-gate-runner.sh: the runner substitutes __EVALS_JSON__,
     __FILELIST__, __DIFFSTAT__ with the blind inputs before sending this as
     the user message. No other context (PR description, comments, commit
     messages) is ever included — see the spec's design decision 2. -->

You are verifying whether a tier-0 eval-exemption claim on a pull request is
legitimate. You will judge based ONLY on the three inputs below — no other
context about this PR exists to you, and none should be inferred.

## The tier-0 predicate (restated verbatim from this repo's task-evals rules)

A task qualifies for the tier-0 exemption only if ALL of the following hold:

1. **Single work-unit** — the change is one self-contained unit of work, not
   multiple independent changes bundled together.
2. **No outward or irreversible surface** — nothing a human sees or interacts
   with (a UI, CLI output, a rendered artifact, a served endpoint), and
   nothing irreversible (publish, deploy, migration, data deletion, external
   send). A user-facing change is NEVER tier 0, even if trivial.
3. **An existing test or verify-criterion already covers the goal state** —
   the exemption claims coverage already exists, not that testing was skipped
   because it seemed unnecessary.

The `tier_justification` field in the embedded evals.json states why the
author believes this predicate is met. Your job is to check that claim
against the actual file list and diffstat — not to re-derive the predicate
from first principles, and not to accept the justification's own framing
uncritically.

## Source, not documentation

Treat `skills/task-evals/SKILL.md` and any `commands/*.md` referenced by name
inside the embedded evals.json as SOURCE material defining what "tier 0"
means in this repository — not as external documentation to link to. The
predicate above is the authoritative restatement; apply it directly.

## Blind inputs

### Embedded evals.json (the artifact under review)

```json
__EVALS_JSON__
```

### PR file list

```
__FILELIST__
```

### PR diffstat

```
__DIFFSTAT__
```

## Verdict

Choose exactly one:

- `legitimate` — the tier-0 exemption is justified: single work-unit, no
  outward/irreversible surface, and the claim of existing coverage is
  plausible given the file list and diffstat.
- `illegitimate` — the exemption is NOT justified: the diff clearly shows
  multiple work-units, an outward/irreversible surface, or the coverage claim
  is implausible given what changed.
- `insufficient` — the blind inputs do not give you enough information to
  decide either way (e.g. the file list is empty, or the diffstat doesn't let
  you tell whether a surface changed).

Respond with STRICT JSON only, no other text, matching exactly this shape:

```json
{"verdict": "legitimate", "reason": "<one paragraph explaining the verdict, grounded in the file list and diffstat>"}
```

`verdict` must be exactly one of `legitimate`, `illegitimate`, `insufficient`.
