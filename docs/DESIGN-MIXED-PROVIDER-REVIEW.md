# Design: mixed-provider (`parallel-review`) graph policy

Status: **DESIGN SPEC — not implemented.** No file this spec references
(`skills/index.yaml`, `skills/agentic-loop/execution-graph.md`,
`codex/runtime/graph.py`, `hooks/scripts/lib/graph_dispatch.sh`) is edited by
this document or by adopting it. Every schema below is a proposal, shown as an
example. Implementation is blocked until this spec and its frozen acceptance
evals exist and pass independent review (per the authorising instruction).

## 0. Problem and scope

Coderails has two provider runtimes — Claude (native skills/hooks) and Codex
(`codex/runtime/graph.py`) — that today run **single-provider per graph
node**: a node's `graph_role` in `skills/index.yaml` picks one implementation,
routed via `claude:` or `codex:` path+status fields
(`hooks/scripts/lib/skill_route.sh` resolves exactly those four fields per
skill_id and ignores unknown sibling keys `(verified)`).

This spec adds ONE new graph policy: `parallel-review`. Under it, both
providers independently review the **same frozen stage artifact**, and a join
node applies a release policy — default unanimous approval, any disagreement
or rejection is a durable hard-stop for human adjudication.

**In scope:** the `parallel-review` mode only, its schema additions, its
record shapes, its join semantics, and the Claude/Codex implementation
boundary.

**Explicitly out of scope (deferred, not designed here):**
- `dual-execution` (both providers *implement*, not just review) — name
  reserved, not specified. See Open Questions.
- Which stages beyond one named pilot node get mixed review.
- Any new Codex `REQUIRED_GATES` gate *kind* — `REQUIRED_GATES` and
  `GATE_RESULTS` are fixed tuples in `codex/runtime/graph.py` lines 22–23
  `(verified)`; adding a gate kind is a Codex-runtime code change, not a
  shared-spec concern. This spec defines the join's **record shape** only —
  what a future Codex change would produce/consume.

