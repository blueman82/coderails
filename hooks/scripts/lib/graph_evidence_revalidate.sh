#!/bin/bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
# graph_evidence_revalidate.sh — completion-time RE-VALIDATION of already-bound
# claude_agent evidence, built on graph_evidence.sh's transcript-reading
# primitives (graph_evidence_transcript, graph_evidence_notifications), which
# this file sources. graph_evidence_bind_wave (graph_evidence_bind.sh) makes
# the binding DECISION at record time; graph_evidence_revalidate_all re-derives
# the same truth from the transcript a second time, immediately before a graph
# is allowed to complete, so a transcript mutated (or evidence hand-edited)
# after a legitimate bind cannot ride that earlier trust to completion.
#
# SOURCED by graph_dispatch.sh, not executed directly.

GRAPH_EVIDENCE_REVALIDATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_EVIDENCE_REVALIDATE_DIR/graph_evidence.sh"
# graph_evidence_bind.sh is sourced for GRAPH_EVIDENCE_BIND_JQ_DEFS, the same
# `looks_provenance` detector bind uses to recognise provenance-shaped
# evidence at any depth. Reusing it (not reimplementing it) is what keeps a
# shape bind would refuse (array-wrapped, nested, trailing-space .kind,
# homoglyph, stringified JSON) from silently reading as "nothing bound" here.
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_EVIDENCE_REVALIDATE_DIR/graph_evidence_bind.sh"

