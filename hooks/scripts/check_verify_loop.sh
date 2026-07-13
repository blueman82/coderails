#!/bin/bash
# Stop hook — blocks (exit 2) in two cases: (1) the response leaves ANY
# "## Did Not Verify" bullet untagged, or (2) the current turn edited >=3
# files and the response has no "## Did Not Verify" header at all. Total
# enforcement: an untagged bullet, or a missing section after enough edits,
# is treated as something the model could have resolved (read the file, run
# the check) and chose to defer or omit.
#
# The ONLY way a DNV bullet passes is an explicit "(unverifiable: <reason>)" tag on
# its leading clause — a deliberate, audited declaration that the item genuinely
# cannot be checked from source (REPL-only action, external system, prod-only
# observation, user intent). The tag is greppable, so overuse is visible on review.
# This forces resolve-or-tag; it cannot force the tag to be honest (tagging a
# checkable item is cheaper than checking it) — the guarantee is "nothing silently
# deferred," and the tag is the auditable seam.
#
# Checks run top to bottom; the first that matches decides.
#   skip  — no transcript to inspect                             → allow stop
#   skip  — already blocked once this turn (loop-guard)          → allow stop
#   skip  — the last response has no text                        → allow stop
#   warn  — no DNV header, turn file_count >= 3, Stop event,
#           active+incomplete agentic loop                        → additionalContext
#           warn, allow stop (SubagentStop never demotes; presence
#           can't fire on SubagentStop anyway — file_count is 0 there)
#   BLOCK — no DNV header AND turn file_count >= 3 (outside the warn
#           case above)                                            → section omitted after edits
#   skip  — no DNV header, turn file_count < 3                    → nothing to enforce
#   skip  — DNV header present, zero bullets (prose-only)         → compliant empty section
#   warn  — DNV header present, untagged bullet, Stop event,
#           active+incomplete agentic loop                        → additionalContext
#           warn, allow stop (SubagentStop never demotes)
#   BLOCK — DNV header present, any untagged bullet (outside the
#           warn case above)                                       → deferred item left open
#   skip  — DNV header present, all bullets tagged                → allow stop
#
# file_count is NOT used as a skip gate on the bullet-policing path (an
# EXISTING section's bullets are always policed regardless of how many files
# were edited this turn — a pure-conversation response can carry deferred
# verifiable claims too). file_count IS used as a gate on the separate
# header-presence check: it decides whether a header must exist at all.
# (file_count was previously session-cumulative; it is now TURN-scoped —
# see dc_file_count in lib/discipline_common.sh — records after the last
# genuine user prompt, so an earlier turn's edits don't nag every later
# pure-conversation stop in the same session.)
#
# 2026-07-13: a file_count>=3 PRESENCE check was added (a different code path
# from bullet-policing) closing the inversion where a response that omitted
# the "## Did Not Verify" section entirely passed silently while an honest
# section with one untagged bullet blocked. It is keyed on the HEADER's
# presence, not on zero bullets — a compliant prose-only section ("nothing
# outstanding") has the header but no bullets and must still pass, the same
# honesty boundary as an all-tagged bullet list. It is wired through the SAME
# als_loop_active_incomplete demotion predicate #155 added for the bullet
# path (same Stop-only, fail-toward-blocking shape) — after #155, a hard
# presence-block in-loop would be the only remaining in-loop hard block,
# inconsistent with the merged demotion arc.

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

. "$(dirname "$0")/lib/discipline_common.sh"
. "$(dirname "$0")/lib/loop_state_common.sh"

log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

IFS= read -r -d '' -t 5 input || true
hook_event=$(echo "$input" | jq -r '.hook_event_name // "Stop"' 2>/dev/null)
session_id=$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
file_count=0
attempts=1

# SubagentStop: the subagent's final text is in last_assistant_message — police it
# directly, without gating on file_count. The message IS the authoritative output;
# an untagged DNV bullet in it is proof of deferred verifiable work regardless of
# whether the subagent transcript is readable.
# (transcript_path on a SubagentStop payload is the PARENT session transcript —
# reading it would check the wrong content and silently miss real violations.)
# NOTE: last_assistant_message is assumed to be a plain string per the SubagentStop
# payload contract. If CC ever delivers a content-block array here, this would need
# a join step.
# NOTE: loop_state_guard and loop_stall_guard are intentionally Stop-only — loop-state
# ownership is a parent-session concept; a subagent has no progress.json to validate.
if [ "$hook_event" = "SubagentStop" ]; then
  text=$(echo "$input" | jq -r '.last_assistant_message // ""' 2>/dev/null)
