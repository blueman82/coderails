#!/bin/bash
# graph_dispatch.sh — Claude-provider dispatch layer on top of
# graph_executor.sh/graph_readiness.sh (both reused verbatim, never
# reimplemented). Neither of those two files has any production caller
# today (verified via repo-wide grep) — this file is the first one.
#
# SOURCED, not executed directly. This script itself CANNOT call the
# `Agent` tool — that tool exists only in an active Claude Code
# orchestrator session's toolset, not on $PATH as a binary, and this file
# must not shell out to a `claude -p` subprocess (that would spawn a
# second, competing Claude session rather than using the orchestrator's
# own Agent tool, and was explicitly ruled out). So dispatch is split:
#
#   graph_dispatch_plan <progress.json> <index.yaml>
#     Pure computation, no side effects, no Agent calls. Computes the
#     current ready wave (graph_executor_ready_nodes, reused verbatim)
#     and resolves each ready node's graph_role to a dispatch target via
#     skills/index.yaml, using the SAME awk block-extraction convention
#     skill_route.sh/codex_dispatch.sh already use for this file (not a
#     new YAML parser). Prints one JSON object per ready node, one per
#     line (JSON Lines), for the orchestrator session to read and then
#     actually dispatch via its own Agent tool calls — this function never
#     dispatches anything itself.
#
#   graph_dispatch_record <progress.json> <wave-results JSON>
#     Takes the orchestrator's REAL collected Agent results for a wave
#     (after every dispatched node in the wave has reported back — never
#     partial) and applies bounded-retry/hard-stop bookkeeping before
#     calling graph_executor_apply_wave exactly once, same one-write-per-
#     wave contract graph_executor.sh already guarantees. Each result must
#     name its outcome via an "outcome" key or, failing that, a "status"
#     key — a result naming NEITHER aborts the whole wave rather than
#     being silently treated as a reported failure (a bare "done" or
#     "stale" result recorded only via "status" must never be mistaken
#     for a retry). A reported "failed" outcome increments retry.attempts
#     (capped at retry.max) and is downgraded to status/outcome "running"
#     (i.e. still in play) while attempts stays below retry.max; once
#     attempts reaches max the node is written as "hard-stop" instead of
#     "failed" so a blocked graph is visible without another wave being
#     computed against it.

GRAPH_DISPATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./graph_executor.sh
. "$GRAPH_DISPATCH_DIR/graph_executor.sh"

# Resolve one graph_role to its dispatch target(s) in skills/index.yaml,
# reusing skill_route.sh/codex_dispatch.sh's fixed-indentation awk
# convention (index.yaml's schema is spec.md's, not owned by any one
# reader of it — see skill_route.sh's own comment). Prints one
# "<skill_id> <source_kind>" line per skill_id whose graph_role equals
# the requested value.
_graph_dispatch_role_matches() { # index_path graph_role
  local index_path="$1" role="$2"
  awk -v role="$role" '
    BEGIN { id = ""; role_val = ""; kind = "" }
    /^  [A-Za-z0-9._-]+:[ \t]*$/ {
      if (id != "" && role_val == role) print id " " kind
      id = $0
      sub(/^  /, "", id)
      sub(/:[ \t]*$/, "", id)
      role_val = ""
      kind = ""
      next
    }
    /^    graph_role: / { v = $0; sub(/^    graph_role: /, "", v); role_val = v }
    /^    source_kind: / { v = $0; sub(/^    source_kind: /, "", v); kind = v }
    END { if (id != "" && role_val == role) print id " " kind }
  ' "$index_path"
}

