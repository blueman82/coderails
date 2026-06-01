#!/bin/bash
# Stop hook — blocks (exit 2) when the response leaves ANY "## Did Not Verify" item
# untagged. Total enforcement: an untagged bullet is treated as something the model
# could have resolved (read the file, run the check) and chose to defer.
#
# The ONLY way a DNV bullet passes is an explicit "(unverifiable: <reason>)" tag on
# its leading clause — a deliberate, audited declaration that the item genuinely
# cannot be checked from source (REPL-only action, external system, prod-only
# observation, user intent). The tag is greppable, so overuse is visible on review.
# This forces resolve-or-tag; it cannot force the tag to be honest (tagging a
# checkable item is cheaper than checking it) — the guarantee is "nothing silently
# deferred," and the tag is the auditable seam.
#
# Checks run top to bottom; the first that matches decides. All but the last let
# the model stop — only an untagged DNV item blocks.
#   skip  — no transcript to inspect                       → allow stop
#   skip  — no files edited this turn (conversation only)  → allow stop
#   skip  — already blocked once this turn (loop-guard)    → allow stop
#   skip  — the last response has no text                  → allow stop
#   skip  — no "## Did Not Verify" bullets                 → allow stop
#   BLOCK — any untagged DNV bullet                        → deferred item left open

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)

# Skip if there is no transcript to inspect.
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  exit 0
fi

# Skip pure-conversation turns: if no files were edited, there is nothing to police.
# Counts unique Write/Edit/MultiEdit targets; a single edited file is enough to
# bring the response in scope (a one-file change can still carry unverified claims).
file_count=$(jq -s -r '
  [.[]?
   | select(.type == "assistant")
   | .message.content[]?
   | select(.type == "tool_use" and (.name == "Write" or .name == "Edit" or .name == "MultiEdit"))
   | .input.file_path]
  | unique | length
' "$transcript" 2>/dev/null)
[ -z "$file_count" ] && file_count=0

if [ "$file_count" -lt 1 ]; then
  exit 0
fi

# Loop-guard: if we already blocked once this turn, allow the stop to avoid looping.
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# Extract the last assistant text block, retrying for the transcript-flush race.
# Each assistant entry is reduced to a STRING (its joined text blocks) before the
# array is built, so a non-text entry contributes "" and can never win `last` over
# a real text block. Assistant content in Claude Code transcripts is always an
# array; the string/else branches are defensive only.
extract_last_text() {
  tail -n "$TAIL_LINES" "$transcript" 2>/dev/null | jq -s -r '
    [.[]?
     | select(.type == "assistant")
     | (.message.content
        | if type == "array" then [ .[]? | select(.type == "text") | .text ] | join(" ")
          elif type == "string" then .
          else "" end)
     | select(type == "string" and length > 0)]
    | last // ""
  ' 2>/dev/null
}

prev_len=-1
attempts=0
text=""
while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
  text=$(extract_last_text)
  cur_len=${#text}
  if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then
    break
  fi
  prev_len=$cur_len
  attempts=$((attempts + 1))
  [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
done

# Skip if the last response has no text: nothing was claimed, nothing to inspect.
if [ -z "$text" ]; then
  exit 0
fi

# Skip if there are no "## Did Not Verify" bullets: nothing to enforce.
dnv_items=$(echo "$text" | awk '
  /^## *(Did Not Verify|Not Verified)/ { in_section=1; next }
  in_section && /^## / { in_section=0 }
  in_section && /^- / { count++ }
  END { print count+0 }
')

if [ "$dnv_items" -eq 0 ]; then
  log_line "hook=verify_loop session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=0 resolvable_dnv_items=0 blocked=0"
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
hatch_pattern='^- *\(unverifiable:'
untagged_bullets=$(echo "$dnv_item_text" | grep -ivE "$hatch_pattern")
# Count untagged bullets that carry any non-whitespace content (a bare "- " is not a claim).
resolvable_dnv_items=$(echo "$untagged_bullets" | grep -cE '^- *[^[:space:]]')
[ -z "$resolvable_dnv_items" ] && resolvable_dnv_items=0

log_line "hook=verify_loop session=$session_id text_len=${#text} attempts=$attempts files=$file_count dnv_items=$dnv_items resolvable_dnv_items=$resolvable_dnv_items blocked=0"

if [ "$resolvable_dnv_items" -gt 0 ]; then
  log_line "hook=verify_loop session=$session_id text_len=${#text} resolvable_dnv_items=$resolvable_dnv_items blocked=1"
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
