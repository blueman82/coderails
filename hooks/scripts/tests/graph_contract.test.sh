#!/bin/bash
# Focused contract check for progress.json's durable execution graph.
set -u

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

jq -n '
  {
    graph: {
      nodes: {
        S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}},
        U1: {status:"ready", outcome:"ready", retry:{attempts:1,max:5}},
        J2: {status:"blocked", outcome:"blocked", retry:{attempts:0,max:1}}
      },
      edges: [{from:"S2",to:"U1"},{from:"U1",to:"J2"}],
      joins: {J2:{id:"J2",mode:"all",inputs:["U1"]}}
    }
  }
' >"$TMP/progress.json"

if jq -e '
  .graph.nodes as $nodes
  | (.graph.edges // []) as $edges
  | (.graph.joins // {}) as $joins
  | ($nodes | type == "object" and (keys | all(test("^(S|U|J|G)[A-Za-z0-9._/-]*$"))))
  and ($nodes | to_entries | all(
      (.value.status | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale"))
      and (.value.outcome | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale"))
      and (.value.retry.attempts | type == "number" and . >= 0)
      and (.value.retry.max | type == "number" and . >= 1 and . <= 5)
      and (.value.retry.attempts <= .value.retry.max)
    ))
  and ($edges | all(.from != .to and ($nodes[.from] != null) and ($nodes[.to] != null)))
  and ($joins | to_entries | all(.value.id == .key and .value.mode == "all" and (.value.inputs | all($nodes[.] != null))))
  and ($edges | map(select(.to == "U1")) | all($nodes[.from].outcome | IN("done","skipped")))
' "$TMP/progress.json" >/dev/null; then
    echo PASS
else
    echo FAIL
    exit 1
fi
