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
# legacy-style — a plain string, no transcript ever resolved at bind time, or
# the transcript no longer resolves at all) has nothing this function can or
# must re-verify, and completes exactly as it always could: revalidation is
# additive on top of a real bind, never a new requirement for a graph that
# was never asked to bind. A node the transcript names as genuinely
# dispatched must still have surviving bound evidence if EITHER of two
# independent anchors proves the wave that dispatched it genuinely bound
# something — see EVIDENCE PRESENCE below for why each anchor is load-bearing:
#   * a SIBLING node dispatched in THE SAME WAVE has surviving evidence, or
#   * .graph.wave_history (written durably at wave-open time by
#     graph_dispatch_begin_wave, and NOT cleared by completion the way
#     .graph.active_wave is) recorded that wave's own cursor and node set.
# A wave with a wave_history entry is now caught even when every one of its
# nodes' evidence was wiped outright and no sibling survives anywhere — the
# gap this file used to disclose here. What remains a genuinely
# indistinguishable, disclosed limit is narrower now: a wave that legitimately
# never recorded a wave_history entry (a pre-fix loop, or a genuinely
# cursorless wave) AND has no surviving sibling either — that shape is still
# information-theoretically identical to "never dispatched" from what
# progress.json and the transcript can prove at completion time. See this
# file's own EVIDENCE PRESENCE notes and the PR description for the
# begun-then-abandoned-wave flip-condition this still does not close.
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
#   * EVIDENCE PRESENCE, the exact complement of spawn presence above, but
#     narrower than "every node any spawn row names" — that wider form was
#     shipped, then refused in review as a critical regression: bind itself
#     leaves a node legitimately UNBOUND whenever its wave never resolved a
#     transcript_cursor (a cursorless wave forces bind's own $matches empty;
#     see graph_evidence_bind.sh), and the wider form demanded evidence bind
#     never demanded in the first place.
#
#     Narrowed to: a done/skipped node named by a spawn row whose OWN
#     wave_id is a $bound_waves member — a wave PROVEN (by a still-surviving
#     $bound entry citing one of that wave's own spawn's tool_use_ids) to
#     have actually bound something — but with zero surviving $bound entries
#     of its own. A sibling node's surviving evidence is what proves the wave
#     was real and cursor-respecting; this node's absence from $bound is then
#     unexplainable except by deletion after a genuine bind. A cursorless (or
#     otherwise legitimately-never-bound) wave's wave_id never enters
#     $bound_waves, so its nodes are never demanded — closing the regression
#     at the root rather than special-casing it.
#
#     Deleting a node's evidence array OUTRIGHT (not disguising it — removing
#     it) previously fell out of every check above, including the leading
#     probe. The SIBLING-ANCHORED branch of this clause needs a SURVIVING
#     SIBLING ENTRY IN THE SAME WAVE — $bound_waves is keyed per wave_id, not
#     per graph. If a wave has no surviving bound entry of its own (every node
#     dispatched in that specific wave had its evidence deleted, whether that
#     wave held one node or several), the sibling-anchored branch alone can no
#     longer tell that wave apart from a genuinely cursorless one.
#
#     That used to be the end of the story: a wave whose OTHER node's evidence
#     survives was caught (the two-node-same-wave test below pins this), but a
#     wave with EVERY node's evidence wiped, or a lone-node wave, was not — a
#     cross-wave sibling deletion and a node retried across two waves whose
#     every attempt's evidence was deleted were both accepted, disclosed
#     limits.
#
#     Both of those are now closed by a SECOND, independent anchor:
#     .graph.wave_history (written durably by graph_dispatch_begin_wave the
#     moment a cursored wave opens — see that function's own header) survives
#     graph_executor_apply_wave's `.graph.active_wave = null` at completion,
#     so it does not need any sibling evidence to still exist. $dispatched
#     below is the union of the SIBLING-anchored set this comment describes
#     and the wave_history-anchored set (see the WAVE-HISTORY WIDENING comment
#     at $dispatched's own derivation) — either anchor alone is now sufficient
#     to prove a wave genuinely bound something and demand each of its
#     dispatched nodes still carry evidence.
#
#     $bound_waves and the sibling-anchored half of $dispatched are derived
#     from $spawn_rows' own .wave_id/.node_id fields — transcript-sourced,
#     never read from progress.json — so the party editing evidence cannot
#     also spoof which wave/node "dispatched." The wave_history-anchored half
#     reads .graph.wave_history, which lives in progress.json itself and is
#     therefore orchestrator-editable — see that derivation's own comment for
#     the two-coordinated-edits framing this implies. The probe no longer
#     makes the "nothing to revalidate" decision by itself on the
#     unresolvable-transcript path (see the bash driver below) — it only
#     decides whether that path can still be treated as the legacy/
#     no-transcript case.
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
#     no provenance-ish text is unaffected: it never selects, and — provided
#     the transcript also has no real dispatch for that node — its graph
#     still completes via the legacy path.
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
      # The per-node presence/uniqueness/terminal-result checks above all pass
      # once a "done" node has ANY one qualifying entry — they never verify
      # that the SURVIVING bound entries are the exact attempt sequence bind
      # produced. Deleting an earlier FAILED attempt's entry while keeping the
      # later successful one satisfies every check above yet erases real
      # retry history; this closes that gap by demanding the bound attempt
      # numbers equal the exact contiguous run 1..expected_count, where
      # expected_count is retry.attempts + 1 (bind mints each entry's
      # .attempt as retry.attempts-at-bind-time + 1, and a successful "done"
      # never increments .attempts further — see graph_dispatch_record, the
      # only place .attempts is incremented, and only on a "failed" report).
      #
      # Deliberately "done" nodes ONLY, not "skipped" too, unlike Python's
      # unconditional +1: a node marked "skipped" after a "failed" report
      # already has retry.attempts incremented to account for that failed
      # attempt, so its own bound entry attempt numbers are already exactly
      # 1..retry.attempts with no "+1" — a skipped node legitimately never
      # earns the extra successful-completion attempt a done node does. The
      # existing "a skipped node carrying bound evidence still completes"
      # case (one failed attempt, retry.attempts=1, one bound entry with
      # attempt=1) pins this: applying the done formula there would demand
      # attempts [1,2] against an actual [1] and false-reject a legitimate,
      # already-tested graph.
      #
      # Only counts entries selected below via `.is_object` (a structured
      # bound object — a legacy free-text string or array-wrapped forgery has
      # no top-level .attempt and normalises to null). A node with zero
      # structured entries at all is left to the existing, more specific
      # "no structured bound entry" branch further down rather than being
      # preempted here with a less precise reason.
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
      # EVIDENCE-PRESENCE re-derivation — the exact complement of the spawn-
      # presence check above, but DELIBERATELY NARROWER than "every node any
      # spawn row names" (an earlier version of this clause used exactly that
      # wider set and was refused as a critical regression in review: it
      # demanded evidence for cursorless-wave nodes bind ITSELF never demands
      # evidence for — see graph_evidence_bind.sh's own comment on
      # `$matches is forced empty` for a cursorless wave. A node bind
      # legitimately left unbound must still complete unbound; this clause
      # must refuse ONLY a node whose evidence bind actually wrote and a
      # later hand-edit then deleted).
      #
      # $bound_waves is the set of wave_ids PROVEN to have bound something:
      # a spawn row's tool_use_id appearing in $bound_tools (an id some
      # surviving evidence entry still cites) is transcript-evidence that
      # THIS wave actually produced a binding. Reading wave_id off the SPAWN
      # ROW, never off the evidence entry's own (attacker-writable, see the
      # SPAWN PRESENCE comment above) copy, keeps this untamperable the same
      # way the rest of this file is.
      #
      # A done/skipped node named by a spawn row whose wave_id is in
      # $bound_waves, but with zero surviving $bound entries of its own, had
      # its evidence deleted from a wave that DID bind — not a cursorless or
      # otherwise legitimately-unbound wave. That is the tamper this clause
      # exists to catch: a sibling node's bound evidence proves the wave was
      # a real, cursor-respecting, binding wave, and this node's absence from
      # $bound is then unexplainable except by deletion.
      #
      # $bound_waves/$dispatched_by_sibling above reconstruct node_id and
      # wave_id but not the cursor bind's own candidate filter also requires
      # (`.line > $cursor` — a spawn recorded before the wave's own cursor is
      # not bindable), so a pre-cursor spawn row sitting in an otherwise-bound
      # wave_id is still counted as sibling-"dispatched". That gap is now
      # closed on the wave_history-anchored path below ($dispatched_by_history
      # applies its own `$r.line > $wh[$r.wave_id].cursor` clause), because
      # the cursor IS now durably retained per-wave — via
      # .graph.wave_history, written at wave-open time and surviving
      # completion's `.graph.active_wave = null` — where it used to be lost
      # the moment a wave completed. Still orchestrator-editable (it lives in
      # the same progress.json as everything else this file re-derives), so a
      # deliberate tamperer can still forge it — see this file's PR
      # description for the "two coordinated edits, not zero" framing that
      # applies here too. The sibling-anchored path's own reconstruction stays
      # as-is; the union with the history-anchored path is what closes this
      # specific gap, not a change to this derivation itself.
      | ([ $bound[] | .tool_use_id | select(. != null) ] | unique) as $bound_tools
      | ([ $spawn_rows[] | select(.tool_use_id as $t | $bound_tools | index($t))
           | .wave_id | select(type == "string") ] | unique) as $bound_waves
      | ([ $spawn_rows[] | select(.wave_id as $w | $bound_waves | index($w))
           | .node_id | select(type == "string") ] | unique) as $dispatched_by_sibling
      # WAVE-HISTORY WIDENING, additive on top of $dispatched_by_sibling above,
      # never a narrowing of it: graph_dispatch_begin_wave now durably records
      # each cursored wave's own {cursor, nodes} into .graph.wave_history at
      # the moment it opens (see that function's own header) — a signal that
      # survives graph_executor_apply_wave's `.graph.active_wave = null` at
      # completion, unlike the cursor $dispatched_by_sibling above relies on a
      # SURVIVING SIBLING to reconstruct. A wave_history entry proves a wave
      # was genuinely opened with these exact nodes and this exact cursor
      # WITHOUT needing any of its own evidence to still survive, closing the
      # residual the pre-fix comment (still above, corrected) described.
      #
      # All three clauses below are independently required — each closes a
      # distinct false-positive/false-negative case measured during design
      # review (see the header note this widening replaces):
      #   * $wh[$r.wave_id] != null — only waves that actually recorded a
      #     cursor participate; a cursorless wave has no wave_history entry at
      #     all (the write side omits the key, never writes null), so its
      #     nodes stay exempt exactly as $dispatched_by_sibling already
      #     exempts them.
      #   * $r.line > $wh[$r.wave_id].cursor — a spawn row whose OWN wave_id
      #     was forward-forged into a dispatch prompt before that wave's
      #     cursor was actually recorded (the orchestrator can write
      #     wave_id:"wave-4" into a prompt before wave-4 exists) is rejected;
      #     mirrors bind's own `.line > $cursor` candidate filter.
      #   * $wh[$r.wave_id].nodes | index($r.node_id) — a stray or replayed
      #     dispatch envelope naming a node/wave pair that was never actually
      #     part of the recorded wave's own node set is rejected. Without
      #     this, a re-dispatch or a copied prompt could drag an uninvolved id
      #     into the demanded set and false-refuse an honest graph — this was
      #     a real bug in an earlier, simpler version of this design that used
      #     only {cursor:N} with no node list.
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
                # A node whose otherwise-qualifying entry was excluded ONLY by
                # the dispatch_status clause reaches the terminal else too, and
                # the notification is not the cause there: it exists and it
                # reports completed. Named separately for the same reason the
                # unstructured-entry branch above is — the terminal else is a
                # catch-all, and letting a mailbox dispatch fall into it sends
                # the operator hunting a notification that is present and fine.
                #
                # The inner select is the exact complement of the qualifying
                # clause above (`!=` becomes `==`), so this branch names the
                # cause only when that clause is what rejected the entry.
                # node_id is not re-matched, for the same reason it is not
                # matched there: $missing_spawn already proved a same-node row
                # exists for this id, and $status_by_tool in graph_evidence.sh
                # is keyed on tool_use_id alone, so two rows sharing an id
                # cannot disagree on dispatch_status.
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
    # This probe alone can no longer decide "nothing to revalidate" (see
    # $evidence_gone in JQ_MAIN below for why: a graph can have real dispatch
    # history for a node whose evidence was since deleted outright, which
    # this probe cannot distinguish from a node that was never dispatched at
    # all). It is kept only to answer a narrower question: whether a session
    # whose transcript no longer resolves can still be treated as the
    # legitimate legacy/no-transcript case, or must fail closed — see the
    # transcript-resolution check below, the only place this flag is read.
    #
    # `looks_provenance` (bind's own detector, reused verbatim) replaces what
    # used to be an exact `select(type == "object" and .kind == "claude_agent")`
    # match. The exact match was the bug: it is a whitelist of ONE shape, so any
    # forged variant simply fell out of it and the node read as "nothing bound"
    # — the tamper's own goal. The normalising detector walks each entry
    # recursively and scans string leaves, so wrapping/nesting/whitespace/
    # homoglyph/stringified-JSON variants all still select, and therefore all
    # still have to prove themselves below.
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
        # A transcript that no longer resolves at all cannot re-derive spawn
        # presence for $evidence_gone below either, so a graph with nothing
        # currently bound stays on the legacy/no-transcript completion path
        # exactly as before. A graph that DOES have something bound but whose
        # transcript is now unresolvable must fail closed — that case was
        # already refused before this change (the "transcript mutated after
        # bind" test below pins it) and stays refused here.
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
