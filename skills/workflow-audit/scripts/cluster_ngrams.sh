#!/bin/bash
# cluster_ngrams.sh — cluster repeated tool-use n-grams across sessions.
#
# Consumes scan_transcripts.sh's stdout JSONL on stdin (one line per session:
# {"session_id","project_slug","event_count","events":[{"tool","head"},...]})
# and emits ONE JSON object on stdout describing n-grams (n=2..5) that recur
# across multiple distinct sessions.
#
# PRIVACY INVARIANT: output may contain only the event strings already
# whitelisted by scan_transcripts.sh (tool names + heads), counts, and session
# ids — nothing else from the input schema passes through.
set -u

MIN_SESSIONS=3
TOP=50

usage() {
  cat <<'EOF'
Usage: cluster_ngrams.sh [--min-sessions N] [--top K] [--help]

Reads scan_transcripts.sh's per-session JSONL stream on stdin and emits one
JSON object on stdout describing n-grams (n=2..5) of tool-use events that
recur across multiple distinct sessions ("clusters").

  --min-sessions N   Minimum distinct sessions an n-gram must appear in to be
                      reported as a cluster (default 3).
  --top K            Cap the number of reported clusters (default 50), sorted
                      by count desc then n desc. Truncation is noted in
                      diagnostics.truncated.
  --help             Show this help and exit.

Output (stdout), one JSON object:
  {"scanned_sessions":N,"clusters":[{"ngram":[...],"n":N,"count":N,"sessions":[...]}],"diagnostics":{"below_threshold":M,"truncated":true|false}}

Errors (stderr): jq_parse_error:<line-no> for a malformed input line (that
line is skipped; remaining lines are still processed).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --min-sessions) MIN_SESSIONS="${2:-3}"; shift 2 ;;
    --top) TOP="${2:-50}"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) printf 'unknown_arg:%s\n' "$1" >&2; exit 1 ;;
  esac
done

# Sanitise numeric args (house contract: fall back to default on non-numeric).
case "$MIN_SESSIONS" in (''|*[!0-9]*) MIN_SESSIONS=3;; esac
case "$TOP" in (''|*[!0-9]*) TOP=50;; esac
# --top 0 ("give me the top zero") is nonsensical input, not a valid request
# for an empty result — floor to 1 rather than reporting empty clusters with
# a misleading diagnostics.truncated:true.
[ "$TOP" -eq 0 ] && TOP=1

# ── Read stdin line-by-line, isolating malformed lines ──────────────────────
# Each line is parsed independently via `fromjson? // empty`; a corrupt line
# emits jq_parse_error:<line-no> on stderr and is dropped, while the rest of
# the stream is still processed (house error contract, same pattern
# scan_transcripts.sh settled on for per-line isolation).
VALID_SESSIONS_JSON=""
line_no=0
while IFS= read -r line || [ -n "$line" ]; do
  line_no=$((line_no + 1))
  [ -z "$line" ] && continue
  # A session record must be a JSON object — valid-but-non-object JSON
  # (false, 0, "x", [1,2,3], null) is rejected here too, otherwise it would
  # survive this guard and crash the downstream .events/.session_id access.
  parsed=$(printf '%s' "$line" | jq -ce 'if type == "object" then . else empty end' 2>/dev/null)
  if [ -z "$parsed" ]; then
    printf 'jq_parse_error:%s\n' "$line_no" >&2
    continue
  fi
  VALID_SESSIONS_JSON="${VALID_SESSIONS_JSON}${parsed}"$'\n'
done

SCANNED_SESSIONS=0
if [ -n "$VALID_SESSIONS_JSON" ]; then
  SCANNED_SESSIONS=$(printf '%s' "$VALID_SESSIONS_JSON" | jq -s 'length')
fi
case "$SCANNED_SESSIONS" in (''|*[!0-9]*) SCANNED_SESSIONS=0;; esac

if [ "$SCANNED_SESSIONS" -eq 0 ]; then
  jq -cn '{scanned_sessions: 0, clusters: [], diagnostics: {below_threshold: 0, truncated: false}}'
  exit 0
fi

# ── Build the event-string form per session, then slide n=2..5 windows ─────
# Event string: `tool` alone when no head, else `tool:head`. This mirrors
# scan_transcripts.sh's own emitted shape (head omitted -> {tool} only).
#
# For each session, jq emits one line per (n, window-start) pair:
#   {"session_id":"...", "n":N, "ngram":[...]}
# This flat stream is then grouped externally (still jq, single -s pass) by
# (n, ngram) to compute count + distinct sessions, since Bash 3.2 has no
# associative arrays to do the grouping in shell.
NGRAM_STREAM=$(printf '%s' "$VALID_SESSIONS_JSON" | jq -c '
  . as $s
  | ($s.events // [])
    | map(
        (if (.tool | type) == "string" then .tool else "" end) as $tool
        | (if (.head | type) == "string" then .head else null end) as $head
        | if ($head and $tool != "") then ($tool + ":" + $head) else $tool end
      ) as $strs
  | ($strs | length) as $len
  | range(2; 6) as $n
  | select($n <= $len)
  | range(0; $len - $n + 1) as $i
  | {session_id: $s.session_id, n: $n, ngram: $strs[$i:$i+$n]}
')

if [ -z "$NGRAM_STREAM" ]; then
  jq -cn '{scanned_sessions: '"$SCANNED_SESSIONS"', clusters: [], diagnostics: {below_threshold: 0, truncated: false}}'
  exit 0
fi

# Group by (n, ngram): count = total occurrences, sessions = sorted unique
# distinct session ids (a session_id repeated across multiple input lines
# must not inflate distinct-session support — `unique` on the grouped
# session_id array enforces that).
GROUPED=$(printf '%s' "$NGRAM_STREAM" | jq -sc '
  group_by([.n, .ngram])
  | map({
      ngram: .[0].ngram,
      n: .[0].n,
      count: length,
      sessions: ([.[].session_id] | unique)
    })
')

ALL_CLUSTERS=$(printf '%s' "$GROUPED" | jq -c --argjson min "$MIN_SESSIONS" '
  map(select((.sessions | length) >= $min))
  | map({ngram, n, count, sessions: (.sessions | sort)})
  | sort_by([-.count, -.n])
')

BELOW_THRESHOLD=$(printf '%s' "$GROUPED" | jq -r --argjson min "$MIN_SESSIONS" '
  [.[] | select((.sessions | length) < $min)] | length
')
case "$BELOW_THRESHOLD" in (''|*[!0-9]*) BELOW_THRESHOLD=0;; esac

TOTAL_CLUSTERS=$(printf '%s' "$ALL_CLUSTERS" | jq -r 'length')
case "$TOTAL_CLUSTERS" in (''|*[!0-9]*) TOTAL_CLUSTERS=0;; esac

TRUNCATED=false
CLUSTERS="$ALL_CLUSTERS"
if [ "$TOTAL_CLUSTERS" -gt "$TOP" ]; then
  TRUNCATED=true
  CLUSTERS=$(printf '%s' "$ALL_CLUSTERS" | jq -c --argjson top "$TOP" '.[0:$top]')
fi

jq -cn \
  --argjson scanned "$SCANNED_SESSIONS" \
  --argjson clusters "$CLUSTERS" \
  --argjson below "$BELOW_THRESHOLD" \
  --argjson truncated "$TRUNCATED" \
  '{scanned_sessions: $scanned, clusters: $clusters, diagnostics: {below_threshold: $below, truncated: $truncated}}'

exit 0
