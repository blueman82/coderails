#!/bin/bash
# scan_transcripts.sh — scan Claude Code session transcripts and emit per-session
# tool-use event sequences.
#
# PRIVACY INVARIANT: no argument text, prose, or file content from transcripts
# may ever appear in output beyond the three whitelisted "head" extractions
# below (Bash: first two whitespace tokens of .input.command; Skill:
# .input.skill; Agent: .input.subagent_type). Every other tool emits name
# only. Never text-grep a transcript — always jq, scoped to assistant records.
set -u

ROOT="${WORKFLOW_AUDIT_ROOT:-$HOME/.claude/projects}"
MODE="all-projects"
PROJECT=""
DAYS=14
LAST_SESSIONS=0

usage() {
  cat <<'EOF'
Usage: scan_transcripts.sh [--all-projects | --project <slug>] [--days N | --last-sessions N] [--help]

Scans Claude Code session transcripts (*.jsonl) under a corpus root and emits
one JSON line per session describing its tool-use event sequence.

  --all-projects       Scan every project directory under the corpus root (default).
  --project <slug>     Scan only the named project directory.
  --days N             Only sessions with activity in the last N days (default 14).
  --last-sessions N     Per project, the N newest sessions (by in-file message
                        timestamp, not file mtime), instead of --days.
  --help               Show this help and exit.

Corpus root: env WORKFLOW_AUDIT_ROOT (default: ~/.claude/projects). Project
directories are the immediate children of the root; session files are
<uuid>.jsonl directly inside each project directory.

Output (stdout), one JSON line per scanned session:
  {"session_id":"...","project_slug":"...","event_count":N,"events":[...]}

Errors (stderr): distinct reasons per failure, e.g. jq_parse_error:<file>,
skipped_own_session:<file>.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --all-projects) MODE="all-projects"; shift ;;
    --project) MODE="project"; PROJECT="${2:-}"; shift 2 ;;
    --days) DAYS="${2:-14}"; shift 2 ;;
    --last-sessions) LAST_SESSIONS="${2:-0}"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) printf 'unknown_arg:%s\n' "$1" >&2; exit 1 ;;
  esac
done

# Sanitise numeric args (case fallback per house contract).
case "$DAYS" in (''|*[!0-9]*) DAYS=14;; esac
case "$LAST_SESSIONS" in (''|*[!0-9]*) LAST_SESSIONS=0;; esac

OWN_SESSION="${CLAUDE_CODE_SESSION_ID:-}"

# ── Resolve the list of project directories to scan ─────────────────────────
declare -a PROJECT_DIRS=()
if [ "$MODE" = "project" ]; then
  if [ -n "$PROJECT" ] && [ -d "$ROOT/$PROJECT" ]; then
    PROJECT_DIRS=("$ROOT/$PROJECT")
  fi