# A node's graph_role: the explicit `graph_role` field on the node if
# present, else the node-id itself with any per-work-unit `[i]` suffix
# stripped (e.g. "U3[2]" -> "U3"). Nothing in the repo seeds an explicit
# graph_role today (verified: codex/runtime/graph.py's build_graph() only
# ever writes status/outcome/retry) — but execution-graph.md's node ids
# (S2.5, S2.6, S9-docs, U3, ...) ARE skills/index.yaml's graph_role
# values verbatim, so the node id is already the right key without an
# explicit field ever being written. The explicit field, when present,
# still wins — an override, not a requirement.
graph_dispatch_node_role() { # progress_json node_id
  local progress="$1" node="$2"
  jq -r --arg n "$node" '
    (.graph.nodes[$n].graph_role // null) as $explicit
    | if ($explicit != null and ($explicit | length) > 0) then $explicit
      else ($n | sub("\\[.*\\]$"; ""))
      end
  ' "$progress" 2>/dev/null
}

# Resolve a ready node-id to exactly one dispatch target. Precedence
# within the matches for that node's graph_role: agent > skill > command
# (an `agent` entry is the direct implementer of a graph node's work; a
# same-role `skill`/`command` entry, e.g. post-review/merge/push, is a
# mechanism that agent invokes internally, not a second independent
# target). Fails closed (empty output, exit 1) when: the node has no
# graph_role recorded, no index.yaml entry claims that graph_role, OR
# more than one entry remains tied within the winning precedence tier
# (e.g. U4b-review's two agent entries) — a silently-guessed target that
# turns out wrong would mark a node done on the wrong evidence, which is
# strictly worse than refusing to dispatch it.
graph_dispatch_resolve_target() { # progress_json node_id index_path
  local progress="$1" node="$2" index_path="$3"
  [ -f "$progress" ] && [ -f "$index_path" ] || return 1

  local role
  role=$(graph_dispatch_node_role "$progress" "$node")
  [ -n "$role" ] || return 1

  local matches
  matches=$(_graph_dispatch_role_matches "$index_path" "$role")
  [ -n "$matches" ] || return 1

  local tier kind_matches count
  for tier in agent skill command; do
    kind_matches=$(printf '%s\n' "$matches" | awk -v k="$tier" '$2 == k')
    count=$(printf '%s\n' "$kind_matches" | grep -c . || true)
    if [ "$count" -eq 1 ]; then
      local skill_id
      skill_id=$(printf '%s' "$kind_matches" | awk '{print $1}')
      local resolved
      resolved=$(bash "$GRAPH_DISPATCH_DIR/skill_route.sh" "$index_path" "$skill_id" claude)
      [ $? -eq 0 ] || return 1
      jq -n -c --arg skill_id "$skill_id" --arg kind "$tier" --arg path "$resolved" \
        '{skill_id:$skill_id, source_kind:$kind, path:$path}'
      return 0
    elif [ "$count" -gt 1 ]; then
      return 1
    fi
  done
  return 1
}

# graph_dispatch_plan <progress.json> <index.yaml>
# Prints one JSON-lines object per ready node:
#   {"node_id":..., "graph_role":..., "kind":"dispatch"|"join",
#    "skill_id":..., "source_kind":..., "path":..., "unresolved":...}
# A ready node that is a JOIN (a key in .graph.joins — per
# execution-graph.md, e.g. J2, satisfied by "orchestrator validated and
# absorbed both results in one state write", not by dispatching an
# agent) is reported with kind:"join" and skill_id/source_kind/path all
# null — this is NOT the same as "unresolved": a join is not something
# any index.yaml entry should ever match, so it is not reported as a
# resolution failure the way a genuinely unmapped node is.
#
# A ready non-join node whose target cannot be resolved is still
# reported (so the orchestrator sees it), with skill_id/source_kind/path
# all null and "unresolved": true — never silently dropped from the wave
# listing.
graph_dispatch_plan() {
  local progress="$1" index_path="$2"
  [ -f "$progress" ] && [ -f "$index_path" ] || return 1

  local ready_nodes
  ready_nodes=$(graph_executor_ready_nodes "$progress") || return 1
  [ -n "$ready_nodes" ] || return 0

  local node role target is_join
  printf '%s\n' "$ready_nodes" | while IFS= read -r node; do
    [ -n "$node" ] || continue
    role=$(graph_dispatch_node_role "$progress" "$node")
    is_join=$(jq -r --arg n "$node" '(.graph.joins // {}) | has($n)' "$progress" 2>/dev/null)
    if [ "$is_join" = "true" ]; then
      jq -n -c --arg node "$node" --arg role "$role" \
        '{node_id:$node, graph_role:$role, kind:"join", skill_id:null, source_kind:null, path:null, unresolved:false}'
    elif target=$(graph_dispatch_resolve_target "$progress" "$node" "$index_path"); then
      jq -n -c --arg node "$node" --arg role "$role" --argjson t "$target" \
        '{node_id:$node, graph_role:$role, kind:"dispatch", skill_id:$t.skill_id, source_kind:$t.source_kind, path:$t.path, unresolved:false}'
    else
      jq -n -c --arg node "$node" --arg role "$role" \
        '{node_id:$node, graph_role:($role|if .=="" then null else . end), kind:"dispatch", skill_id:null, source_kind:null, path:null, unresolved:true}'
    fi
  done
}

# graph_dispatch_record <progress.json> <wave-results JSON>
# wave-results shape: {"<node_id>": {"outcome":"done"|"skipped"|"failed"|
#   "stale" (accepts "status" as a fallback key when "outcome" is
#   absent — at least one of the two is REQUIRED, or the whole wave is
#   rejected), "provider":"claude", "skill_id":..., "implementation":...,
#   "evidence":... (optional, e.g. PR number/path), "stale_check":...
#   (only when outcome/status is "stale")}, ...}, plus optional sibling
# "decisions_absorbed" — same envelope graph_executor_apply_wave already
# accepts, passed straight through for that field.
#
# This function is the ONLY place retry.attempts is incremented and
# hard-stop is decided; graph_executor_apply_wave itself never mutates
# attempts (it only validates whatever it's handed). Reads each node's
# CURRENT retry state from progress.json before folding in the new
# result, so a resumed run picks up the right attempt count rather than
# resetting it.
graph_dispatch_record() {
  local progress="$1" wave_json="$2"
  [ -f "$progress" ] || return 1

  printf '%s' "$wave_json" | jq -e '
    type == "object" and ((keys - ["decisions_absorbed"]) | length > 0)
  ' >/dev/null 2>&1 || return 1

  # Needs BOTH the wave results and progress.json's current retry state
  # (to increment attempts from the right baseline on resume) — one jq
  # pass reading progress.json, with the wave passed in as --argjson.
  #
  # $reported: a result must name its outcome via `outcome` or, failing
  # that, `status` (both are accepted on input — see this function's own
  # header) — never silently defaulted to "failed". A result naming
  # NEITHER aborts the whole wave via error() (same fail-closed posture
  # graph_executor_apply_wave already uses for its own contract
  # violations) rather than mis-recording a real done/skipped/stale
  # result as a phantom retry, which would also defeat the stale_check
  # gate below it (a "status":"stale" result with no "outcome" would
  # otherwise be silently rewritten to "running" before ever reaching
  # graph_executor_apply_wave's stale_check enforcement).
  #
  # $attempts is capped at $max via `min` — an uncapped increment can
  # exceed $max (e.g. a caller re-reporting "failed" against an
  # already-exhausted node, or a legitimate retry.max:0 seed failing
  # once) and graph_executor_apply_wave's own attempts<=max contract
  # would then abort the ENTIRE wave inside the lock, discarding every
  # other node's result in it — capping here keeps that abort scoped to
  # a genuine contract violation, not a same-wave side effect of one
  # node's own bookkeeping.
  local folded
  folded=$(jq -c --argjson wave "$wave_json" '
    (.graph.nodes // {}) as $nodes
    | ($wave | del(.decisions_absorbed)) as $results
    | (reduce ($results | keys[]) as $id ({}; . + {
        ($id): (
          (($nodes[$id].retry.attempts // 0)) as $prev_attempts
          | (($nodes[$id].retry.max // 5)) as $max
          | ($results[$id]) as $r
          | ($r.outcome // $r.status // null) as $reported
          | (if $reported == null
             then error("graph_dispatch: node \($id) reported neither outcome nor status")
             else $reported end) as $reported
          | (if $reported == "failed" then ([$prev_attempts + 1, $max] | min) else $prev_attempts end) as $attempts
          | (if $reported == "failed" and $attempts >= $max then "hard-stop"
             elif $reported == "failed" then "running"
             else $reported end) as $final
          | $r + {
              status: $final,
              outcome: $final,
              retry: {attempts: $attempts, max: $max}
            }
        )
      }))
      + {decisions_absorbed: ($wave.decisions_absorbed // [])}
  ' "$progress")
  [ -n "$folded" ] || return 1

  graph_executor_apply_wave "$progress" "$folded"
}
