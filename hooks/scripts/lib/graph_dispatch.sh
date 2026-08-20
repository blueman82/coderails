#!/bin/bash
# graph_dispatch.sh — Claude dispatch layer on top of
# graph_executor.sh/graph_readiness.sh (both reused verbatim).
#
# SOURCED, not executed directly. This script itself CANNOT call the
# `Agent` tool — that tool exists only in an active Claude Code
# orchestrator session's toolset, not on $PATH as a binary, and this file
# must not shell out to a `claude -p` subprocess (that would spawn a
# second, competing Claude session rather than using the orchestrator's
# own Agent tool, and was explicitly ruled out). So dispatch is split:
#
#   graph_dispatch_plan <progress.json>
#     Pure computation, no side effects, no Agent calls. Computes the
#     current ready wave (graph_executor_ready_nodes, reused verbatim)
#     and resolves each ready node's graph_role through the Claude plugin's
#     fixed role map below. Prints one JSON object per ready node, one per
#     line (JSON Lines), for the orchestrator session to read and dispatch
#     via its own Agent tool calls — this function never dispatches itself.
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
GRAPH_DISPATCH_ROOT="$(cd "$GRAPH_DISPATCH_DIR/../../.." && pwd)"
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_DISPATCH_DIR/graph_executor.sh"

# Claude owns this graph and its dispatch targets. Ambiguous orchestration
# nodes are deliberately absent so they fail closed as unresolved.
_graph_dispatch_target_for_role() { # graph_role
    case "$1" in
    S-1) printf '%s\n' 'improve-prompt|skill|skills/improve-prompt/SKILL.md' ;;
    S2) printf '%s\n' 'preflight-scout|agent|agents/preflight-scout.md' ;;
    S2.5) printf '%s\n' 'design-scout|agent|agents/design-scout.md' ;;
    S2.6) printf '%s\n' 'disposition-scout|agent|agents/disposition-scout.md' ;;
    S2.7a) printf '%s\n' 'spec-reviewer|agent|agents/spec-reviewer.md' ;;
    S2.7c) printf '%s\n' 'task-evals|skill|skills/task-evals/SKILL.md' ;;
    S2.7e) printf '%s\n' 'proof-author|agent|agents/proof-author.md' ;;
    G12) printf '%s\n' 'verify-merged-pr|skill|skills/verify-merged-pr/SKILL.md' ;;
    S9-wiki) printf '%s\n' 'wiki-writer|agent|agents/wiki-writer.md' ;;
    S9-docs) printf '%s\n' 'docs-auditor|agent|agents/docs-auditor.md' ;;
    U3) printf '%s\n' 'loop-worker|agent|agents/loop-worker.md' ;;
    U6) printf '%s\n' 'push|command|commands/push.md' ;;
    *) return 1 ;;
    esac
}

# A node's graph_role: the explicit `graph_role` field on the node if
# present, else the node-id itself with any per-work-unit `[i]` suffix
# stripped (e.g. "U3[2]" -> "U3"). Current graph seeds omit an explicit
# graph_role and write status/outcome/retry only, but execution-graph.md's node ids
# (S2.5, S2.6, S9-docs, U3, ...) are the fixed role-map keys below, so
# the node id is already the right key without an explicit field. The
# explicit field, when present, still wins — an override, not a requirement.
graph_dispatch_node_role() { # progress_json node_id
    local progress="$1" node="$2"
    jq -r --arg n "$node" '
    (.graph.nodes[$n].graph_role // null) as $explicit
    | if ($explicit != null and ($explicit | length) > 0) then $explicit
      else ($n | sub("\\[.*\\]$"; ""))
      end
  ' "$progress" 2>/dev/null
}

# Resolve a ready node-id to exactly one Claude dispatch target. Fails closed
# when the node has no role, the role is not mapped, or the mapped file is
# absent. Workflow nodes with multiple required actions remain unmapped.
graph_dispatch_resolve_target() { # progress_json node_id
    local progress="$1" node="$2"
    [ -f "$progress" ] || return 1

    local role
    role=$(graph_dispatch_node_role "$progress" "$node")
    [ -n "$role" ] || return 1

    local target skill_id source_kind path
    target=$(_graph_dispatch_target_for_role "$role") || return 1
    IFS='|' read -r skill_id source_kind path <<EOF
$target
EOF
    [ -f "$GRAPH_DISPATCH_ROOT/$path" ] || return 1
    jq -n -c --arg skill_id "$skill_id" --arg kind "$source_kind" --arg path "$path" \
        '{skill_id:$skill_id, source_kind:$kind, path:$path}'
}

# graph_dispatch_plan <progress.json>
# Prints one JSON-lines object per ready node:
#   {"node_id":..., "graph_role":..., "kind":"dispatch"|"join",
#    "skill_id":..., "source_kind":..., "path":..., "unresolved":...}
# A ready node that is a JOIN (a key in .graph.joins — per
# execution-graph.md, e.g. J2, satisfied by "orchestrator validated and
# absorbed both results in one state write", not by dispatching an
# agent) is reported with kind:"join" and skill_id/source_kind/path all
# null — this is NOT the same as "unresolved": a join is not something
# any role-map entry should ever match, so it is not reported as a
# resolution failure the way a genuinely unmapped node is.
#
# A ready non-join node whose target cannot be resolved is still
# reported (so the orchestrator sees it), with skill_id/source_kind/path
# all null and "unresolved": true — never silently dropped from the wave
# listing.
graph_dispatch_plan() {
    local progress="$1"
    [ -f "$progress" ] || return 1

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
        elif target=$(graph_dispatch_resolve_target "$progress" "$node"); then
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
