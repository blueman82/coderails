#!/bin/bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
# graph_evidence.sh — provenance binding for Claude graph node evidence.
#
# SOURCED by graph_dispatch.sh, not executed directly.
#
# THE PROBLEM: graph_dispatch_record used to take the orchestrator's
# self-reported {outcome, evidence} per node on trust. graph_executor_apply_wave
# only type-checks that `evidence` is an array, so a wholly fabricated reference
# was persisted verbatim into a node's evidence array. Self-reported evidence
# with no provenance check is not evidence.
#
# THE FIX: bind each node's evidence to an artefact the orchestrator cannot
# fabricate — the `Agent` tool_use recorded in Claude Code's OWN session
# transcript. The orchestrator writes the transcript only by actually calling
# the Agent tool; it cannot retroactively add a record to it.
#
# CLAUDE-NATIVE, NOT A PORT. Codex binds spawn_agent/SubAgentActivity/
# task_complete across a parent rollout and a child thread, because that is
# what a Codex rollout contains. Claude Code's transcript has a different
# shape, verified by inspecting a live session file
# (~/.claude/projects/<munged-cwd>/<session-id>.jsonl):
#
#   * the subagent tool is named `Agent` (NOT `Task`)
#   * tool-use ids are `toolu_*`
#   * `.input.prompt` stores the dispatch prompt UNTRUNCATED, so the
#     CODERAILS_GRAPH_DISPATCH envelope (and its node_id/wave_id/session_id)
#     parses straight back out of it
#   * records carry `uuid`, `parentUuid`, `sessionId`, `isSidechain`
#
# So the binding is expressed in Claude's own vocabulary — tool_use_id,
# record_uuid, subagent_type — not Codex's field names. The logical schema
# (bind spawn -> node -> attempt, bounded below by a wave cursor) is shared
# deliberately; the field names and the walk are not.
#
# THE KEY DESIGN DECISION: the reference is DERIVED from the transcript, never
# taken from the caller. For each node in the wave we look up the Agent
# tool_use whose envelope names that node, that wave and this session. A
# caller-supplied `spawn_ref` is treated purely as a CLAIM to be checked
# against the derived truth — matching claims are redundant, non-matching
# claims are refused. That is what makes forgery, cross-node replay and
# pre-cursor replay all fail from one rule rather than three special cases.

GRAPH_EVIDENCE_ENVELOPE_KEY="CODERAILS_GRAPH_DISPATCH"

# graph_evidence_transcript <session_id>
# Resolve this session's transcript. Mirrors the established repo idiom
# (loop_cost.sh / loop_state_common.sh): glob
# ${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}/*/<session_id>.jsonl.
# Prints the path; returns 1 when none resolves.
graph_evidence_transcript() {
    local session="$1" projects_dir f
    [ -n "$session" ] || return 1
    case "$session" in
    */* | ..*) return 1 ;; # never let a session id escape the projects dir
    esac
    projects_dir="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
    for f in "$projects_dir"/*/"$session.jsonl"; do
        [ -f "$f" ] || continue
        printf '%s\n' "$f"
        return 0
    done
    return 1
}

