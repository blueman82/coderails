# Graph specification recovery

[Runbook](RUNBOOK.md).

## Graph refused with `spec_*`, or `instantiate` refused

- Symptom: A command such as `inspect`, `begin-wave`, `add-unit`, or `complete` fails with a spec error.
  The error can be `spec_edge_missing`, `spec_unknown_node`, `spec_node_missing`, or `spec_hash_mismatch`.
  The command `graph.py instantiate` can give `instantiate_refused_<foreign|state|nonempty|bad_id>`.

- Query: `python3 scripts/lib/spec_counters.py [--since <ISO ts>]` counts those codes plus `instantiate_ok`, `instantiate_noop`, and `skip_when_met`.
  It counts one `skip_when_met` for each `plan` call in which a node satisfies the skip condition.
  Each load refusal logs `load/refused/<code>` in the loop's `recovery-trace.jsonl`.

- Remediation: `spec_edge_missing` names the missing edge, for example `J2.8 -> U3[2]`.
  The spec makes the edge necessary if the two nodes exist.
  Run `graph.py add-unit` to add the unit and its edges. Do not edit `progress.json` by hand.

  For a graph with an `instantiate` stamp, `spec_hash_mismatch` means `graph-spec.yaml` changed after the build.
  Finish the loop with the previous spec checkout or start a new loop.
  The codes `spec_unknown_node` and `spec_node_missing` mean someone added or removed nodes by hand.
  Run `instantiate` in a started loop with no graph data. A nonempty loop gives `instantiate_refused_nonempty`.

  A second run with the same policy level and units gives `instantiate_noop`.

- Edit `packages/graph-semantics/graph-spec.yaml` or `policy.yaml` in JSON syntax. Run `python3 scripts/gen_graph_docs.py`.
  The test `scripts/tests/gen_graph_docs_test.py` fails if the tables differ from the spec.
  The installer puts the two files next to `graph_spec.py` in each provider's `agentic-loop/scripts`.

- Off-switch: Set `CODERAILS_GRAPH_SPEC=off` to skip the spec check when the loader runs. The values `0` and `false` also work.
  The check is on by default. Unset the setting to turn the check back on.
  Use the switch only to unblock a loop that a spec change blocks. Then build the loop again.
  The loader gives `spec_join_inputs` if a stamped graph has a missing join or unit input.
  The loader gives `spec_profile_downgrade` if the stamped policy level is below `graph.profile` in `policy.yaml`.

- Limits: `graph.profile` in `policy.yaml` defaults to `full`. Each spec node must belong to FULL.
  A spec that removes a node from FULL gives `spec_profile` before `instantiate` runs.
  The owner must lower the policy floor to `units-only` before `instantiate --profile units-only` can run. The flag alone gives a refusal.

  The spec checks edges only between nodes that exist. An unstamped graph built by hand or by `start` can run without `J2.8` or the prep nodes.
  Two options remain open for the owner. One option is for `start` to set the stamp through `instantiate`. The other is for `plan` and `begin-wave` to refuse unstamped graphs with `full`.
  The spec checks join inputs only in stamped graphs.

  An agent can remove `graph.spec_sha256` to use the weaker check for an unstamped graph.
  It can also edit `spec_profile` and drop more nodes, edges, and joins. The policy floor blocks this edit only if `policy.yaml` says `full`.

  Hooks do not read `loop_evals_min_units`. The skip rules for irreversible surfaces and `no PR` units use human judgment.
  The `skip_when_met` result reports the machine condition and does not record a skip.

  The session user can edit the spec, policy, and `progress.json`. The check finds unintended changes by an agent that follows the rules.
  It cannot prove that someone did not edit the data.
