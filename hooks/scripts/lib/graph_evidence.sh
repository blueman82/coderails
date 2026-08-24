#!/bin/bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
# graph_evidence.sh — transcript-reading primitives for Claude graph node
# evidence: resolve the session transcript, and walk it for raw Agent spawns,
# <task-notification> blocks, and the wave cursor. Each of these is one jq
# pass that extracts AND shape-filters in a single walk (never a separate
# later validation stage) — that is what keeps them primitives rather than
# decisions, even though graph_evidence_notifications' shape filter is itself
# a security-relevant one (see its own header). The binding/validation
# DECISION logic built on top of these primitives (graph_evidence_bind_wave
# in graph_evidence_bind.sh, graph_evidence_revalidate_all in
# graph_evidence_revalidate.sh) sources this file. Split for the repo's own
# file-size convention — this is a straight line-for-line cut, not a
# redesign; the three files together are still one logical unit.
#
# SOURCED by graph_dispatch.sh (via graph_evidence_bind.sh and
# graph_evidence_revalidate.sh), not executed directly.
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
# The pin is UNCONDITIONAL — there is no env opt-out. An escape hatch the
# constrained party can set is not a barrier, it is a second door: whoever can
# export CLAUDE_PROJECTS_DIR can export the escape just as easily. Tests get
# isolation by redirecting HOME itself, which moves the pin with them.
graph_evidence_transcript() {
    local session="$1" projects_dir default_dir f
    [ -n "$session" ] || return 1
    case "$session" in
    */* | ..*) return 1 ;; # never let a session id escape the projects dir
    esac
    default_dir="$HOME/.claude/projects"
    projects_dir="${CLAUDE_PROJECTS_DIR:-$default_dir}"
    case "$projects_dir" in
    "$default_dir" | "$default_dir"/*) ;;
    *) return 1 ;; # redirected outside $HOME: refuse to read it at all
    esac
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
#   {line, node_id, wave_id, tool_use_id, record_uuid, subagent_type,
#    session_mismatch, dispatch_status}
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
#
# An envelope whose OWN `session_id` field disagrees with the transcript's
# `session_id` (a forged/replayed envelope from another session) is NOT
# dropped silently here — it is emitted with session_mismatch:true so
# graph_evidence_bind_wave can refuse it with a NAMED session reason instead
# of the node falling through to the generic "nothing to bind" path.
#
# dispatch_status is the matching tool_result's `.toolUseResult.status`
# (verified live shape: a `type:"user"` record whose `.message.content[0]`
# carries `{tool_use_id, type:"tool_result"}`), joined in by tool_use_id.
# A mailbox/teammate dispatch (SendMessage/`Agent(name: ...)`) sets this to
# `teammate_spawned`, never `async_launched`. Its completion arrives later as
# a `<teammate-message teammate_id="...">` block, not a `<task-notification>`
# — and unlike task-notification's harness-stamped `origin.kind`, a
# teammate-message carries no discriminator at all (origin is null on every
# real one checked: 1451/1451 across the full local transcript corpus), so it
# cannot be correlated back to a spawn without trusting the orchestrator's own
# self-chosen name. graph_evidence_bind_wave refuses to bind a "done" node on
# a teammate_spawned spawn for exactly that reason, rather than accepting it
# as evidence at reduced strength.
graph_evidence_spawns() {
    local transcript="$1" session="$2"
    [ -f "$transcript" ] || return 1
    jq -e -c --slurp --raw-input --arg session "$session" --arg key "$GRAPH_EVIDENCE_ENVELOPE_KEY" '
      split("\n")
      | map(select(length > 0))
      | map(fromjson) as $recs         # aborts the whole program on bad JSON
      | ($recs
         | map(select(.type == "user" and (.isSidechain // false) != true
                      and (.sessionId // $session) == $session
                      and (.toolUseResult.status? // null) != null
                      and (.message.content[0].tool_use_id? // null) != null))
         | map({key: .message.content[0].tool_use_id, value: .toolUseResult.status})
         | from_entries) as $status_by_tool
      | ($recs | to_entries
      | map(
          (.key + 1) as $line
          | .value as $rec
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
          | {line: $line,
             node_id: ($env.node_id // null),
             wave_id: ($env.wave_id // null),
             tool_use_id: ($tu.id // null),
             record_uuid: $uuid,
             subagent_type: ($tu.input.subagent_type // null),
             session_mismatch: (($env.session_id // $session) != $session),
             dispatch_status: ($status_by_tool[$tu.id // ""] // null)}
          | select(.node_id != null and .wave_id != null
                   and (.tool_use_id | type == "string") and (.tool_use_id | length) > 0)
        ))
      | flatten
      | .[]
    ' "$transcript" 2>/dev/null
}

# graph_evidence_notifications <transcript> <session_id>
# Emit one compact JSON object per <task-notification> block found in the
# PARENT session's own transcript — never a child's own async output file,
# which is orchestrator-writable and therefore forgeable:
#   {tool_use_id, task_id, status, result}
#
# The real live shape (verified against actual ~/.claude/projects/*/*.jsonl
# transcripts) puts the notification text in one of two places, and ONLY
# these two record shapes are trusted as a genuine harness-written
# notification:
#   * `type:"queue-operation"` — a raw string on `.content`. Confirmed live:
#     this record type carries no `origin` field at all (checked ~1000 real
#     records), and it is written only by the harness's own queue delivery —
#     never reachable from a tool call's return value.
#   * `type:"user"` with `origin.kind == "task-notification"` — a raw string
#     on `.message.content`. `origin` is a harness-stamped field the
#     orchestrator's own Bash cannot set when appending to its own transcript.
#
# Any OTHER record with a string content field (confirmed live: ~2000
# type:"user" records with no origin at all — Stop-hook feedback, dispatch
# prompts, and other plain text landing on the main thread) is EXCLUDED even
# if its text happens to contain literal <task-notification> markup. Without
# this restriction, a subagent's own output echoing forged notification
# markup could land as ordinary string content on the main thread and be
# mistaken for a real completion record — anchoring to these two shapes is
# what closes that injection vector. Only main-thread records count, same
# isSidechain rule as graph_evidence_spawns, and only records honestly
# belonging to $session.
#
# Fails closed the same way graph_evidence_spawns does: `jq -e` aborts the
# whole program non-zero on the first unparseable transcript line, so a
# corrupt record is never silently read as "no notifications".
graph_evidence_notifications() {
    local transcript="$1" session="$2"
    [ -f "$transcript" ] || return 1
    jq -e -c --slurp --raw-input --arg session "$session" '
      split("\n")
      | map(select(length > 0))
      | map(
          (. | fromjson) as $rec          # aborts the whole program on bad JSON
          | select(($rec.isSidechain // false) != true)
          | select(($rec.sessionId // $session) == $session)
          | (if ($rec.type == "queue-operation" and ($rec.content | type) == "string")
             then $rec.content
             elif ($rec.type == "user" and ($rec.origin.kind // "") == "task-notification"
                   and ($rec.message.content | type) == "string")
             then $rec.message.content
             else null end) as $text
          | select($text != null and ($text | contains("<task-notification>")))
          | [ $text | scan("<task-notification>([\\s\\S]*?)</task-notification>") ] as $blocks
          | $blocks[]
          | .[0] as $block
          | {
              tool_use_id: ($block | capture("<tool-use-id>(?<v>[\\s\\S]*?)</tool-use-id>").v // null),
              task_id: ($block | capture("<task-id>(?<v>[\\s\\S]*?)</task-id>").v // null),
              status: ($block | capture("<status>(?<v>[\\s\\S]*?)</status>").v // null),
              result: ($block | capture("<result>(?<v>[\\s\\S]*?)</result>").v // "")
            }
          | select(.tool_use_id != null)
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