else
  transcript=$(echo "$input" | jq -r '.transcript_path // empty')

  # Skip if there is no transcript to inspect.
  if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
  fi

  # Count unique Write/Edit/MultiEdit targets for the CURRENT TURN (records
  # after the last genuine user prompt — see dc_file_count). It is NOT a
  # skip gate for bullet-policing below: an EXISTING DNV section's bullets
  # are always policed regardless of file_count. It IS the gate input for
  # the separate header-presence check further down.
  file_count=$(dc_file_count "$transcript")

  # Extract the last assistant text block, retrying for the transcript-flush race.
  # Each assistant entry is reduced to a STRING (its joined text blocks) before the
  # array is built, so a non-text entry contributes "" and can never win `last` over
  # a real text block. Assistant content in Claude Code transcripts is always an
  # array; the string/else branches are defensive only.
  text=$(dc_stable_text "$transcript" "$TAIL_LINES" "$MAX_ATTEMPTS" "$SLEEP_S")
  attempts=$DC_LAST_ATTEMPTS
fi

# Loop-guard: if we already blocked once this turn, allow the stop to avoid looping.
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# Skip if the last response has no text: nothing was claimed, nothing to inspect.
# Logged (not silent) so a degraded/empty-text check is auditable — this now
# also short-circuits the header-presence check further down.
if [ -z "$text" ]; then
  log_line "hook=verify_loop event=$hook_event session=$session_id attempts=$attempts files=$file_count skipped=empty_text blocked=0"
  exit 0
fi

# Does a "## Did Not Verify" HEADER exist at all? This is distinct from
# dnv_items below: a header with zero bullets (prose-only, e.g. "nothing
# outstanding") is a COMPLIANT empty section — the same honesty boundary as
# an all-tagged bullet list — and must not be confused with the header being
# absent entirely.
has_dnv_header=0
echo "$text" | grep -qE '^## *(Did Not Verify|Not Verified)' && has_dnv_header=1

if [ "$has_dnv_header" -eq 0 ]; then
  # Presence check: file_count is 0 on the SubagentStop path (never computed
  # there), so this never fires for SubagentStop — intended, since a subagent
  # transcript is not scanned for file_count on that path. On the Stop path,
  # >=3 unique edited files this TURN with no DNV header at all is the same
  # omission the section-policing below catches for untagged bullets —
  # resolve or tag, don't skip the section entirely.
  if [ "$file_count" -ge 3 ]; then
    presence_msg="[verify-loop-block] session modified $file_count files but the response has no \"## Did Not Verify\" section. Rule (CLAUDE.md): after any response that edits files, end with a ## Did Not Verify section — resolve each item or tag it (unverifiable: <reason>). Add the section before stopping."

    # Loop-scoped warn demotion — same predicate, same fail-toward-blocking
    # shape as the bullet path below (#155). Evaluated lazily, only once a
    # block is imminent. SubagentStop never reaches this branch (the whole
    # has_dnv_header block above is dead on that path since file_count is
    # always 0 there), so this mirrors the bullet path's demotion contract
    # for consistency rather than adding new in-loop exposure.
    if [ "$hook_event" = "Stop" ] && als_loop_active_incomplete "$transcript" "$cwd" "$(als_sanitise_session_id "$session_id")"; then
      if jq -n --arg m "${presence_msg/\[verify-loop-block\]/[discipline-warn(loop)]}" \
        '{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":$m}}'; then
        log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=0 resolvable_dnv_items=0 presence_block=1 would_block=1 warned=1 blocked=0"
        exit 0
      fi
    fi

    log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=0 resolvable_dnv_items=0 presence_block=1 blocked=1"
    echo "$presence_msg" >&2
    exit 2
  fi
  log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=0 resolvable_dnv_items=0 blocked=0"
  exit 0
fi