**Pilot node, at freeze time:** `U4b-review[i]` is named as the intended
pilot — it is the existing single-provider review node
(`skills/agentic-loop/execution-graph.md` row: "required review Skill,
security/deploy review when triggered, and SHA-bound post-review artifact
exist" `(verified)`), the natural extension point per the authorising
instruction. **At freeze, `mode: parallel-review` is applied to ZERO nodes** —
this spec does not edit `index.yaml`, so no node actually carries the new
field yet. "Pilot" names the *first candidate* for a future, separately
reviewed change, not a live assignment.

---

## 1. The `mode` enum

```yaml
# Proposed enum, for a future per-node or per-policy declaration (see §2 for
# exactly where it is proposed to live in the schema).
mode: parallel-review   # the ONLY legal value today
```

No other value is defined. `dual-execution` is named only to be excluded —
see §8 Open Questions. An implementation MUST reject any `mode` value other
than `parallel-review` as invalid, not silently ignore it.

---

## 2. Schema addition to `skills/index.yaml` (proposed, not applied)

### 2.1 Where it does NOT go

The task's own illustrative example nests `mode`/`reviewers`/`join` under a
top-level `U4b-review:` key. That shape does not match the real file
`(verified, read this session)`: `skills/index.yaml` is keyed by **skill/agent
id** under a single `skills:` map (e.g. `deploy-safety-reviewer:`,
`source-auditor:`, `spec-reviewer:`), and each entry independently carries a
`graph_role` field pointing *at* a node id. Node ids are **not** top-level
keys, and `graph_role` is already many-to-one: `deploy-safety-reviewer`,
`source-auditor`, and `post-review` (the command) all carry
`graph_role: U4b-review` today `(verified)`. Attaching `mode: parallel-review`
to a single skill/agent entry would be ambiguous about which of several
entries sharing that `graph_role` the policy applies to.

### 2.2 Where it does go: a new top-level `graph_policies:` section

A new top-level map, sibling to `skills:`, keyed by **node id** (not skill
id). This composes cleanly with the many-to-one `graph_role` relationship
(the policy describes the *node*, independent of how many skill entries route
into it) and requires zero change to any existing `skills:` entry's shape —
`required_inputs`, `output_contract`, `claude:`/`codex:` path+status all stay
exactly as they are.

```yaml
# skills/index.yaml — PROPOSED ADDITION, not applied by this spec.
# Sibling top-level key to the existing `skills:` map.

graph_policies:
  U4b-review:
    mode: parallel-review
    reviewers:
      - provider: claude
        route: agents/deploy-safety-reviewer.md
      - provider: codex
        route: codex/agents/deploy-safety-reviewer.md
    join:
      node: J4b-review          # see §4 for why the join needs its own node id
      policy: unanimous          # the only policy value defined today (§5)
    frozen_input:
      digest_algorithm: sha256   # see §3.1
```

Rules for this section, stated as constraints a future implementation must
satisfy:

- A `graph_policies` entry's key MUST be a node id that already exists in
  `execution-graph.md`'s contract table (e.g. `U4b-review`) — this spec does
  not introduce new base node ids, only a join node addition (§4).
- `reviewers[].provider` MUST be exactly one of `claude`/`codex`, matching the
  vocabulary `skill_route.sh` already accepts `(verified)`; the schema
  reuses this vocabulary rather than inventing a third.
- `reviewers[].route` is a path, in the same spirit as `skills:`'s existing
  `claude.path`/`codex.path` fields — it names which agent body each provider
  runs for this review, NOT a new resolution mechanism. It is not consumed by
  `skill_route.sh` today (that script only reads a `skill_id`'s own
  `claude:`/`codex:` sub-block `(verified)`); a future implementation must
  either extend that resolver or add a sibling one — this spec does not
  decide which, since that is an implementation-owned detail, not a contract
  detail.
- `join.node` is a NEW node id, never one of the two `reviewers[].provider`'s
  own nodes — required by graph.py's own constraint (§4).
- Additive-only: `skill_route.sh`'s `awk` block-scanner reads only a matching
  skill_id's own `claude:`/`codex:` sub-fields and stops at the next
  same-indentation key `(verified)`; it does not parse or reject a sibling
  `graph_policies:` top-level key. This is a narrow claim about one resolver,
  not a guarantee every future or third-party consumer of `index.yaml`
  ignores unknown top-level keys `(inferred — only skill_route.sh was read
  this session)`.

---

## 3. Input / output / evidence / provenance records

### 3.1 Frozen-input digest (REQUIRED, not optional)

Both reviewers must bind to the exact same artifact bytes. Without a digest
neither reviewer chose, "mismatched evidence" (§6) is undetectable — two
reviewers could each attest a self-computed digest of two *different*
artifacts and the join would see two matching-shaped records with no way to
tell they diverged from the truth.

```json
{
  "schema_version": 1,
  "node": "U4b-review[i]",
  "artifact_ref": "<path or PR#+SHA identifying the frozen stage artifact>",
  "digest_algorithm": "sha256",
  "digest": "<hex sha256 of the exact artifact bytes>",
  "distributed_at": "<ISO-8601 timestamp>",
  "distributed_by": "<neutral dispatcher identity — see §7>"
}
```

This record is written ONCE, at fan-out time, by the neutral dispatch step
(§7) — never by either reviewer. It is the canonical digest every reviewer
attestation (§3.2/§3.3) is compared against. This is the third artifact the
join needs to detect mismatched-vs-truth, not just mismatched-vs-each-other
(see §6 "Mismatched evidence").

### 3.2 Provenance triple — reused, not reinvented

`codex/runtime/graph.py`'s live-gate path already requires a `run_id` /
`revision` / `head` triple bound into every gate artifact
(`_metadata_error`, lines 298–306 `(verified)`; `_invoke`'s artifact
validation, line 331 `(verified)`). This spec reuses that triple's *concept*
for both providers rather than inventing a parallel scheme, with one
disambiguation:

**`revision` is overloaded in `graph.py` today** — `_metadata_error` requires
the `_run` triple's `revision` to be a non-empty **string** (line 301
`(verified)`), while `_persist` separately writes `graph["revision"]` as an
**integer** state-file counter (lines 449–454 `(verified)`). These are two
different things with the same field name. This spec's provenance triple
uses the **string** form (the `_run`-triple sense — e.g. a git SHA or a
task/session revision label), NOT the integer state-counter. A future
implementation MUST NOT compare a reviewer's `revision` string against the
state file's integer counter; they are different values with the same name
in the existing codebase.

### 3.3 Per-provider evidence record shape

Both providers write a structurally identical evidence record. Codex's
already has a home (its own gate-artifact convention); Claude has no
equivalent mechanism today `(verified — no comparable provenance artifact
found in AGENTS.md's hook/skill map)`, so this spec defines what Claude's
record needs, sourced from Claude's own `progress.json`/session state so the
join compares like-for-like:

