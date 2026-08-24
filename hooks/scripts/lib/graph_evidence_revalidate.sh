#!/bin/bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
# graph_evidence_revalidate.sh — completion-time RE-VALIDATION of already-bound
# claude_agent evidence, built on graph_evidence.sh's transcript-reading
# primitives (graph_evidence_transcript, graph_evidence_notifications), which
# this file sources. graph_evidence_bind_wave (graph_evidence_bind.sh) makes
# the binding DECISION at record time; graph_evidence_revalidate_all here
# re-derives the same truth from the transcript a second time, immediately
# before a graph is allowed to complete, so a transcript mutated (or evidence
# hand-edited) after a legitimate bind cannot ride that earlier trust to
# completion.
#
# SOURCED by graph_dispatch.sh, not executed directly.

GRAPH_EVIDENCE_REVALIDATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_EVIDENCE_REVALIDATE_DIR/graph_evidence.sh"

# graph_evidence_revalidate_all <progress.json>
# Re-checks EVERY "done" node's already-bound claude_agent evidence again,
# immediately before a graph is allowed to complete. graph_evidence_bind_wave
# verifies a binding once, at record time — this re-derives the same truth
# from the transcript a second time at completion time, so a transcript
# mutated (or evidence hand-edited) AFTER a legitimate bind cannot ride that
# earlier trust all the way to completion.
#
# A graph with NO claude_agent-kind evidence anywhere (every node bound
# legacy-style — a plain string, or no transcript ever resolved at bind
# time) has nothing this function can or must re-verify, and completes
# exactly as it always could: revalidation is additive on top of a real
# bind, never a new requirement for a graph that was never asked to bind.
#
# Otherwise, re-checks:
#   * the parent session transcript still resolves and parses cleanly
#   * GLOBAL UNIQUENESS: across every claude_agent evidence entry on every
#     "done" OR "skipped" node (graph_dispatch_complete admits both as a
#     terminal state — see its own gate), no tool_use_id or agent_id is bound
#     to more than one node. Skipped nodes are included here because the
#     non-done bind branch in graph_evidence_bind_wave writes claude_agent
#     evidence for them too (a retry/hard-stop attempt carried forward), so a
#     scan limited to "done" alone would miss an id shared between a done node
#     and a skipped one.
#   * TERMINAL-RESULT RECHECK, "done" nodes only (a skipped node's carried
#     evidence never had a completed notification to begin with — that is
#     legitimate, not a gap): each "done" node carrying any claude_agent
#     evidence must have AT LEAST ONE entry that both carries a non-empty
#     .agent_id — the field graph_evidence_bind_wave mints ONLY on its
#     successful-completion path (~line 531), never on the retry/hard-stop
#     carry-forward path (~line 503) — and still has at least one
#     <task-notification> for its tool_use_id reporting status=completed
#     with a non-empty result and a matching agent_id. Checked PER NODE
#     rather than per entry so that hand-stripping .agent_id off the one
#     entry that used to prove a node cannot make it look, node-wide, like
#     every remaining entry is a legitimate no-agent_id carried-forward
#     retry reference (see the recheck's own inline comment for why
#     per-entry alone is vacuously satisfiable). A carried-forward entry
#     with no agent_id at all is not re-demanded a notification it was
#     never bound against — treating it as if it needed one would deadlock
#     every node that ever retried before finishing.
#
# DEFERRED (not closed by this pass, scope-safe reason recorded here rather
# than invented state to fix it): revalidation re-derives NOTIFICATION
# presence for a bound entry, but never re-derives SPAWN presence — a
# transcript with the original Agent-dispatch tool_use record itself deleted
# (while the notification block for that tool_use_id survives) still passes.
# Closing this durably requires knowing, at revalidate-time, whether each
# done node's binding was made under a cursor-bound wave — and
# progress.json does not retain that once .graph.active_wave is cleared at
# wave-close. The two ways to reconstruct it both cost more than this pass's
# scope allows: (a) a new durable per-node provenance marker/store, which is
# explicitly out of scope for this PR; or (b) re-deriving "a spawn exists
# for this node in the transcript" from the transcript alone at
# revalidate-time, which cannot distinguish a legitimate spawn-less bind
# (the cursorless/legacy-graph path graph_evidence.test.sh already pins as
# correct) from a tampered one, and so would reject graphs this same suite
# requires to still complete.
#
# Fails closed (non-zero, a NAMED "graph_evidence: ... revalidation ..."
# reason on stderr) on any failure, including an unreadable/malformed
# transcript.
graph_evidence_revalidate_all() {
    local progress="$1" session
    [ -f "$progress" ] || return 1

    session=$(jq -r '.session_id // empty' "$progress" 2>/dev/null) || return 1
    [ -n "$session" ] || return 1

    # Nothing bound to revalidate — a legacy/no-transcript graph completes
    # exactly as it always could. The selector here MUST match the uniqueness
    # scan below (done-or-skipped) or a graph whose only claude_agent evidence
    # sits on a skipped node would short-circuit here and never reach it.
    local probe_rc
    jq -e '
      [ .graph.nodes // {} | to_entries[] | select(.value.status | IN("done","skipped"))
        | (.value.evidence // []) | if type == "array" then . else [.] end
        | .[] | select(type == "object" and .kind == "claude_agent") ] | length > 0
    ' "$progress" >/dev/null 2>&1
    probe_rc=$?
    # rc=1: the jq boolean expression evaluated false — genuinely nothing
    # bound, proceed to completion as always. Any OTHER nonzero (a crash on a
    # malformed node shape, e.g. rc=5) must fail closed with a named reason
    # instead of being folded into the same "nothing to revalidate" exit, or
    # the header's own "fails closed on any failure" claim would be false for
    # this probe specifically.
    if [ "$probe_rc" -eq 1 ]; then
        return 0
    elif [ "$probe_rc" -ne 0 ]; then
        printf 'graph_evidence: revalidation could not evaluate bound evidence in %s\n' \
            "$progress" >&2
        return 1
    fi

    local transcript raw_notifications notif_rc notifications_json
    if ! transcript=$(graph_evidence_transcript "$session"); then
        printf 'graph_evidence: revalidation could not resolve the transcript for session %s\n' \
            "$session" >&2
        return 1
    fi
    raw_notifications=$(graph_evidence_notifications "$transcript" "$session")
    notif_rc=$?
    if [ "$notif_rc" -gt 4 ]; then
        printf 'graph_evidence: revalidation found the transcript for session %s malformed or unreadable\n' \
            "$session" >&2
        return 1
    fi
    notifications_json=$(printf '%s' "$raw_notifications" | jq -c --slurp '.' 2>/dev/null) || return 1
    [ -n "$notifications_json" ] || notifications_json='[]'

    jq -e --argjson notifications "$notifications_json" '
      ($notifications | group_by(.tool_use_id) | map({key: .[0].tool_use_id, value: .}) | from_entries) as $notif_by_tool
      | (.graph.nodes // {}) as $nodes
      | [ $nodes | to_entries[] | select(.value.status | IN("done","skipped"))
          | .key as $id
          | (.value.evidence // []) | if type == "array" then . else [.] end
          | .[] | select(type == "object" and .kind == "claude_agent")
          | . + {node_id: $id} ] as $bound
      # Global uniqueness across every done-or-skipped node evidence: a
      # tool_use_id or agent_id bound to more than one node is tamper,
      # whatever the transcript says now.
      | ([ $bound[] | .tool_use_id ] | group_by(.) | map(select(length > 1)) | length > 0) as $dup_tool
      | ([ $bound[] | .agent_id // empty ] | group_by(.) | map(select(length > 1)) | length > 0) as $dup_agent
      # Terminal-result recheck applies only to entries on "done" nodes that
      # actually carry a minted agent_id — a carried-forward retry-attempt
      # reference (no agent_id) legitimately never had a notification and
      # must not be re-demanded one here, or every node that ever retried
      # before succeeding could never complete.
      #
      # Checked PER NODE, not per entry: a "done" node with ANY claude_agent
      # evidence must have AT LEAST ONE entry that both carries an agent_id
      # and still passes the notification recheck below. Per-entry ("every
      # agent_id-bearing entry that exists must still pass") is vacuously
      # true once every agent_id has been stripped from a nodes evidence — a
      # hand-edit that deletes the .agent_id field on a bound entry would
      # make it indistinguishable from a legitimate carried-forward retry
      # entry and skip the recheck entirely for that node. Requiring a node
      # to have earned at least one still-good qualifying entry closes
      # that gap: the other agent_id-stripped entries no longer count as a
      # legitimate substitute for the one that used to prove it.
      | ([ $bound[] | .node_id ] | unique) as $done_or_skipped_ids
      | ($done_or_skipped_ids
         | map(select(($nodes[.].status // "") == "done"))) as $done_with_evidence
      | if $dup_tool or $dup_agent
        then error("graph_evidence: revalidation found a tool_use_id or agent_id bound to more than one node")
        else
          reduce $done_with_evidence[] as $id (null;
            if . != null then . else
              ([ $bound[] | select(.node_id == $id and (.agent_id // "") != "")
                 | . as $ev
                 | ($notif_by_tool[$ev.tool_use_id] // []) as $notifs
                 | ([ $notifs[] | select(.status == "completed" and ((.result // "") | length) > 0) ]) as $good
                 | select(($good | length) > 0 and ($ev.agent_id == ($good[0].task_id // $ev.tool_use_id))) ]
                 | length > 0) as $has_valid_qualifying_entry
              | if $has_valid_qualifying_entry then null
                else error("graph_evidence: revalidation found no still-valid completed-notification evidence for node \($id)")
                end
            end)
        end
      | true
    ' "$progress" >/dev/null
}