# Header is present: count its bullets. Zero bullets under a present header
# is a compliant empty section (nothing to enforce) — the header itself is
# the model's declaration that it considered the question.
dnv_items=$(echo "$text" | awk '
  /^## *(Did Not Verify|Not Verified)/ { in_section=1; next }
  in_section && /^## / { in_section=0 }
  in_section && /^- / { count++ }
  END { print count+0 }
')

if [ "$dnv_items" -eq 0 ]; then
  log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=0 resolvable_dnv_items=0 blocked=0"
  exit 0
fi

dnv_item_text=$(echo "$text" | awk '
  /^## *(Did Not Verify|Not Verified)/ { in_section=1; next }
  in_section && /^## / { in_section=0 }
  in_section && /^- / { print }
')

# Total enforcement: ANY "## Did Not Verify" bullet blocks unless it is explicitly
# tagged as genuinely uncheckable. An untagged bullet means "I deferred something I
# could have resolved" — read the file, run the check, or delete the bullet. There
# is no file-naming requirement: a prose claim ("the dedup test catches the bug")
# blocks just as a filename does, because it too is checkable.
#
# Escape hatch — the ONLY way past: a bullet whose leading clause is an explicit
# "(unverifiable: <reason>)" tag. It is a deliberate, audited declaration that the
# item genuinely cannot be checked from source — a REPL-only action, external-system
# behaviour, prod-only observation, or user intent. The tag is anchored to the
# bullet's leading clause (right after "- ") so it can't be sprinkled mid-sentence
# to dodge a claim, and it is greppable so overuse is visible on review.
#
# Honest boundary: this forces every item to be resolved or explicitly tagged. It
# CANNOT force the tag to be truthful — tagging a checkable item is cheaper than
# checking it. The guarantee is "nothing is silently deferred," not "everything was
# actually verified." The tag is the auditable seam.
#
# Loop-scoped exception: on a Stop event inside an active, incomplete agentic
# loop, this enforcement demotes to a model-visible warn (additionalContext,
# exit 0) instead of a block — see the demotion branch below. SubagentStop
# never demotes, so worker output stays under full enforcement.
hatch_pattern='^- *\(unverifiable:'
untagged_bullets=$(echo "$dnv_item_text" | grep -ivE "$hatch_pattern")
# Count untagged bullets that carry any non-whitespace content (a bare "- " is not a claim).
resolvable_dnv_items=$(echo "$untagged_bullets" | grep -cE '^- *[^[:space:]]')
[ -z "$resolvable_dnv_items" ] && resolvable_dnv_items=0

log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=$dnv_items resolvable_dnv_items=$resolvable_dnv_items blocked=0"

if [ "$resolvable_dnv_items" -gt 0 ]; then
  # Loop-scoped warn demotion (Stop event only — SubagentStop never reaches
  # this branch, so workers stay block-enforced). Evaluated lazily, only once
  # a block is imminent, so non-loop sessions never pay the transcript-
  # invocation scan. Fail-toward-blocking: the jq emission runs FIRST and its
  # own exit status gates the log line and exit 0 — if jq fails, execution
  # falls through to the normal block path below instead of silently exiting
  # 0 with a log line that falsely claims warned=1.
  if [ "$hook_event" = "Stop" ] && als_loop_active_incomplete "$transcript" "$cwd" "$(als_sanitise_session_id "$session_id")"; then
    if jq -n --arg m "[discipline-warn(loop)] Your '## Did Not Verify' section has untagged items — anything not
explicitly marked uncheckable is treated as something you could have resolved:
${dnv_item_text}
Resolve each before stopping: read the file, run the check (Read/Grep/Bash), or delete the bullet.
If an item GENUINELY cannot be checked from source (a REPL-only action, external-system
behaviour, prod-only observation, or user intent), keep it but tag its leading clause:
  - (unverifiable: <reason>) <the item>
That tag is the only escape hatch — every untagged bullet blocks outside a loop and is flagged inside one." \
      '{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":$m}}'; then
      log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} resolvable_dnv_items=$resolvable_dnv_items would_block=1 warned=1 blocked=0"
      exit 0
    fi
  fi

  log_line "hook=verify_loop event=$hook_event session=$session_id text_len=${#text} resolvable_dnv_items=$resolvable_dnv_items blocked=1"
  echo "[verify-loop-block] Your '## Did Not Verify' section has untagged items — anything not
explicitly marked uncheckable is treated as something you could have resolved:
${dnv_item_text}
Resolve each before stopping: read the file, run the check (Read/Grep/Bash), or delete the bullet.
If an item GENUINELY cannot be checked from source (a REPL-only action, external-system
behaviour, prod-only observation, or user intent), keep it but tag its leading clause:
  - (unverifiable: <reason>) <the item>
That tag is the only escape hatch — every untagged bullet blocks, file-naming or not." >&2
  exit 2
fi

exit 0