```json
{
  "schema_version": 1,
  "gate": "parallel-review",
  "node": "U4b-review[i]",
  "provider": "claude",
  "run_id": "<session id or loop invocation id>",
  "revision": "<git SHA or task revision label — string, never the graph.py state-counter int>",
  "head": "<git head SHA the reviewer ran against>",
  "frozen_input_digest": "<hex sha256 the reviewer attests it reviewed>",
  "digest_algorithm": "sha256",
  "verdict": { "...": "see §3.4" },
  "written_at": "<ISO-8601 timestamp>"
}
```

The Codex-side record is the same shape with `"provider": "codex"` and its
`run_id`/`revision`/`head` sourced the way Codex's existing live-gate path
already sources them (`_metadata_error`'s `_run` mapping `(verified)`) — no
new Codex provenance mechanism, reuse of the existing one.

Both records carry their OWN `frozen_input_digest` (self-attested) — this is
what the join compares against the canonical §3.1 record to detect
mismatched evidence (§6), and against each other to detect a distribution
inconsistency.

### 3.4 Verdict shape (minimum)

```json
{
  "outcome": "approve",
  "reasoning": "<free-text or structured findings — minimum: a non-empty string>"
}
```

`outcome` MUST be exactly `"approve"` or `"reject"`. No third value (e.g.
"needs-changes") is defined at freeze — that widening is deferred, not
designed here, to keep the join's policy in §5 binary and unambiguous.

---

## 4. Atomic fan-out / join semantics

### 4.1 The join is a distinct node, never inline in either reviewer's node

`prepare_implementations` in `codex/runtime/graph.py` raises `"multiple gates
map to node"` if two gate mappings resolve to the same graph node (lines
199–201 `(verified)`). Two independent review gates (Claude's and Codex's)
therefore CANNOT both map onto the single existing `U4b-review[i]` node — the
join MUST be a separate node id. This spec names it `J4b-review[i]`,
following the existing `J`-prefix join convention (`J2`, `J2.8`,
`J12-all-units` `(verified, execution-graph.md)`).

Naming it with the `J` prefix and `[i]` templating is not cosmetic — it is
load-bearing for the staged contract-table change (§4.3): `build_graph` in
`graph.py` auto-registers any node whose name starts with `J` as a join with
`mode: "all"` over its computed inputs (lines 160–164 `(verified)`), and
`_expand` already handles `[i]` per-work-unit templating (lines 110–113
`(verified)`). A correctly named `J4b-review[i]` staged row gets correct
all-inputs join gating from the existing parser with **zero** `graph.py` code
change.

### 4.2 Disjoint write paths — the closable half of independence

The task frames "neither reviewer sees the other's verdict before
submitting" as needing to be a structural property, not prose. Per
`AGENTS.md`'s own enforcement-ceiling section `(verified, read this session)`:
a hook or dispatch mechanism runs inside the same trust domain as the agent
it gates — "there is no privilege boundary between them" — and sandboxing
(where used at all) contains **filesystem writes**, not reads. That ceiling
applies here exactly as stated for hooks; this spec closes what is closable
under it and names what is not.

**Closable — specified as a mechanism, not a rule:**
- Each provider's evidence record (§3.3) is written to a path scoped to that
  provider and this run only, e.g. `<loop-state-dir>/parallel-review/<node>/<run_id>/claude.json`
  and `.../codex.json` — disjoint write roots per provider.
- Neither provider's declared write-scope for this review step includes the
  sibling's path. (Enforcement mechanism for that scoping — a sandboxed
  worker's `allowWrite` list, a Codex dispatch's own cwd/output-path
  contract, or both — is an implementation detail owned by each provider's
  own build, not specified here; this spec specifies WHICH paths must be
  disjoint, not how each runtime enforces it.)
- The join (§4.1) is the only party that reads both records, and only after
  both exist (§4.3 sequencing).

**Not closable — named as an open residual, not silently assumed away:**
- A provider that CHOSE to read the sibling's write path before submitting
  its own verdict is not prevented from doing so by anything in this design.
  `AGENTS.md`'s stated ceiling is explicit that this repo's enforcement
  mechanisms audit and redirect a cooperating agent; they do not constitute a
  privilege boundary against a provider that reads outside its declared
  scope. This spec does not invent a sealed-envelope, timing-lock, or
  encryption mechanism to close this — nothing in the current repo provides
  one, and manufacturing one here would be unimplemented, untested
  contract surface, contrary to the "minimal frozen contract" goal. Flagged
  explicitly, not left as unexamined prose: **residual risk — a
  non-cooperating provider can read the sibling's evidence path before
  writing its own verdict; disjoint write paths prevent accidental
  collision, not deliberate peeking.**

