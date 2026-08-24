#!/bin/bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
# graph_evidence_bind.sh — provenance BINDING/VALIDATION decision logic for
# Claude graph node evidence, built on graph_evidence.sh's transcript-reading
# primitives (graph_evidence_transcript, graph_evidence_spawns,
# graph_evidence_notifications, graph_evidence_cursor), which this file
# sources. See graph_evidence.sh's own header for THE PROBLEM/THE FIX this
# mechanism exists to close, and THE KEY DESIGN DECISION (the reference is
# DERIVED from the transcript, never taken from the caller) that
# graph_evidence_bind_wave below implements.
#
# SOURCED by graph_dispatch.sh, not executed directly.
#
# A "done" node's evidence additionally needs a genuine terminal result: a
# <task-notification> in the parent session's own transcript, matched by
# tool_use_id, reporting status=completed with a non-empty result —
# graph_evidence_notifications() in graph_evidence.sh. See
# graph_evidence_revalidate.sh's own header for how this is re-checked again
# at completion time.

GRAPH_EVIDENCE_BIND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_EVIDENCE_BIND_DIR/graph_evidence.sh"

# _graph_evidence_resolve_context <progress.json> <wave_json>
# Bash-only prelude for graph_evidence_bind_wave, split into its own function
# purely to keep graph_evidence_bind_wave's own line count under this repo's
# function-size ceiling — no behaviour change from the single-function form.
#
# Resolves the session, walks the transcript for raw spawns and
# notifications (failing closed on genuine corruption, tolerant of a
# legitimately transcript-less/spawn-less/notification-less wave per the
# same rc-discrimination rules documented where graph_evidence_spawns and
# graph_evidence_notifications are defined), and prints ONE compact JSON
# envelope on success: {spawns, notifications, transcript_clean}. Returns
# non-zero (printing nothing) on any of the fail-closed conditions
# graph_evidence_bind_wave's caller-facing contract already documents.
_graph_evidence_resolve_context() {
    local session transcript spawns_json notifications_json cited_count

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

    # transcript_clean drives the difference between "this node genuinely has
    # no spawn to bind" and "we could not look". Only a transcript that
    # RESOLVED and PARSED lets the gate demand a binding; anything else leaves
    # the legacy posture, where an uncited node passes through.
    local transcript_clean=false raw_spawns rc
    notifications_json='[]'
    if transcript=$(graph_evidence_transcript "$session"); then
        # Capture the walk's own exit status. A pipeline reports only its last
        # command, and `jq -e --slurp` turns empty input into [] with rc 0, so
        # piping straight into it would discard the walk's rc=5 abort on a
        # malformed record — the very failure this must fail closed on.
        #
        # rc=4 ("this transcript, once parsed clean, simply has zero Agent
        # spawns at all") is a legitimate empty result, not a failure — e.g. a
        # wave satisfied entirely by joins, with no Agent dispatch needed at
        # all. Only a genuine parse abort (rc>4, e.g. rc=5 on a malformed
        # record) is fail-closed here — the SAME `-gt 4` discrimination the
        # notifications walk below already applies, kept consistent rather
        # than treating an empty spawn list as indistinguishable from
        # corruption.
        raw_spawns=$(graph_evidence_spawns "$transcript" "$session")
        rc=$?
        if [ "$rc" -gt 4 ]; then
            printf 'graph_evidence: transcript for session %s is malformed or unreadable\n' \
                "$session" >&2
            return 1 # malformed/unreadable transcript: fail closed, always
        fi
        spawns_json=$(printf '%s' "$raw_spawns" | jq -c --slurp '.' 2>/dev/null) || return 1
        [ -n "$spawns_json" ] || return 1
        transcript_clean=true

        # Notifications are read from the SAME resolved, verified-parseable
        # transcript — never a separate, orchestrator-writable file. rc=4
        # ("no notifications at all in this transcript") is a legitimate
        # empty result, not a failure; only a genuine parse abort (rc>4) is
        # fail-closed here, mirroring the spawns walk above.
        local raw_notifications notif_rc
        raw_notifications=$(graph_evidence_notifications "$transcript" "$session")
        notif_rc=$?
        if [ "$notif_rc" -gt 4 ]; then
            printf 'graph_evidence: transcript for session %s is malformed or unreadable\n' \
                "$session" >&2
            return 1
        fi
        notifications_json=$(printf '%s' "$raw_notifications" | jq -c --slurp '.' 2>/dev/null) || return 1
        [ -n "$notifications_json" ] || notifications_json='[]'
    else
        if [ "$cited_count" -ne 0 ]; then
            # A claim with nothing to check it against is unverifiable.
            printf 'graph_evidence: node evidence cites a spawn but no transcript resolves for session %s\n' \
                "$session" >&2
            return 1
        fi
        # A cursor in active_wave means begin-wave DID resolve this transcript.
        # If it is unreadable now — deleted, or CLAUDE_PROJECTS_DIR redirected
        # away from $HOME between begin-wave and record — the wave cannot be
        # verified and must not be recorded on trust.
        if jq -e '(.graph.active_wave.transcript_cursor // null) != null' \
            "$progress" >/dev/null 2>&1; then
            printf 'graph_evidence: transcript for session %s could not be resolved\n' \
                "$session" >&2
            return 1
        fi
        spawns_json='[]'
    fi

    jq -n -c --argjson spawns "$spawns_json" --argjson notifications "$notifications_json" \
        --argjson transcript_clean "$transcript_clean" \
        '{spawns: $spawns, notifications: $notifications, transcript_clean: $transcript_clean}'
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
#   * no match and nothing cited -> pass the node through unbound (a join, or
#                                   a node this session did not dispatch via
#                                   Agent; binding is additive and must not
#                                   retroactively invalidate such nodes)
#   * more than one match        -> DENY (ambiguous; one node gets one spawn
#                                   per wave)
#
# Reuse is refused globally: a tool_use_id already bound to ANY node in
# progress.json, or claimed twice within this wave, is rejected. So one spawn
# can never satisfy two nodes or two attempts.
# The jq program's source lives in the two file-scope constants below
# (GRAPH_EVIDENCE_BIND_JQ_DEFS / GRAPH_EVIDENCE_BIND_JQ_BODY), concatenated
# and run through ONE jq invocation — not two separate jq calls. Splitting
# the invocation itself would break the single shared `reduce` accumulator
# (used/used_agents) and jq's error() propagation across the two halves.
# Moving the SOURCE TEXT to file scope (rather than a `local` var inside the
# function) is what actually reduces graph_evidence_bind_wave's own line
# count for this repo's function-size ceiling — a local heredoc assignment
# still counts every physical line toward the function's own total, since
# the ceiling check counts brace-depth-delimited lines textually. No
# behaviour change: verified byte-for-byte (modulo an inert trailing
# newline) against the original single-quoted jq program via a runtime
# dump-and-diff before this split shipped.
GRAPH_EVIDENCE_BIND_JQ_DEFS=$(cat <<'JQ_DEFS_EOF'
# Normalising detectors, applied to ONE caller-supplied evidence entry.
# Both walk the entry recursively (..) so nesting and array-wrapping
# cannot hide provenance, and fold case/punctuation so a trailing space
# or a homoglyph-ish variant still trips. String leaves are scanned too,
# so the bound shape serialised as a JSON string is caught.
#
# .agent_id is included alongside spawn_ref/tool_use_id: only this gate
# may ever mint an agent_id (derived from the transcript own
# <task-id>), so a caller-supplied .agent_id anywhere in an evidence
# entry is exactly as much a forged provenance claim as a caller-
# supplied spawn_ref/tool_use_id.
def norm_ids:
  [ .. | objects | (.spawn_ref?, .tool_use_id?, .agent_id?) | select(type == "string") ];
def looks_provenance:
  ([ .. | objects | (.kind?, .spawn_ref?, .tool_use_id?, .agent_id?)
     | select(type == "string") ]
   | any(ascii_downcase | gsub("[^a-z_]"; "") | test("claude_agent|toolu")))
  or ([ .. | strings ]
      | any(test("toolu_|\"kind\"\\s*:\\s*\"claude_agent")));
# A caller-supplied .agent_id specifically (any depth) — distinct from
# looks_provenance because it must be refused even when the entry has
# no spawn_ref/tool_use_id at all, and refused with a message naming
# "agent_id" rather than falling into the generic ownership message.
def has_caller_agent_id:
  [ .. | objects | .agent_id? | select(type == "string") ] | length > 0;
JQ_DEFS_EOF
)
GRAPH_EVIDENCE_BIND_JQ_BODY=$(cat <<'JQ_BODY_EOF'
(.graph.active_wave // {}) as $active
| ($active.wave_id // null) as $wave_id
# A wave with no recorded cursor has no lower bound, so it cannot tell a
# fresh spawn from an old one with the same wave id. Rather than binding
# unbounded (which let a six-lines-earlier wave-1 spawn replay into a new
# wave-1), a cursorless wave binds NOTHING: $matches is forced empty
# below. Combined with $binding_required, that makes a missing cursor
# inert in both directions — it can neither mint a reference nor be used
# to demand one. Legacy waves keep working precisely because they also
# cannot be required to bind.
| ($active.transcript_cursor // null) as $cursor_raw
| ($cursor_raw // -1) as $cursor
# Binding is MANDATORY when the gate can actually see the truth: a cursor
# was recorded, the transcript resolved and parsed clean, and the node is
# not a join. Without this, a node that simply stays silent is never
# checked — the party the gate constrains could opt out of it by
# reporting plain-string evidence and citing nothing.
| ($cursor_raw != null and $transcript_clean) as $binding_required
| (.graph.joins // {}) as $joins
| (.graph.nodes // {}) as $nodes
# Every tool_use_id already bound anywhere in the graph — the reuse set.
# Descends recursively (..): a top-level-only scan missed ids nested in
# an array or under another key, which let the same real spawn bind to a
# second node.
| ([ $nodes[]? | (.evidence // []) | .. | objects
     | .tool_use_id? | select(type == "string") ]) as $already_bound
# Every agent_id already bound anywhere in the graph — the identity
# reuse set. One underlying agent (one transcript <task-id>) must never
# satisfy two different graph nodes, even across separate tool_use_ids.
| ([ $nodes[]? | (.evidence // []) | .. | objects
     | .agent_id? | select(type == "string") ]) as $already_bound_agents
# Notifications this wave candidate spawns can be checked against,
# indexed by tool_use_id for a fast per-node lookup.
| ($notifications | group_by(.tool_use_id) | map({key: .[0].tool_use_id, value: .}) | from_entries) as $notif_by_tool
| reduce ($wave | keys[]) as $id (
    {out: {}, used: $already_bound, used_agents: $already_bound_agents};
    ($wave[$id]) as $result
    # Captured while `.` is still the reduce state — inside the pipeline
    # below `.` becomes each intermediate value, not the accumulator.
    | (.used) as $used_ids
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
        # A claim is ANY caller-supplied evidence entry that asserts
        # provenance ANYWHERE inside it. Only this gate may mint a
        # reference, so rather than enumerating forged shapes — which
        # loses to array-wrapping, nesting, a trailing space, a homoglyph
        # or the shape as a JSON string — each entry is NORMALISED
        # (recursively walked, its string leaves included) and rejected
        # if it carries provenance-ish content at any depth.
        #
        # `claim_of` returns the cited id (or "" when the entry is
        # provenance-shaped without a usable id, which still counts as a
        # claim and so still has to match a real spawn).
        | ([ $evidence[] | select(looks_provenance)
             | (norm_ids | if length > 0 then .[0] else "" end) ]) as $claims
        | ([ $evidence[] | select(looks_provenance | not) ]) as $kept
        # A caller-supplied .agent_id is refused unconditionally, before
        # anything else: only this gate may mint an agent_id, so its
        # mere presence in caller-reported evidence is forged
        # provenance regardless of whether the node also owns a real
        # spawn to bind.
        | if ([ $evidence[] | select(has_caller_agent_id) ] | length) > 0
          then error("graph_evidence: node \($id) cites a caller-supplied agent_id, which only this gate may mint")
          else . end
        # Spawns this node genuinely owns in this wave, after the cursor,
        # oldest first. A node legitimately has MORE THAN ONE: a real wave
        # fans a single node out to several agents at once (observed live
        # in this repo — one node with three concurrent Agent calls inside
        # one wave, e.g. a review node dispatching three reviewers), and
        # apply_wave writes each node exactly once per wave, so all of
        # them are present by the time the wave is recorded. Demanding
        # exactly one would therefore deny legitimate waves.
        #
        # Loosening HOW MANY does not loosen WHICH: a bound id must still
        # come from this list (own node, own wave, after the cursor) and
        # must still be unused, so forgery, cross-node replay, pre-cursor
        # replay and reuse all still fail.
        #
        # session_mismatch entries (an envelope whose own session_id
        # disagrees with this session) are excluded from binding, but
        # tracked separately so a node whose only spawn is session-
        # mismatched gets a NAMED session error instead of the generic
        # "nothing to bind" message. Checked WITHOUT the cursor filter —
        # a forged/replayed envelope is refused on the forgery alone,
        # not on where it happens to sit relative to the cursor.
        | ([ if $cursor_raw == null then empty else $spawns[] end
             | select(.node_id == $id and .wave_id == $wave_id and .line > $cursor
                      and (.session_mismatch // false) != true) ]
           | sort_by(.line)) as $candidates
        | ([ $spawns[]
             | select(.node_id == $id and .wave_id == $wave_id
                      and (.session_mismatch // false) == true) ]
           | length > 0) as $has_session_mismatch
        | ([ $candidates[] | . as $c
             | select(($used_ids | index($c.tool_use_id)) == null) ]) as $free
        | ($free | if length > 0 then [.[-1]] else [] end) as $matches
        | if ($matches | length) == 0
          then
            if ($claims | length) > 0
            then error("graph_evidence: node \($id) cites an unbindable spawn \($claims[0])")
            elif $has_session_mismatch
            then error("graph_evidence: node \($id) has a spawn envelope whose session does not match this session")
            # Citing nothing must not be a way out. When the gate can see
            # the truth, a non-join node with no spawn in this wave was
            # never dispatched, whatever it reports about itself.
            elif ($binding_required and ($joins | has($id) | not))
            then error("graph_evidence: node \($id) has no spawn in \($wave_id); nothing to bind")
            else .out[$id] = ($result + {evidence: ($carried_kept + $kept)})
            end
          else
            ($matches[0]) as $m
            # A claim may name ANY spawn this node genuinely owns in this
            # wave (with fan-out, several are legitimate) — but nothing
            # else. A forged, cross-node, cross-wave or pre-cursor id is
            # absent from $candidates and still fails here.
            | ([ $candidates[] | .tool_use_id ]) as $ownable
            | if ($claims | map(. as $cl | select(($ownable | index($cl)) == null))
                   | length) > 0
              then error("graph_evidence: node \($id) cites a spawn it does not own")
              elif (.used | index($m.tool_use_id)) != null
              then error("graph_evidence: spawn \($m.tool_use_id) is already bound")
              elif (($result.outcome // $result.status // "") != "done")
              then
                # Only a "done" node needs a successful terminal result
                # bound to it — a retry ("failed" -> folded to "pending"
                # or "hard-stop" by graph_dispatch_record before this
                # gate ever runs) legitimately has no completed
                # notification yet, and must still bind this attempt
                # spawn reference so the retry/hard-stop evidence trail
                # stays intact.
                .used += [$m.tool_use_id]
                | .out[$id] = ($result + {evidence: ($carried_kept + $kept + [{
                      kind: "claude_agent",
                      attempt: (($nodes[$id].retry.attempts // 0) + 1),
                      wave_id: $wave_id,
                      tool_use_id: $m.tool_use_id,
                      record_uuid: $m.record_uuid,
                      subagent_type: $m.subagent_type}])})
              elif ($m.dispatch_status // "") == "teammate_spawned" then error("graph_evidence: node \($id) was dispatched via mailbox/teammate (spawn \($m.tool_use_id)); mailbox-dispatched agents cannot bind graph evidence — re-dispatch via unnamed Agent for nodes that must bind as done")
              else
                # Terminal-result requirement: the spawn alone is not
                # enough. At least one <task-notification> in the
                # parent session own transcript, matched by tool-use-id,
                # must report status=completed with a non-empty result
                # before a done node evidence entry can bind.
                ($notif_by_tool[$m.tool_use_id] // []) as $notifs
                | ([ $notifs[] | select(.status == "completed" and ((.result // "") | length) > 0) ]) as $good
                | if ($notifs | length) == 0
                  then error("graph_evidence: node \($id) has no completed notification for spawn \($m.tool_use_id)")
                  elif ($good | length) == 0
                  then ($notifs[-1].status // "unknown") as $bad_status
                    | error("graph_evidence: node \($id) spawn \($m.tool_use_id) has notification status \($bad_status), not a successful completion")
                  else
                    ($good[0].task_id // $m.tool_use_id) as $agent_id
                    | if (.used_agents | index($agent_id)) != null
                      then error("graph_evidence: agent_id \($agent_id) is already bound to another node")
                      else
                        .used += [$m.tool_use_id]
                        | .used_agents += [$agent_id]
                        | .out[$id] = ($result + {evidence: ($carried_kept + $kept + [{
                              kind: "claude_agent",
                              attempt: (($nodes[$id].retry.attempts // 0) + 1),
                              wave_id: $wave_id,
                              tool_use_id: $m.tool_use_id,
                              record_uuid: $m.record_uuid,
                              subagent_type: $m.subagent_type,
                              agent_id: $agent_id}])})
                      end
                  end
              end
          end
      end
  )
| .out
JQ_BODY_EOF
)

graph_evidence_bind_wave() {
    local progress="$1" wave_json="$2"
    local context spawns_json notifications_json transcript_clean
    context=$(_graph_evidence_resolve_context "$progress" "$wave_json") || return 1
    [ -n "$context" ] || return 1
    spawns_json=$(printf '%s' "$context" | jq -c '.spawns') || return 1
    notifications_json=$(printf '%s' "$context" | jq -c '.notifications') || return 1
    transcript_clean=$(printf '%s' "$context" | jq -r '.transcript_clean') || return 1

    jq -e -c --argjson spawns "$spawns_json" --argjson wave "$wave_json" \
        --argjson transcript_clean "$transcript_clean" \
        --argjson notifications "$notifications_json" \
        "$GRAPH_EVIDENCE_BIND_JQ_DEFS
$GRAPH_EVIDENCE_BIND_JQ_BODY" "$progress"
    # stderr is deliberately NOT suppressed: every denial above is raised via
    # error() with a "graph_evidence:" message naming the node and the reason.
    # Swallowing it would make a cursor denial indistinguishable from a wave-id
    # mismatch, both to an operator reading a refused wave and to a test
    # asserting that it denied for the right reason.
}
