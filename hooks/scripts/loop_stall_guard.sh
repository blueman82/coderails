#!/bin/bash
# shellcheck disable=SC1091,SC2016 # Runtime-resolved library and literal jq programs are intentional.
# Stop hook — anti-stall. When an agentic loop is active and incomplete, block
# (exit 2) unless the stopping turn carries a valid LOOP-STOP declaration:
#   LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>
# Checks PRESENCE + a vocab CATEGORY only (honest boundary, same as check_verify_loop):
# it forces a categorised declaration, it cannot force the reason to be truthful.
#
# Shared loop-detection lives in lib/loop_state_common.sh (also used by
# loop_state_guard.sh, the presence/ownership guard, and voice_announce.sh, the
# lifecycle-announcement hook); the active-window decision is identical across
# guards, and the stable-text extraction (als_stable_last_text) is shared with
# voice_announce.sh specifically.
#
# Gates run top to bottom; the first that matches decides.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — loop complete, not re-armed, session-owned          → allow (loop done)
#   skip  — last message carries a valid LOOP-STOP declaration  → allow (declared)
#   BLOCK — active + incomplete + no valid declaration

. "$(dirname "$0")/lib/loop_state_common.sh"

TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"

IFS= read -r -d '' -t 5 input || true
# If jq is absent, this extraction silently yields empty, transcript stays "",
# and als_gate_no_transcript below allows the stop — fail-open is relied on here,
# not just an accident of the missing-transcript path.
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)

# Best-effort jq read-modify-write of progress.json's loop_stop_counts.<category>.
# Sole writer of this field (hook-owned; the orchestrator must never write it).
# Never fails the stop: any missing file, malformed JSON, or mv failure is logged
# and swallowed — declaring the stop matters more than the counter write succeeding.
bump_loop_stop_count() {
    local category="$1"
    command -v jq >/dev/null 2>&1 || return 0
    [ -n "$ALS_PATH" ] && [ -f "$ALS_PATH" ] || return 0
    if als_atomic_progress_update "$ALS_PATH" \
        --arg cat "$category" \
        '.loop_stop_counts[$cat] = ((.loop_stop_counts[$cat] // 0) + 1)'; then
        :
    else
        als_log "hook=loop_stall_guard session=$session_id counter_write=jq_failed category=$category"
    fi
}

gate_graph_complete() {
    local category="$1"
    als_is_complete_category "$category" || return 0
    command -v jq >/dev/null 2>&1 || return 0
    [ -n "$ALS_PATH" ] && [ -f "$ALS_PATH" ] || return 0
    jq -e '(.graph | type) == "object"' "$ALS_PATH" >/dev/null 2>&1 || return 0
    local loop revision
    loop=$(jq -r '.loop_id // ""' "$ALS_PATH" 2>/dev/null)
    revision=$(jq -r '.revision // ""' "$ALS_PATH" 2>/dev/null)
    if ! jq -e '(.loop_id | type) == "string" and (.loop_id | length) > 0 and
      (.revision | type) == "number" and (.revision | floor) == .revision' \
        "$ALS_PATH" >/dev/null 2>&1; then
        echo "[loop-stall-guard] LOOP-STOP: complete refused: graph identity is missing or malformed." >&2
        exit 2
    fi
    if ! jq -e '
      (.graph | type) == "object" and .graph.active_wave == null and .graph.hard_stop == null
      and ([.graph.nodes[] | select(.status | IN("done","skipped") | not)] | length) == 0
      and ([.graph.joins[] | select(.released != true)] | length) == 0
    ' "$ALS_PATH" >/dev/null 2>&1; then
        echo "[loop-stall-guard] LOOP-STOP: complete refused: the durable graph is unfinished." >&2
        exit 2
    fi
    local loop_dir
    loop_dir=$(dirname "$ALS_PATH")
    als_read_loop_evals_result "$loop_dir"
    if ! jq -e --arg session "$session_id" --arg loop "$loop" --arg revision "$revision" '
      .session_id == $session and .loop_id == $loop and ((.revision | tostring) == $revision)
    ' "$loop_dir/evals.json" >/dev/null 2>&1; then
        ALS_LOOP_EVALS_RESULT="STALE"
    fi
    # Completion demands a real graded verdict. FROZEN is a DISPATCH-time
    # state (loop_dispatch_guard) and falls into the fail-closed default
    # below by construction — spelled out in the message because "evals are
    # FROZEN" otherwise reads like a pass to someone seeing it at a stop.
    case "$ALS_LOOP_EVALS_RESULT" in GO | VERIFICATION_LEVEL0) ;; *)
        echo "[loop-stall-guard] LOOP-STOP: complete refused: loop evals are $ALS_LOOP_EVALS_RESULT." >&2
        if [ "$ALS_LOOP_EVALS_RESULT" = "FROZEN" ]; then
            echo "[loop-stall-guard] FROZEN means the suite was frozen pre-build and never graded — it authorised dispatch, not completion. Run the evals, record evidence per P0, then: post_evals.sh grade-loop <loop_dir>/evals.json" >&2
        fi
        exit 2
        ;;
    esac
    # Absence is already fully adjudicated by als_gate_proofs_on_complete
    # (called just before this function, in gate_loop_stop_declared): it
    # exits 2 on every illegitimate absence and allows the two legitimate
    # ones (grandfathered schema_version, or a valid proof_disposition).
    # Re-requiring proof.json to exist here would make that escape hatch
    # unreachable for any loop using .graph. Only check identity when the
    # file is actually present — the one thing the sibling gate does not
    # verify (it never compares proof.json's session_id/loop_id against the
    # current loop).
    if [ -f "$loop_dir/proof.json" ]; then
        jq -e --arg session "$session_id" --arg loop "$loop" '
      .session_id == $session and .loop_id == $loop
    ' "$loop_dir/proof.json" >/dev/null 2>&1 || {
            echo "[loop-stall-guard] LOOP-STOP: complete refused: proof.json belongs to another loop." >&2
            exit 2
        }
    fi
    jq -e --arg session "$session_id" --arg loop "$loop" '
    .session_id == $session and .loop_id == $loop
  ' "$loop_dir/retro.json" >/dev/null 2>&1 || {
        echo "[loop-stall-guard] LOOP-STOP: complete refused: retro.json belongs to another loop." >&2
        exit 2
    }
}

