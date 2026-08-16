# Claude evidence artifact handoff — Mac mini to Codex laptop

Neither `parallel_review.sh` nor `parallel_review_join.sh` implements or assumes any
specific cross-machine transport. Both take a caller-supplied output path and never
reach outside it. This file names the interface contract those scripts expect on
either side of a handoff — it does not invent a transport, because none exists in
this codebase today and none should be fabricated here.

## What must cross the machine boundary

Exactly one file: the Claude evidence record `parallel_review::run` writes (see
`hooks/scripts/lib/parallel_review.sh`), shaped per the frozen spec's §3.3:

```json
{
  "schema_version": 1,
  "gate": "parallel-review",
  "node": "<node-id>",
  "provider": "claude",
  "run_id": "...",
  "revision": "...",
  "head": "...",
  "frozen_input_digest": "<hex sha256>",
  "digest_algorithm": "sha256",
  "verdict": { "outcome": "approve" | "reject", "reasoning": "<non-empty string>" },
  "written_at": "<ISO-8601>"
}
```

## Path convention (spec §3.3/§4.2, not enforced by code — a naming discipline)

`<loop-state-dir>/parallel-review/<node>/<run_id>/claude.json`

The join (`parallel_review_join::evaluate`) takes this as a plain path argument — it
does not care how the file arrived, only that it exists, is readable, and its
`run_id`/`revision`/`head`/`frozen_input_digest` fields match the canonical §3.1
record the same `run_id` produced. Preserving the exact `<run_id>` segment across
the handoff is what lets the Codex-laptop join match it against its own
independently-computed canonical record for the identical run.

## What this repo does NOT provide

- No sync mechanism (rsync/scp/shared drive/object store) between the two machines.
- No verification step baked into the transport itself — file-integrity checking is
  the join's own job (§6.3 mismatched-evidence, §6.2 stale-evidence), not the
  handoff's.
- No committed example/sample artifact — see "why nothing is attached" below.

## Why nothing is attached to this doc

A real Claude evidence record is only valid when its `run_id`/`revision`/`head`
triple matches an actual run, and its `frozen_input_digest` matches an actual
frozen artifact from that run. A canned or hand-typed "example" file, if ever
mistaken for a real evidence record, would satisfy `parallel_review_join::evaluate`'s
structural checks while attesting to nothing — decoupled from any Claude run that
occurred. Fabricating one to make the transport step "visible" here would produce
exactly the failure mode §3.1's canonical-digest requirement exists to prevent, so
none is committed. The real evidence record only comes to exist as the direct
output of `parallel_review::run` against a real frozen artifact.

## Operator responsibility (outside this codebase)

1. On the Mac mini: run `parallel_review::run` for the `claude` leg of a real
   `parallel-review` node, writing to a path under `<loop-state-dir>/parallel-review/<node>/<run_id>/claude.json`.
2. Transport that one file to the Codex laptop, preserving the `<node>/<run_id>/`
   path segments (the mechanism — scp, a shared mount, a sync tool — is an
   operational choice, not a code contract this repo defines).
3. On the Codex laptop: the neutral join reads it via that path, alongside the
   locally-produced `codex.json` and the canonical `<run_id>` digest record, and
   evaluates per `parallel_review_join::evaluate`'s existing four-check contract
   (`hooks/scripts/lib/parallel_review_join.sh`) — no new logic required, only a
   real file at a real path.

## Ceiling this handoff inherits

Per `hooks/scripts/lib/parallel_review_join.sh`'s own `ponytail:` comment: the
canonical §3.1 digest record does not itself carry `run_id`/`revision`/`head`, so
the join trusts that the SAME triple was supplied to both the fan-out digest write
and the join evaluation call. A cross-machine handoff makes this trust boundary
literal — whichever script invokes `parallel_review_join::evaluate` on the Codex
laptop must independently know the correct `run_id`/`revision`/`head` for the run
being joined, not read it back from any artifact. This is the same disclosed
limitation carried since PR #415, now made explicit at the point where it becomes
operationally load-bearing.
