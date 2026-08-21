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
# Resolve this session's transcript by globbing
# <projects_dir>/*/<session_id>.jsonl. Prints the path; returns 1 when none
# resolves.
#
# The party this gate constrains is the orchestrator's own self-report, and
# that party has arbitrary Bash — so the transcript location must NOT be
# something it can redirect. CLAUDE_PROJECTS_DIR is honoured (it is the
# established repo idiom, used by loop_cost.sh and loop_state_common.sh) only
# while it stays UNDER $HOME/.claude/projects, which is the one place the
# orchestrator cannot author records into without actually making the tool
# call. Pointing it at a hand-authored transcript elsewhere otherwise lets
# fabricated spawns "derive" fake truth and bind.
#
# Tests legitimately need a transcript outside $HOME, so an explicit,
# obviously-named opt-out exists. It is deliberately NOT the same variable:
# an env var a test sets on purpose cannot be reached by accident, and the
# name says what it is.
GRAPH_EVIDENCE_TEST_ESCAPE="GRAPH_EVIDENCE_ALLOW_UNPINNED_TRANSCRIPT"
graph_evidence_transcript() {
    local session="$1" projects_dir default_dir f
    [ -n "$session" ] || return 1
    case "$session" in
    */* | ..*) return 1 ;; # never let a session id escape the projects dir
    esac
    default_dir="$HOME/.claude/projects"
    projects_dir="${CLAUDE_PROJECTS_DIR:-$default_dir}"
    if [ "${!GRAPH_EVIDENCE_TEST_ESCAPE:-}" != "1" ]; then
        case "$projects_dir" in
        "$default_dir" | "$default_dir"/*) ;;
        *) return 1 ;; # redirected outside $HOME: refuse to read it at all
        esac
    fi
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
# The wave's lower bound: the number of RECORDS already in the transcript at
# begin-wave. Any Agent spawn bindable to that wave must appear STRICTLY AFTER
# this record, so a spawn from an earlier wave cannot be replayed into it.
#
# Counts records exactly as graph_evidence_spawns numbers them — non-empty
# lines — rather than newlines. `wc -l` counts newlines, so a final line
# written without a trailing newline (a transcript caught mid-append) would go
# uncounted here while still being numbered by the splitter, leaving a spawn on
# that line looking one position past the cursor. That is precisely the replay
# the cursor exists to prevent.
graph_evidence_cursor() {
    local transcript="$1"
    [ -f "$transcript" ] || return 1
    grep -c '[^[:space:]]' "$transcript" 2>/dev/null || true
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

    # transcript_clean drives the difference between "this node genuinely has
    # no spawn to bind" and "we could not look". Only a transcript that
    # RESOLVED and PARSED lets the gate demand a binding; anything else leaves
    # the legacy posture, where an uncited node passes through.
    local transcript_clean=false raw_spawns rc
    if transcript=$(graph_evidence_transcript "$session"); then
        # Capture the walk's own exit status. A pipeline reports only its last
        # command, and `jq -e --slurp` turns empty input into [] with rc 0, so
        # piping straight into it would discard the walk's rc=5 abort on a
        # malformed record — the very failure this must fail closed on.
        raw_spawns=$(graph_evidence_spawns "$transcript" "$session")
        rc=$?
        if [ "$rc" -ne 0 ]; then
            return 1 # malformed/unreadable transcript: fail closed, always
        fi
        spawns_json=$(printf '%s' "$raw_spawns" | jq -c --slurp '.' 2>/dev/null) || return 1
        [ -n "$spawns_json" ] || return 1
        transcript_clean=true
    else
        [ "$cited_count" -eq 0 ] || return 1 # a claim with nothing to check it against
        # A cursor in active_wave means begin-wave DID resolve this transcript.
        # If it is unreadable now — deleted, or CLAUDE_PROJECTS_DIR redirected
        # away from $HOME between begin-wave and record — the wave cannot be
        # verified and must not be recorded on trust.
        if jq -e '(.graph.active_wave.transcript_cursor // null) != null' \
            "$progress" >/dev/null 2>&1; then
            return 1
        fi
        spawns_json='[]'
    fi

    jq -e -c --argjson spawns "$spawns_json" --argjson wave "$wave_json" \
        --argjson transcript_clean "$transcript_clean" '
      # Normalising detectors, applied to ONE caller-supplied evidence entry.
      # Both walk the entry recursively (..) so nesting and array-wrapping
      # cannot hide provenance, and fold case/punctuation so a trailing space
      # or a homoglyph-ish variant still trips. String leaves are scanned too,
      # so the bound shape serialised as a JSON string is caught.
      def norm_ids:
        [ .. | objects | (.spawn_ref?, .tool_use_id?) | select(type == "string") ];
      def looks_provenance:
        ([ .. | objects | (.kind?, .spawn_ref?, .tool_use_id?)
           | select(type == "string") ]
         | any(ascii_downcase | gsub("[^a-z_]"; "") | test("claude_agent|toolu")))
        or ([ .. | strings ]
            | any(test("toolu_|\"kind\"\\s*:\\s*\"claude_agent")));
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
              | ([ if $cursor_raw == null then empty else $spawns[] end
                   | select(.node_id == $id and .wave_id == $wave_id and .line > $cursor) ]) as $matches
              | if ($matches | length) > 1
                then error("graph_evidence: node \($id) matches multiple spawns in \($wave_id)")
                elif ($matches | length) == 0
                then
                  if ($claims | length) > 0
                  then error("graph_evidence: node \($id) cites an unbindable spawn \($claims[0])")
                  # Citing nothing must not be a way out. When the gate can see
                  # the truth, a non-join node with no spawn in this wave was
                  # never dispatched, whatever it reports about itself.
                  elif ($binding_required and ($joins | has($id) | not))
                  then error("graph_evidence: node \($id) has no spawn in \($wave_id); nothing to bind")
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