### 4.3 Sequencing: fan-out, then join-reads-only-after-both

```
U4[i] --> U4b-review[i]  (unchanged existing node; frozen-input distribution point)
                |
                +--> [claude reviewer writes claude.json]  --+
                |                                             |
                +--> [codex reviewer writes codex.json]   ----+--> J4b-review[i]
```

1. `U4b-review[i]` (existing node, unchanged shape) becomes the fan-out point:
   the neutral dispatcher (§7) computes and writes the §3.1 frozen-input
   digest record, then triggers both reviewers against the identical
   artifact.
2. Each reviewer writes ONLY its own evidence record (§3.3), never touching
   the sibling's path, never reading the join's authoritative record before
   it exists (it does not exist yet at this point by construction — §7).
3. `J4b-review[i]`'s node-level dispatchability is gated by graph.py's
   existing join semantics: a join's predecessors are its declared `inputs`,
   and `ready()` requires every predecessor to be in `{done, skipped}`
   before the join is dispatchable (`ready()`, lines 235–240 `(verified)`).
   This governs WHEN the join node runs, not WHETHER the evidence it reads is
   actually present — `ready()` treats a `skipped` reviewer the same as a
   `done` one, so it does not by itself guarantee `claude.json`/`codex.json`
   exist on disk (see §6.1's `missing-evidence` check, which the join must
   perform explicitly, independent of node outcome).
4. The join first applies §6.1's both-vs-one-skipped check. If both
   predecessors skipped, the join skips too (no evidence was ever expected).
   Otherwise it independently verifies the expected evidence file(s) exist,
   reads them, applies the release policy (§5), and writes ITS OWN record
   (§5.2) — never overwriting either reviewer's evidence file.

### 4.4 Staged contract-table constraints (not applied by this spec)

If and when `execution-graph.md`'s table is actually edited (a future,
separately reviewed change — **not this spec**), the new rows must satisfy
`load_contract`'s parser:

- Every node id referenced in a `Node / true prerequisites` cell must appear
  inside backticks and be a declared id somewhere in the same table, or
  `load_contract` raises `references undeclared node(s)` (lines 68–71
  `(verified)`) and the Codex runtime fails to load the contract at all.
- The `Conditional skip or join` column text is load-bearing, not
  descriptive prose: `dispatch` is computed as `not any(marker in
  conditional.lower() for marker in ("no standalone work", "cross-cutting"))`
  (line 63 `(verified)`). Writing either phrase into `J4b-review[i]`'s
  conditional cell would make `execute()` auto-skip it as a non-dispatchable
  cross-cutting guard (lines 427, 433–436 `(verified)`) — silently bypassing
  the release gate this whole design exists to enforce. **This must never be
  done for the join row** — call this out explicitly in the staged rows so a
  future editor does not "fix" a hard-stop by marking the join
  cross-cutting.
