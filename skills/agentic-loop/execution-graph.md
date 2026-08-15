# Execution graph — stable contract

Detail-carrier for [SKILL.md](SKILL.md)'s "The phases" section. This is a contract spec, not a
phase-by-phase instruction — consult it whenever you need a node's exact prerequisites, readiness
predicate, or skip condition; the phase prose in SKILL.md covers what to *do*, this file covers
what makes a node *ready*.

Before dispatching any candidate node, run the read-only readiness query
`${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/graph_readiness.sh <path-to-progress.json> <node-id>`
and dispatch only nodes it reports `ready` for. Its `blocked` output means "not
yet ready to dispatch" — it fail-closes the same way on missing or malformed
`progress.json` as on a real non-terminal predecessor, so it cannot distinguish
the two. Conversely, a node with no recorded incoming edges is vacuously
`ready` — register the candidate's node and edges before querying, not after.
Run ready independent nodes in one wave, but preserve every listed dependency.
The orchestrator is the only writer of `progress.json`: collect a wave's results, then do one
read-modify-write before releasing its join. Inside an authorised loop, the
`U*` lane below repeats per work-unit.

Node IDs are stable documentation identifiers. `S*` nodes run once; `U<i>*`
nodes run once per work-unit `i`; `J*` nodes are explicit joins. A skipped node
is still recorded as `skipped: <predicate>` in loop state; it is not a failed
node and cannot satisfy a prerequisite by omission.

```text
S-2 -> S-1 -> S0 -> S0.4 -> S0.5 -> S1 -> S2
                                      |       |
                                      |       +--> S2.5 --+
                                      |       +--> S2.6 --+--> J2 --> S2.7a --> S2.7b --+
                                      |       +--> S2.7c -------------------------------+
                                      |       +--> S2.7d[i] -----------------------------+--> S2.8 --> J2.8
                                      |       +--> S2.7e -------------------------------+
                                      |                                                    |
                                      +----------------------------------------------------+
                                                                                           v
                  +--> U3[i] --> U4[i] --> U4b-review[i] --> U5[i] --> U6[i] --> U7/8[i]
                  |       ^                 |                    |          |          |
J2.8 ------------+       |                 |                    +----------+----------+
                  |       |                 +--> U5-repair[i] --/           |
                  |       +-------------------- retry-until-green ----------+
                  |                                                            v
                  |                                                     U4b-merge-gate[i]
                  |                                                            |
                  +<-- U10-respawn[i] <---------------------------------------+
                                                                               v
                                                                        J12-all-units
                                                                               |
                                                                    S9-wiki -> S9-docs
                                                                               |
                                                                    S13-proof -> S13-retro
                                                                               |
                                                                        S13-complete
```

The diagram is a shape guide; the table is authoritative where a line would be
ambiguous.

