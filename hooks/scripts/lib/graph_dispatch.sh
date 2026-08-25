#!/bin/bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
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
#   graph_dispatch_record <progress.json> <wave-envelope JSON>
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
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_DISPATCH_ROOT/scripts/lib/eval-artifact.sh"
# graph_evidence_bind.sh and graph_evidence_revalidate.sh each transitively
# source graph_evidence.sh themselves (idempotent — function defs and one
# constant, safe to load twice). Both are still sourced explicitly here so
# this file's own dependencies are readable at a glance rather than implied
# by a transitive chain. graph_evidence_revalidate.sh now sources
# graph_evidence_bind.sh itself for GRAPH_EVIDENCE_BIND_JQ_DEFS: the
# completion-time gate must select bound evidence with the SAME normalising
# detector the bind-time gate used, or a shape bind would have refused can be
# hand-edited in afterwards and revalidation will not even see it. That is a
# real shared-contract dependency, not a fabricated one.
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_DISPATCH_DIR/graph_evidence_bind.sh"
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_DISPATCH_DIR/graph_evidence_revalidate.sh"

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

_graph_dispatch_graph_valid() {
    local progress="$1"
    graph_executor_graph_valid "$progress"
}

# Records the wave's transcript cursor alongside its node set: the length of
# this session's own Claude Code transcript at the moment the wave opens. Only
# Agent spawns appearing AFTER that line may later bind as evidence for this
# wave's nodes, so a spawn from an earlier wave cannot be replayed into it
# (see graph_evidence.sh). The cursor is omitted — not faked — when no
# transcript resolves (every existing test fixture, and any non-session
# caller); a wave without a cursor still binds by node+wave id, it simply has
# no lower bound to enforce.
#
# The SAME {cursor, nodes} pair is also folded into .graph.wave_history,
# keyed by this wave's own wave_id, whenever a cursor resolves (omitted, not
# written as null, for a cursorless wave — same convention as
# .graph.active_wave.transcript_cursor above). Unlike .graph.active_wave,
# wave_history is never cleared — graph_executor_apply_wave's own completion
# path only nulls active_wave, so a wave_history entry durably survives past
# that wave's completion. This is what lets graph_evidence_revalidate_all
# prove a wave genuinely bound something even after every one of its nodes'
# evidence has since been deleted, with no surviving sibling left to infer it
# from — see that file's own header for the read side of this contract.
graph_dispatch_begin_wave() {
    local progress="$1" ready_json session cursor cursor_json='null'
    [ -f "$progress" ] || return 1
    _graph_dispatch_graph_valid "$progress" || return 1
    jq -e '(.graph.hard_stop // null) == null
           and ([.graph.nodes[] | select(.status == "hard-stop")] | length) == 0' \
        "$progress" >/dev/null 2>&1 || return 1
    ready_json=$(graph_executor_ready_nodes "$progress" |
        jq -Rsc 'split("\n") | map(select(length > 0)) | sort') || return 1
    [ "$(printf '%s' "$ready_json" | jq 'length')" -gt 0 ] || return 1

    session=$(jq -r '.session_id // empty' "$progress" 2>/dev/null)
    if [ -n "$session" ] && cursor=$(graph_evidence_transcript "$session" |
        { read -r t && graph_evidence_cursor "$t"; }); then
        case "$cursor" in '' | *[!0-9]*) cursor_json='null' ;; *) cursor_json="$cursor" ;; esac
    fi

    als_atomic_progress_update "$progress" --argjson wave_nodes "$ready_json" \
        --argjson transcript_cursor "$cursor_json" '
      (.graph.nodes) as $nodes
      | (.graph.edges) as $edges
      | (.graph.joins) as $joins
      | if .graph.hard_stop != null or ([.graph.nodes[] | select(.status == "hard-stop")] | length) != 0
        then error("graph_dispatch: graph has a hard stop") else . end
      | if .graph.active_wave != null then error("graph_dispatch: active wave already exists") else . end
      | ([ $nodes | keys[] as $id
           | select(($joins | has($id) | not)
                    and ($nodes[$id].status | IN("pending","ready"))
                    and ([ $edges[] | select(.to == $id) | .from ]
                         | all(. as $pred | ($nodes[$pred].outcome // "") | IN("done","skipped"))))
           | $id ] | sort) as $live_ready
      | if $live_ready != $wave_nodes then error("graph_dispatch: ready wave changed") else . end
      | .revision = ((.revision // 0) + 1)
      | .graph.active_wave = ({wave_id:("wave-" + (.revision | tostring)),revision:.revision,nodes:$wave_nodes}
          + (if $transcript_cursor == null then {} else {transcript_cursor:$transcript_cursor} end))
      | .graph.wave_history = ((.graph.wave_history // {})
          + (if $transcript_cursor == null then {}
             else {(.graph.active_wave.wave_id):
                    {cursor:$transcript_cursor, nodes:$wave_nodes}} end))
      | reduce $wave_nodes[] as $id (.;
          .graph.nodes[$id].status = "running"
          | .graph.nodes[$id].outcome = "running")
    ' || return 1

    jq -c '{nodes:.graph.active_wave.nodes,revision:.revision,wave_id:.graph.active_wave.wave_id}' "$progress"
}

graph_dispatch_inspect() {
    local progress="$1" ready_json
    [ -f "$progress" ] || return 1
    _graph_dispatch_graph_valid "$progress" || return 1
    ready_json=$(graph_executor_ready_nodes "$progress" |
        jq -Rsc 'split("\n") | map(select(length > 0)) | sort') || return 1
    jq -c --argjson ready "$ready_json" '{
      session_id,loop_id,revision,
      active_wave:.graph.active_wave,
      running:[.graph.nodes | to_entries[] | select(.value.status == "running") | .key] | sort,
      ready:$ready,
      hard_stop:.graph.hard_stop
    }' "$progress"
}

graph_dispatch_complete() {
    local progress="$1" session="" evals="" proof="" retro=""
    shift
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --session)
            session="${2:-}"
            shift 2
            ;;
        --evals)
            evals="${2:-}"
            shift 2
            ;;
        --proof)
            proof="${2:-}"
            shift 2
            ;;
        --retro)
            retro="${2:-}"
            shift 2
            ;;
        *) return 1 ;;
        esac
    done
    [ -f "$progress" ] && [ -f "$evals" ] && [ -f "$proof" ] && [ -f "$retro" ] || return 1
    _graph_dispatch_graph_valid "$progress" || return 1
    # Revalidate every already-bound "done" node's evidence again, right
    # before completion is allowed — a bind that was genuinely valid when
    # graph_dispatch_record ran must still be valid now, not just trusted
    # forever. See graph_evidence_revalidate_all's own header for what it
    # re-checks and why (transcript mutated after bind is exactly the case
    # this line exists to catch).
    graph_evidence_revalidate_all "$progress" || return 1

    local loop revision stamped_checksum recomputed_checksum
    loop=$(jq -r '.loop_id // empty' "$progress")
    revision=$(jq -r '.revision // -1' "$progress")
    [ -n "$session" ] && [ "$(jq -r '.session_id // empty' "$progress")" = "$session" ] && [ -n "$loop" ] || return 1
    jq -e '
      .graph.active_wave == null
      and .graph.hard_stop == null
      and ([.graph.nodes[] | select(.status | IN("done","skipped") | not)] | length) == 0
      and ([.graph.joins[] | select(.released != true)] | length) == 0
    ' "$progress" >/dev/null 2>&1 || return 1
    jq -e --arg session "$session" --arg loop "$loop" --argjson revision "$revision" '
      .scope == "loop" and .session_id == $session and .loop_id == $loop and .revision == $revision
      and .result == "GO"
      and ((.verification_justification // "") | type == "string" and length > 0)
      and .grading.by == "post_evals.sh grade-loop"
      and ((.grading.checksum // "") | type == "string" and length > 0)
      and (.grading.amendments_at_grade == ((.amendments // []) | length))
    ' "$evals" >/dev/null 2>&1 || return 1
    eval_artifact::compute_go "$evals" || return 1
    stamped_checksum=$(jq -r '.grading.checksum' "$evals") || return 1
    recomputed_checksum=$(eval_artifact::grading_checksum "$evals" GO) || return 1
    [ -n "$recomputed_checksum" ] && [ "$stamped_checksum" = "$recomputed_checksum" ] || return 1
    jq -e --arg session "$session" --arg loop "$loop" '
      .session_id == $session and .loop_id == $loop
      and (.proofs | type == "array" and length > 0)
      and (.proofs | all(.status == "pass" and ((.evidence // "") | length > 0)))
    ' "$proof" >/dev/null 2>&1 || return 1
    jq -e --arg session "$session" --arg loop "$loop" '
      (.schema_version | type == "number" and . >= 1)
      and .session_id == $session and .loop_id == $loop and .status == "complete"
    ' "$retro" >/dev/null 2>&1
}

# graph_dispatch_record <progress.json> <wave-envelope JSON>
# wave-envelope shape: {"wave_id":"...","results":{"<node_id>":
# {"outcome":"done"|"skipped"|"failed"|
#   "stale" (accepts "status" as a fallback key when "outcome" is
#   absent — at least one of the two is REQUIRED, or the whole wave is
#   rejected), "provider":"claude", "skill_id":..., "implementation":...,
#   "evidence":... (optional, e.g. PR number/path), "stale_check":...
#   (only when outcome/status is "stale")}, ...}, plus optional sibling
# "decisions_absorbed" — an optional sibling of results, passed through to
# graph_executor_apply_wave.
#
# This function is the ONLY place retry.attempts is incremented and
# hard-stop is decided; graph_executor_apply_wave itself never mutates
# attempts (it only validates whatever it's handed). Reads each node's
# CURRENT retry state from progress.json before folding in the new
# result, so a resumed run picks up the right attempt count rather than
# resetting it.
graph_dispatch_record() {
    local progress="$1" envelope_json="$2" wave_json wave_id
    [ -f "$progress" ] || return 1
    _graph_dispatch_graph_valid "$progress" || return 1
    jq -e '(.graph.active_wave | type) == "object"' "$progress" >/dev/null 2>&1 || return 1

    printf '%s' "$envelope_json" | jq -e '
      type == "object"
      and ((keys - ["wave_id","results","decisions_absorbed"]) | length == 0)
      and (.wave_id | type) == "string" and (.wave_id | length) > 0
      and (.results | type) == "object" and (.results | length) > 0
      and ((.decisions_absorbed // []) | type) == "array"
    ' >/dev/null 2>&1 || return 1
    wave_id=$(printf '%s' "$envelope_json" | jq -r '.wave_id') || return 1
    wave_json=$(printf '%s' "$envelope_json" | jq -c \
        '.results + {decisions_absorbed:(.decisions_absorbed // [])}') || return 1

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
    # already-exhausted node) and graph_executor_apply_wave's own
    # attempts<=max contract
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
             elif $reported == "failed" then "pending"
             else $reported end) as $final
          | $r + {
              status: $final,
              outcome: $final,
              retry: {attempts: $attempts, max: $max},
              evidence: ((if (($nodes[$id].evidence // []) | type) == "array"
                          then ($nodes[$id].evidence // []) else [$nodes[$id].evidence] end)
                         + (if (($r.evidence // []) | type) == "array"
                            then ($r.evidence // []) else [$r.evidence] end))
            }
        )
      }))
      + {decisions_absorbed: ($wave.decisions_absorbed // [])}
  ' "$progress")
    [ -n "$folded" ] || return 1

    # Provenance gate. Every node's evidence is bound to a real Agent tool_use
    # in this session's own transcript before anything is written; a claim
    # that cannot be bound aborts the WHOLE wave here, so durable state is
    # never touched by a forged, replayed or reused reference. Runs after the
    # retry fold so the bound reference carries the right attempt number, and
    # before apply_wave so the rejection costs no state write.
    local bound
    bound=$(graph_evidence_bind_wave "$progress" "$folded") || return 1
    [ -n "$bound" ] || return 1

    graph_executor_apply_wave "$progress" "$bound" "$wave_id"
}
