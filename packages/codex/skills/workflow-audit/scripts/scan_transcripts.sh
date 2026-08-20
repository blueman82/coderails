#!/bin/bash
# Scan native Codex session JSONL and emit privacy-bounded tool sequences.
set -euo pipefail

ROOT="${WORKFLOW_AUDIT_ROOT:-$HOME/.codex/sessions}"
MODE="all-projects"
PROJECT=""
DAYS=14
LAST_SESSIONS=0

usage() {
    cat <<'EOF'
Usage: scan_transcripts.sh [--all-projects | --project <slug>] [--days N | --last-sessions N] [--help]

Scans native Codex session JSONL and emits one JSON line per root session.

  --all-projects       Scan sessions from every project (default).
  --project <slug>     Scan sessions whose session_meta cwd basename is <slug>.
  --days N             Only sessions active in the last N days (default 14).
  --last-sessions N    Per project, scan the N newest root sessions by JSONL
                       timestamp instead of --days.
  --help               Show this help and exit.

Corpus root: env WORKFLOW_AUDIT_ROOT (default: ~/.codex/sessions).
Files may be nested below the root, as in ~/.codex/sessions/YYYY/MM/DD/*.jsonl.

Output (stdout), one JSON line per scanned session:
  {"session_id":"...","project_slug":"...","event_count":N,"events":[...]}

Only completed CommandExecution, FileChange, Extension, and
CollabAgentToolCall items are read. Message, prompt, result, and reasoning
content is never copied to output.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
    --all-projects)
        MODE="all-projects"
        shift
        ;;
    --project)
        MODE="project"
        PROJECT="${2:-}"
        shift 2
        ;;
    --days)
        DAYS="${2:-14}"
        shift 2
        ;;
    --last-sessions)
        LAST_SESSIONS="${2:-0}"
        shift 2
        ;;
    --help)
        usage
        exit 0
        ;;
    *)
        printf 'unknown_arg:%s\n' "$1" >&2
        exit 1
        ;;
    esac
done

case "$DAYS" in '' | *[!0-9]*) DAYS=14 ;; esac
case "$LAST_SESSIONS" in '' | *[!0-9]*) LAST_SESSIONS=0 ;; esac

OWN_SESSION="${CODEX_SESSION_ID:-}"
OWN_THREAD="${CODEX_THREAD_ID:-}"

JQ_FILTER='
  def string_or_empty: if type == "string" then . else "" end;
  def command_head:
    (.command // [])
    | if type == "array" then (.[2] // "") else "" end
    | string_or_empty
    | [splits("\\s+")] | map(select(length > 0)) | .[0:2] | join(" ");
  [ .[]?
    | select(.type == "event_msg" and .payload.type == "item_completed")
    | .payload.item
    | select(type == "object")
    | if .type == "CommandExecution" then
        {tool: "CommandExecution", head: command_head}
      elif .type == "FileChange" then
        {tool: "FileChange"}
      elif .type == "Extension" then
        {tool: "Extension", head: (
          (.kind // "") | string_or_empty | if . == "web.search" then . else "" end
        )}
      elif .type == "CollabAgentToolCall" then
        {tool: "CollabAgentToolCall", head: (
          (.tool // "") | string_or_empty
          | if . == "spawn_agent" or . == "send_input" or . == "wait" or . == "close_agent"
            then . else "" end
        )}
      else empty end
    | if (.head? // "") == "" then {tool} else . end
  ]
'

valid_records() {
    local file="$1"
    jq -R -n '[inputs | fromjson? // empty]' "$file" 2>/dev/null
}

has_corrupt_line() {
    local file="$1" parsed_count="$2" raw_count
    raw_count=$(grep -c . "$file" 2>/dev/null || true) # Empty files legitimately make grep return 1.
    case "$raw_count" in '' | *[!0-9]*) raw_count=0 ;; esac
    [[ "$parsed_count" -lt "$raw_count" ]]
}

latest_timestamp() {
    jq -r '[.[]? | .timestamp? | select(type == "string")] | max // ""' <<<"$1"
}

timestamp_epoch() {
    local timestamp="$1" without_fraction
    without_fraction="${timestamp%%.*}"
    without_fraction="${without_fraction%Z}"
    if date -j -u -f '%Y-%m-%dT%H:%M:%S' "$without_fraction" '+%s' 2>/dev/null; then
        return 0
    fi
    date -d "$timestamp" '+%s' 2>/dev/null
}

emit_session() {
    local file="$1" session_id="$2" slug="$3" records events
    records=$(valid_records "$file")
    events=$(jq -c "$JQ_FILTER" <<<"$records")
    jq -c --arg sid "$session_id" --arg slug "$slug" '
    {session_id: $sid, project_slug: $slug, event_count: length, events: .}
  ' <<<"$events"
}

declare -a ALL_FILES=()
if [[ -d "$ROOT" ]]; then
    while IFS= read -r -d '' file; do
        ALL_FILES+=("$file")
    done < <(find "$ROOT" -type f -name '*.jsonl' -print0 | sort -z)
fi

declare -a CANDIDATE_FILES=() CANDIDATE_SLUGS=() CANDIDATE_IDS=() CANDIDATE_TIMESTAMPS=()
for file in "${ALL_FILES[@]:-}"; do
    [[ -n "$file" ]] || continue
    records=$(valid_records "$file")
    parsed_count=$(jq -r 'length' <<<"$records")
    if has_corrupt_line "$file" "$parsed_count"; then
        printf 'jq_parse_error:%s\n' "$file" >&2
    fi

    metadata=$(jq -c '[.[]? | select(.type == "session_meta") | .payload | select(type == "object")][0] // {}' <<<"$records")
    if [[ "$metadata" == '{}' ]]; then
        printf 'missing_session_meta:%s\n' "$file" >&2
        continue
    fi

    parent_thread=$(jq -r '.parent_thread_id // ""' <<<"$metadata")
    [[ -z "$parent_thread" ]] || continue

    cwd=$(jq -r 'if (.cwd | type) == "string" then .cwd else "" end' <<<"$metadata")
    slug="${cwd%/}"
    slug="${slug##*/}"
    [[ -n "$slug" ]] || slug="unknown"

    session_id=$(jq -r '
    if (.session_id | type) == "string" and .session_id != "" then .session_id
    elif (.id | type) == "string" then .id else "" end
  ' <<<"$metadata")
    thread_id=$(jq -r 'if (.id | type) == "string" then .id else "" end' <<<"$metadata")
    if [[ -z "$session_id" ]]; then
        printf 'missing_session_id:%s\n' "$file" >&2
        continue
    fi

    if { [[ -n "$OWN_SESSION" ]] && [[ "$session_id" == "$OWN_SESSION" || "$thread_id" == "$OWN_SESSION" ]]; } ||
        { [[ -n "$OWN_THREAD" ]] && [[ "$thread_id" == "$OWN_THREAD" ]]; }; then
        printf 'skipped_own_session:%s\n' "$file" >&2
        continue
    fi
    [[ "$MODE" != "project" || "$slug" == "$PROJECT" ]] || continue

    CANDIDATE_FILES+=("$file")
    CANDIDATE_SLUGS+=("$slug")
    CANDIDATE_IDS+=("$session_id")
    CANDIDATE_TIMESTAMPS+=("$(latest_timestamp "$records")")
done

FILE_COUNT=${#CANDIDATE_FILES[@]}
TOTAL_BYTES=0
for file in "${CANDIDATE_FILES[@]:-}"; do
    [[ -n "$file" ]] || continue
    size=$(wc -c <"$file" | tr -d ' ')
    case "$size" in '' | *[!0-9]*) size=0 ;; esac
    TOTAL_BYTES=$((TOTAL_BYTES + size))
done
TOTAL_MB=$(awk -v bytes="$TOTAL_BYTES" 'BEGIN { printf "%.2f", bytes / 1048576 }')
printf 'scanning file_count=%s total_mb=%s\n' "$FILE_COUNT" "$TOTAL_MB" >&2

declare -a SELECTED=()
if [[ "$LAST_SESSIONS" -gt 0 ]]; then
    RANKED=""
    for ((index = 0; index < FILE_COUNT; index++)); do
        RANKED+="${CANDIDATE_SLUGS[$index]}"$'\t'"${CANDIDATE_TIMESTAMPS[$index]}"$'\t'"$index"$'\n'
    done
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        SELECTED+=("${line##*$'\t'}")
    done < <(printf '%s' "$RANKED" | sort -t $'\t' -k1,1 -k2,2r | awk -F'\t' -v n="$LAST_SESSIONS" '{ seen[$1]++; if (seen[$1] <= n) print }')
else
    cutoff_epoch=$(($(date +%s) - DAYS * 86400))
    for ((index = 0; index < FILE_COUNT; index++)); do
        timestamp="${CANDIDATE_TIMESTAMPS[$index]}"
        if [[ -z "$timestamp" ]]; then
            SELECTED+=("$index")
        elif epoch=$(timestamp_epoch "$timestamp"); then
            [[ "$epoch" -ge "$cutoff_epoch" ]] && SELECTED+=("$index")
        else
            SELECTED+=("$index")
        fi
    done
fi

for index in "${SELECTED[@]:-}"; do
    [[ -n "$index" ]] || continue
    emit_session "${CANDIDATE_FILES[$index]}" "${CANDIDATE_IDS[$index]}" "${CANDIDATE_SLUGS[$index]}"
done