| ID | Node / true prerequisites | Ready when | Conditional skip or join |
|---|---|---|---|
| `S-2` | Stub state | path helper returns the session-owned state path | never skipped |
| `S-1` | Improve prompt | prompt is adopted, revised, or explicit opt-out is recorded | full-autonomous auto-adopts; otherwise one bounded input point |
| `S0` | Read envelope | envelope class and stop conditions are recorded | never skipped |
| `S0.4` | Model-cost notice | notice emitted | never a gate; no model switch is performed by the orchestrator |
| `S0.5` | Operating rules | confidence, verification, and `LOOP-STOP` rules are active | never skipped |
| `S1` | Plan | work-unit list, dependencies, and success criteria exist | Phase 1 confirmation may be `awaiting-input` |
| `S2` | Plan | pre-flight agent result, wiki/theme intake, retro lessons, and clean-base check exist | never spawn implementation before this node |
| `S2.5` | `S2` | design scout returned a recommendation and flip-condition | skip when no unresolved design fork |
| `S2.6` | `S2` | disposition scout returned a result for every retirement unit | skip when no named existing path is retired |
| `J2` | `S2.5` and `S2.6` | all triggered scouts returned; orchestrator validated and absorbed both results in one state write | skipped branches contribute an explicit skip record |
| `S2.7a` | `J2` | durable `spec.md` exists | only if `work_units >= 3` or a cross-unit dependency exists |
| `S2.7b` | `S2.7a` | durable `plan.md` exists and matches the work-unit list | same predicate as `S2.7a`; `S2.7b` is sequential after it |
| `S2.7c` | `S2` plus authorising prompt | loop-scope evals are frozen before build | required for a Phase 2.7 loop or an irreversible-surface trigger |
| `S2.7d[i]` | `S2` plus each unit definition | PR-scope evals are frozen before that unit builds | skip only for a unit with no PR; required before its merge gate |
| `S2.7e` | `S2` plus executable-surface decision | blind `proof.json` exists, or explicit no-executable disposition is recorded | required for every executable loop; independent of `S2.7a/b` |
| `S2.8` | `S2` and `S2.7b` when triggered | every build unit has one recorded model role | may run beside independent evidence branches; never releases a unit without its required inputs |
| `J2.8` | `S2.8`, plus `S2.7d[i]`/`S2.7e` where required | all inputs for the first eligible unit are present | later units wait on their own true prerequisites |
| `U3[i]` | `J2.8`, unit dependencies, and required eval/proof inputs | worker produced the unit's committed artifact/OPEN PR terminal state | units with `blockedBy` dependencies wait; independent units may run in waves |
| `U4[i]` | `U3[i]` | artifact, worktree, PR, and worker report were checked by the orchestrator | idle is not failure; failed artifact check enters repair |
| `U4b-review[i]` | `U4[i]` | required review Skill, security/deploy review when triggered, and SHA-bound post-review artifact exist | review findings go to `U5[i]`; no merge on a missing artifact |
| `U5[i]` | `U4b-review[i]` or a verified reported regression | source-of-truth premise is confirmed and diagnosis is disconfirmed | premise disproven is a hard-stop; otherwise spawn the repair worker |
| `U5-repair[i]` | `U5[i]` | distinct fix attempt applied and locally verified | back to `U4[i]`; at most 5 distinct attempts per failure |
| `U6[i]` | current unit is verified and any in-scope confirmation decision is resolved | envelope permits autonomous continuation or required approval is granted | no extra ask inside the envelope |
| `U7/8[i]` | `U6[i]` | stack-specific push/deploy tactic completed, if applicable | skip when no push/deploy surface; these phases do not add generic policy |
| `U4b-merge-gate[i]` | `U4b-review[i]`, `U6[i]`, `U7/8[i]`, PR-scope eval, review artifact, and integrity attestation | exact-head review/eval/integrity checks and gate-time smoke pass; merge reports `MERGED` | any missing/stale/failing gate enters `U5-repair[i]` or hard-stop after retry bound |
| `U10-respawn[i]` | `U4[i]` artifact check shows dispatch failure/idle without artifact | new versioned worker name and fresh dispatch exist | not triggered by an idle ping alone; returns to `U4[i]` |
| `J12-all-units` | every unit's merge gate passed | each merged PR and dependent deployment evidence is freshly rechecked | no unit may be silently omitted |
| `G10` | any respawn path | every replacement worker name is versioned | cross-cutting Phase 10 guard; no standalone work |
| `G11` | every worker dispatch and report | prompts and reports carry confidence labels | cross-cutting Phase 11 guard; no standalone work |
| `G12` | every artifact boundary | the orchestrator freshly rechecks the artifact before releasing a dependent node | cross-cutting Phase 12 guard; `J12-all-units` is its final aggregate join |
| `S9-wiki` | `J12-all-units` | clustered wiki ingest and lint landed and were verified on `origin/main` | skip only when no wiki update is in scope; still record the skip |
| `S9-docs` | `S9-wiki` | one `/sync-docs` audit completed and findings triaged | pre-existing drift is reported, not folded into scope |
| `S13-proof` | `S9-docs` | every frozen proof command ran verbatim in the orchestrator session and passed | absent proof requires the recorded no-executable disposition |
| `S13-retro` | `S13-proof` | Phase 13 report, cost, decisions, artifacts, eval result, standing orders, and feedback are written | never a mid-loop checkpoint |
| `S13-complete` | `S13-retro` | final aggregate verification passes; `progress.json` is complete and `retro.json` is valid | terminal node; emits `LOOP-STOP: complete` |

`S0.5`, `U4`, `U4b-review`, `U6`, and `S13-complete` carry the Phase 11/12
confidence-label and fresh-evidence rules; they are guards on the nodes above,
not extra work. A review finding, failing eval, smoke failure, or verification
failure follows `U5 -> U5-repair -> U4` and consumes one distinct retry attempt.
After five diagnosed attempts for the same failure, the edge terminates at the
hard-stop rather than looping. Independent failure domains may use parallel
repair workers, each with its own bound, then join at `U4`.