gate_loop_stop_declared() {
    # Stable extract rides out the transcript-flush race (shared with voice_announce.sh).
    text=$(als_stable_last_text "$transcript" "$TAIL_LINES" "$MAX_ATTEMPTS" "$SLEEP_S")
    # The regex is built from the single-source vocab; the category must be followed
    # by a non-alphanumeric char or end-of-line so "completed" does not match "complete".
    if printf '%s\n' "$text" | grep -qiE "^[[:space:]]*LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})([^[:alnum:]]|$)"; then
        # If the message carries more than one LOOP-STOP line, `tail -1` counts the
        # LAST one. This is intentional, not incidental: SKILL.md defines the
        # declaration as the turn's ENDING line ("End the stopping turn with:"), so
        # only the final declaration reflects the turn's actual outcome.
        category=$(printf '%s\n' "$text" | grep -oiE "LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})" | grep -oiE "(${LOOP_STOP_VOCAB})\$" | tail -1)
        als_gate_retro_on_complete "$category" "loop_stall_guard" "$session_id"
        als_gate_work_units_on_complete "$category" "loop_stall_guard" "$session_id"
        als_gate_proofs_on_complete "$category" "loop_stall_guard" "$session_id" "$transcript"
        gate_graph_complete "$category"
        als_report_cost_on_complete "$category" "loop_stall_guard" "$session_id"
        # SINGLE-JSON-DOCUMENT emission: als_gate_proofs_on_complete (withdrawn
        # proofs) and als_report_cost_on_complete (cost) both append to the
        # shared $ALS_PENDING_SYSMSG accumulator (see its definition in
        # loop_state_common.sh) instead of each emitting their own top-level
        # {systemMessage:...} JSON — two concatenated JSON objects on one hook's
        # stdout is not valid as a single document under a whole-buffer JSON
        # parse. This is the ONE place either message reaches the human: emitted
        # ONLY here, ONLY once, AFTER both gates above have had their chance to
        # append.
        [ -n "$ALS_PENDING_SYSMSG" ] && jq -n --arg m "$ALS_PENDING_SYSMSG" '{systemMessage: $m}' 2>/dev/null
        bump_loop_stop_count "$category"
        als_log "hook=loop_stall_guard session=$session_id invocations=$ALS_INVOCATIONS declared=1 blocked=0"
        exit 0
    fi
}

block_missing_declaration() {
    als_log "hook=loop_stall_guard session=$session_id invocations=$ALS_INVOCATIONS declared=0 blocked=1"
    echo "[loop-stall-guard] Active agentic loop, no LOOP-STOP declaration in your last message.
Continue the loop, OR declare your stop by ending your message with a line:
  LOOP-STOP: <${LOOP_STOP_VOCAB}> — <reason>
Declaring \`complete\` means the loop is done: also set progress.json status to
\"complete\" and run the Phase 13 self-audit." >&2
    exit 2
}

als_gate_no_transcript "$transcript"
als_gate_stop_loop "$stop_hook_active"
als_gate_require_active_loop "$transcript" "loop_stall_guard" "$session_id"
als_load_progress "$cwd" "$session_id"
als_gate_unstubbed_grace "loop_stall_guard" "$session_id"
gate_loop_stop_declared
als_gate_loop_complete "loop_stall_guard" "$session_id"
block_missing_declaration