- The existing table's prerequisite cells already generate edges
  (`build_graph`, lines 148–154 `(verified)`); the ` ```text ` diagram is a
  secondary edge source (`_diagram_edges`, lines 75–103). A table-only staged
  addition is sufficient; no diagram edit is required for correctness,
  though updating the diagram for human readability is good practice when
  the change is actually applied.

**Illustrative staged rows (NOT applied — for future reviewers' reference
only):**

`U4b-review[i]` (the existing node, unchanged shape) stays the true
prerequisite of BOTH new reviewer nodes below — it is the fan-out point
(§4.3) that computes and writes the §3.1 frozen-input digest record before
either reviewer runs. The staged rows do not bypass it; `U4[i]` is
`U4b-review[i]`'s own prerequisite, unchanged, not a direct prerequisite of
either reviewer node. This keeps this table and §4.3's diagram describing
the identical graph.

```text
| ID | Node / true prerequisites | Ready when | Conditional skip or join |
|---|---|---|---|
| `U4b-review-claude[i]` | `U4b-review[i]` | Claude reviewer wrote `claude.json` evidence record bound to the frozen-input digest | skip when node is not under `parallel-review` mode |
| `U4b-review-codex[i]` | `U4b-review[i]` | Codex reviewer wrote `codex.json` evidence record bound to the frozen-input digest | skip when node is not under `parallel-review` mode |
| `J4b-review[i]` | `U4b-review-claude[i]` and `U4b-review-codex[i]` | both evidence records present, fresh, and matching; join record written | disagreement or any reject is a durable hard-stop, not a retry |
```

(This table fragment is illustrative prose in this design doc only. Applying
it to the real `execution-graph.md`, and reconciling it with the existing
single-provider `U4b-review[i]` row, is explicitly deferred to the future
implementation session — see §7 for why `graph.py`'s `prepare_implementations`
forces a real decision here rather than leaving it vague.)

**Not durable until a further real-table edit reroutes downstream
prerequisites.** The real, currently-live `execution-graph.md` lists
`U4b-review[i]` — not any join node — as a direct prerequisite of `U5[i]`
(line 167: `` `U5[i]` | `U4b-review[i]` or a verified reported regression ``
`(verified)`) and of `U4b-merge-gate[i]` (line 171: `` `U4b-merge-gate[i]` |
`U4b-review[i]`, `U6[i]`, ... `` `(verified)`). The staged addition above
does not reroute either. So even once `J4b-review[i]` is staged and a
correctly-computed disagreement hard-stop is written to its own record
(§5.2), that hard-stop is NOT durable/enforced end-to-end until a future,
separately reviewed contract-table edit changes `U5[i]`'s and
`U4b-merge-gate[i]`'s true-prerequisite cells to depend on `J4b-review[i]`
instead of (or in addition to) `U4b-review[i]`. `_propagate_blocks` only
follows declared edges (§6.1) — a hard-stop on a node nothing downstream
depends on does not, by itself, block merge.

---

## 5. Unanimous approval and disagreement hard-stop

### 5.1 Default release policy

- Both reviewers' verdict `outcome == "approve"` → join outcome = `pass`.
- Either reviewer's verdict `outcome == "reject"`, OR the two verdicts
  otherwise conflict → join outcome = `hard-stop`, durable, requires human
  adjudication.

This is the ONLY policy value defined today (`join.policy: unanimous` in
§2.2's schema). No majority/weighted/single-provider-override policy is
specified — that widening is out of scope.

### 5.2 Join record shape

```json
{
  "schema_version": 1,
  "node": "J4b-review[i]",
  "policy": "unanimous",
  "frozen_input_digest": "<the canonical §3.1 digest this join validated both reviewers against>",
  "inputs": {
    "claude": { "run_id": "...", "revision": "...", "head": "...", "outcome": "approve", "verdict_ref": "<path to claude.json>" },
    "codex":  { "run_id": "...", "revision": "...", "head": "...", "outcome": "approve", "verdict_ref": "<path to codex.json>" }
  },
  "outcome": "pass",
  "hard_stop_reason": null,
  "evaluated_at": "<ISO-8601 timestamp>",
  "evaluated_by": "<neutral join-step identity — see §7>"
}
```

On disagreement or rejection:

```json
{
  "schema_version": 1,
  "node": "J4b-review[i]",
  "policy": "unanimous",
  "frozen_input_digest": "...",
  "inputs": { "claude": { "...": "..." }, "codex": { "...": "..." } },
  "outcome": "hard-stop",
  "hard_stop_reason": "conflicting-verdicts",
  "evaluated_at": "...",
  "evaluated_by": "..."
}
```

`hard_stop_reason` is one of the four negative-case labels from §6:
`missing-evidence`, `stale-evidence`, `mismatched-evidence`,
`conflicting-verdicts`. This is the ONE place the join record captures why a
hard-stop happened — cross-referenced from §6, not duplicated as a separate
mechanism.

This record is written ONCE by the join step, never overwriting either
reviewer's own evidence record (§4.2/§4.3).

---

## 6. Negative acceptance cases

Each case names what it means mechanically, and exactly which field(s) the
join checks to detect it. All four are checked at join time, in this order
(each is a distinct, non-overlapping check):

### 6.1 Missing evidence
**Mechanical meaning:** one provider's evidence record (§3.3) does not exist
at the expected path when the join attempts to read it.

**This is NOT already prevented by graph.py's existing join machinery — it
must be an explicit, first-class check at join time.** `ready()`'s predicate
(`graph.py` lines 235–240 `(verified)`) treats `"skipped"` as fully equivalent
to `"done"` for readiness purposes: `all(... nodes[item].get("outcome") in
{"done", "skipped"} ...)`. And `_propagate_blocks` (lines 345–357
`(verified)`) only escalates a node to `hard-stop` when a predecessor's
outcome is in `{"failed", "stale", "hard-stop"}` — `"skipped"` is absent from
that set. So a reviewer node that finishes as `skipped` (not `failed`) makes
the join both ready AND never blocked.

A skipped reviewer is not a hypothetical edge case here — it is the EXPECTED
outcome under two mechanisms already in this spec/codebase:
1. §4.4's own staged rows give both `U4b-review-claude[i]` and
   `U4b-review-codex[i]` a "skip when node is not under `parallel-review`
   mode" conditional.
2. `apply_work_unit_disposition` (lines 168–176 `(verified)`) unconditionally
   sets `outcome: "skipped"` on any `[i]`-templated node whenever
   `work_units` is not supplied for that run — independent of mode.

Concrete failure this design must not permit: Claude's reviewer runs and
writes `claude.json`. Codex's reviewer node is skipped (either mechanism
above). `ready()` returns `True` for `J4b-review[i]` — both predecessors are
in `{done, skipped}`. `_propagate_blocks` never touches it, since `skipped`
is not a blocking outcome. The join dispatches with only ONE evidence record
on disk and no `codex.json` on disk — exactly the missing-evidence case this
subsection exists to catch, reached via the "already handled" path the
previous version of this text relied on.

**Detection (the actual required check):** at join time, before comparing
any verdicts, the join step MUST independently confirm evidence-record
existence at the expected filesystem paths (§4.2's disjoint write roots).
Node `outcome` being terminal (`done` or `skipped`) is NOT sufficient
evidence that a record exists — it must be treated as an existence claim to
verify, not a fact to trust. This is a NEW check this spec must specify; it
is not solved by, and must not be described as solved by, existing
`ready()`/`_propagate_blocks` machinery.

This check MUST distinguish two shapes of "skipped," not collapse them:

- **Both reviewer predecessors skipped** — the whole `U4b-review[i]` instance
  was never under `parallel-review` mode (§4.4's own skip conditional), or no
  `work_units` were supplied for this run (`apply_work_unit_disposition`).
  Neither reviewer was ever expected to write evidence. The join itself MUST
  skip in this case — this is not a missing-evidence hard-stop, it is the
  correct, intentional absence of a parallel-review cycle for this instance.
- **Exactly one reviewer predecessor skipped, the other `done`** — asymmetric.
  One provider's evidence record was expected and is absent while its
  sibling's exists. THIS is `hard_stop_reason: missing-evidence`: a
  predecessor reviewer node whose outcome is `skipped` while its sibling is
  `done` MUST be treated as missing-evidence at the join, never as a silent
  pass-through equivalent to `done`.
- (Both `done` but a file is nonetheless absent from disk — e.g. a write that
  reported success but did not actually land — is also `missing-evidence`;
  file existence is the ground truth in every case, node outcome is only a
  hint.)

A join whose own dispatchability was gated on both predecessors being
`{done, skipped}` (§4.3 step 3) still runs this file-existence and
both-vs-one-skipped check before producing any outcome other than its own
skip.

### 6.2 Stale evidence
**Mechanical meaning:** a provider's evidence record's provenance
(`run_id`/`revision`/`head`, §3.2) does not match the current run's
provenance — e.g. the record is a leftover from a prior loop iteration at
the same path.
**Detection:** the join compares each reviewer record's `run_id`/`revision`/
`head` triple against the expected current-run values (the same values the
neutral dispatcher stamped into the §3.1 frozen-input record at fan-out
time). Any mismatch on any of the three fields → `hard_stop_reason:
stale-evidence`.

### 6.3 Mismatched evidence
**Mechanical meaning:** both providers submitted valid, fresh records, but
the frozen-input digest either reviewer attests (§3.3's own
`frozen_input_digest` field) differs from the canonical digest the neutral
dispatcher actually distributed (§3.1) — proving that reviewer was not
reviewing the same frozen artifact as its sibling, even if it never noticed.
**Detection:** this is exactly why §3.1's independent, dispatcher-written
digest record exists — without it, the join could only compare the two
reviewers' self-attested digests to EACH OTHER, which detects
reviewer-vs-reviewer disagreement but not reviewer-vs-truth (two reviewers
could each attest the same WRONG digest and pass a same-to-each-other-only
check). The join compares BOTH reviewers' `frozen_input_digest` against
§3.1's canonical record independently. Either one differing →
`hard_stop_reason: mismatched-evidence`.

### 6.4 Conflicting evidence
**Mechanical meaning:** both evidence records are valid and fresh (passed
6.1–6.3), but the two verdicts' `outcome` fields disagree, or either is
`"reject"`.
**This is not a new case — it is the unanimous-approval hard-stop from §5,
restated here only for completeness of the negative-case enumeration.**
Detection: `inputs.claude.outcome != inputs.codex.outcome`, or either
`outcome == "reject"` → `hard_stop_reason: conflicting-verdicts`. See §5.1
for the authoritative policy definition; this subsection does not duplicate
it, only cross-references it per the task's own instruction.

---

## 7. Claude-owned vs. Codex-owned implementation boundaries

Per the authorising instruction's explicit constraint, restated precisely:

- **Claude-owned:** `agents/`, `skills/*.md` (and their detail-carriers, e.g.
  a future `execution-graph.md` edit), `hooks/scripts/lib/*.sh` — with ONE
  named exception: `hooks/scripts/lib/graph_dispatch.sh` is carved OUT of
  Claude's implementation surface even though it lives under
  `hooks/scripts/lib/` and is today invoked by the Claude-side orchestrator
  per `execution-graph.md`'s own "Resolving and recording a wave" section
  `(verified)`. It is called out by name in the authorising instruction as a
  file neither provider's implementation may touch for this feature — treat
  it as frozen for the purposes of `parallel-review`, not as evidence of
  which provider "owns" it architecturally.
- **Codex-owned:** `codex/` files only, including `codex/runtime/graph.py`.
- **Neither imports or wraps the other's runtime.** A Claude-side reviewer
  never calls into `codex/runtime/graph.py`; a Codex-side reviewer never
  invokes a Claude skill/hook directly.

### 7.1 The one shared surface: the join

The join/comparison logic (§4, §5) is unavoidably shared — it must read both
providers' evidence. This spec resolves ownership as follows, with reasoning:

**Decision: the join's authoritative record is written by a neutral third
step — neither provider's own runtime executes it as its own gate.**

Reasoning, grounded in what was actually read this session:

1. **The "whichever side runs last" alternative fails a concrete graph.py
   constraint.** If the Codex side were to own writing the join record as
   part of `codex/runtime/graph.py`'s own gate execution, `_metadata_error`
   requires every gate-tagged node's `_run` triple and `provenance.provider
   == "codex"` (lines 298–306 `(verified)`) — meaning a join record that also
   needs to certify CLAUDE's evidence would need Codex's own runtime to
   validate a Claude-authored artifact, which is exactly the failure mode
   the authorising instruction already named: `_invoke()` hardcodes
   `artifact.get("provider") != "codex"` as a validation failure (line 331
   `(verified)`) — a Claude-authored evidence artifact currently FAILS
   Codex's own gate validator. Making Codex own the join inherits this
   defect unless Codex's validator is changed to accept a differently-shaped
   join record — which is a real Codex-side change, but even so it
   conflates "Codex validates its own gate" with "Codex adjudicates between
   two providers," collapsing the exact separation the parallel-review
   design exists to enforce (independent review, not one provider grading
   the other).
2. **Symmetrically, Claude owning the join has the mirror problem**: nothing
   in `AGENTS.md`'s hook map gives Claude-side tooling any existing
   provenance-comparison mechanism for a Codex-authored artifact either
   `(verified — no such comparator found in the hook event map)`; Claude
   would have to invent one, with the same "one provider grading the other"
   conflict of interest in reverse.
3. **A neutral third step avoids both.** The join is defined as its own
   node (`J4b-review[i]`, §4.1) with its own record path, written only
   after both reviewer records exist (§4.3), by a dispatch step that is
   NOT itself one of the two `graph_policies.reviewers` entries — e.g. the
   same orchestrator-level mechanism that already performs `J2`'s
   analogous "orchestrator validated and absorbed both results in one
   state write" role (`execution-graph.md`'s `J2` row: "all triggered
   scouts returned; orchestrator validated and absorbed both results in
   one state write" `(verified)`). `J2` is precedent in this exact
   codebase for "the orchestrator, not either scout, owns the join write" —
   this design follows that existing convention rather than inventing a
   new one.
4. Which repo/language the neutral step's code physically lives in
   (Claude-side orchestration code vs. a small standalone script) is left to
   the future implementation session, with one hard constraint: it MUST NOT
   be implemented as a Codex `REQUIRED_GATES` gate kind (out of scope, §0)
   and MUST NOT be implemented as one provider's reviewer agent also writing
   the join record (defeats independence, item 1/2 above).
5. **A second, independent Codex-side dependency, distinct from item 1's
   `_invoke()` artifact check: `_metadata_error`'s mapping-validation layer
   has the same `provider == "codex"` restriction, and it is unconditional.**
   Item 1 above names `_invoke()`'s artifact-provider check (line 331,
   `artifact.get("provider") != "codex"`) as one place Codex's runtime
   rejects a Claude-authored thing. `_metadata_error` (lines 254–258
   `(verified)`) is a SEPARATE occurrence of the same pattern at a different
   layer: `if record.get("provider") != "codex": return "provider must be
   codex"` applies to EVERY implementation-mapping record, not only
   gate-tagged ones. It is invoked from `prepare_implementations` (line
   219–220 `(verified)`, which iterates every node's mapping in the
   implementation config) and from `_run_node` at actual dispatch time (line
   364 `(verified)`). Combined with `prepare_implementations` requiring every
   dispatchable node in the contract table to have a mapping entry (lines
   216–218 `(verified)`): if a Claude-owned reviewer node
   (`U4b-review-claude[i]`) is staged into the shared `execution-graph.md`
   table that Codex's runtime parses (`CONTRACT`, line 20, IS that file
   `(verified)`), it becomes dispatchable and requires a mapping — but no
   mapping can be accepted unless `provider == "codex"`. **There is currently
   no legal way to give a Claude-owned node a mapping in this schema that
   Codex's runtime will accept.** Staging `U4b-review-claude[i]` into the
   real contract table therefore requires `_metadata_error`'s
   `provider != "codex"` check (line 258) to ALSO change, alongside the
   `_invoke()` change item 1 already names — two distinct Codex-runtime code
   dependencies, not one, both out of scope for this spec (§0) and both
   deferred to the future Codex-owned implementation session.

### 7.2 Consequence for the staged `graph.py` mapping

Per graph.py's `prepare_implementations`, every dispatchable node without an
implementation mapping raises `missing implementation mapping: {name}` (line
217–218 `(verified)`), which `_run_node` turns into a `hard-stop` (lines
365–366 `(verified)`). So when `J4b-review[i]` is eventually added to the
real contract table (a future, separately reviewed change — not this spec),
**only ONE real option exists: it needs an actual Codex-side gate mapping (or
equivalent dispatchable-node implementation), full stop.**

There is no non-dispatchable alternative available in the current schema.
`load_contract`'s dispatch computation is exactly `not any(marker in
conditional.lower() for marker in ("no standalone work", "cross-cutting"))`
(line 63 `(verified)`) — those two exact marker phrases are the ONLY
mechanism in this codebase that can set `dispatch: False` for a node. If a
staged conditional cell avoids both marker phrases, the node IS dispatchable
by construction (the `not any(...)` computation defaults to `True`), which
forces prepare_implementations's mapping requirement regardless. And using
either marker phrase on the join row is explicitly forbidden by §4.4 of this
same spec, because it fail-opens the very release gate this design exists to
enforce. There is no third path: a conditional-cell description that is
"non-dispatchable but not cross-cutting/no-standalone-work" is not a thing
`load_contract` can express.

This spec states the constraint; resolving it with an actual Codex-side
mapping is explicitly deferred to the future Codex-owned implementation
session (§0, "new gate kind out of scope"). It is a real Codex-runtime-code
dependency, not something contract-table staging alone can resolve — see
§7.1 item 5 for the second, distinct Codex-side dependency this spec
identifies alongside it (`_metadata_error`'s `provider == "codex"` check
blocking a Claude-owned node's mapping).

---

## 8. Open Questions Deliberately Left Unresolved

- Whether `dual-execution` (both providers independently *implement*, not
  just review) should be added later. Deferred here — no schema, no record
  shape, no join semantics for it exist in this spec.
- Which graph stages beyond the named pilot (`U4b-review[i]`) are high-value
  enough for mixed review. Not enumerated broadly, per the authorising
  instruction.
- Whether disagreement is always human-owned, or may eventually use a
  bounded third-adjudicator class (a tie-breaking reviewer, an escalation
  policy short of full human adjudication). §5's default policy is
  unconditionally human-owned on any hard-stop; whether that ever loosens is
  not decided here.
- The `J4b-review[i]` disagreement hard-stop is not durable/enforced until a
  future real-table edit reroutes `U5[i]`'s and `U4b-merge-gate[i]`'s
  prerequisites to depend on it instead of (or in addition to)
  `U4b-review[i]` — see §4.4's closing note for the mechanical detail
  (`_propagate_blocks` only follows declared edges).

These four are explicitly out of scope for this freeze and are not
resolved, hinted at, or pre-justified anywhere above.