else
  if [ -d "$ROOT" ]; then
    while IFS= read -r -d '' d; do
      PROJECT_DIRS+=("$d")
    done < <(find "$ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
  fi
fi

# ── Collect all session files across resolved project dirs ─────────────────
declare -a ALL_FILES=()
for d in "${PROJECT_DIRS[@]:-}"; do
  [ -z "$d" ] && continue
  while IFS= read -r -d '' f; do
    ALL_FILES+=("$f")
  done < <(find "$d" -maxdepth 1 -type f -name '*.jsonl' -print0 2>/dev/null | sort -z)
done

# ── Sanity stderr line: file count + total MB about to be scanned ──────────
FILE_COUNT=${#ALL_FILES[@]}
TOTAL_BYTES=0
for f in "${ALL_FILES[@]:-}"; do
  [ -z "$f" ] && continue
  sz=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
  case "$sz" in (''|*[!0-9]*) sz=0;; esac
  TOTAL_BYTES=$((TOTAL_BYTES + sz))
done
TOTAL_MB=$(awk -v b="$TOTAL_BYTES" 'BEGIN { printf "%.2f", b / 1048576 }')
printf 'scanning file_count=%s total_mb=%s\n' "$FILE_COUNT" "$TOTAL_MB" >&2

# ── Per-file jq extraction ───────────────────────────────────────────────────
# Records are scoped select(.type=="assistant") FIRST, then tool_use content
# items. This means every non-assistant record type (attachment,
# queue-operation, last-prompt, mode, permission-mode, bridge-session,
# ai-title, custom-title, agent-name, worktree-state, plain user records) is
# excluded by construction — last-prompt (a resume cache) is never read.
JQ_FILTER='
  [ .[]?
    | select(.type == "assistant")
    | . as $rec
    | ($rec.message.content // [])
    | (if type == "array" then . else [] end)[]?
    | select(.type == "tool_use")
    | {
        tool: .name,
        head: (
          if .name == "Bash" then
            ((.input.command // "") | if type == "string" then . else "" end
             | [splits("\\s+")] | map(select(length > 0)) | .[0:2] | join(" "))
          elif .name == "Skill" then
            (.input.skill // "" | if type == "string" then . else "" end)
          elif .name == "Agent" then
            (.input.subagent_type // "" | if type == "string" then . else "" end)
          else
            null
          end
        )
      }
  ]
'

LATEST_TS_FILTER='
  [ .[]? | select(.type == "assistant" or .type == "user") | .timestamp? // empty ] | max // ""
'

# Parse each line independently via `fromjson? // empty` (jq -R -n, reading raw
# lines): a single corrupt line becomes `empty` and is dropped rather than
# failing the whole file's `jq -s` slurp, so one bad line no longer discards
# every valid event in the session. valid_records() emits the parsed records
# as a JSON array on stdout; a corrupt line is detected by comparing the
# parsed-line count against the file's non-blank line count.
valid_records() {
  local file="$1"
  jq -R -n '[ inputs | fromjson? // empty ]' "$file" 2>/dev/null
}

has_corrupt_line() {
  local file="$1" parsed_count="$2"
  local raw_count
  raw_count=$(grep -c . "$file" 2>/dev/null)
  case "$raw_count" in (''|*[!0-9]*) raw_count=0;; esac
  [ "$parsed_count" -lt "$raw_count" ]
}

latest_timestamp() {
  local file="$1"
  local records; records=$(valid_records "$file")
  if [ -z "$records" ]; then
    printf 'jq_parse_error:%s\n' "$file" >&2
    printf ''
    return 1
  fi
  jq -r "$LATEST_TS_FILTER" <<<"$records" 2>/dev/null
}

emit_session() {
  local file="$1" session_id="$2" slug="$3"
  local records
  records=$(valid_records "$file")
  if [ -z "$records" ]; then
    printf 'jq_parse_error:%s\n' "$file" >&2
    return 1
  fi
  local parsed_count; parsed_count=$(jq -r 'length' <<<"$records" 2>/dev/null)
  case "$parsed_count" in (''|*[!0-9]*) parsed_count=0;; esac
  if has_corrupt_line "$file" "$parsed_count"; then
    printf 'jq_parse_error:%s\n' "$file" >&2
  fi
  local events_json
  events_json=$(jq -c "$JQ_FILTER" <<<"$records" 2>/dev/null)
  local jq_rc=$?
  if [ "$jq_rc" -ne 0 ]; then
    printf 'jq_parse_error:%s\n' "$file" >&2
    return 1
  fi
  jq -c --arg sid "$session_id" --arg slug "$slug" \
    '{session_id: $sid, project_slug: $slug, event_count: (. | length), events: (. | map(if .head == null then {tool} else . end))}' \
    <<<"$events_json"
}

# ── Filter files by mode (own-session exclusion, --days / --last-sessions) ──
declare -a CANDIDATES=()
for f in "${ALL_FILES[@]:-}"; do
  [ -z "$f" ] && continue
  base=$(basename "$f" .jsonl)
  if [ -n "$OWN_SESSION" ] && [ "$base" = "$OWN_SESSION" ]; then
    printf 'skipped_own_session:%s\n' "$f" >&2
    continue
  fi
  CANDIDATES+=("$f")
done

if [ "$LAST_SESSIONS" -gt 0 ]; then
  # Group by project dir, take newest N per project (by in-file timestamp, NOT
  # mtime). Bash 3.2 (macOS default) has no associative arrays, so grouping is
  # done with a sortable "dir<TAB>timestamp<TAB>file" line list piped through
  # sort + awk instead of a declare -A.
  RANKED=""
  for f in "${CANDIDATES[@]:-}"; do
    [ -z "$f" ] && continue
    d=$(dirname "$f")
    ts=$(latest_timestamp "$f")
    RANKED+="${d}	${ts}	${f}"$'\n'
  done
  CANDIDATES=()
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    CANDIDATES+=("${line##*$'\t'}")
  done < <(printf '%s' "$RANKED" | sort -t $'\t' -k1,1 -k2,2r | \
    awk -F'\t' -v n="$LAST_SESSIONS" '{ c[$1]++; if (c[$1] <= n) print }')
else
  # --days filtering: keep files whose latest in-file timestamp is within N days.
  cutoff_epoch=$(( $(date +%s) - DAYS * 86400 ))
  FILTERED=()
  for f in "${CANDIDATES[@]:-}"; do
    [ -z "$f" ] && continue
    ts=$(latest_timestamp "$f")
    [ -z "$ts" ] && { FILTERED+=("$f"); continue; }
    ts_epoch=$(date -j -f '%Y-%m-%dT%H:%M:%S' "${ts%%.*}" +%s 2>/dev/null || date -d "$ts" +%s 2>/dev/null)
    case "$ts_epoch" in (''|*[!0-9]*) FILTERED+=("$f"); continue;; esac
    if [ "$ts_epoch" -ge "$cutoff_epoch" ]; then
      FILTERED+=("$f")
    fi
  done
  CANDIDATES=("${FILTERED[@]:-}")
fi

for f in "${CANDIDATES[@]:-}"; do
  [ -z "$f" ] && continue
  session_id=$(basename "$f" .jsonl)
  slug=$(basename "$(dirname "$f")")
  emit_session "$f" "$session_id" "$slug"
done

exit 0
