# Graph specification recovery

[Runbook](RUNBOOK.md).

## Graph refused with `spec_*`, or `instantiate` refused

- Symptom: any graph command (`inspect`, `begin-wave`, `add-unit`, `complete`, ...) fails with `spec_edge_missing`,
  `spec_unknown_node`, `spec_node_missing` or `spec_hash_mismatch`; or `graph.py instantiate` fails with
  `instantiate_refused_<foreign|state|nonempty|bad_id>`.
- Query: `python3 scripts/lib/spec_counters.py [--since <ISO ts>]` counts those codes plus `instantiate_ok`,
  `instantiate_noop` and `skip_when_met` (one count per `plan` call in which a node's skip predicate held). Each refused
  load also leaves a `load/refused/<code>` row in the loop's `recovery-trace.jsonl`.
- Remediation: `spec_edge_missing` names the missing edge (for example `J2.8 -> U3[2]`): the spec requires it whenever both
  nodes exist, so add the edge by registering units with `graph.py add-unit` (which wires it) rather than editing
  `progress.json`. For a graph stamped by `instantiate`: `spec_hash_mismatch` means `graph-spec.yaml` changed after the
  graph was built (finish that loop on the old spec checkout, or start a new loop); `spec_unknown_node` /
  `spec_node_missing` mean nodes were added or removed by hand. `instantiate` builds only into an empty started loop
  (`instantiate_refused_nonempty` otherwise); a re-run with the same profile and units is `instantiate_noop`.
- Edit the graph structure in `packages/graph-semantics/graph-spec.yaml` / `policy.yaml` (JSON syntax) and run
  `python3 scripts/gen_graph_docs.py`; `scripts/tests/gen_graph_docs_test.py` fails the run when the generated tables drift.
  The installer materializes both files next to `graph_spec.py` in each provider's `agentic-loop/scripts`.
- Off-switch: `CODERAILS_GRAPH_SPEC=off` (also `0` or `false`) in the environment skips the whole spec check on load
  (default ON; unset to re-enable). Use it only to rescue a loop whose graph a spec change has stranded, then rebuild it.
  `spec_join_inputs` (a stamped graph's join is missing or lacks a unit's input) and `spec_profile_downgrade` (the stamp is
  below `policy.yaml` `graph.profile`) are the other refusal codes.
- Limits: `policy.yaml` default `graph.profile` is `full`. Every spec node must belong to FULL; a spec
  that removes one from FULL is refused with `spec_profile` before instantiate. `instantiate --profile units-only`
  requires the owner to lower the policy floor to `units-only` first; the flag alone is refused. Spec edges are
  enforced only between nodes that exist, so an unstamped (hand-built or `start`-built) graph that never creates `J2.8` or
  the prep nodes is not refused: making `start` stamp via `instantiate`, or having `plan`/`begin-wave` refuse an unstamped
  graph once `full` is chosen, is an open owner decision. Join inputs are enforced on stamped graphs only. Downgrade path:
  a hand-editing agent can delete `graph.spec_sha256` (back to the weaker unstamped check) or rewrite `spec_profile` and drop
  the extra nodes, edges and joins; the policy profile floor refuses the second only while `policy.yaml` says `full`.
  `loop_evals_min_units` is documented but not read by any hook yet. Judgement skip rules (irreversible-surface triggers,
  `no PR` units) stay prose: `skip_when_met` is only the machine predicate and is a hint, not a recorded skip. Same-user
  boundary: the spec, policy and `progress.json` are plain files the session user can edit; this is drift detection for a
  cooperating agent, not tamper evidence.