# graph_evidence_revalidate_all <progress.json>
# Re-checks every "done"/"skipped" node's already-bound claude_agent evidence
# a second time, immediately before a graph completes. A graph with nothing
# provenance-shaped bound anywhere (legacy string binds, or no transcript)
# has nothing to re-verify and completes exactly as before — revalidation is
# additive on a real bind, never a new requirement for a graph never asked to
# bind. What each recheck below (GLOBAL UNIQUENESS, TERMINAL-RESULT,
# PER-ATTEMPT SEQUENCE, SPAWN PRESENCE, EVIDENCE PRESENCE) verifies, and why,
# is documented at its own point of use in the jq program below — that is
# the only copy of that reasoning; this header does not restate it.
#
# One disclosed residual: EVIDENCE PRESENCE proves a wave genuinely bound
# something via either a surviving sibling node's evidence or a durable
# .graph.wave_history entry (see that clause). A wave that legitimately never
# recorded either — a pre-fix loop, or a genuinely cursorless wave — and lost
# every node's evidence is still information-theoretically identical to
# "never dispatched" from what progress.json and the transcript can prove at
# completion time. See the PR description for the begun-then-abandoned-wave
# flip-condition this does not close.
#
# Fails closed (non-zero, a NAMED "graph_evidence: ... revalidation ..."
# reason on stderr) on any failure, including an unreadable/malformed
# transcript.
#
# The two jq programs below live at file scope, not as locals inside
# graph_evidence_revalidate_all, because this repo's function-size ceiling
# counts brace-depth-delimited lines textually — a local heredoc would still
# charge every physical line to the function's own total. Both are
# concatenated after GRAPH_EVIDENCE_BIND_JQ_DEFS at call time, so
# `looks_provenance` resolves to the SAME detector the bind-time gate uses.
GRAPH_EVIDENCE_REVALIDATE_JQ_PROBE=$(cat <<'JQ_PROBE_EOF'
      [ .graph.nodes // {} | to_entries[] | select(.value.status | IN("done","skipped"))
        | (.value.evidence // []) | if type == "array" then . else [.] end
        | .[] | select(looks_provenance) ] | length > 0
JQ_PROBE_EOF
)
GRAPH_EVIDENCE_REVALIDATE_JQ_MAIN=$(cat <<'JQ_MAIN_EOF'
      ($notifications | group_by(.tool_use_id) | map({key: .[0].tool_use_id, value: .}) | from_entries) as $notif_by_tool
      # Freshly re-derived spawn ROWS, session-matched only (same exclusion
      # graph_evidence_bind_wave applies before binding, so a cross-session
      # replayed envelope can't satisfy a spawn demand it never could at bind
      # time). Kept as ROWS, not flattened to a bare id list: bind only binds
      # a spawn to a node whose OWN envelope names that node (`.node_id ==
      # $id`), so an id existing under a DIFFERENT node was never bindable —
      # a flat list would let a done node whose own spawn was deleted forge a
      # citation of another node's real live spawn. .node_id comes from the
      # transcript envelope, unreachable by the party editing progress.json.
      | ([ $spawns[] | select((.session_mismatch // false) != true)
           | select((.tool_use_id | type) == "string") ]) as $spawn_rows
      | (.graph.nodes // {}) as $nodes
      # Selected with the bind-time normalising detector (not an exact .kind
      # match), so every forged variant is dragged INTO this check. But the id
      # fields are read at the TOP LEVEL ONLY, exactly where
      # graph_evidence_bind_wave writes them: deep select is fail-closed (more
      # entries must prove themselves); deep read would be fail-open (a forged
      # entry burying a real id under a benign key would satisfy the very
      # check it should fail). Deep select, shallow read.
      | [ $nodes | to_entries[] | select(.value.status | IN("done","skipped"))
          | .key as $id
          | (.value.evidence // []) | if type == "array" then . else [.] end
          | .[] | select(looks_provenance)
          | {node_id: $id,
             is_object: (type == "object"),
             tool_use_id: (if type == "object" then (.tool_use_id? // null) else null end),
             agent_id: (if type == "object" then (.agent_id? // null) else null end),
             attempt: (if type == "object" then (.attempt? // null) else null end)}
          | .tool_use_id = (if (.tool_use_id | type) == "string" then .tool_use_id else null end)
          | .agent_id = (if (.agent_id | type) == "string" then .agent_id else null end)
          | .attempt = (if (.attempt | type) == "number" then .attempt else null end) ] as $bound
      # Global uniqueness across every done-or-skipped node evidence: a
      # tool_use_id or agent_id bound to more than one node is tamper,
      # whatever the transcript says now.
      #
      # `// empty` on BOTH, so an absent id is dropped rather than compared.
      # A missing tool_use_id is now normalised to null (an entry that is
      # provenance-shaped but carries no top-level id — every forged variant,
      # and a legitimate carried-forward reference), and `group_by` would
      # otherwise read two such nulls as one id "bound twice" and reject on
      # the wrong reason. Those entries are refused below on the reason that
      # actually applies to them, not on a spurious duplicate.
      | ([ $bound[] | .tool_use_id // empty ] | group_by(.) | map(select(length > 1)) | length > 0) as $dup_tool
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
      # PER-ATTEMPT SEQUENCE recheck, "done" nodes only (mirrors
      # graph_evidence.py's `sorted(attempts) != range(1, expected_count+1)`).
      # Presence/uniqueness/terminal-result above pass on ANY one qualifying
      # entry, so deleting an earlier FAILED attempt's entry while keeping the
      # successful one erases real retry history undetected. Close that by
      # demanding the bound attempts equal the contiguous run 1..expected_count,
      # where expected_count = retry.attempts + 1 (bind mints each entry's
      # .attempt as retry.attempts-at-bind-time + 1).
      #
      # "done" only, not "skipped": bash's graph_dispatch_record increments
      # .attempts on every "failed" report (incl. the hard-stop one), never
      # on "done" — so a skipped node's retry.attempts already equals its
      # bound attempts with no extra +1; the done formula would demand
      # [1,2] against its actual [1] (pinned by "a skipped node carrying
      # bound evidence still completes") and false-reject it. Python's own
      # `(1 if status in {"done","skipped"} else 0)` also excludes
      # "skipped" — not "unconditionally", per an earlier draft here.
      #
      # `.is_object` only: a legacy string/array forgery has no top-level
      # .attempt; a node with zero structured entries is left to the more
      # specific "no structured bound entry" branch further down.
      #
      # Disclosed residual, same shape as EVIDENCE-PRESENCE's "two
      # coordinated edits, not zero" below: editing BOTH the surviving
      # entry's .attempt and the node's retry.attempts (same orchestrator-
      # owned progress.json) together defeats this — PR's Security scope.
      | ([ $done_with_evidence[] | . as $id
           | select([ $bound[] | select(.node_id == $id and .is_object) ] | length > 0)
           | (($nodes[$id].retry.attempts // 0) + 1) as $expected_count
           | ([ $bound[] | select(.node_id == $id and .is_object) | .attempt ] | sort) as $attempts
           | select($attempts != [range(1; $expected_count + 1)])
           | $id ]) as $bad_attempt_sequence
      # SPAWN-PRESENCE re-derivation, per ENTRY and only for entries that
      # actually assert a top-level tool_use_id. Such an entry can only have
      # been written by graph_evidence_bind_wave, which mints tool_use_id
      # solely from a spawn row graph_evidence_spawns read out of THIS
      # transcript — so the spawn provably existed, and demanding it back
      # cannot punish a legitimate bind. An entry with no tool_use_id (the
      # cursorless/legacy-graph bind, or a carried-forward retry reference)
      # is never asked for a spawn it was never bound against, which is what
      # keeps the legacy completion path working.
      #
      # Matched on the spawn row's OWN node_id, mirroring bind's
      # `.node_id == $id` candidate filter. wave_id is deliberately omitted
      # (the entry's wave_id is attacker-writable post-bind; the row's node_id
      # is not). dispatch_status is filtered on the qualifying-entry check
      # below rather than in this all-entries scan, because bind refuses
      # teammate_spawned only on its done branch — filtering here would
      # deadlock a legitimate mailbox-dispatched retry carry-forward or
      # skipped node.
      #
      # `. as $e` first: inside the inner select the input is a spawn row, so
      # a bare `.tool_use_id` there would read the ROW's id, not the entry's.
      | ([ $bound[] | . as $e | select($e.tool_use_id != null)
           | select([ $spawn_rows[]
                      | select(.tool_use_id == $e.tool_use_id
                               and .node_id == $e.node_id) ] | length == 0) ]) as $missing_spawn
      # EVIDENCE-PRESENCE re-derivation, the complement of spawn presence,
      # DELIBERATELY NARROWER than "every node any spawn row names": that
      # wider set was refused in review as a critical regression, since bind
      # itself leaves a cursorless wave's nodes legitimately unbound (see
      # graph_evidence_bind.sh's `$matches is forced empty`) and the wider
      # form demanded evidence bind never demanded. This clause must refuse
      # ONLY a node whose evidence bind actually wrote and was later deleted.
      #
      # $bound_waves = wave_ids PROVEN to have bound something: a spawn row's
      # tool_use_id appearing in $bound_tools is transcript-evidence that wave
      # produced a binding. wave_id is read off the SPAWN ROW, never off the
      # evidence entry's own attacker-writable copy.
      #
      # A done/skipped node named by a spawn row whose wave_id is in
      # $bound_waves, with zero surviving $bound entries of its own, had its
      # evidence deleted from a wave that DID bind: a sibling's surviving
      # evidence proves the wave was real and cursor-respecting, so this
      # node's absence is unexplainable except by deletion.
      #
      # $dispatched_by_sibling omits the cursor filter bind's own candidate
      # filter applies (`.line > $cursor`), so a pre-cursor spawn row in an
      # otherwise-bound wave_id still counts as "dispatched" here. Closed
      # below by $dispatched_by_history, which applies its own cursor check
      # against .graph.wave_history (durably retained per-wave since it
      # survives completion's `.graph.active_wave = null`, unlike the cursor
      # this sibling path can only reconstruct from a surviving sibling).
      # wave_history is still orchestrator-editable (lives in progress.json),
      # so a coordinated tamperer can forge it too — see the PR description's
      # "two coordinated edits, not zero" framing.
      | ([ $bound[] | .tool_use_id | select(. != null) ] | unique) as $bound_tools
      | ([ $spawn_rows[] | select(.tool_use_id as $t | $bound_tools | index($t))
           | .wave_id | select(type == "string") ] | unique) as $bound_waves
      | ([ $spawn_rows[] | select(.wave_id as $w | $bound_waves | index($w))
           | .node_id | select(type == "string") ] | unique) as $dispatched_by_sibling
      # WAVE-HISTORY WIDENING, additive on $dispatched_by_sibling, never a
      # narrowing: graph_dispatch_begin_wave durably records each cursored
      # wave's {cursor, nodes} into .graph.wave_history at open time, so a
      # wave_history entry alone proves a wave was genuinely opened with
      # these exact nodes/cursor without needing any evidence to survive.
      #
      # Three independently-required clauses below, each closing a distinct
      # false-positive/false-negative found during design review:
      #   * $wh[$r.wave_id] != null — a cursorless wave never gets a
      #     wave_history entry (the write side omits the key), so its nodes
      #     stay exempt exactly as $dispatched_by_sibling already exempts them.
      #   * $r.line > $wh[$r.wave_id].cursor — rejects a spawn row whose
      #     wave_id was forward-forged into a prompt before that wave's cursor
      #     was recorded; mirrors bind's own `.line > $cursor` filter.
      #   * $wh[$r.wave_id].nodes | index($r.node_id) — rejects a stray or
      #     replayed dispatch naming a node/wave pair outside the recorded
      #     wave's own node set. Without this a copied prompt could drag an
      #     uninvolved id into the demanded set and false-refuse an honest
      #     graph — a real bug in an earlier {cursor:N}-only design.
      | (.graph.wave_history // {}) as $wh
      | ([ $spawn_rows[] | . as $r
           | select(($r.wave_id | type) == "string" and ($wh[$r.wave_id] // null) != null)
           | select($r.line > $wh[$r.wave_id].cursor)
           | select($wh[$r.wave_id].nodes | index($r.node_id))
           | $r.node_id ]) as $dispatched_by_history
      | (($dispatched_by_sibling + $dispatched_by_history) | unique) as $dispatched
      | ([ $dispatched[] | . as $nid
           | select(($nodes[$nid].status // "") | IN("done","skipped"))
           | select([ $bound[] | select(.node_id == $nid) ] | length == 0) ]) as $evidence_gone
      | if $dup_tool or $dup_agent
        then error("graph_evidence: revalidation found a tool_use_id or agent_id bound to more than one node")
        elif ($missing_spawn | length) > 0
        then error("graph_evidence: revalidation found no Agent spawn in the transcript for tool_use_id \($missing_spawn[0].tool_use_id) bound to node \($missing_spawn[0].node_id)")
        elif ($evidence_gone | length) > 0
        then error("graph_evidence: revalidation found a real Agent spawn in the transcript for node \($evidence_gone[0]) but no bound evidence survives on it")
        elif ($bad_attempt_sequence | length) > 0
        then error("graph_evidence: revalidation found node \($bad_attempt_sequence[0]) missing one or more of its bound retry attempts; surviving evidence does not form a contiguous attempt sequence")
        else
          reduce $done_with_evidence[] as $id (null;
            if . != null then . else
              # A qualifying entry clears FOUR things, all read at the top
              # level: a minted agent_id; a still-present session-matched spawn
              # for its tool_use_id naming THIS node (refuses a buried/nested
              # id — arraywrap, nested, jsonstring); that spawn not being a
              # mailbox/teammate dispatch (mirrors graph_evidence_bind.sh's own
              # refusal to bind DONE against teammate_spawned — a mailbox
              # dispatch reports via <teammate-message>, which carries no
              # harness discriminator and can never prove completion); and a
              # still-valid completed notification agreeing with that agent_id
              # (refuses a real top-level tool_use_id with no minted agent_id —
              # trailspace, homoglyph, spawnref).
              #
              # node_id is deliberately NOT re-matched here: $missing_spawn
              # already proved a same-node spawn row exists for this id before
              # this reduce runs, and graph_evidence.sh's $status_by_tool is
              # keyed on tool_use_id alone, so two rows sharing an id can never
              # disagree on dispatch_status — re-matching could not discriminate.
              ([ $bound[] | . as $ev
                 | select($ev.node_id == $id and ($ev.agent_id // "") != ""
                          and $ev.tool_use_id != null)
                 | select([ $spawn_rows[]
                            | select(.tool_use_id == $ev.tool_use_id
                                     and (.dispatch_status // "") != "teammate_spawned") ]
                          | length > 0)
                 | ($notif_by_tool[$ev.tool_use_id] // []) as $notifs
                 | ([ $notifs[] | select(.status == "completed" and ((.result // "") | length) > 0) ]) as $good
                 | select(($good | length) > 0 and ($ev.agent_id == ($good[0].task_id // $ev.tool_use_id))) ]
                 | length > 0) as $has_valid_qualifying_entry
              | if $has_valid_qualifying_entry then null
                # A node none of whose selected entries is an object reaches
                # here too (legacy string or array-wrapped forgery, worded
                # shape-neutrally since neither is "free text"); named
                # separately so the error blames the real cause, not
                # notification evidence.
                elif ([ $bound[] | select(.node_id == $id and .is_object) ] | length) == 0
                then error("graph_evidence: revalidation found no structured bound entry on node \($id); its evidence is a string or array, not the bound object shape")
                # A node whose otherwise-qualifying entry was excluded ONLY by
                # the dispatch_status clause also reaches the terminal else;
                # named separately so a mailbox dispatch (notification present
                # and completed) doesn't send the operator hunting a
                # notification that was never the problem. Inner select is the
                # exact complement of the qualifying clause's dispatch_status
                # check (`!=` becomes `==`). node_id not re-matched, same
                # reasoning as the qualifying clause above.
                elif ([ $bound[] | . as $ev
                        | select($ev.node_id == $id and ($ev.agent_id // "") != ""
                                 and $ev.tool_use_id != null)
                        | select([ $spawn_rows[]
                                   | select(.tool_use_id == $ev.tool_use_id
                                            and (.dispatch_status // "") == "teammate_spawned") ]
                                 | length > 0) ] | length) > 0
                then error("graph_evidence: revalidation found node \($id) bound to a spawn dispatched via mailbox/teammate; mailbox-dispatched agents report completion as a <teammate-message> carrying no harness discriminator, so they cannot prove completion — re-dispatch via unnamed Agent for nodes that must bind as done")
                else error("graph_evidence: revalidation found no still-valid completed-notification evidence for node \($id)")
                end
            end)
        end
      | true
JQ_MAIN_EOF
)

graph_evidence_revalidate_all() {
    local progress="$1" session
    [ -f "$progress" ] || return 1

    session=$(jq -r '.session_id // empty' "$progress" 2>/dev/null) || return 1
    [ -n "$session" ] || return 1

    # Does ANYTHING on a done/skipped node currently look provenance-shaped?
    # Can no longer decide "nothing to revalidate" alone (see $evidence_gone
    # in JQ_MAIN: a node's real dispatch history can outlive its since-deleted
    # evidence, indistinguishable here from "never dispatched"). Kept only to
    # answer a narrower question, read only below: can a session whose
    # transcript no longer resolves still be treated as the legacy/
    # no-transcript case, or must it fail closed?
    #
    # `looks_provenance` (bind's own detector) replaces an exact `.kind ==
    # "claude_agent"` match, which was itself the bug — a whitelist of one
    # shape that any forged variant fell out of, reading as "nothing bound".
    # The normalising detector scans string leaves recursively, so wrapping/
    # nesting/whitespace/homoglyph/stringified-JSON variants all still select
    # and must prove themselves below.
    local probe_rc nothing_bound=0
    jq -e "$GRAPH_EVIDENCE_BIND_JQ_DEFS
$GRAPH_EVIDENCE_REVALIDATE_JQ_PROBE" "$progress" >/dev/null 2>&1
    probe_rc=$?
    # rc=1: the jq boolean expression evaluated false — nothing on this graph
    # currently looks bound. Any OTHER nonzero (a crash on a malformed node
    # shape, e.g. rc=5) must fail closed with a named reason instead of being
    # folded into the same exit, or the header's own "fails closed on any
    # failure" claim would be false for this probe specifically.
    if [ "$probe_rc" -eq 1 ]; then
        nothing_bound=1
    elif [ "$probe_rc" -ne 0 ]; then
        printf 'graph_evidence: revalidation could not evaluate bound evidence in %s\n' \
            "$progress" >&2
        return 1
    fi

    local transcript raw_notifications notif_rc notifications_json
    if ! transcript=$(graph_evidence_transcript "$session"); then
        # An unresolvable transcript can't re-derive spawn presence for
        # $evidence_gone either, so nothing-bound stays on the legacy/
        # no-transcript path unchanged; something bound but unresolvable
        # fails closed (pinned by the "transcript mutated after bind" test).
        if [ "$nothing_bound" -eq 1 ]; then
            return 0
        fi
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

    # Re-derive SPAWN presence from the same resolved transcript. rc>4 is a
    # genuine parse abort (fails closed); rc=4, a clean parse with zero Agent
    # spawns, is legitimate (same `-gt 4` split _graph_evidence_resolve_context
    # applies to its own spawns walk) — an empty set is not a pass, it just
    # means every tool_use_id-asserting entry below fails to find its spawn,
    # exactly right for a transcript whose dispatch records were deleted.
    local raw_spawns spawn_rc spawns_json
    raw_spawns=$(graph_evidence_spawns "$transcript" "$session")
    spawn_rc=$?
    if [ "$spawn_rc" -gt 4 ]; then
        printf 'graph_evidence: revalidation found the transcript for session %s malformed or unreadable\n' \
            "$session" >&2
        return 1
    fi
    spawns_json=$(printf '%s' "$raw_spawns" | jq -c --slurp '.' 2>/dev/null) || return 1
    [ -n "$spawns_json" ] || spawns_json='[]'

    jq -e --argjson notifications "$notifications_json" \
        --argjson spawns "$spawns_json" \
        "$GRAPH_EVIDENCE_BIND_JQ_DEFS
$GRAPH_EVIDENCE_REVALIDATE_JQ_MAIN" "$progress" >/dev/null
}
