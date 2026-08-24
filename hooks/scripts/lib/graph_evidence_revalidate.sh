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
# graph_evidence_bind.sh is sourced for ONE thing: GRAPH_EVIDENCE_BIND_JQ_DEFS,
# the normalising `looks_provenance`/`norm_ids` detectors the bind-time gate
# uses to recognise provenance-shaped evidence at any depth. Revalidation MUST
# select bound evidence with the same detector bind used, or a shape bind would
# have refused (array-wrapped, nested under a benign key, a trailing space in
# .kind, a homoglyph, the bound object serialised as a JSON string) can be
# hand-edited into a node AFTER a legitimate bind and this gate will not even
# see it — the entry falls out of an exact-shape filter, the node looks like it
# has nothing bound, and the tamper rides to completion. Reusing the defs (not
# reimplementing them) is what keeps the two gates from drifting apart.
# shellcheck disable=SC1091  # path is resolved from this sourced file at runtime
. "$GRAPH_EVIDENCE_REVALIDATE_DIR/graph_evidence_bind.sh"

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
#   * SPAWN PRESENCE, re-derived from the transcript: every bound entry that
#     actually asserts a tool_use_id must still have a real Agent-dispatch
#     tool_use record for that id in this session's transcript, freshly
#     re-derived via graph_evidence_spawns. Deleting the original dispatch
#     record while leaving the <task-notification> block intact previously
#     still passed, because only notification presence was ever re-derived.
#
#     The demand is keyed on the spawn row, not on a bare id: the row must be
#     session-matched AND its own transcript envelope must name THE SAME NODE
#     the entry sits on. A flat "does this id exist anywhere" test let a
#     done node whose own dispatch record was deleted forge a citation of
#     a different, still-running node's real live spawn — the id existed, so the
#     demand was satisfied by a spawn that was never bindable to this node.
#     Session-mismatched rows are excluded for the same reason bind refuses
#     them: accepting any row regardless of the envelope's own session_id
#     would reopen the cross-session replay path bind already closes.
#
#     dispatch_status is NOT filtered in this presence scan, because bind
#     refuses a teammate_spawned spawn only on its DONE branch — a retry
#     carry-forward or a skipped node legitimately carries mailbox-dispatched
#     evidence. That demand is made instead on the terminal-result recheck's
#     qualifying entry, exactly where bind makes it.
#
#     The earlier deferral of this check reasoned that re-deriving spawn
#     presence "cannot distinguish a legitimate spawn-less bind from a
#     tampered one". That is true only if the demand is made per NODE. Made
#     per ENTRY, keyed on whether the entry itself asserts a tool_use_id, the
#     distinction is exact and needs no new durable state: an entry carrying
#     a tool_use_id was, by construction, bound against a real Agent spawn —
#     graph_evidence_bind_wave mints tool_use_id ONLY from a $candidates row
#     that graph_evidence_spawns read out of the transcript — so demanding
#     that spawn back is demanding something that provably existed. A
#     legitimately spawn-less bind (the cursorless/legacy-graph path) carries
#     no tool_use_id at all and is therefore never asked for a spawn it was
#     never bound against.
#
#     WIDENING, recorded rather than left to be discovered: this demand covers
#     EVERY entry asserting a tool_use_id on a "done" OR "skipped" node, which
#     includes two shapes previously re-checked for nothing at all — a
#     carried-forward failed-attempt reference with no agent_id, and a skipped
#     node's carried evidence (the terminal-result recheck is done-only, so a
#     skipped node was scanned for uniqueness alone). Both are still correct
#     demands: each such entry was bound against a real spawn too. Neither
#     deadlocks a legitimate graph, because every attempt's spawn lives in the
#     same session transcript — pinned by the "a retried node with a
#     carried-forward attempt entry still completes" and "a skipped node
#     carrying bound evidence still completes" cases in
#     graph_dispatch_complete.test.sh, each with its own deletion arm pinned
#     alongside it. The consequence to be aware of is that a graph now
#     depends on its FULL dispatch history surviving in the transcript, not
#     just the attempts that finally succeeded.
#
#     A THIRD widening, disclosed rather than filtered: `looks_provenance`
#     scans string leaves, so a legacy plain-STRING entry merely MENTIONING a
#     tool_use_id or "kind":"claude_agent" as free text now selects into the
#     bound set, normalises to no ids at all, and can never yield a qualifying
#     entry — so completion is refused. Accepted, not fixed: demanding a
#     top-level JSON object before consulting looks_provenance would drop the
#     array-wrapped AND JSON-string forgeries back out of the check entirely,
#     since neither is a top-level object (measured, not assumed). The refusal
#     instead names the cause — no STRUCTURED bound entry — rather than blaming
#     notification evidence. Worded shape-neutrally because an array-wrapped
#     forgery reaches the same branch and is not free text. A legacy string with
#     no provenance-ish text is unaffected: it never selects, and its graph
#     still short-circuits at the probe.
#
# Fails closed (non-zero, a NAMED "graph_evidence: ... revalidation ..."
# reason on stderr) on any failure, including an unreadable/malformed
# transcript.
# The two jq programs below live at file scope, not as locals inside
# graph_evidence_revalidate_all, for the same reason graph_evidence_bind.sh
# hoists GRAPH_EVIDENCE_BIND_JQ_{DEFS,BODY}: this repo's function-size
# ceiling counts brace-depth-delimited lines textually, so a local heredoc
# still charges every physical line to the function's own total. No
# behaviour change from the inline form.
#
# Both are concatenated after GRAPH_EVIDENCE_BIND_JQ_DEFS at call time, so
# `looks_provenance` resolves to the SAME detector the bind-time gate uses.
GRAPH_EVIDENCE_REVALIDATE_JQ_PROBE=$(cat <<'JQ_PROBE_EOF'
      [ .graph.nodes // {} | to_entries[] | select(.value.status | IN("done","skipped"))
        | (.value.evidence // []) | if type == "array" then . else [.] end
        | .[] | select(looks_provenance) ] | length > 0
JQ_PROBE_EOF
)
GRAPH_EVIDENCE_REVALIDATE_JQ_MAIN=$(cat <<'JQ_MAIN_EOF'
      ($notifications | group_by(.tool_use_id) | map({key: .[0].tool_use_id, value: .}) | from_entries) as $notif_by_tool
      # Freshly re-derived spawn ROWS, session-matched only. A row whose own
      # envelope session_id disagrees with this session is excluded, the same
      # exclusion graph_evidence_bind_wave applies before binding — honouring
      # it here too keeps a cross-session replayed envelope from satisfying a
      # spawn demand it could never have satisfied at bind time.
      #
      # Kept as ROWS, not flattened to a bare id list. A flat list can only
      # answer "does this id exist anywhere in the transcript", which is not
      # the question: graph_evidence_bind_wave binds a spawn to a node only
      # when the spawn's OWN envelope names that node (bind's $candidates
      # filter, `.node_id == $id`), so an id that exists but belongs to a
      # DIFFERENT node was never bindable here. Answering only the flat
      # question let a done node whose own spawn record was deleted forge a
      # citation of a second, still-running node's real live spawn and pass.
      # The row's .node_id comes from the transcript envelope, which the
      # party editing progress.json cannot reach.
      | ([ $spawns[] | select((.session_mismatch // false) != true)
           | select((.tool_use_id | type) == "string") ]) as $spawn_rows
      | (.graph.nodes // {}) as $nodes
      # Entries are selected with the bind-time normalising detector, NOT an
      # exact .kind match, so every forged variant is dragged INTO this check
      # rather than falling out of it. But the id fields each entry is judged
      # on are read at the TOP LEVEL ONLY, exactly where
      # graph_evidence_bind_wave writes them. That asymmetry is deliberate and
      # load-bearing: selecting deeply is fail-closed (more entries must prove
      # themselves), whereas READING deeply would be fail-open — a forged entry
      # that buries a real tool_use_id/agent_id under a benign key would
      # present both fields to the reader and satisfy the very checks it should
      # fail. Deep select, shallow read.
      | [ $nodes | to_entries[] | select(.value.status | IN("done","skipped"))
          | .key as $id
          | (.value.evidence // []) | if type == "array" then . else [.] end
          | .[] | select(looks_provenance)
          | {node_id: $id,
             is_object: (type == "object"),
             tool_use_id: (if type == "object" then (.tool_use_id? // null) else null end),
             agent_id: (if type == "object" then (.agent_id? // null) else null end)}
          | .tool_use_id = (if (.tool_use_id | type) == "string" then .tool_use_id else null end)
          | .agent_id = (if (.agent_id | type) == "string" then .agent_id else null end) ] as $bound
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
      # `.node_id == $id` candidate filter — see this file's SPAWN PRESENCE
      # header for why wave_id is deliberately omitted (the entry's wave_id is
      # attacker-writable post-bind; the row's node_id is not) and why
      # dispatch_status is filtered on the qualifying-entry check below rather
      # than in this all-entries scan (bind refuses teammate_spawned only on
      # its done branch, so filtering here would deadlock a legitimate
      # mailbox-dispatched retry carry-forward or skipped node).
      #
      # `. as $e` first: inside the inner select the input is a spawn row, so
      # a bare `.tool_use_id` there would read the ROW's id, not the entry's.
      | ([ $bound[] | . as $e | select($e.tool_use_id != null)
           | select([ $spawn_rows[]
                      | select(.tool_use_id == $e.tool_use_id
                               and .node_id == $e.node_id) ] | length == 0) ]) as $missing_spawn
      | if $dup_tool or $dup_agent
        then error("graph_evidence: revalidation found a tool_use_id or agent_id bound to more than one node")
        elif ($missing_spawn | length) > 0
        then error("graph_evidence: revalidation found no Agent spawn in the transcript for tool_use_id \($missing_spawn[0].tool_use_id) bound to node \($missing_spawn[0].node_id)")
        else
          reduce $done_with_evidence[] as $id (null;
            if . != null then . else
              # A qualifying entry must clear FOUR things, all read at the top
              # level: a minted agent_id, a still-present session-matched spawn
              # for its tool_use_id that the transcript says belongs to THIS
              # node, that spawn not being a mailbox/teammate dispatch, and a
              # still-valid completed notification agreeing with that agent_id.
              #
              # Each clause closes a different forged shape: the spawn clause
              # refuses a buried/nested tool_use_id (arraywrap, nested,
              # jsonstring — those bury their ids, so nothing is read at the
              # top level to match a spawn against); the agent_id clause
              # refuses a shape presenting a real top-level tool_use_id but
              # never minting an agent_id (trailspace, homoglyph, spawnref).
              #
              # The dispatch_status clause mirrors graph_evidence_bind.sh line
              # 342, which refuses to bind a DONE node against a
              # teammate_spawned spawn: a mailbox dispatch reports completion
              # as a <teammate-message> carrying no harness discriminator, so
              # it can never prove completion the way an async_launched spawn
              # does. Made here rather than in the presence scan above because
              # bind makes it only on its done branch too.
              #
              # node_id is deliberately NOT re-matched here: $missing_spawn is
              # raised BEFORE this reduce, so any entry reaching this point
              # already proved a same-node spawn row exists for its id. Adding
              # it back could only discriminate if two rows sharing one
              # tool_use_id carried different dispatch_status values, which
              # graph_evidence.sh makes impossible ($status_by_tool is a
              # from_entries map keyed on tool_use_id alone) — dead weight no
              # test could pin.
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
                # here too; blaming notification evidence would misname the
                # cause, since nothing structured was ever bound. Worded
                # shape-neutrally on purpose: both a legacy free-text string
                # and an array-wrapped forgery land here, and calling an array
                # "free text" would be the same misattribution this branch
                # exists to avoid. See the WIDENING note in this file's header.
                elif ([ $bound[] | select(.node_id == $id and .is_object) ] | length) == 0
                then error("graph_evidence: revalidation found no structured bound entry on node \($id); its evidence is a string or array, not the bound object shape")
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

    # Nothing bound to revalidate — a legacy/no-transcript graph completes
    # exactly as it always could. The selector here MUST match the uniqueness
    # scan below (done-or-skipped) or a graph whose only claude_agent evidence
    # sits on a skipped node would short-circuit here and never reach it.
    #
    # `looks_provenance` (bind's own detector, reused verbatim) replaces what
    # used to be an exact `select(type == "object" and .kind == "claude_agent")`
    # match. The exact match was the bug: it is a whitelist of ONE shape, so any
    # forged variant simply fell out of it and the node read as "nothing bound"
    # — the tamper's own goal. The normalising detector walks each entry
    # recursively and scans string leaves, so wrapping/nesting/whitespace/
    # homoglyph/stringified-JSON variants all still select, and therefore all
    # still have to prove themselves below.
    local probe_rc
    jq -e "$GRAPH_EVIDENCE_BIND_JQ_DEFS
$GRAPH_EVIDENCE_REVALIDATE_JQ_PROBE" "$progress" >/dev/null 2>&1
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

    # Re-derive SPAWN presence from the same resolved transcript. rc>4 is a
    # genuine parse abort and fails closed; rc=4 ("this transcript parsed clean
    # and simply has zero Agent spawns") is a legitimate empty result, the same
    # `-gt 4` discrimination _graph_evidence_resolve_context applies to its own
    # spawns walk. An empty set is NOT a pass here — it means every bound entry
    # asserting a tool_use_id below will fail to find its spawn, which is
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