# graph_evidence_spawns <transcript> <session_id>
# Emit one compact JSON object per Agent tool_use carrying a dispatch
# envelope, in transcript order, each stamped with its 1-based line offset:
#   {line, node_id, wave_id, tool_use_id, record_uuid, subagent_type}
#
# Fails closed on a malformed transcript. `jq -e` over the whole file gives ONE
# exit code for the whole parse: jq aborts non-zero on the first unparseable
# line, so a truncated or corrupt record can never be silently skipped and read
# as "this session has no spawns" (which would then read as an absent
# reference and, on a lenient caller, as a pass). Empty output is NOT treated
# as success by callers — see graph_evidence_bind_wave.
#
# Only main-thread records count: `isSidechain: true` records are a subagent's
# own transcript replayed into the same file, so a child re-emitting its
# prompt must not be mistakable for the parent dispatching it.
graph_evidence_spawns() {
    local transcript="$1" session="$2"
    [ -f "$transcript" ] || return 1
    jq -e -c --slurp --raw-input --arg session "$session" --arg key "$GRAPH_EVIDENCE_ENVELOPE_KEY" '
      split("\n")
      | map(select(length > 0))
      | to_entries
      | map(
          (.key + 1) as $line
          | (.value | fromjson) as $rec          # aborts the whole program on bad JSON
          | select(($rec.isSidechain // false) != true)
          | select(($rec.sessionId // $session) == $session)
          | ($rec.uuid // "") as $uuid
          | (($rec.message.content // []) | if type == "array" then . else [] end)
          | map(select((.type? == "tool_use") and (.name? == "Agent")))
          | .[]?
          | . as $tu
          | ($tu.input.prompt // "") as $prompt
          | select(($prompt | type) == "string" and ($prompt | startswith($key + "=")))
          | ($prompt | ltrimstr($key + "=") | split("\n")[0]) as $raw
          | ($raw | try fromjson catch null) as $env
          | select($env != null and ($env | type) == "object")
          | select((($env.session_id // $session) == $session))
          | {line: $line,
             node_id: ($env.node_id // null),
             wave_id: ($env.wave_id // null),
             tool_use_id: ($tu.id // null),
             record_uuid: $uuid,
             subagent_type: ($tu.input.subagent_type // null)}
          | select(.node_id != null and .wave_id != null
                   and (.tool_use_id | type == "string") and (.tool_use_id | length) > 0)
        )
      | flatten
      | .[]
    ' "$transcript" 2>/dev/null
}

# graph_evidence_cursor <transcript>
# The wave's lower bound: the transcript's current length at begin-wave. Any
# Agent spawn bindable to that wave must appear STRICTLY AFTER this line, so a
# spawn from an earlier wave cannot be replayed into this one. A line count is
# sufficient and monotonic — the transcript is append-only JSON Lines.
graph_evidence_cursor() {
    local transcript="$1"
    [ -f "$transcript" ] || return 1
    wc -l <"$transcript" | tr -d ' '
}

# graph_evidence_bind_wave <progress.json> <wave_json>
# The gate. Reads the wave results folded by graph_dispatch_record and returns
# them with each node's evidence array carrying a derived provenance reference.
# Prints the rewritten wave JSON on success; returns non-zero (printing
# nothing) when any node's claim cannot be honoured — the caller must abort the
# whole wave, leaving durable state untouched.
#
# Per node in the wave, with $spawns = this session's Agent tool_uses that name
# that node and this wave and sit after the wave cursor:
#
#   * exactly one match          -> bind it, dropping any caller-supplied
#                                   {spawn_ref} claim that agrees with it
#   * a caller cited a spawn_ref that is not that match (absent from the
#     transcript, owned by another node, from another wave, or before the
#     cursor)                    -> DENY the wave
#   * no match and nothing cited -> pass the node through unbound (a join, or a
#                                   node this session did not dispatch via
#                                   Agent; binding is additive and must not
#                                   retroactively invalidate such nodes)
#   * more than one match        -> DENY (ambiguous; one node gets one spawn
#                                   per wave)
#
# Reuse is refused globally: a tool_use_id already bound to ANY node in
# progress.json, or claimed twice within this wave, is rejected. So one spawn
# can never satisfy two nodes or two attempts.
graph_evidence_bind_wave() {
    local progress="$1" wave_json="$2"
    local session transcript spawns_json cited_count

    session=$(jq -r '.session_id // empty' "$progress" 2>/dev/null) || return 1
    [ -n "$session" ] || return 1

    # Does any node in this wave actually cite a spawn_ref? Determines how
    # hard a missing transcript bites: a cited ref with no transcript to check
    # it against is unverifiable and therefore denied, while a wave that cites
    # nothing (every existing suite, and every join) stays workable.
    cited_count=$(printf '%s' "$wave_json" | jq '
      [ to_entries[] | select(.key != "decisions_absorbed")
        | (.value.evidence // []) | if type == "array" then . else [.] end
        | .[] | select(type == "object" and has("spawn_ref")) ] | length' 2>/dev/null)
    case "$cited_count" in '' | *[!0-9]*) return 1 ;; esac

    if transcript=$(graph_evidence_transcript "$session"); then
        # One jq -e over the whole file: empty output here means "no spawns",
        # non-zero means "unreadable", and the two are never conflated.
        if ! spawns_json=$(graph_evidence_spawns "$transcript" "$session" |
            jq -e -c --slurp '.' 2>/dev/null); then
            return 1 # malformed/unreadable transcript: fail closed, always
        fi
    else
        [ "$cited_count" -eq 0 ] || return 1 # a claim with nothing to check it against
        spawns_json='[]'
    fi

    jq -e -c --argjson spawns "$spawns_json" --argjson wave "$wave_json" '
      (.graph.active_wave // {}) as $active
      | ($active.wave_id // null) as $wave_id
      # A wave with no recorded cursor has no lower bound. Waves begun before
      # this change carry none; they still bind by node+wave, they just cannot
      # exclude a pre-wave spawn. Documented ceiling, not a silent pass.
      | ($active.transcript_cursor // -1) as $cursor
      | (.graph.nodes // {}) as $nodes
      # Every tool_use_id already bound anywhere in the graph — the reuse set.
      | ([ $nodes[]? | (.evidence // [])
           | if type == "array" then . else [.] end
           | .[] | select(type == "object") | .tool_use_id? | select(. != null) ]) as $already_bound
      | reduce ($wave | keys[]) as $id (
          {out: {}, used: $already_bound};
          ($wave[$id]) as $result
          | if $id == "decisions_absorbed" then .out[$id] = $result
            else
              ((($result.evidence // []) | if type == "array" then . else [$result.evidence] end)) as $all_evidence
              # graph_dispatch_record prepends the EXISTING node evidence
              # (earlier attempts of this node) before handing the wave over, so
              # only the tail is caller-supplied. Provenance refs this gate
              # minted on a previous attempt live in that prefix and must be
              # carried through untouched — re-validating them would refuse
              # every retry, since those spawns predate the current cursor.
              | ((($nodes[$id].evidence // []) | if type == "array" then . else [$nodes[$id].evidence] end)) as $carried
              | ($all_evidence[:($carried | length)]) as $prefix
              | (if $prefix == $carried then $all_evidence[($carried | length):]
                 else $all_evidence end) as $evidence
              | (if $prefix == $carried then $carried else [] end) as $carried_kept
              # A claim is ANY caller-supplied object that asserts provenance:
              # the documented {spawn_ref} form, or an object already wearing
              # the bound shape (kind/tool_use_id). Only this gate may mint a
              # provenance reference — otherwise a caller bypasses the whole
              # check by writing the OUTPUT shape directly instead of a claim.
              | ([ $evidence[] | select(type == "object")
                   | (.spawn_ref? // .tool_use_id?
                      // (if (.kind? == "claude_agent") then "" else null end))
                   | select(. != null) ]) as $claims
              | ([ $evidence[] | select((type == "object"
                     and (has("spawn_ref") or has("tool_use_id")
                          or (.kind? == "claude_agent"))) | not) ]) as $kept
              | ([ $spawns[]
                   | select(.node_id == $id and .wave_id == $wave_id and .line > $cursor) ]) as $matches
              | if ($matches | length) > 1
                then error("graph_evidence: node \($id) matches multiple spawns in \($wave_id)")
                elif ($matches | length) == 0
                then
                  if ($claims | length) > 0
                  then error("graph_evidence: node \($id) cites an unbindable spawn \($claims[0])")
                  else .out[$id] = ($result + {evidence: ($carried_kept + $kept)})
                  end
                else
                  ($matches[0]) as $m
                  | if ($claims | map(select(. != $m.tool_use_id)) | length) > 0
                    then error("graph_evidence: node \($id) cites a spawn it does not own")
                    elif (.used | index($m.tool_use_id)) != null
                    then error("graph_evidence: spawn \($m.tool_use_id) is already bound")
                    else
                      .used += [$m.tool_use_id]
                      | .out[$id] = ($result + {evidence: ($carried_kept + $kept + [{
                            kind: "claude_agent",
                            attempt: (($nodes[$id].retry.attempts // 0) + 1),
                            wave_id: $wave_id,
                            tool_use_id: $m.tool_use_id,
                            record_uuid: $m.record_uuid,
                            subagent_type: $m.subagent_type}])})
                    end
                end
            end
        )
      | .out
    ' "$progress"
    # stderr is deliberately NOT suppressed: every denial above is raised via
    # error() with a "graph_evidence:" message naming the node and the reason.
    # Swallowing it would make a cursor denial indistinguishable from a wave-id
    # mismatch, both to an operator reading a refused wave and to a test
    # asserting that it denied for the right reason.
}
